"""检索服务单测：双路命中/单路命中/无命中/降级分级/引用元数据/耗时打点。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import load_config
from app.retrieval import RetrievalUnavailable
from app.retrieval.retrieve import (
    DECLINE,
    FALLBACK,
    NORMAL,
    WEAK,
    Citation,
    RetrievalResult,
    _merge_hits,
    retrieve,
)


def _cfg(**overrides):
    cfg = load_config()
    for k, v in overrides.items():
        setattr(cfg.retrieval, k, v)
    return cfg


def _qdrant_mock(hits):
    """hits: list of (parent_id, score, file_id, file_name, text)"""
    qdrant = MagicMock()
    qdrant.collection = "kb_blocks"

    points = []
    for pid, score, fid, fname, text in hits:
        p = SimpleNamespace(
            score=score,
            payload={
                "parent_id": pid,
                "file_id": fid,
                "file_name": fname,
                "text": text,
                "kb_id": "kb-1",
            },
        )
        points.append(p)

    resp = SimpleNamespace(points=points)
    qdrant.get_client.return_value.query_points.return_value = resp
    qdrant.is_available.return_value = True
    return qdrant


def _es_mock(hits):
    """hits: list of (parent_id, score, file_id, file_name, text)"""
    es = MagicMock()
    es.index = "kb_blocks"

    max_score = max((s for _, s, *_ in hits), default=0.0)
    es_hits = []
    for pid, score, fid, fname, text in hits:
        es_hits.append(
            {
                "_id": pid,
                "_score": score,
                "_source": {
                    "parent_id": pid,
                    "file_id": fid,
                    "file_name": fname,
                    "text": text,
                    "kb_id": "kb-1",
                },
            }
        )

    def _search(*args, **kwargs):
        return {"hits": {"hits": es_hits, "max_score": max_score}}

    es.get_client.return_value.search = _search
    es.is_available.return_value = True
    return es


def _embedding_mock():
    emb = MagicMock()
    emb.embed_query.return_value = [0.1] * 4
    return emb


# ---- _merge_hits 单元 ----


def test_merge_both_hits_weighted_sum():
    sem = {
        "p1": {"score": 0.9, "file_id": "f1", "file_name": "a.md", "text": "内容A"},
        "p2": {"score": 0.7, "file_id": "f1", "file_name": "a.md", "text": "内容B"},
    }
    kw = {
        "p1": {"score": 5.0, "file_id": "f1", "file_name": "a.md", "text": "内容A"},
        "p3": {"score": 3.0, "file_id": "f2", "file_name": "b.md", "text": "内容C"},
    }
    merged = _merge_hits(sem, kw, semantic_weight=0.6)
    assert len(merged) == 3
    # p1 双路命中：sem_norm=0.9, kw_norm=5/5=1.0 → 0.9*0.6 + 1.0*0.4 = 0.94
    top = merged[0]
    assert top.parent_id == "p1"
    assert top.score == pytest.approx(0.94, abs=0.001)
    assert top.semantic_score is not None
    assert top.keyword_score is not None
    assert top.file_name == "a.md"


def test_merge_only_semantic():
    sem = {
        "p1": {"score": 0.8, "file_id": "f1", "file_name": "a.md", "text": "内容A"},
    }
    merged = _merge_hits(sem, {}, semantic_weight=0.6)
    assert len(merged) == 1
    assert merged[0].score == pytest.approx(0.8, abs=0.001)
    assert merged[0].semantic_score is not None
    assert merged[0].keyword_score is None


def test_merge_only_keyword():
    kw = {
        "p1": {"score": 4.0, "file_id": "f1", "file_name": "a.md", "text": "内容A"},
        "p2": {"score": 2.0, "file_id": "f2", "file_name": "b.md", "text": "内容B"},
    }
    merged = _merge_hits({}, kw, semantic_weight=0.6)
    assert len(merged) == 2
    # 归一化：4/4=1.0, 2/4=0.5
    assert merged[0].score == pytest.approx(1.0, abs=0.001)
    assert merged[1].score == pytest.approx(0.5, abs=0.001)
    assert merged[0].semantic_score is None
    assert merged[0].keyword_score is not None


def test_merge_empty_both():
    assert _merge_hits({}, {}, 0.6) == []


def test_merge_semantic_score_clamped_to_0_1():
    # cosine 可能 >1 或 <0（边界情况），应截断
    sem = {
        "p1": {"score": 1.2, "file_id": "f1", "file_name": "a.md", "text": "x"},
        "p2": {"score": -0.3, "file_id": "f2", "file_name": "b.md", "text": "y"},
    }
    merged = _merge_hits(sem, {}, 0.6)
    assert merged[0].score == pytest.approx(1.0, abs=0.001)
    assert merged[1].score == pytest.approx(0.0, abs=0.001)


def test_merge_top_score_first():
    sem = {
        "p1": {"score": 0.5, "file_id": "f1", "file_name": "a.md", "text": "A"},
    }
    kw = {
        "p2": {"score": 10.0, "file_id": "f2", "file_name": "b.md", "text": "B"},
    }
    merged = _merge_hits(sem, kw, semantic_weight=0.6)
    # p2: 仅关键词 → 1.0（归一化）
    # p1: 仅语义 → 0.5
    assert [c.parent_id for c in merged] == ["p2", "p1"]


# ---- retrieve 集成 ----


def test_retrieve_normal_level_double_hit():
    cfg = _cfg(threshold=0.6, weak_threshold=0.45, top_k=5, semantic_weight=0.6)
    qdrant = _qdrant_mock([("p1", 0.9, "f1", "a.md", "多态是面向对象特性")])
    es = _es_mock([("p1", 8.0, "f1", "a.md", "多态是面向对象特性")])
    emb = _embedding_mock()

    result = retrieve("什么是多态", "kb-1", cfg, qdrant, es, emb)

    assert result.level == NORMAL
    assert len(result.citations) == 1
    assert result.citations[0].file_name == "a.md"
    assert result.semantic_hits == 1
    assert result.keyword_hits == 1
    assert result.total_ms > 0
    assert result.semantic_ms > 0
    assert result.keyword_ms > 0


def test_retrieve_weak_level_double_hit_low_score():
    cfg = _cfg(threshold=0.6, weak_threshold=0.45, top_k=5, semantic_weight=0.6)
    # 双路都命中同一父块，但语义分低 → 加权和落在 [0.45, 0.6) → weak
    # 语义 0.5 + 关键词归一化 0.5 → 0.5*0.6 + 0.5*0.4 = 0.3+0.2 = 0.5 → weak
    qdrant = _qdrant_mock([("p1", 0.5, "f1", "a.md", "相关内容")])
    es = _es_mock(
        [
            ("p2", 10.0, "f2", "b.md", "其他内容"),
            ("p1", 5.0, "f1", "a.md", "相关内容"),
        ]
    )
    result = retrieve("相关", "kb-1", cfg, qdrant, es, _embedding_mock())

    # p2 仅关键词（归一化 1.0）→ 最高分但单路 → fallback
    # p1 双路（0.5 + 5/10=0.5 → 加权 0.5）→ weak 区间，但因 p2 更高排第二
    assert result.level == FALLBACK
    # 检查双路命中的那条分数正确
    p1 = next(c for c in result.citations if c.parent_id == "p1")
    assert p1.score == pytest.approx(0.5, abs=0.001)
    assert p1.semantic_score is not None
    assert p1.keyword_score is not None


def test_retrieve_weak_level_pure_double_hit():
    """双路都命中，且最高分落在 [weak_threshold, threshold) → weak 级。"""
    cfg = _cfg(threshold=0.6, weak_threshold=0.45, top_k=5, semantic_weight=0.6)
    # p1 双路：sem=0.2（低分）, kw_norm=1.0（ES 最高）
    # 加权：0.2*0.6 + 1.0*0.4 = 0.12+0.4 = 0.52 → weak 区间
    # p2 双路：sem=0.15, kw_norm=0.5 → 0.15*0.6+0.5*0.4 = 0.09+0.2 = 0.29
    qdrant = _qdrant_mock(
        [
            ("p1", 0.2, "f1", "a.md", "A"),
            ("p2", 0.15, "f2", "b.md", "B"),
        ]
    )
    es = _es_mock(
        [
            ("p1", 10.0, "f1", "a.md", "A"),
            ("p2", 5.0, "f2", "b.md", "B"),
        ]
    )
    result = retrieve("查询", "kb-1", cfg, qdrant, es, _embedding_mock())
    assert result.level == WEAK
    assert len(result.citations) == 2
    assert result.citations[0].score == pytest.approx(0.52, abs=0.001)


def test_retrieve_fallback_only_semantic():
    cfg = _cfg(threshold=0.6, weak_threshold=0.45, top_k=5, semantic_weight=0.6)
    qdrant = _qdrant_mock([("p1", 0.8, "f1", "a.md", "内容A")])
    es = MagicMock()
    es.is_available.return_value = True
    es.get_client.return_value.search.return_value = {"hits": {"hits": [], "max_score": 0.0}}

    result = retrieve("查询", "kb-1", cfg, qdrant, es, _embedding_mock())
    assert result.level == FALLBACK
    assert len(result.citations) == 1
    assert result.semantic_hits == 1
    assert result.keyword_hits == 0


def test_retrieve_decline_no_hits():
    cfg = _cfg(threshold=0.6, weak_threshold=0.45, top_k=5, semantic_weight=0.6)
    qdrant = MagicMock()
    qdrant.is_available.return_value = True
    qdrant.get_client.return_value.search.return_value = []
    es = MagicMock()
    es.is_available.return_value = True
    es.get_client.return_value.search.return_value = {"hits": {"hits": [], "max_score": 0.0}}

    result = retrieve("无结果查询", "kb-1", cfg, qdrant, es, _embedding_mock())
    assert result.level == DECLINE
    assert result.citations == []
    assert result.semantic_hits == 0
    assert result.keyword_hits == 0


def test_retrieve_qdrant_unavailable_degrades_to_keyword():
    cfg = _cfg(threshold=0.6, weak_threshold=0.45, top_k=5, semantic_weight=0.6)
    qdrant = MagicMock()
    qdrant.is_available.return_value = False
    qdrant.get_client.side_effect = RetrievalUnavailable("qdrant down")

    es = _es_mock([("p1", 5.0, "f1", "a.md", "内容A")])
    result = retrieve("查询", "kb-1", cfg, qdrant, es, _embedding_mock())
    # Qdrant 不可用 → 仅关键词 → fallback
    assert result.level == FALLBACK
    assert len(result.citations) == 1
    assert result.semantic_hits == 0


def test_retrieve_es_unavailable_degrades_to_semantic():
    cfg = _cfg(threshold=0.6, weak_threshold=0.45, top_k=5, semantic_weight=0.6)
    es = MagicMock()
    es.is_available.return_value = False
    es.get_client.side_effect = RetrievalUnavailable("es down")

    qdrant = _qdrant_mock([("p1", 0.9, "f1", "a.md", "内容A")])
    result = retrieve("查询", "kb-1", cfg, qdrant, es, _embedding_mock())
    assert result.level == FALLBACK
    assert len(result.citations) == 1
    assert result.keyword_hits == 0


def test_retrieve_both_unavailable_returns_decline():
    cfg = _cfg(threshold=0.6, weak_threshold=0.45, top_k=5, semantic_weight=0.6)
    qdrant = MagicMock()
    qdrant.is_available.return_value = False
    qdrant.get_client.side_effect = RetrievalUnavailable("qdrant down")
    es = MagicMock()
    es.is_available.return_value = False
    es.get_client.side_effect = RetrievalUnavailable("es down")

    result = retrieve("查询", "kb-1", cfg, qdrant, es, _embedding_mock())
    assert result.level == DECLINE
    assert result.citations == []


def test_retrieve_respects_top_k():
    cfg = _cfg(threshold=0.6, weak_threshold=0.45, top_k=2, semantic_weight=0.6)
    qdrant = _qdrant_mock(
        [
            ("p1", 0.9, "f1", "a.md", "A"),
            ("p2", 0.8, "f1", "a.md", "B"),
            ("p3", 0.7, "f2", "b.md", "C"),
        ]
    )
    es = MagicMock()
    es.is_available.return_value = True
    es.get_client.return_value.search.return_value = {"hits": {"hits": [], "max_score": 0.0}}

    result = retrieve("查询", "kb-1", cfg, qdrant, es, _embedding_mock())
    assert len(result.citations) == 2


def test_citation_to_fields():
    c = Citation(
        file_id="f1",
        file_name="a.md",
        parent_id="p1",
        text="hello",
        score=0.85,
        semantic_score=0.9,
        keyword_score=0.8,
    )
    assert c.file_id == "f1"
    assert c.file_name == "a.md"
    assert c.parent_id == "p1"
    assert c.text == "hello"
    assert c.score == 0.85


def test_retrieval_result_defaults():
    r = RetrievalResult()
    assert r.citations == []
    assert r.level == DECLINE
    assert r.total_ms == 0.0
