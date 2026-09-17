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
    raise NotImplementedError


def p1_4(ctx) -> None:
    raise NotImplementedError


def p1_5(store, qdrant, es, cfg) -> None:
    raise NotImplementedError


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
