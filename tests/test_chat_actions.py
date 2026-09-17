"""hint / skip / skip_opening 交互测试（SSE 端点）。"""

from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from app.interview.graph import compile_graph
from app.interview.prompts.opening import OPENING_TEXT
from app.main import app

QUESTION_JSON = '{"question": "什么是多态", "topic": "OOP"}'


async def test_hint_returns_hint_and_locks_after_one():
    """hint：返回提示内容；第二次 hint 被拒绝（每题限 1 次）。"""
    async with app.router.lifespan_context(app):
        mock_llm = MagicMock()
        mock_llm.complete_sync = MagicMock(return_value=(QUESTION_JSON, {"total_tokens": 10}))
        app.state.llm_client = mock_llm
        app.state.compiled_graph = compile_graph(mock_llm, app.state.checkpointer)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            create_resp = await client.post(
                "/api/sessions", json={"scene": "intern", "question_count": 5}
            )
            session_id = create_resp.json()["id"]

            # 首次调用出题
            await client.post(f"/api/chat/{session_id}", json={})

            # hint 调用：mock 返回提示
            mock_llm.complete = AsyncMock(return_value=("提示：多态是一种接口多实现", {}))
            resp = await client.post(f"/api/chat/{session_id}", json={"action": "hint"})
            body = resp.content.decode("utf-8")
            assert "event: token" in body
            assert "提示：多态是一种接口多实现" in body

            # 第二次 hint 被拒绝
            resp2 = await client.post(f"/api/chat/{session_id}", json={"action": "hint"})
            body2 = resp2.content.decode("utf-8")
            assert "event: error" in body2
            assert "已使用过提示" in body2


async def test_skip_advances_to_next_question():
    """skip：未作答不计分，直接出下一题。"""
    async with app.router.lifespan_context(app):
        call_count = [0]

        def mock_complete(api_key, prompt, callbacks=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return (QUESTION_JSON, {"total_tokens": 10})  # 首题
            return ('{"question": "第二题", "topic": "基础"}', {"total_tokens": 10})  # skip 后

        mock_llm = MagicMock()
        mock_llm.complete_sync = mock_complete
        app.state.llm_client = mock_llm
        app.state.compiled_graph = compile_graph(mock_llm, app.state.checkpointer)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            create_resp = await client.post(
                "/api/sessions", json={"scene": "intern", "question_count": 5}
            )
            session_id = create_resp.json()["id"]

            await client.post(f"/api/chat/{session_id}", json={})
            resp = await client.post(f"/api/chat/{session_id}", json={"action": "skip"})
            body = resp.content.decode("utf-8")
            assert "event: token" in body
            assert "第二题" in body


async def test_skip_last_question_generates_report():
    """skip 最后一题：直接生成报告并结束。"""
    async with app.router.lifespan_context(app):
        call_count = [0]

        def mock_complete(api_key, prompt, callbacks=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return (QUESTION_JSON, {})  # 首题
            if call_count[0] == 6:
                return (
                    "# 面试报告\n\n总分：80\n\n## 四维分项",
                    {},
                )  # 第 6 次 = 最后一题跳过 → report
            return (QUESTION_JSON, {})  # 第 2-5 次：skip 后的新题

        mock_llm = MagicMock()
        mock_llm.complete_sync = mock_complete
        app.state.llm_client = mock_llm
        app.state.compiled_graph = compile_graph(mock_llm, app.state.checkpointer)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            # count=1 会被 Pydantic ge=5 拒绝，用 count=5 连续 skip
            create_resp = await client.post(
                "/api/sessions", json={"scene": "intern", "question_count": 5}
            )
            session_id = create_resp.json()["id"]

            await client.post(f"/api/chat/{session_id}", json={})
            # 第 1 次 skip → 第 2 题（mock 第 3 次调用）
            await client.post(f"/api/chat/{session_id}", json={"action": "skip"})
            # 第 2 次 skip → 第 3 题
            await client.post(f"/api/chat/{session_id}", json={"action": "skip"})
            # 第 3 次 skip → 第 4 题
            await client.post(f"/api/chat/{session_id}", json={"action": "skip"})
            # 第 4 次 skip → 第 5 题
            await client.post(f"/api/chat/{session_id}", json={"action": "skip"})
            # 第 5 次 skip → 最后一题跳过 → report
            resp = await client.post(f"/api/chat/{session_id}", json={"action": "skip"})
            body = resp.content.decode("utf-8")
            assert "event: done" in body
            assert "finished" in body
            assert "面试报告" in body


async def test_skip_opening_skips_opening_text():
    """skip_opening=true：首次调用直接出题，不出现开场白。"""
    async with app.router.lifespan_context(app):
        mock_llm = MagicMock()
        mock_llm.complete_sync = MagicMock(return_value=(QUESTION_JSON, {"total_tokens": 10}))
        app.state.compiled_graph = compile_graph(mock_llm, app.state.checkpointer)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            create_resp = await client.post(
                "/api/sessions",
                json={"scene": "intern", "question_count": 5, "skip_opening": True},
            )
            session_id = create_resp.json()["id"]

            resp = await client.post(f"/api/chat/{session_id}", json={})
            body = resp.content.decode("utf-8")
            assert "多态" in body
            assert OPENING_TEXT[:20] not in body


async def test_skip_opening_false_plays_opening():
    """skip_opening=false：首次调用包含开场白。"""
    async with app.router.lifespan_context(app):
        mock_llm = MagicMock()
        mock_llm.complete_sync = MagicMock(return_value=(QUESTION_JSON, {"total_tokens": 10}))
        app.state.compiled_graph = compile_graph(mock_llm, app.state.checkpointer)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            create_resp = await client.post(
                "/api/sessions", json={"scene": "intern", "question_count": 5}
            )
            session_id = create_resp.json()["id"]

            resp = await client.post(f"/api/chat/{session_id}", json={})
            body = resp.content.decode("utf-8")
            assert OPENING_TEXT[:20] in body
            assert "多态" in body
