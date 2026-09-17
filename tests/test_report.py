from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient

from app.interview.graph import compile_graph
from app.main import app


def _make_llm_ask():
    """出题 mock：总是返回同一题。"""
    llm = MagicMock()
    llm.complete_sync = MagicMock(
        return_value=('{"question": "什么是多态", "topic": "OOP"}', {"total_tokens": 10})
    )
    return llm


def _make_llm_eval(report_text="# 面试报告\n\n总分：70分"):
    """评估 mock：不追问。"""
    llm = MagicMock()
    llm.complete_sync = MagicMock(
        return_value=(
            '{"score": {"技术深度": 7, "表达清晰度": 6, "问题解决": 6, "项目经验": 5}, '
            '"comment": "回答正确", "needs_followup": false, "followup_reason": ""}',
            {"total_tokens": 20},
        )
    )
    return llm


def _make_llm_report(report_text="# 面试报告\n\n总分：70分"):
    """报告 mock。"""
    llm = MagicMock()
    llm.complete_sync = MagicMock(return_value=(report_text, {"total_tokens": 30}))
    return llm


def _make_llm_multi(ask_text, eval_text, report_text):
    """多步 mock：按调用顺序返回 ask → eval → ask → report。

    count=5 会话：首次出题(ask) → 回答后评估(eval) → 出第 2 题(ask) → finish 报告(report)
    count=1 会话：首次出题(ask) → 回答后评估(eval) → 路由 report → 报告(report)
    """
    responses = [
        (ask_text, {"total_tokens": 10}),
        (eval_text, {"total_tokens": 20}),
        (ask_text, {"total_tokens": 10}),
        (report_text, {"total_tokens": 30}),
    ]
    call_idx = [0]

    def _complete(api_key, prompt, callbacks=None):
        i = call_idx[0]
        call_idx[0] += 1
        if i < len(responses):
            return responses[i]
        return (report_text, {"total_tokens": 30})

    llm = MagicMock()
    llm.complete_sync = _complete
    return llm


def _make_llm_natural(rounds: int, ask_text, eval_text, report_text):
    """自然结束 mock：rounds 轮问答后进入 report。

    每轮：ask → eval（推进题号）；全部轮次完成后 → report。
    调用序列：ask, eval, ask, eval, ..., ask, eval, report
    """
    responses = []
    for _ in range(rounds):
        responses.append((ask_text, {"total_tokens": 10}))
        responses.append((eval_text, {"total_tokens": 20}))
    responses.append((report_text, {"total_tokens": 30}))
    call_idx = [0]

    def _complete(api_key, prompt, callbacks=None):
        i = call_idx[0]
        call_idx[0] += 1
        if i < len(responses):
            return responses[i]
        return (report_text, {"total_tokens": 30})

    llm = MagicMock()
    llm.complete_sync = _complete
    return llm


def _install_mock(llm):
    """替换 app.state 中的 LLM 与编译图（lifespan 初始化的是真实 LLM）。"""
    app.state.llm_client = llm
    app.state.compiled_graph = compile_graph(llm, app.state.checkpointer)


async def _setup_and_run(client, session_id, answer="多态是同一接口不同实现"):
    """执行首次调用 + 回答。"""
    await client.post(f"/api/chat/{session_id}", json={})
    await client.post(f"/api/chat/{session_id}", json={"answer": answer})


async def test_finish_session_no_scores():
    """无评分记录时提前结束 → 400。"""
    async with app.router.lifespan_context(app):
        _install_mock(_make_llm_ask())

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            resp = await client.post("/api/sessions", json={"scene": "intern", "question_count": 5})
            session_id = resp.json()["id"]
            await client.post(f"/api/chat/{session_id}", json={})
            resp = await client.post(f"/api/sessions/{session_id}/finish")
            assert resp.status_code == 400


