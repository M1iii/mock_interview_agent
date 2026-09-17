"""TokenStreamHandler 单元测试 + _stream_task 心跳测试。"""

import asyncio

from app.api.chat import TokenStreamHandler, _stream_task


async def _drain(queue: asyncio.Queue) -> list:
    for _ in range(5):
        await asyncio.sleep(0)
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def _register(h: TokenStreamHandler, run_id: str = "r") -> None:
    """模拟 LangChain 流程：LLM run 开始（fixed_node 模式下直接注册节点）。"""
    h.on_llm_start({}, ["prompt"], run_id=run_id, parent_run_id=None, tags=[], metadata={})


# --- fixed_node: ask_question ---


async def test_ask_question_streams_and_strips_marker():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    h = TokenStreamHandler(loop, queue, fixed_node="ask_question")
    _register(h)
    for t in ["请", "介绍", "你的", "项目", "\n", "【主题】", "项目经验"]:
        h.on_llm_new_token(t, run_id="r", parent_run_id=None, tags=[])
    items = await _drain(queue)
    joined = "".join(payload for _, payload in items)
    assert joined.rstrip("\n") == "请介绍你的项目"
    assert not any("【主题】" in payload for _, payload in items)


async def test_ask_question_marker_split_across_tokens():
    """marker 与行首换行落在同一 token 中时，残留的换行也被清理。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    h = TokenStreamHandler(loop, queue, fixed_node="ask_question")
    _register(h)
    for t in ["什么", "是多", "态", "\n【主题】", "OOP"]:
        h.on_llm_new_token(t, run_id="r", parent_run_id=None, tags=[])
    items = await _drain(queue)
    joined = "".join(payload for _, payload in items)
    assert joined == "什么是多态"
    assert not any("【主题】" in payload for _, payload in items)


async def test_ask_question_marks_stops_forwarding():
    """marker 命中后（含命中当次）不再转发任何 token。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    h = TokenStreamHandler(loop, queue, fixed_node="ask_question")
    _register(h)
    for t in ["题目", "\n【主题】A", "B", "C"]:
        h.on_llm_new_token(t, run_id="r", parent_run_id=None, tags=[])
    items = await _drain(queue)
    joined = "".join(payload for _, payload in items)
    assert joined == "题目"
    assert h.forwarded("ask_question") == 1


async def test_follow_up_streams_all_tokens():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    h = TokenStreamHandler(loop, queue, fixed_node="follow_up")
    _register(h)
    for t in ["请", "详细", "说明"]:
        h.on_llm_new_token(t, run_id="r", parent_run_id=None, tags=[])
    items = await _drain(queue)
    assert items == [("token", "请"), ("token", "详细"), ("token", "说明")]


async def test_evaluate_does_not_forward():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    h = TokenStreamHandler(loop, queue, fixed_node="evaluate")
    _register(h)
    h.on_llm_new_token("评分JSON", run_id="r", parent_run_id=None, tags=[])
    items = await _drain(queue)
    assert items == []


async def test_empty_token_ignored():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    h = TokenStreamHandler(loop, queue, fixed_node="ask_question")
    _register(h)
    h.on_llm_new_token("", run_id="r", parent_run_id=None, tags=[])
    items = await _drain(queue)
    assert items == []


# --- run 树溯源（无 fixed_node）---


async def test_resolves_node_from_run_tree():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    h = TokenStreamHandler(loop, queue)
    h.on_chain_start(
        {}, {}, run_id="g1", parent_run_id=None, tags=[], metadata={}, name="LangGraph"
    )
    h.on_chain_start(
        {}, {}, run_id="n1", parent_run_id="g1", tags=[], metadata={}, name="ask_question"
    )
    h.on_llm_start({}, ["prompt"], run_id="l1", parent_run_id="n1", tags=[], metadata={})
    for t in ["问", "题", "\n【主题】OS"]:
        h.on_llm_new_token(t, run_id="l1", parent_run_id="n1", tags=[])
    items = await _drain(queue)
    joined = "".join(payload for _, payload in items)
    assert joined == "问题"
    assert h.forwarded("ask_question") == 2


async def test_report_emits_status_once_and_no_tokens():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    h = TokenStreamHandler(loop, queue)
    h.on_chain_start(
        {}, {}, run_id="g1", parent_run_id=None, tags=[], metadata={}, name="LangGraph"
    )
    h.on_chain_start({}, {}, run_id="n1", parent_run_id="g1", tags=[], metadata={}, name="report")
    h.on_llm_start({}, ["prompt"], run_id="l1", parent_run_id="n1", tags=[], metadata={})
    h.on_llm_new_token("报告全文", run_id="l1", parent_run_id="n1", tags=[])
    items = await _drain(queue)
    assert items == [("status", {"kind": "report", "message": "报告生成中，请稍候…"})]


# --- _stream_task 心跳 ---


async def test_stream_task_heartbeat_when_idle():
    queue: asyncio.Queue = asyncio.Queue()

    async def slow_task():
        await asyncio.sleep(0.3)
        return "ok"

    task = asyncio.create_task(slow_task())
    frames: list[bytes] = []
    async for frame in _stream_task(task, queue, heartbeat=0.05):
        frames.append(frame)
    task.result()
    texts = [f.decode("utf-8") for f in frames]
    assert any("event: heartbeat" in t for t in texts)


async def test_stream_task_forwards_queue_and_result():
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    async def emit():
        await asyncio.sleep(0.02)
        loop.call_soon_threadsafe(queue.put_nowait, ("token", "内容"))
        await asyncio.sleep(0.02)
        return "ok"

    task = asyncio.create_task(emit())
    frames: list[bytes] = []
    async for frame in _stream_task(task, queue, heartbeat=0.1):
        frames.append(frame)
    assert task.result() == "ok"
    texts = "".join(f.decode("utf-8") for f in frames)
    assert "event: token" in texts
    assert "内容" in texts
