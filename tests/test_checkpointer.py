from pathlib import Path

from langchain_core.messages import HumanMessage
from omegaconf import OmegaConf

from app.interview.graph import compile_graph
from app.interview.nodes import report_node
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


# --- 最终审查修复轮（MAJOR：API Key 明文不得落盘）---

SECRET = "sk-testkey123456"


class _SeqLLM:
    """按序返回预置响应（evaluate / ask_question 各一次）。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete_sync(self, api_key, prompt, callbacks=None):
        self.calls += 1
        idx = min(self.calls - 1, len(self._responses) - 1)
        return self._responses[idx], {}


_EVAL_JSON = (
    '{"score": {"技术深度": 7}, "comment": "正确", "needs_followup": false, "followup_reason": ""}'
)
_QUESTION_JSON = '{"question": "什么是多态", "topic": "OOP"}'


def _disk_bytes(db: Path) -> bytes:
    """扫描 SQLite 库文件 + WAL/SHM 侧车文件的原始字节（含未 checkpoint 的已提交数据）。"""
    return b"".join(p.read_bytes() for p in sorted(db.parent.glob(f"{db.name}*")) if p.is_file())


def test_checkpoint_raw_bytes_exclude_api_key(tmp_path):
    """invoke + update_state 两条落盘路径都不得出现 `_api_key` 或 `sk-` 明文。

    SqliteSaver.setup 开启 `PRAGMA journal_mode=WAL`，已提交数据先落在 -wal 侧车文件，
    故须扫描库文件 + -wal/-shm 全部原始字节（这就是磁盘上真实存在的内容）。
    """
    db = tmp_path / "interview.db"
    c1 = create_checkpointer(_cfg(str(db)))
    graph = compile_graph(_fake_llm(_QUESTION_JSON), checkpointer=c1)
    config = {"configurable": {"thread_id": "s-secret"}}

    init = initial_state(scene="intern", question_count=5)
    init["_api_key"] = SECRET
    graph.invoke(init, config)
    graph.update_state(config, {"_api_key": SECRET, "hints_used": 1})

    raw = _disk_bytes(db)
    assert raw  # 确认确实扫到了落盘内容（避免空文件导致假通过）
    assert b"_api_key" not in raw
    assert b"sk-" not in raw
    assert SECRET.encode() not in raw


def test_state_channel_key_absent_after_restart(tmp_path):
    """落盘脱敏后：重建 checkpointer 读回的状态不含 _api_key，其余字段完整。"""
    db = tmp_path / "interview.db"
    c1 = create_checkpointer(_cfg(str(db)))
    graph = compile_graph(_fake_llm(_QUESTION_JSON), checkpointer=c1)
    config = {"configurable": {"thread_id": "s-restart"}}
    init = initial_state(scene="intern", question_count=5, kb_id="kb-9")
    init["_api_key"] = SECRET
    graph.invoke(init, config)

    c2 = create_checkpointer(_cfg(str(db)))
    values = compile_graph(_fake_llm(_QUESTION_JSON), checkpointer=c2).get_state(config).values
    assert values["kb_id"] == "kb-9"
    assert values["current_question"]
    assert "_api_key" not in values


def test_resume_and_report_after_restart_with_injected_key(tmp_path):
    """模拟重启后续聊：Key 由调用方注入 → evaluate / ask_question 不因缺 Key 报错；
    report 路径（skip-last / finish 场景）同样由调用方注入 Key。"""
    db = tmp_path / "interview.db"
    c1 = create_checkpointer(_cfg(str(db)))
    compile_graph(_fake_llm(_QUESTION_JSON), checkpointer=c1).invoke(
        {**initial_state(scene="intern", question_count=5), "_api_key": SECRET},
        {"configurable": {"thread_id": "s-continue"}},
    )

    # 重启：新 checkpointer + 新图，续聊（回答 → evaluate → ask_question）
    config = {"configurable": {"thread_id": "s-continue"}}
    c2 = create_checkpointer(_cfg(str(db)))
    llm = _SeqLLM([_EVAL_JSON, _QUESTION_JSON])
    graph2 = compile_graph(llm, checkpointer=c2)
    graph2.invoke(
        {"messages": [HumanMessage(content="多态是同一接口不同实现")], "_api_key": SECRET},
        config,
    )
    values = graph2.get_state(config).values
    assert len(values["scores"]) == 1
    assert values["question_index"] == 1
    assert "_api_key" not in values  # 仍未落盘

    # 报告路径（skip-last / finish：直接调节点 + update_state 写回）
    state = dict(values)
    state["_api_key"] = SECRET
    result = report_node(state, _fake_llm("面试报告正文"))
    graph2.update_state(config, result)
    assert graph2.get_state(config).values["_report"] == "面试报告正文"
    assert b"_api_key" not in db.read_bytes()
