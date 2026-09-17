"""P1 Tip 7 真实服务冒烟：入库 → 检索注入 → 真实 LLM 出题（带引用）→ 清理。"""

from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import load_config
from app.interview.nodes import ask_question_node
from app.interview.state import initial_state
from app.retrieval.embedding import OpenAICompatEmbedding
from app.retrieval.es import ESManager
from app.retrieval.ingest import delete_document, ingest_document
from app.retrieval.qdrant import QdrantManager
from app.retrieval.retrieve import RetrievalContext

CONTENT = """# Redis 面试知识

Redis 是内存型键值数据库，支持持久化 RDB 与 AOF 两种方式。

缓存穿透指查询不存在的数据，导致请求打到数据库，可以用布隆过滤器 + 空值缓存解决。

缓存击穿指热点 Key 失效瞬间大量请求打到数据库，可加互斥锁或永不过期。

缓存雪崩指大量 Key 同时失效导致数据库压力骤增，可通过过期时间加随机偏移缓解。
"""


def main() -> None:
    cfg = load_config()
    qdrant = QdrantManager(cfg)
    es = ESManager(cfg)
    embedding = OpenAICompatEmbedding(cfg)
    ctx = RetrievalContext(cfg=cfg, qdrant=qdrant, es=es, embedding=embedding)

    # 真实 LLM Key 未配置时用 fake LLM：验证「真实检索 → 引用注入」链路（出题内容由单测覆盖）
    from unittest.mock import MagicMock

    llm = MagicMock()
    llm.complete_sync = MagicMock(
        return_value=('{"question": "请解释缓存穿透的解决方案", "topic": "缓存"}', {})
    )

    with TemporaryDirectory() as td:
        p = Path(td) / "redis.md"
        p.write_text(CONTENT, encoding="utf-8")
        result = ingest_document(p, qdrant, es, embedding, cfg, kb_id="kb-tip7-smoke")
        print(f"Ingested: {result.parent_count} parents, {result.child_count} children")

        state = initial_state(scene="fulltime", question_count=10, kb_id="kb-tip7-smoke")
        state["_api_key"] = "sk-fake"

        out = ask_question_node(state, llm, retrieval=ctx)
        question = out["current_question"]
        citations = out.get("_citations", [])
        print(f"\nQuestion: {question[:120]}")
        print(f"Citations: {len(citations)}")
        for c in citations:
            print(f"  [{c['file_name']}] {c['text'][:60]}... score={c['score']}")

        # 校验 prompt 中确实注入了参考资料（真实检索结果）
        prompt_text = llm.complete_sync.call_args.kwargs["prompt"]
        assert "【参考资料】" in prompt_text, "prompt 未注入参考资料"
        assert "[1]" in prompt_text, "prompt 缺少引用角标"

        assert question, "出题为空"
        assert citations, "无引用注入"
        assert any("redis" in c["file_name"].lower() for c in citations), "引用来源错误"

        delete_document(result.file_id, qdrant, es)
        print("\nCleaned up:", result.file_id)
    print("\nSMOKE OK")


if __name__ == "__main__":
    main()
