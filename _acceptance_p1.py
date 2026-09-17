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
    raise NotImplementedError


def p1_3(ctx, cfg) -> None:
    raise NotImplementedError


def p1_4(ctx) -> None:
    raise NotImplementedError


def p1_5(store, qdrant, es, cfg) -> None:
    raise NotImplementedError


def p1_6() -> None:
    raise NotImplementedError


def p1_7(store, qdrant, es, cfg) -> None:
    raise NotImplementedError


def cleanup(store, qdrant, es) -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
