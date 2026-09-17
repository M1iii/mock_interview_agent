"""检索服务：语义（Qdrant）+ 关键词（ES）双路召回 → 合并 → 降级分级。

合并策略（方案 B，2026-09-17 确认）：
- 双路都有命中 → 各自 min-max 归一化到 [0,1]，按 semantic_weight / (1-semantic_weight) 加权求和
- 仅单路命中 → 直接以该路归一化分为最终分，标记 fallback 级
- 双路均无命中 → decline 级

降级四级：normal ≥ threshold / weak ≥ weak_threshold / fallback 单路 / decline 无命中。
"""

import time
from dataclasses import dataclass, field

from loguru import logger
from omegaconf import DictConfig
from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.retrieval import RetrievalUnavailable
from app.retrieval.embedding import EmbeddingProvider
from app.retrieval.es import ESManager
from app.retrieval.qdrant import QdrantManager

NORMAL = "normal"
WEAK = "weak"
FALLBACK = "fallback"
DECLINE = "decline"


@dataclass
class RetrievalContext:
    """出题节点检索注入所需组件集合（图构建时注入，测试可替换为 fake）。"""

    cfg: DictConfig
    qdrant: QdrantManager
    es: ESManager
    embedding: EmbeddingProvider


@dataclass
class Citation:
    """引用条目（父块粒度，按文件维度展示来源折叠）。"""

    file_id: str
    file_name: str
    parent_id: str
    text: str
    score: float  # 最终合并分（0~1）
    semantic_score: float | None = None
    keyword_score: float | None = None


@dataclass
class RetrievalResult:
    citations: list[Citation] = field(default_factory=list)
    level: str = DECLINE  # normal / weak / fallback / decline
    total_ms: float = 0.0  # 总耗时（毫秒，P1-6 打点）
    semantic_ms: float = 0.0
    keyword_ms: float = 0.0
    semantic_hits: int = 0
    keyword_hits: int = 0


def retrieve(
    query: str,
    kb_id: str,
    cfg: DictConfig,
    qdrant: QdrantManager,
    es: ESManager,
    embedding: EmbeddingProvider,
) -> RetrievalResult:
    """执行检索：双路召回 → 合并去重 → 分级 → 返回引用列表（按最终分降序）。

    kb_id 用于过滤：只在指定知识库范围内召回（按父块 payload.kb_id 过滤）。
    """
    result = RetrievalResult()
    start = time.perf_counter()

    threshold = float(cfg.retrieval.threshold)  # default 0.6
    weak_threshold = float(cfg.retrieval.weak_threshold)  # default 0.45
    top_k = int(cfg.retrieval.top_k)
    semantic_weight = float(cfg.retrieval.semantic_weight)  # default 0.6
    score_threshold = float(cfg.retrieval.score_threshold)  # default 0.3
    min_should_match = cfg.retrieval.min_should_match  # default "75%"

    # ---- 语义路 ----
    semantic_hits: dict[str, dict] = {}
    try:
        t0 = time.perf_counter()
        vec = embedding.embed_query(query)
        client = qdrant.get_client()
        resp = client.query_points(
            collection_name=qdrant.collection,
            query=vec,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
            with_payload=True,
        )
        result.semantic_ms = (time.perf_counter() - t0) * 1000
        for p in resp.points:
            pid = p.payload.get("parent_id")
            if not pid:
                continue
            # 同一父块可能有多个子块命中，取最高语义分
            prev = semantic_hits.get(pid)
            if prev is None or p.score > prev["score"]:
                semantic_hits[pid] = {
                    "score": float(p.score),
                    "file_id": p.payload.get("file_id", ""),
                    "file_name": p.payload.get("file_name", ""),
                    "text": p.payload.get("text", ""),
                }
        result.semantic_hits = len(semantic_hits)
    except RetrievalUnavailable as e:
        logger.warning("semantic retrieval skipped: {err}", err=repr(e))
    except Exception as e:  # noqa: BLE001 - 单路故障不阻断另一路
        logger.error("semantic retrieval error: {err}", err=repr(e))

    # 语义路命中：按 parent_id 回查 ES 父块全文（引用上卷，失败回退子块文本）
    if semantic_hits:
        _backfill_parent_text(semantic_hits, es)

    # ---- 关键词路 ----
    keyword_hits: dict[str, dict] = {}
    try:
        t0 = time.perf_counter()
        client = es.get_client()
        resp = client.search(
            index=es.index,
            query={
                "bool": {
                    "must": [
                        {
                            "match": {
                                "text": {"query": query, "minimum_should_match": min_should_match}
                            }
                        },
                        {"term": {"kb_id": kb_id}},
                    ]
                }
            },
            size=top_k,
            _source=["parent_id", "file_id", "file_name", "text"],
        )
        result.keyword_ms = (time.perf_counter() - t0) * 1000
        max_score = resp.get("hits", {}).get("max_score") or 0.0
        for hit in resp.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            pid = src.get("parent_id")
            if not pid:
                continue
            keyword_hits[pid] = {
                "score": float(hit.get("_score", 0.0)),
                "file_id": src.get("file_id", ""),
                "file_name": src.get("file_name", ""),
                "text": src.get("text", ""),
                "max_score": float(max_score),
            }
        result.keyword_hits = len(keyword_hits)
    except RetrievalUnavailable as e:
        logger.warning("keyword retrieval skipped: {err}", err=repr(e))
    except Exception as e:  # noqa: BLE001 - 单路故障不阻断另一路
        logger.error("keyword retrieval error: {err}", err=repr(e))

    # ---- 合并 ----
    merged = _merge_hits(
        semantic_hits,
        keyword_hits,
        semantic_weight,
    )

    # ---- 分级 ----
    # 以最高分引用的命中类型为准：双路命中才评 normal/weak，单路命中评 fallback
    if not merged:
        result.level = DECLINE
    else:
        top = merged[0]
        top_is_double = top.semantic_score is not None and top.keyword_score is not None
        if top_is_double:
            if top.score >= threshold:
                result.level = NORMAL
            elif top.score >= weak_threshold:
                result.level = WEAK
            else:
                result.level = WEAK  # 双路都有但分都低，仍算 weak（有参考价值）
        else:
            result.level = FALLBACK

    result.citations = merged[:top_k]
    result.total_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "retrieval done: level={lvl} hits={n} total={t:.1f}ms (sem={s:.1f}ms kw={k:.1f}ms)",
        lvl=result.level,
        n=len(result.citations),
        t=result.total_ms,
        s=result.semantic_ms,
        k=result.keyword_ms,
    )
    return result


