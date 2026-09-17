"""P1 验收（P1-1~P1-7）真实环境独立脚本：入库 → 召回 → 引用 → 降级 → 级联 → P95 → 切换。

用法：uv run python _acceptance_p1.py [--only p1-1|p1-2|...|p1-7|all] [--keep]
--keep 保留验收库（默认结束清理）。退出码 0 = 全部通过，1 = 有未通过项。
"""

import argparse
import json
import statistics  # noqa: F401 - 后续 Task（P1-6 P95 统计）使用
import sys
import time
import uuid  # noqa: F401 - 后续 Task 使用
from pathlib import Path

from app.config import load_config
from app.retrieval.embedding import OpenAICompatEmbedding
from app.retrieval.es import ESManager
from app.retrieval.qdrant import QdrantManager
from app.retrieval.retrieve import (  # noqa: F401 - 后续 Task（P1-2 召回）使用
    RetrievalContext,
    retrieve,
)
from app.store.knowledge import READY, KnowledgeStore

CORPUS_DIR = Path("tests/acceptance/corpus")
QUESTIONS = json.loads(Path("tests/acceptance/questions.json").read_text(encoding="utf-8"))


class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, item: str, passed: bool, data: str = "") -> None:
        self.items.append({"item": item, "passed": passed, "data": data})
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {item}" + (f" | {data}" if data else ""))

    def summary(self) -> tuple[int, int]:
        ok = sum(1 for i in self.items if i["passed"])
        return ok, len(self.items) - ok


report = Report()
kb_id = f"kb-acceptance-{time.strftime('%Y%m%d%H%M%S')}"

_GOLD: dict[str, str] = {}  # qid -> gold_parent_id
_TIMINGS: list[float] = []  # P1-6 采样


def _locate_gold(es, q: dict) -> str | None:
    client = es.get_client()
    resp = client.search(
        index=es.index,
        query={
            "bool": {
                "must": [
                    # match_phrase 因索引端 ik_max_word 会插入重叠子词（如 不存在→不存/存在）
                    # 破坏短语相邻位置，50 条仅命中 11 条；gold_snippet 全文逐字存在于唯一
                    # parent 块内，改用 match（整段句子）定位语义不变（已验证 50/50 且
                    # 返回的 parent 均逐字包含该 snippet）。
                    {"match": {"text": q["gold_snippet"]}},
                    {"term": {"kb_id": kb_id}},
                ]
            }
        },
        size=1,
        _source=["parent_id"],
    )
    hits = resp.get("hits", {}).get("hits", [])
    return hits[0]["_source"]["parent_id"] if hits else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--only",
        default="all",
        nargs="+",
        choices=["p1-1", "p1-2", "p1-3", "p1-4", "p1-5", "p1-6", "p1-7", "all"],
    )
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    qdrant = QdrantManager(cfg)
    es = ESManager(cfg)
    embedding = OpenAICompatEmbedding(cfg)
    store = KnowledgeStore(cfg.retrieval.kb_db)
    ctx = RetrievalContext(cfg=cfg, qdrant=qdrant, es=es, embedding=embedding)

    checks = (
        ["p1-1", "p1-2", "p1-3", "p1-4", "p1-5", "p1-6", "p1-7"]
        if "all" in args.only
        else args.only
    )

    try:
        if "p1-1" in checks:
            p1_1(store, qdrant, es, embedding, cfg)
        if "p1-2" in checks:
            p1_2(ctx)
        if "p1-3" in checks:
            p1_3(ctx, cfg)
        if "p1-4" in checks:
            p1_4(ctx)
        if "p1-5" in checks:
            p1_5(store, qdrant, es, cfg)
        if "p1-6" in checks:
            p1_6()
        if "p1-7" in checks:
            p1_7(store, qdrant, es, cfg)
    finally:
        if not args.keep:
            cleanup(store, qdrant, es)

    ok, failed = report.summary()
    print(f"\n== P1 ACCEPTANCE SUMMARY == passed={ok} failed={failed}")
    sys.exit(0 if failed == 0 else 1)


def _ingest_file(store, qdrant, es, embedding, cfg, path: Path) -> tuple[bool, str]:
    from app.retrieval.ingest import file_id_of, ingest_document

    file_id = file_id_of(path)
    # 幂等重跑：kb_files.file_id 全表唯一（id = f-{file_id}），重入库复用原记录而非重复 INSERT
    record = store.get_file(f"f-{file_id}")
    if record is None:
        record = store.add_file(kb_id, file_id, path.name, str(path), path.stat().st_size)
    try:
        result = ingest_document(path, qdrant, es, embedding, cfg, kb_id=kb_id)
        store.update_file_status(record.id, READY, block_count=result.child_count)
        return True, f"parents={result.parent_count} children={result.child_count}"
    except Exception as e:  # noqa: BLE001 - 验收统计失败文件
        store.update_file_status(record.id, "failed", error=str(e)[:500])
        return False, repr(e)


