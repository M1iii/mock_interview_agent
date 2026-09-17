from omegaconf import OmegaConf

from app.interview.graph import compile_graph
from app.interview.state import initial_state
from app.store.checkpointer import create_checkpointer, delete_thread

LLM_CFG = OmegaConf.create(
    {
        "llm": {
            "model_id": "test-model",
            "base_url": "https://api.example.com",
            "timeout": 60,
            "max_retries": 2,
        }
    }
)


def _cfg(db: str) -> OmegaConf:
    return OmegaConf.create({"interview": {"db": db}})


class _FakeLLM:
    """不触网 stub：complete_sync 返回预置响应（同 test_stream_integration 的 FakeStreamLLM）。

    brief 原 _fake_llm 返回真实 DeepSeekClient（api.example.com），invoke 出题节点
    会真实触网失败；本测试只验证 checkpointer 持久化，用 stub 保证确定性与速度。
    """

    def __init__(self, response: str) -> None:
        self._response = response

    def complete_sync(self, api_key, prompt, callbacks=None):
        return self._response, {}


def _fake_llm(response: str):
    return _FakeLLM(response)


def test_sqlite_checkpointer_persists_across_restart(tmp_path):
    """P2-3 核心：图状态落盘，重建 checkpointer 后状态完整恢复。"""
    db = tmp_path / "interview.db"
    c1 = create_checkpointer(_cfg(str(db)))
    graph = compile_graph(_fake_llm('{"question": "题1", "topic": "基础"}'), checkpointer=c1)
    config = {"configurable": {"thread_id": "s-1"}}
    init = initial_state(scene="fulltime", question_count=10, kb_id="kb-1")
    init["_api_key"] = "sk-test123"
    graph.invoke(init, config)

    # 模拟重启：新建 checkpointer 读同一文件
    c2 = create_checkpointer(_cfg(str(db)))
    graph2 = compile_graph(_fake_llm('{"question": "题2", "topic": "进阶"}'), checkpointer=c2)
    values = graph2.get_state(config).values
    assert values is not None
    assert values["kb_id"] == "kb-1"
    assert values["question_count"] == 10


def test_sqlite_checkpointer_delete_thread(tmp_path):
    db = tmp_path / "interview.db"
    c1 = create_checkpointer(_cfg(str(db)))
    graph = compile_graph(_fake_llm('{"question": "题1", "topic": "基础"}'), checkpointer=c1)
    config = {"configurable": {"thread_id": "s-2"}}
    init = initial_state(scene="intern", question_count=5)
    init["_api_key"] = "sk-test123"
    graph.invoke(init, config)
    delete_thread(c1, "s-2")
    values = graph.get_state(config).values
    assert not values or not values.get("messages")


def test_checkpointer_fallback_memory():
    """未传 cfg 时回退 MemorySaver（既有 P0 测试兼容）。"""
    c = create_checkpointer()
    from langgraph.checkpoint.memory import MemorySaver

    assert isinstance(c, MemorySaver)