async def test_finish_session_success():
    """有评分记录时提前结束 → 生成报告 + 状态=finished。"""
    async with app.router.lifespan_context(app):
        llm = _make_llm_multi(
            '{"question": "什么是多态", "topic": "OOP"}',
            '{"score": {"技术深度": 7, "表达清晰度": 6, "问题解决": 6, "项目经验": 5}, '
            '"comment": "回答正确", "needs_followup": false, "followup_reason": ""}',
            "# 面试报告\n\n总分：70分",
        )
        _install_mock(llm)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            resp = await client.post("/api/sessions", json={"scene": "intern", "question_count": 5})
            session_id = resp.json()["id"]
            await _setup_and_run(client, session_id)

            resp = await client.post(f"/api/sessions/{session_id}/finish")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "finished"
            assert "面试报告" in data["report"]


async def test_finish_already_finished():
    """已结束的会话再次结束 → 400。"""
    async with app.router.lifespan_context(app):
        llm = _make_llm_multi(
            '{"question": "test", "topic": "test"}',
            '{"score": {"技术深度": 5, "表达清晰度": 5, "问题解决": 5, "项目经验": 5}, '
            '"comment": "ok", "needs_followup": false, "followup_reason": ""}',
            "# 报告",
        )
        _install_mock(llm)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            resp = await client.post("/api/sessions", json={"scene": "intern", "question_count": 5})
            session_id = resp.json()["id"]
            await _setup_and_run(client, session_id, "回答")

            # 提前结束
            resp = await client.post(f"/api/sessions/{session_id}/finish")
            assert resp.status_code == 200
            # 再次结束
            resp = await client.post(f"/api/sessions/{session_id}/finish")
            assert resp.status_code == 400


async def test_get_report_not_finished():
    """未结束的会话导出报告 → 400。"""
    async with app.router.lifespan_context(app):
        _install_mock(_make_llm_ask())

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            resp = await client.post("/api/sessions", json={"scene": "intern", "question_count": 5})
            session_id = resp.json()["id"]
            resp = await client.get(f"/api/sessions/{session_id}/report")
            assert resp.status_code == 400


async def test_get_report_success():
    """已结束的会话导出报告 → Markdown 文件下载。"""
    async with app.router.lifespan_context(app):
        llm = _make_llm_multi(
            '{"question": "test", "topic": "test"}',
            '{"score": {"技术深度": 5, "表达清晰度": 5, "问题解决": 5, "项目经验": 5}, '
            '"comment": "ok", "needs_followup": false, "followup_reason": ""}',
            "# 面试报告\n\n总分：50分",
        )
        _install_mock(llm)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            resp = await client.post("/api/sessions", json={"scene": "intern", "question_count": 5})
            session_id = resp.json()["id"]
            await _setup_and_run(client, session_id, "回答")
            await client.post(f"/api/sessions/{session_id}/finish")

            resp = await client.get(f"/api/sessions/{session_id}/report")
            assert resp.status_code == 200
            data = resp.json()
            assert "面试报告" in data["report"]
            assert data["status"] == "finished"
            # mock 输出无 ```json 摘要块 → 降级为 null
            assert data["summary"] is None


async def test_status_synced_after_natural_finish():
    """自然结束（5 轮问答全部完成）后 SessionStore status 同步为 finished。"""
    async with app.router.lifespan_context(app):
        llm = _make_llm_natural(
            5,
            '{"question": "test", "topic": "test"}',
            '{"score": {"技术深度": 5, "表达清晰度": 5, "问题解决": 5, "项目经验": 5}, '
            '"comment": "ok", "needs_followup": false, "followup_reason": ""}',
            "# 报告",
        )
        _install_mock(llm)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/settings/api-key", json={"api_key": "sk-testkey123456"})
            resp = await client.post("/api/sessions", json={"scene": "intern", "question_count": 5})
            session_id = resp.json()["id"]

            # 首次调用（出题）
            await client.post(f"/api/chat/{session_id}", json={})
            # 5 轮问答：每轮回答后评估推进一题
            for i in range(5):
                await client.post(f"/api/chat/{session_id}", json={"answer": f"回答{i}"})

            # 查会话列表，确认 status=finished
            resp = await client.get("/api/sessions")
            data = resp.json()
            assert len(data) == 1
            assert data[0]["status"] == "finished"
