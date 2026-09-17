"""SSE 对话端点：流式 token / status / heartbeat / done / error + 全局单流式锁。

与 LangGraph 图的交互（分次调用）：
- 首次 POST（无 answer）：initial_state → graph 跑 opening → ask_question → END 暂停
- 后续 POST（有 answer）：注入回答 → graph 跑 evaluate → 路由 → ask_question/follow_up → END 暂停
- 最后一次（evaluate → report）：graph 跑 report → END 结束
- checkpointer 按 thread_id 自动保存/恢复状态
- 任何异常路径必须释放单流式锁

流式约定（TokenStreamHandler 路由）：
- 每次请求首事件先发 status(thinking)「正在思考…」占位，覆盖 prefill/评估静默期
- 题干（ask_question）：逐 token 转发，并截断末尾「【主题】」标记行
- 追问（follow_up）：逐 token 转发
- 评估（evaluate）：评分 JSON，不转发
- 报告（report）：不逐 token 转发；开始生成时先发 status(report)「报告生成中...」，
  生成完成后由本模块一次性输出全文（token → done(finished)）
- 图执行期间 15s 无事件时发 heartbeat 保活
- 无流式 token（如测试 mock）时回退：从 checkpointer 状态提取最新 AI 消息"""

import asyncio
import json
import time
import traceback
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage

from app.api.deps import get_key_store, get_llm_client, get_session, get_session_store
from app.interview.nodes import ask_question_node, report_node
from app.interview.prompts.hint import HINT
from app.interview.prompts.opening import OPENING_TEXT
from app.interview.state import initial_state
from app.llm.client import DeepSeekClient
from app.llm.keys import KeyStore
from app.logging import logger
from app.store.sessions import InMemorySessionStore, SessionMeta

router = APIRouter(prefix="/chat", tags=["chat"])

# 全局单流式锁（进程内，asyncio 协程级互斥）
_stream_lock = asyncio.Lock()

# 心跳间隔（秒）
HEARTBEAT_INTERVAL = 15

# 节点 run 名集合（用于回调 run 树溯源）
_NODE_NAMES = frozenset({"opening", "ask_question", "evaluate", "follow_up", "report"})

# 题干输出中的主题标记行，流式时截断
_MARKER = "【主题】"