def _backfill_parent_text(semantic_hits: dict[str, dict], es: ESManager) -> None:
    """语义路命中后按 parent_id 回查 ES 父块全文；失败回退子块文本（引用始终存在）。"""
    try:
        client = es.get_client()
        resp = client.mget(index=es.index, ids=list(semantic_hits), _source=["text"])
    except Exception as e:  # noqa: BLE001 - 回查失败仅回退文本，不阻断检索
        logger.warning("parent text backfill failed, fallback to child text: {err}", err=repr(e))
        return
    for doc in resp.get("docs", []):
        pid = doc.get("_id")
        src = doc.get("_source") or {}
        if pid in semantic_hits and src.get("text"):
            semantic_hits[pid]["text"] = src["text"]


def _merge_hits(
    semantic: dict[str, dict],
    keyword: dict[str, dict],
    semantic_weight: float,
) -> list[Citation]:
    """按方案 B 合并：双路命中 → 归一化加权和；单路 → 直接归一化分。"""
    if not semantic and not keyword:
        return []

    # 语义路归一化（cosine 理论 [-1,1]，实际常用 [0,1] 区间，截断到 [0,1]）
    sem_scores = {pid: max(0.0, min(1.0, h["score"])) for pid, h in semantic.items()}

    # 关键词路归一化（按 ES max_score 做 min-max，min 取 0，结果 ∈ [0,1]）
    kw_max = max((h["score"] for h in keyword.values()), default=0.0)
    kw_scores: dict[str, float] = {}
    for pid, h in keyword.items():
        kw_scores[pid] = (h["score"] / kw_max) if kw_max > 0 else 0.0

    all_pids = set(semantic) | set(keyword)
    keyword_weight = 1.0 - semantic_weight
    citations: list[Citation] = []

    for pid in all_pids:
        sem_hit = semantic.get(pid)
        kw_hit = keyword.get(pid)
        sem_norm = sem_scores.get(pid)
        kw_norm = kw_scores.get(pid)

        if sem_hit is not None and kw_hit is not None:
            final = sem_norm * semantic_weight + kw_norm * keyword_weight
            text = sem_hit["text"] or kw_hit["text"]
            file_id = sem_hit["file_id"] or kw_hit["file_id"]
            file_name = sem_hit["file_name"] or kw_hit["file_name"]
        elif sem_hit is not None:
            final = sem_norm
            text = sem_hit["text"]
            file_id = sem_hit["file_id"]
            file_name = sem_hit["file_name"]
        else:
            assert kw_hit is not None
            final = kw_norm
            text = kw_hit["text"]
            file_id = kw_hit["file_id"]
            file_name = kw_hit["file_name"]

        citations.append(
            Citation(
                file_id=file_id,
                file_name=file_name,
                parent_id=pid,
                text=text,
                score=round(final, 4),
                semantic_score=round(sem_norm, 4) if sem_norm is not None else None,
                keyword_score=round(kw_norm, 4) if kw_norm is not None else None,
            )
        )

    citations.sort(key=lambda c: c.score, reverse=True)
    return citations