def p1_1(store, qdrant, es, embedding, cfg) -> None:
    store.create_kb(kb_id, "acceptance", embedding.model_id, embedding.dims)
    results = {}
    for p in sorted(CORPUS_DIR.glob("*.md")):
        ok, data = _ingest_file(store, qdrant, es, embedding, cfg, p)
        results[p.name] = (ok, data)
    ok_count = sum(1 for ok, _ in results.values() if ok)
    rate = ok_count / len(results)
    report.add(
        "P1-1 入库成功率",
        rate >= 0.95,
        f"{ok_count}/{len(results)} = {rate:.0%} | "
        + ", ".join(f"{n}:{'OK' if ok else 'FAIL'}" for n, (ok, _) in results.items()),
    )
    # 幂等重跑：同 file_id 先清旧再入库，块数应一致
    first = {n: d for n, (ok, d) in results.items() if ok}
    idem_ok = True
    for p in sorted(CORPUS_DIR.glob("*.md")):
        ok, data = _ingest_file(store, qdrant, es, embedding, cfg, p)
        idem_ok = idem_ok and ok and data == first[p.name]
    report.add("P1-1 幂等重跑（块数一致）", idem_ok)


def p1_2(ctx) -> None:
    es = ctx.es
    locate_ok = 0
    for q in QUESTIONS:
        gid = _locate_gold(es, q)
        if gid:
            _GOLD[q["id"]] = gid
            locate_ok += 1
    report.add("P1-2 gold 定位率", locate_ok == len(QUESTIONS), f"{locate_ok}/{len(QUESTIONS)}")

    hit = 0
    miss_list = []
    for q in QUESTIONS:
        gid = _GOLD.get(q["id"])
        if gid is None:
            continue
        r = retrieve(q["query"], kb_id, ctx.cfg, ctx.qdrant, ctx.es, ctx.embedding)
        _TIMINGS.append(r.total_ms)
        ok = any(c.parent_id == gid for c in r.citations)
        hit += ok
        if not ok:
            miss_list.append(f"{q['id']}({q['topic']})")
    rate = hit / len(QUESTIONS)
    report.add(
        "P1-2 Top-K=5 召回命中率",
        rate >= 0.80,
        f"{hit}/{len(QUESTIONS)} = {rate:.0%} | miss: {', '.join(miss_list) if miss_list else '-'}",
    )


def p1_3(ctx, cfg) -> None:
    from app.interview.nodes import ask_question_node
    from app.interview.state import initial_state
    from app.llm.client import DeepSeekClient
    from app.llm.keys import KeyStore

    llm = DeepSeekClient(cfg)
    # KeyStore.__init__ 不接收 cfg 且全局 Key 仅经 set_global_key 写入（运行时由设置接口注入），
    # 独立脚本需从 cfg（LLM_API_KEY/.env）显式设置后再读取。
    key_store = KeyStore()
    key_store.set_global_key(cfg.llm.api_key)
    key = key_store.get_global_key()
    judge_prompt = (
        "你是引用准确性验收裁判。判断下面的「引用片段」是否支撑「面试题目」，"
        "即引用内容与题目讨论同一知识点、能作为答题依据。\n"
        "题目：{question}\n引用：[{n}] {text}\n只输出 true 或 false。"
    )

    judged = total_cites = true_cites = 0
    details = []
    for q in QUESTIONS:
        gid = _GOLD.get(q["id"])
        if gid is None:
            continue
        state = initial_state(scene="fulltime", question_count=5, kb_id=kb_id)
        state["_api_key"] = key
        state["scores"] = [
            {"topic": q["topic"]}
        ]  # 口径 C：检索按题目主题召回（_build_search_query 读 scores）
        try:
            out = ask_question_node(state, llm, retrieval=ctx)
        except Exception as e:  # noqa: BLE001 - LLM 单题失败不中断
            details.append(f"{q['id']}:ask-error {repr(e)[:80]}")
            continue
        if out.get("_citations") is None or len(out["_citations"]) == 0:
            details.append(f"{q['id']}:no-citations")
            continue
        question = out["current_question"]
        for n, c in enumerate(out["_citations"], start=1):
            prompt = judge_prompt.format(question=question, n=n, text=c["text"][:200])
            try:
                raw, _ = llm.complete_sync(api_key=key, prompt=prompt)
                verdict = raw.strip().lower()
                is_true = verdict.startswith("true")
            except Exception as e:  # noqa: BLE001
                is_true = False
                details.append(f"{q['id']}:judge-error {repr(e)[:80]}")
            total_cites += 1
            true_cites += 1 if is_true else 0
        judged += 1

    rate = true_cites / total_cites if total_cites else 0.0
    report.add(
        "P1-3 引用准确率（normal 级）",
        rate >= 0.90 and judged >= 40,
        f"judged={judged}/50 cites={true_cites}/{total_cites} = {rate:.0%} | "
        + ("; ".join(details[:5]) if details else "-"),
    )


