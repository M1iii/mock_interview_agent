"""全局设置 API：联网搜索 Key（verify-key）端点 + lifespan 种子（P2-4）。"""

from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.llm.keys import KeyStore
from app.main import app


async def test_verify_key_put_get_and_clear():
    async with app.router.lifespan_context(app):
        # 隔离：避免 .env 种子（VERIFY_API_KEY）影响「未配置」用例
        app.state.key_store = KeyStore()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/verify-key")
            assert resp.status_code == 200
            assert resp.json() == {"masked_key": "", "is_set": False}

            resp = await client.put("/api/settings/verify-key", json={"verify_key": "bocha-abc123"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_set"] is True
            assert data["masked_key"]  # 只回掩码，不回明文
            assert "bocha-abc123" not in data["masked_key"]

            resp = await client.get("/api/settings/verify-key")
            assert resp.status_code == 200
            assert resp.json()["is_set"] is True

            resp = await client.put("/api/settings/verify-key", json={"verify_key": ""})
            assert resp.status_code == 200
            assert resp.json() == {"masked_key": "", "is_set": False}


async def test_lifespan_seeds_verify_key_from_env(monkeypatch):
    """修复 1-2：lifespan 把 .env 的 VERIFY_API_KEY（cfg.verify.api_key）种入 KeyStore。"""
    cfg = load_config()
    monkeypatch.setattr(cfg.verify, "api_key", "bocha-from-env")
    monkeypatch.setattr("app.main.load_config", lambda: cfg)

    async with app.router.lifespan_context(app):
        assert app.state.key_store.get_verify_key() == "bocha-from-env"
        # 图实际使用的 VerifyContext 挂载在 app.state（验收脚本据此断言 Key 通路）
        assert app.state.verify_ctx is not None


async def test_lifespan_no_verify_key_when_env_empty(monkeypatch):
    cfg = load_config()
    monkeypatch.setattr(cfg.verify, "api_key", "")
    monkeypatch.setattr("app.main.load_config", lambda: cfg)

    async with app.router.lifespan_context(app):
        assert app.state.key_store.get_verify_key() is None
