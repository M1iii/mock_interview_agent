import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import app


async def _set_key(client: AsyncClient, key: str = "sk-testkey123456"):
    resp = await client.put("/api/settings/api-key", json={"api_key": key})
    return resp


async def test_set_api_key_success():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _set_key(client)
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_set"] is True
            assert "sk-" in data["masked_key"]
            assert data["masked_key"] != "sk-testkey123456"


async def test_set_api_key_invalid_prefix():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/api/settings/api-key", json={"api_key": "invalid"})
            assert resp.status_code == 400


async def test_get_api_key_not_set():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/api-key")
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_set"] is False
            assert data["masked_key"] == ""


async def test_get_api_key_after_set():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _set_key(client, "sk-mykey123456789")
            resp = await client.get("/api/settings/api-key")
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_set"] is True
            assert data["masked_key"].startswith("sk-")


async def test_create_session_without_key():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/sessions",
                json={"scene": "intern", "question_count": 5},
            )
            assert resp.status_code == 400


async def test_create_session_success():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _set_key(client)
            resp = await client.post(
                "/api/sessions",
                json={"scene": "intern", "question_count": 5, "skip_opening": False},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"]
            assert data["scene"] == "intern"
            assert data["question_count"] == 5
            assert data["status"] == "ongoing"
            assert "实习" in data["title"]


async def test_create_session_with_kb_id():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _set_key(client)
            resp = await client.post(
                "/api/sessions",
                json={"scene": "intern", "question_count": 5, "kb_id": "kb-abc123"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["kb_id"] == "kb-abc123"


async def test_create_session_kb_id_optional():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _set_key(client)
            resp = await client.post("/api/sessions", json={"scene": "intern", "question_count": 5})
            assert resp.status_code == 200
            assert resp.json()["kb_id"] is None


async def test_create_session_fulltime():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _set_key(client)
            resp = await client.post(
                "/api/sessions",
                json={"scene": "fulltime", "question_count": 10},
            )
            assert resp.status_code == 200
            assert "全职" in resp.json()["title"]


async def test_create_session_invalid_scene():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _set_key(client)
            resp = await client.post(
                "/api/sessions",
                json={"scene": "invalid", "question_count": 5},
            )
            assert resp.status_code == 422


async def test_create_session_invalid_question_count():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _set_key(client)
            resp = await client.post(
                "/api/sessions",
                json={"scene": "intern", "question_count": 3},
            )
            assert resp.status_code == 422


async def test_list_sessions_empty():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/sessions")
            assert resp.status_code == 200
            assert resp.json() == []


async def test_list_sessions_after_create():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _set_key(client)
            await client.post("/api/sessions", json={"scene": "intern", "question_count": 5})
            await client.post("/api/sessions", json={"scene": "fulltime", "question_count": 10})
            resp = await client.get("/api/sessions")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2


async def test_delete_session():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _set_key(client)
            create_resp = await client.post(
                "/api/sessions", json={"scene": "intern", "question_count": 5}
            )
            session_id = create_resp.json()["id"]
            config = {"configurable": {"thread_id": session_id}}
            # 写入 checkpointer 状态（模拟进行中的对话）
            await asyncio.to_thread(
                app.state.compiled_graph.update_state,
                config,
                {"messages": [{"role": "assistant", "content": "开场白"}]},
            )
            assert app.state.checkpointer.get_tuple(config) is not None
            resp = await client.delete(f"/api/sessions/{session_id}")
            assert resp.status_code == 200
            list_resp = await client.get("/api/sessions")
            assert len(list_resp.json()) == 0
            # checkpointer 状态同步清除（N-8 级联删）
            assert app.state.checkpointer.get_tuple(config) is None


async def test_delete_session_not_found():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/api/sessions/nonexistent")
            assert resp.status_code == 404


async def test_list_sessions_progress_fields():
    """列表返回消息数与当前题号（实时读 checkpointer，随对话推进更新）。"""
    from unittest.mock import MagicMock

    from app.interview.graph import compile_graph

    QUESTION_JSON = '{"question": "什么是多态", "topic": "OOP"}'
    call_count = [0]

    def mock_complete(api_key, prompt, callbacks=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return (QUESTION_JSON, {})
        if call_count[0] == 2:
            return (
                '{"score": {"技术深度": 7, "表达清晰度": 6, "问题解决": 6, "项目经验": 5}, '
                '"comment": "正确", "needs_followup": false, "followup_reason": ""}',
                {},
            )
        return ('{"question": "请介绍项目", "topic": "项目经验"}', {})

    mock_llm = MagicMock()
    mock_llm.complete_sync = mock_complete

    async with app.router.lifespan_context(app):
        app.state.llm_client = mock_llm
        app.state.compiled_graph = compile_graph(mock_llm, app.state.checkpointer)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _set_key(client)
            sid = (
                await client.post("/api/sessions", json={"scene": "intern", "question_count": 5})
            ).json()["id"]

            # 未对话：0 消息、第 0 题
            data = (await client.get("/api/sessions")).json()
            sess = next(s for s in data if s["id"] == sid)
            assert sess["message_count"] == 0
            assert sess["question_index"] == 0

            # 首调后：开场白 + 题干，第 1 题
            await client.post(f"/api/chat/{sid}", json={})
            data = (await client.get("/api/sessions")).json()
            sess = next(s for s in data if s["id"] == sid)
            assert sess["message_count"] == 2
            assert sess["question_index"] == 0

            # 回答后：+ 用户回答 + 下一题，进入第 2 题
            await client.post(f"/api/chat/{sid}", json={"answer": "多态是同一接口不同实现"})
            data = (await client.get("/api/sessions")).json()
            sess = next(s for s in data if s["id"] == sid)
            assert sess["message_count"] == 4
            assert sess["question_index"] == 1
