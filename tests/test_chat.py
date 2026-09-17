import asyncio
import json
from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage

from app.api.chat import _extract_latest_ai, _sse_event, _stream_lock
from app.interview.graph import compile_graph
from app.main import app


def test_sse_event_format():
    data = _sse_event("token", {"content": "你好"})
    text = data.decode("utf-8")
    assert text.startswith("event: token\n")
    assert "data: " in text
    assert text.endswith("\n\n")
    payload = json.loads(text.split("data: ")[1].strip())
    assert payload["content"] == "你好"


def test_sse_event_heartbeat():
    data = _sse_event("heartbeat", {})
    text = data.decode("utf-8")
    assert "event: heartbeat" in text


def test_sse_event_error():
    data = _sse_event("error", {"message": "失败"})
    text = data.decode("utf-8")
    payload = json.loads(text.split("data: ")[1].strip())
    assert payload["message"] == "失败"


def test_sse_event_done():
    data = _sse_event("done", {"node": "ask_question"})
    text = data.decode("utf-8")
    payload = json.loads(text.split("data: ")[1].strip())
    assert payload["node"] == "ask_question"


def test_stream_lock_is_asyncio_lock():
    assert isinstance(_stream_lock, asyncio.Lock)


def test_extract_latest_ai_found():
    messages = [
        HumanMessage(content="用户回答"),
        AIMessage(content="面试题"),
    ]
    assert _extract_latest_ai(messages) == "面试题"


def test_extract_latest_ai_none():
    messages = [HumanMessage(content="只有用户消息")]
    assert _extract_latest_ai(messages) is None


def test_extract_latest_ai_empty():
    assert _extract_latest_ai([]) is None


def test_extract_latest_ai_dict_format():
    messages = [
        {"role": "user", "content": "answer"},
        {"role": "assistant", "content": "追问内容"},
    ]
    assert _extract_latest_ai(messages) == "追问内容"


async def test_chat_404_missing_session():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat/nonexistent",
                json={"answer": "test"},
            )
            assert resp.status_code == 404


async def test_health():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}


async def test_chat_first_call_initializes_state():
    """首次调用（无 answer）：mock LLM → opening + ask_question 执行 → 返回题干。"""
    async with app.router.lifespan_context(app):
        # mock LLM complete_sync
        mock_llm = MagicMock()
        mock_llm.complete_sync = MagicMock(
            return_value=('{"question": "什么是多态", "topic": "OOP"}', {"total_tokens": 10})
        )
        app.state.compiled_graph = compile_graph(mock_llm, app.state.checkpointer)

        # 设置全局 Key + 新建会话
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            create_resp = await client.post(
                "/api/sessions", json={"scene": "intern", "question_count": 5}
            )
            session_id = create_resp.json()["id"]

            # 首次调用（无 answer）
            resp = await client.post(f"/api/chat/{session_id}", json={})
            assert resp.status_code == 200
            body = resp.content.decode("utf-8")
            assert "event: token" in body
            assert "event: done" in body
            assert "多态" in body


async def test_chat_second_call_injects_answer():
    """第二次调用（有 answer）：mock LLM → evaluate + ask_question 执行 → 返回新题。"""
    async with app.router.lifespan_context(app):
        call_count = [0]

        def mock_complete(api_key, prompt, callbacks=None):
            call_count[0] += 1
            if call_count[0] == 1:
                # ask_question（首次）
                return ('{"question": "什么是多态", "topic": "OOP"}', {"total_tokens": 10})
            elif call_count[0] == 2:
                # evaluate
                return (
                    '{"score": {"技术深度": 7, "表达清晰度": 6, "问题解决": 6, "项目经验": 5}, '
                    '"comment": "回答基本正确", "needs_followup": false, "followup_reason": ""}',
                    {"total_tokens": 20},
                )
            else:
                # ask_question（第 2 题）
                return (
                    '{"question": "请介绍你的项目", "topic": "项目经验"}',
                    {"total_tokens": 10},
                )

        mock_llm = MagicMock()
        mock_llm.complete_sync = mock_complete
        app.state.compiled_graph = compile_graph(mock_llm, app.state.checkpointer)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            create_resp = await client.post(
                "/api/sessions", json={"scene": "intern", "question_count": 5}
            )
            session_id = create_resp.json()["id"]

            # 首次调用
            await client.post(f"/api/chat/{session_id}", json={})
            # 第二次调用（回答）
            resp = await client.post(
                f"/api/chat/{session_id}", json={"answer": "多态是同一接口不同实现"}
            )
            assert resp.status_code == 200
            body = resp.content.decode("utf-8")
            assert "event: token" in body
            assert "项目" in body