class _UnavailableQdrant:
    """检索不可用 stub：语义路降级（retrieve 捕获 RetrievalUnavailable 跳过）。"""

    def get_client(self):
        from app.retrieval import RetrievalUnavailable

        raise RetrievalUnavailable("disabled for acceptance")


class _UnavailableES:
    """检索不可用 stub：关键词路降级（retrieve 捕获 RetrievalUnavailable 跳过）。"""

    def get_client(self):
        from app.retrieval import RetrievalUnavailable

        raise RetrievalUnavailable("disabled for acceptance")


def p1_4(ctx) -> None:
    from app.retrieval.retrieve import FALLBACK, NORMAL, WEAK

    normal_q = QUESTIONS[0]["query"]  # 正常知识点：预期 normal/weak
    unrelated_q = "今天天气怎么样明天会下雨吗"  # 无关：预期 decline
    dual = retrieve(normal_q, kb_id, ctx.cfg, ctx.qdrant, ctx.es, ctx.embedding)
    es_only = retrieve(normal_q, kb_id, ctx.cfg, _UnavailableQdrant(), ctx.es, ctx.embedding)
    sem_only = retrieve(normal_q, kb_id, ctx.cfg, ctx.qdrant, _UnavailableES(), ctx.embedding)
    decline = retrieve(unrelated_q, kb_id, ctx.cfg, ctx.qdrant, ctx.es, ctx.embedding)

    checks = [
        (
            "双路命中 → normal/weak 且引用非空",
            dual.level in (NORMAL, WEAK) and bool(dual.citations),
            f"level={dual.level} cites={len(dual.citations)}",
        ),
        ("仅语义路 → fallback", sem_only.level == FALLBACK, f"level={sem_only.level}"),
        ("仅关键词路 → fallback", es_only.level == FALLBACK, f"level={es_only.level}"),
        (
            "无关查询 → decline 且引用空",
            decline.level == "decline" and not decline.citations,
            f"level={decline.level}",
        ),
    ]
    for name, passed, data in checks:
        report.add(f"P1-4 {name}", passed, data)


def _qdrant_count(qdrant, qfilter) -> int:
    client = qdrant.get_client()
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return client.count(
        collection_name=qdrant.collection,
        count_filter=Filter(
            must=[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in qfilter.items()]
        ),
        exact=True,
    ).count


def _es_count(es, qfilter) -> int:
    client = es.get_client()
    must = [{"match": {k: v}} for k, v in qfilter.items()]
    return client.count(index=es.index, query={"bool": {"must": must}})["count"]


def p1_5(store, qdrant, es, cfg) -> None:
    from app.retrieval.ingest import delete_document, file_id_of

    # 文件级：删第一篇
    first = sorted(CORPUS_DIR.glob("*.md"))[0]
    fid = file_id_of(first)
    delete_document(fid, qdrant, es)
    qc = _qdrant_count(qdrant, {"kb_id": kb_id, "file_id": fid})
    ec = _es_count(es, {"kb_id": kb_id, "file_id": fid})
    report.add(
        "P1-5 文件级删除级联（Qdrant+ES 0 命中）", qc == 0 and ec == 0, f"qdrant={qc} es={ec}"
    )

    # 库级：删除整个库（模拟 API 级联：delete_kb → delete_document 循环）
    # 注意：此处不 unlink 语料文件——store.add_file 记录的 path 是
    # tests/acceptance/corpus/*.md 的真实路径（git 受控），unlink 会误删语料，
    # 破坏重跑与工作区；删除级联只清 Qdrant/ES 向量与索引，保留源文件。
    files = store.delete_kb(kb_id)
    for f in files:
        delete_document(f.file_id, qdrant, es)
    qc = _qdrant_count(qdrant, {"kb_id": kb_id})
    ec = _es_count(es, {"kb_id": kb_id})
    meta_left = store.get_kb(kb_id) is not None
    report.add(
        "P1-5 库级删除级联（三处 0 残留）",
        qc == 0 and ec == 0 and not meta_left,
        f"qdrant={qc} es={ec} meta_left={meta_left}",
    )


def p1_6() -> None:
    if len(_TIMINGS) < len(QUESTIONS):
        report.add("P1-6 检索 P95", False, "无采样数据（需先跑 p1-2）")
        return
    times = sorted(_TIMINGS)
    p95 = times[int(len(times) * 0.95) - 1]
    report.add(
        "P1-6 单次检索 P95",
        p95 <= 2000,
        f"P95={p95:.0f}ms P50={statistics.median(times):.0f}ms max={max(times):.0f}ms",
    )


def p1_7(store, qdrant, es, cfg) -> None:
    raise NotImplementedError


def cleanup(store, qdrant, es) -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
