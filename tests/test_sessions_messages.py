"""会话消息历史接口测试：GET /api/sessions/{id}/messages。"""

from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient

from app.interview.graph import compile_graph
from app.interview.prompts.opening import OPENING_TEXT
from app.main import app

QUESTION_JSON = '{"question": "什么是多态", "topic": "OOP"}'


async def _install_mock_and_session(client, llm=None) -> str:
    """安装 mock LLM（默认或自定义）并创建会话。"""
    if llm is None:
        llm = MagicMock()
        llm.complete_sync = MagicMock(return_value=(QUESTION_JSON, {"total_tokens": 10}))
    app.state.llm_client = llm
    app.state.compiled_graph = compile_graph(llm, app.state.checkpointer)
    await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
    resp = await client.post("/api/sessions", json={"scene": "intern", "question_count": 5})
    return resp.json()["id"]


async def test_messages_empty_for_new_session():
    """未开始对话：messages 为空。"""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            session_id = await _install_mock_and_session(client)
            resp = await client.get(f"/api/sessions/{session_id}/messages")
            assert resp.status_code == 200
            data = resp.json()
            assert data["messages"] == []
            assert data["status"] == "ongoing"
            assert data["hints_used"] == 0
            assert data["question_index"] == 0


async def test_messages_after_first_call():
    """首次调用后：含开场白 + 题干。"""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            session_id = await _install_mock_and_session(client)
            await client.post(f"/api/chat/{session_id}", json={})

            resp = await client.get(f"/api/sessions/{session_id}/messages")
            data = resp.json()
            roles = [m["role"] for m in data["messages"]]
            contents = "".join(m["content"] for m in data["messages"])
            assert roles == ["ai", "ai"]
            assert OPENING_TEXT[:20] in contents
            assert "多态" in contents
            assert data["question_index"] == 0


async def test_messages_after_answer():
    """回答后：含用户回答 + 下一题。"""
    async with app.router.lifespan_context(app):
        call_count = [0]

        def mock_complete(api_key, prompt, callbacks=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return (QUESTION_JSON, {})  # 首题
            if call_count[0] == 2:
                return (
                    '{"score": {"技术深度": 7, "表达清晰度": 6, "问题解决": 6, "项目经验": 5}, '
                    '"comment": "正确", "needs_followup": false, "followup_reason": ""}',
                    {},
                )  # evaluate
            return ('{"question": "请介绍项目", "topic": "项目经验"}', {})  # 第 2 题

        mock_llm = MagicMock()
        mock_llm.complete_sync = mock_complete

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            session_id = await _install_mock_and_session(client, llm=mock_llm)
            await client.post(f"/api/chat/{session_id}", json={})
            await client.post(f"/api/chat/{session_id}", json={"answer": "多态是同一接口不同实现"})

            resp = await client.get(f"/api/sessions/{session_id}/messages")
            data = resp.json()
            contents = "".join(m["content"] for m in data["messages"])
            roles = [m["role"] for m in data["messages"]]
            assert "user" in roles
            assert "多态是同一接口不同实现" in contents
            assert "请介绍项目" in contents
            assert data["question_index"] == 1


async def test_messages_404_missing_session():
    """不存在的会话 → 404。"""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/sessions/nonexistent/messages")
            assert resp.status_code == 404