def _sse_event(event: str, data: dict) -> bytes:
    """格式化 SSE 事件。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


async def _single_event(event: str, data: dict) -> AsyncIterator[bytes]:
    """单个 SSE 事件生成器（用于排队提示等单次响应）。"""
    yield _sse_event(event, data)


def _extract_latest_ai(messages: list) -> str | None:
    """从 messages 中提取最新的 AIMessage 内容。"""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            if msg.content:
                return msg.content
        elif isinstance(msg, dict) and msg.get("role") == "assistant":
            content = msg.get("content", "")
            if content:
                return content
    return None


class TokenStreamHandler(BaseCallbackHandler):
    """把节点内 LLM 的逐 token 转发到 asyncio 队列，按节点名路由。

    - ask_question：转发并截断「【主题】」标记行
    - follow_up：转发
    - evaluate / report：不转发（报告触发时先发 status 占位）
    fixed_node：非图路径（skip 出题）时固定节点名，跳过 run 树溯源。
    """

    def __init__(
        self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, fixed_node: str | None = None
    ) -> None:
        self._loop = loop
        self._q = queue
        self._fixed_node = fixed_node
        self._chains: dict[str, str] = {}
        self._parents: dict[str, str | None] = {}
        self._llm_nodes: dict[str, str] = {}
        self._forwarded: dict[str, int] = {}
        self._report_notified = False
        self._marker_seen = False
        self._marker_buf = ""
        self._marker_emitted = 0

    # --- 内部 ---

    def _put(self, item: tuple) -> None:
        self._loop.call_soon_threadsafe(self._q.put_nowait, item)

    def _resolve_node(self, run_id: str | None) -> str:
        """从 LLM run 的父链溯源到节点名（run 树：LangGraph → 节点 → LLM）。"""
        if self._fixed_node:
            return self._fixed_node
        seen: set[str] = set()
        while run_id and run_id not in seen:
            seen.add(run_id)
            name = self._chains.get(run_id, "")
            if name in _NODE_NAMES:
                return name
            run_id = self._parents.get(run_id)
        return ""

    def _strip_marker(self, token: str) -> str | None:
        """题干流式截断：命中「【主题】」后不再转发（标记可能跨 token 到达）。

        命中时 marker 前的残留内容去掉行尾换行（该换行属于标记行）。
        """
        if self._marker_seen:
            return None
        self._marker_buf += token
        idx = self._marker_buf.find(_MARKER)
        if idx >= 0:
            self._marker_seen = True
            head = self._marker_buf[:idx].rstrip("\n")
            out = head[self._marker_emitted :] or None
            self._marker_emitted = len(head)
            return out
        out = self._marker_buf[self._marker_emitted :] or None
        self._marker_emitted = len(self._marker_buf)
        return out

    # --- 回调 ---

    def on_chain_start(
        self,
        serialized,
        inputs,
        *,
        run_id,
        parent_run_id,
        tags,
        metadata,
        run_type=None,
        name=None,
        **kwargs,
    ) -> None:
        rid = str(run_id)
        self._chains[rid] = str(name)
        self._parents[rid] = str(parent_run_id) if parent_run_id else None

    def on_llm_start(
        self, serialized, prompts, *, run_id, parent_run_id, tags, metadata, **kwargs
    ) -> None:
        node = self._resolve_node(str(parent_run_id) if parent_run_id else None)
        self._llm_nodes[str(run_id)] = node
        if node == "report" and not self._report_notified:
            self._report_notified = True
            self._put(("status", {"kind": "report", "message": "报告生成中，请稍候…"}))

    def on_llm_new_token(self, token, *, chunk=None, run_id, parent_run_id, tags, **kwargs) -> None:
        if not token:
            return
        node = self._llm_nodes.get(str(run_id), "")
        if node == "ask_question":
            out = self._strip_marker(token)
        elif node in ("follow_up", ""):
            out = token
        else:  # evaluate / report / opening（无 LLM）
            out = None
        if out:
            self._forwarded[node] = self._forwarded.get(node, 0) + 1
            self._put(("token", out))

    def forwarded(self, node: str) -> int:
        """某节点已转发的 token 数（=0 表示流式未产生内容，需回退取 state）。"""
        return self._forwarded.get(node, 0)


def _item_to_sse(item: tuple) -> bytes:
    kind, payload = item
    if kind == "status":
        return _sse_event("status", payload)
    return _sse_event("token", {"content": payload})


def _take_or_cancel(getter: asyncio.Task) -> tuple | None:
    """取队列项：getter 已完成则取结果（竞态兜底），否则取消并返回 None。"""
    if getter.done():
        return getter.result()
    getter.cancel()
    try:
        return getter.result()
    except asyncio.CancelledError, asyncio.InvalidStateError:
        return None


async def _stream_task(
    task: asyncio.Task, queue: asyncio.Queue, heartbeat: float = HEARTBEAT_INTERVAL
) -> AsyncIterator[bytes]:
    """转发后台任务产出的事件，空闲 heartbeat 秒发心跳；任务完成后排空队列。

    调用方须在 async for 结束后调用 task.result() 取结果/重抛异常。
    """
    while True:
        getter = asyncio.create_task(queue.get())
        done, _ = await asyncio.wait(
            {task, getter}, return_when=asyncio.FIRST_COMPLETED, timeout=heartbeat
        )
        if not done:
            _take_or_cancel(getter)
            yield _sse_event("heartbeat", {"ts": int(time.time())})
            continue
        if getter in done:
            yield _item_to_sse(getter.result())
        if task in done:
            if getter not in done:
                item = _take_or_cancel(getter)
                if item:
                    yield _item_to_sse(item)
            break
    while True:
        try:
            yield _item_to_sse(queue.get_nowait())
        except asyncio.QueueEmpty:
            break


@router.post("/{session_id}")
async def chat(
    session_id: str,
    request: Request,
    session: SessionMeta = Depends(get_session),
    llm: DeepSeekClient = Depends(get_llm_client),
    key_store: KeyStore = Depends(get_key_store),
    session_store: InMemorySessionStore = Depends(get_session_store),
):
    """SSE 对话端点：接收用户回答，流式返回 LLM 回复。"""

    # 单流式锁：已有回复进行中 → 立即返回排队提示
    if _stream_lock.locked():
        return StreamingResponse(
            _single_event("error", {"message": "上一回复生成中，请稍候"}),
            media_type="text/event-stream",
        )

    body = await request.json()
    answer = body.get("answer")
    action = body.get("action")  # "hint" | "skip"

    async def event_stream():
        async with _stream_lock:
            try:
                # 获取会话的 API Key 快照
                api_key = key_store.get(session_id)
                if not api_key:
                    yield _sse_event("error", {"message": "会话 Key 缺失"})
                    return

                # 首事件占位：LLM prefill/评估等静默期，前端据此展示「正在思考…」
                yield _sse_event("status", {"kind": "thinking"})

                compiled = request.app.state.compiled_graph
                config = {"configurable": {"thread_id": session_id}}

                # 检查 checkpointer 是否已有状态
                state_snapshot = await asyncio.to_thread(compiled.get_state, config)
                has_state = state_snapshot.values and state_snapshot.values.get("messages")
                prev_scores = (state_snapshot.values or {}).get("scores") or []

                loop = asyncio.get_running_loop()
                queue: asyncio.Queue = asyncio.Queue()
                handler: TokenStreamHandler | None = None

                if not has_state:
                    # 首次调用：开场白（可选）后出题，题干流式
                    if not session.get("skip_opening", False):
                        yield _sse_event("token", {"content": OPENING_TEXT})
                    init = initial_state(
                        scene=session["scene"],
                        question_count=session["question_count"],
                        skip_opening=session.get("skip_opening", False),
                        kb_id=session.get("kb_id"),
                        resume_id=session.get("resume_id"),
                        interview_type=session.get("interview_type", "technical"),
                    )
                    init["_api_key"] = api_key
                    handler = TokenStreamHandler(loop, queue)
                    task = asyncio.create_task(
                        asyncio.to_thread(compiled.invoke, init, {**config, "callbacks": [handler]})
                    )
                    async for frame in _stream_task(task, queue):
                        yield frame
                    task.result()
                elif answer:
                    # 提交回答：图跑 evaluate（JSON 不转发）→ 追问/下一题流式，或 report
                    handler = TokenStreamHandler(loop, queue)
                    task = asyncio.create_task(
                        asyncio.to_thread(
                            compiled.invoke,
                            {"messages": [HumanMessage(content=answer)], "_api_key": api_key},
                            {**config, "callbacks": [handler]},
                        )
                    )
                    async for frame in _stream_task(task, queue):
                        yield frame
                    task.result()
                elif action == "hint":
                    # 提示一下：直接调 LLM 生成提示（不走图），每题限 1 次
                    state_snapshot = await asyncio.to_thread(compiled.get_state, config)
                    state = state_snapshot.values
                    if not state or not state.get("current_question"):
                        yield _sse_event("error", {"message": "当前没有可提示的题目"})
                        return
                    if state.get("hints_used", 0) >= 1:
                        yield _sse_event("error", {"message": "本题已使用过提示"})
                        return
                    state["_api_key"] = api_key
                    scene = state.get("scene", "fulltime")
                    prompt = HINT.format(scene=scene, current_question=state["current_question"])
                    raw, _ = await llm.complete(api_key, [HumanMessage(content=prompt)], session_id)
                    await asyncio.to_thread(
                        compiled.update_state,
                        config,
                        {"hints_used": 1, "messages": [AIMessage(content=raw)]},
                    )
                elif action == "skip":
                    # 跳过此题：未作答不计分，推进题号；最后一题跳过 → 直接生成报告
                    state_snapshot = await asyncio.to_thread(compiled.get_state, config)
                    state = state_snapshot.values
                    if not state or state.get("status") == "finished":
                        yield _sse_event("error", {"message": "面试已结束"})
                        return
                    state["_api_key"] = api_key
                    next_index = state.get("question_index", 0) + 1
                    if next_index >= state.get("question_count", 10):
                        # 最后一题跳过 → 报告（占位 + 一次性输出）
                        yield _sse_event(
                            "status", {"kind": "report", "message": "报告生成中，请稍候…"}
                        )
                        result = await asyncio.to_thread(report_node, state, llm)
                        await asyncio.to_thread(compiled.update_state, config, result)
                        session_store.update_status(session_id, "finished")
                        yield _sse_event(
                            "token", {"content": result.get("_report", "面试报告不可用")}
                        )
                        qi = state.get("question_index", 0)
                        yield _sse_event(
                            "done", {"node": "report", "finished": True, "question_index": qi}
                        )
                        return
                    # 出下一题：不走图，直接调节点并流式转发题干
                    state["question_index"] = next_index
                    state["hints_used"] = 0
                    state["followups"] = 0
                    handler = TokenStreamHandler(loop, queue, fixed_node="ask_question")
                    task = asyncio.create_task(
                        asyncio.to_thread(
                            ask_question_node,
                            state,
                            llm,
                            [handler],
                            request.app.state.retrieval,
                            request.app.state.resume_store,
                            request.app.state.config,
                        )
                    )
                    async for frame in _stream_task(task, queue):
                        yield frame
                    result = task.result()
                    result["question_index"] = next_index
                    await asyncio.to_thread(compiled.update_state, config, result)

                # 获取更新后的状态
                state_snapshot = await asyncio.to_thread(compiled.get_state, config)
                state = state_snapshot.values

                # 检查图是否已结束（报告已由流式阶段占位，此处一次性输出全文）
                if state.get("status") == "finished":
                    session_store.update_status(session_id, "finished")
                    report = state.get("_report", "面试报告不可用")
                    yield _sse_event("token", {"content": report})
                    qi = state.get("question_index", 0)
                    yield _sse_event(
                        "done", {"node": "report", "finished": True, "question_index": qi}
                    )
                    return

                # 暂停点产出的内容：已流式则不重复；无 token（mock/兜底）从 state 提取
                node_name = "ask_question" if state.get("current_question") else "follow_up"
                if handler is None or handler.forwarded(node_name) == 0:
                    latest_ai = _extract_latest_ai(state.get("messages", []))
                    if latest_ai:
                        yield _sse_event("token", {"content": latest_ai})
                # 出题引用的知识来源：随题干一起下发，前端渲染来源折叠
                citations = state.get("_citations") or []
                if node_name == "ask_question" and citations:
                    yield _sse_event("citations", {"citations": citations})
                qi = state.get("question_index", 0)
                yield _sse_event("done", {"node": node_name, "question_index": qi})

                # 评估结果下发：仅 answer 路径（evaluate 节点执行）且 scores 有新增
                if answer and not action:
                    final_scores = state.get("scores") or []
                    if len(final_scores) > len(prev_scores):
                        last = final_scores[-1]
                        yield _sse_event(
                            "assess",
                            {
                                "dimensions": last.get("dimensions", {}),
                                "comment": last.get("comment", ""),
                                "score": last.get("score", 0),
                                "citations": last.get("citations", []),
                                "verification": last.get("verification"),
                            },
                        )

            except Exception as e:
                logger.error("chat error: {err}\n{tb}", err=repr(e), tb=traceback.format_exc())
                yield _sse_event("error", {"message": "服务异常，请重试"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
