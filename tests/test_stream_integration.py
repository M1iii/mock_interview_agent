"""流式集成测试：skip 出题逐 token / 报告占位 + 一次性输出（SSE 端点）。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.interview.graph import compile_graph
from app.main import app
from app.retrieval.retrieve import NORMAL, Citation, RetrievalResult


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """解析 SSE 响应体为 (event, data) 列表。"""
    events: list[tuple[str, dict]] = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        name = ""
        data = ""
        for line in frame.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if name and data:
            events.append((name, json.loads(data)))
    return events


class FakeStreamLLM:
    """complete_sync 触发回调逐 token 转发，模拟真实 LLM 流式输出。

    token_chunks：按「带 callbacks 的调用」顺序指定切分（默认逐字符）。
    图路径下 LangGraph 不会把 config callbacks 注入节点显式参数，因此
    complete_sync 仅在调用方显式传 callbacks 时才触发流式转发。
    """

    def __init__(
        self,
        responses: list[tuple[str, dict]],
        token_chunks: list[list[str]] | None = None,
    ):
        self._responses = list(responses)
        self._chunks = list(token_chunks) if token_chunks else None
        self.complete = AsyncMock(return_value=("提示内容", {}))
        self.call_count = 0

    def complete_sync(self, api_key, prompt, callbacks=None):
        text, usage = self._responses.pop(0)
        self.call_count += 1
        if callbacks:
            cbs = callbacks if isinstance(callbacks, list) else [callbacks]
            chunks = self._chunks.pop(0) if self._chunks else list(text)
            for cb in cbs:
                # 模拟 LangChain 流程：LLM run 开始（fixed_node 模式下注册节点名）
                cb.on_llm_start({}, [prompt], run_id="l1", parent_run_id=None, tags=[], metadata={})
                for t in chunks:
                    cb.on_llm_new_token(t, chunk=None, run_id="l1", parent_run_id=None, tags=[])
        return text, usage


async def _make_session(client) -> str:
    await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
    resp = await client.post("/api/sessions", json={"scene": "intern", "question_count": 5})
    return resp.json()["id"]


async def test_skip_next_question_streams_tokens():
    """skip：下一题题干逐 token 转发，且「【主题】」标记行被截断。"""
    async with app.router.lifespan_context(app):
        llm = FakeStreamLLM(
            responses=[
                ('{"question": "首题", "topic": "基础"}', {}),
                ("第二题\n【主题】进阶", {}),
            ],
            token_chunks=[
                ["第二题", "\n", "【主题】进阶"],
            ],
        )
        app.state.llm_client = llm
        app.state.compiled_graph = compile_graph(llm, app.state.checkpointer)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            session_id = await _make_session(client)
            await client.post(f"/api/chat/{session_id}", json={})

            resp = await client.post(f"/api/chat/{session_id}", json={"action": "skip"})
            events = _parse_sse(resp.content.decode("utf-8"))
            assert events[0] == ("status", {"kind": "thinking"})  # 静默期占位先发
            token_events = [d for name, d in events if name == "token"]
            joined = "".join(d["content"] for d in token_events)
            assert len(token_events) >= 2  # 逐 token 而非单次
            assert joined.rstrip("\n") == "第二题"
            assert "【主题】" not in joined
            assert any(name == "done" for name, _ in events)


async def test_skip_last_question_status_then_full_report():
    """skip 最后一题：先发「报告生成中」占位，再一次性输出报告全文 + done(finished)。"""
    async with app.router.lifespan_context(app):
        report_text = "# 面试报告\n\n总分：80\n\n## 四维分项"
        llm = FakeStreamLLM(
            responses=[('{"question": "题", "topic": "基础"}', {})] * 5 + [(report_text, {})]
        )
        app.state.llm_client = llm
        app.state.compiled_graph = compile_graph(llm, app.state.checkpointer)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            session_id = await _make_session(client)
            await client.post(f"/api/chat/{session_id}", json={})
            for _ in range(4):
                await client.post(f"/api/chat/{session_id}", json={"action": "skip"})

            resp = await client.post(f"/api/chat/{session_id}", json={"action": "skip"})
            events = _parse_sse(resp.content.decode("utf-8"))
            statuses = [d for name, d in events if name == "status"]
            tokens = [d for name, d in events if name == "token"]
            dones = [d for name, d in events if name == "done"]
            assert [d["kind"] for d in statuses] == ["thinking", "report"]
            assert "报告生成中" in statuses[-1]["message"]
            assert len(tokens) == 1  # 报告一次性输出，不逐 token
            assert tokens[0]["content"] == report_text
            assert dones and dones[0].get("finished") is True


async def test_answer_emits_assess_event():
    """answer：评估完成后下发 assess 事件（维度/评语/得分），首调无 assess。"""
    async with app.router.lifespan_context(app):
        llm = FakeStreamLLM(
            responses=[
                ('{"question": "首题", "topic": "基础"}', {}),
                (
                    '{"score": {"技术深度": 7, "表达清晰度": 6, "问题解决": 5, "项目经验": 4}, '
                    '"comment": "概念正确，需深入", '
                    '"needs_followup": false, "followup_reason": ""}',
                    {},
                ),
                ('{"question": "第二题", "topic": "进阶"}', {}),
            ]
        )
        app.state.llm_client = llm
        app.state.compiled_graph = compile_graph(llm, app.state.checkpointer)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            session_id = await _make_session(client)

            # 首调：无评估，不发 assess
            resp = await client.post(f"/api/chat/{session_id}", json={})
            events = _parse_sse(resp.content.decode("utf-8"))
            assert not any(name == "assess" for name, _ in events)

            # 回答：评估后下发 assess（dimensions/comment/score）
            resp = await client.post(
                f"/api/chat/{session_id}", json={"answer": "多态是同一接口不同实现"}
            )
            events = _parse_sse(resp.content.decode("utf-8"))
            assesses = [d for name, d in events if name == "assess"]
            assert len(assesses) == 1
            assert assesses[0]["dimensions"] == {
                "技术深度": 7,
                "表达清晰度": 6,
                "问题解决": 5,
                "项目经验": 4,
            }
            assert assesses[0]["comment"] == "概念正确，需深入"
            assert assesses[0]["score"] == 5.5


async def test_assess_event_includes_citations_when_present():
    """answer + kb 会话：assess 事件透传出题节点检索写入的 citations（端到端）。

    真实 SSE 端点 + 真实图 + 真实 checkpointer，仅 patch 检索函数。
    """
    async with app.router.lifespan_context(app):
        llm = FakeStreamLLM(
            responses=[
                ('{"question": "请解释缓存穿透", "topic": "缓存"}', {}),
                (
                    '{"score": {"技术深度": 7, "表达清晰度": 6, "问题解决": 5, "项目经验": 4}, '
                    '"comment": "概念正确，需结合资料深入", '
                    '"needs_followup": false, "followup_reason": ""}',
                    {},
                ),
                ('{"question": "第二题", "topic": "进阶"}', {}),
            ]
        )
        result = RetrievalResult(level=NORMAL)
        result.citations = [
            Citation(
                file_id=f"f{i}",
                file_name=f"doc{i}.md",
                parent_id=f"p{i}",
                text=f"Redis 缓存穿透的内容片段 {i}，用于构造题目背景信息。",
                score=round(0.95 - i * 0.1, 2),
            )
            for i in range(3)
        ]
        app.state.llm_client = llm
        app.state.compiled_graph = compile_graph(llm, app.state.checkpointer, retrieval=MagicMock())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            resp = await client.post(
                "/api/sessions", json={"scene": "intern", "question_count": 5, "kb_id": "kb-1"}
            )
            session_id = resp.json()["id"]

            with patch("app.interview.nodes.retrieve", return_value=result):
                # 首调：无评估，不发 assess（出题检索写入 _citations）
                resp = await client.post(f"/api/chat/{session_id}", json={})
                events = _parse_sse(resp.content.decode("utf-8"))
                assert not any(name == "assess" for name, _ in events)

                # 回答：评估后 assess 携带 score 中写入的 citations
                resp = await client.post(
                    f"/api/chat/{session_id}", json={"answer": "缓存穿透是查询不存在的数据"}
                )
                events = _parse_sse(resp.content.decode("utf-8"))
                assesses = [d for name, d in events if name == "assess"]
                assert len(assesses) == 1
                cites = assesses[0]["citations"]
                assert len(cites) == 3
                assert cites[0] == {
                    "file_name": "doc0.md",
                    "text": "Redis 缓存穿透的内容片段 0，用于构造题目背景信息。",
                    "score": 0.95,
                }
                assert cites[1]["file_name"] == "doc1.md"
                assert cites[2]["text"] == "Redis 缓存穿透的内容片段 2，用于构造题目背景信息。"


async def test_followup_round_emits_assess_each_time():
    """追问轮次：每次回答评估后都下发 assess（同题多轮各更新一次）。"""
    async with app.router.lifespan_context(app):
        llm = FakeStreamLLM(
            responses=[
                ('{"question": "首题", "topic": "基础"}', {}),
                (
                    '{"score": {"技术深度": 6}, "comment": "第一轮评价", '
                    '"needs_followup": true, "followup_reason": "深挖"}',
                    {},
                ),
                ("追问内容", {}),
                (
                    '{"score": {"技术深度": 8}, "comment": "第二轮评价", '
                    '"needs_followup": false, "followup_reason": ""}',
                    {},
                ),
                ('{"question": "第二题", "topic": "进阶"}', {}),
            ]
        )
        app.state.llm_client = llm
        app.state.compiled_graph = compile_graph(llm, app.state.checkpointer)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            session_id = await _make_session(client)
            await client.post(f"/api/chat/{session_id}", json={})

            resp = await client.post(f"/api/chat/{session_id}", json={"answer": "第一轮回答"})
            events = _parse_sse(resp.content.decode("utf-8"))
            assesses = [d for name, d in events if name == "assess"]
            assert len(assesses) == 1
            assert assesses[0]["comment"] == "第一轮评价"
            assert assesses[0]["dimensions"] == {"技术深度": 6}

            resp = await client.post(f"/api/chat/{session_id}", json={"answer": "第二轮回答"})
            events = _parse_sse(resp.content.decode("utf-8"))
            assesses = [d for name, d in events if name == "assess"]
            assert len(assesses) == 1
            assert assesses[0]["comment"] == "第二轮评价"
            assert assesses[0]["dimensions"] == {"技术深度": 8}
