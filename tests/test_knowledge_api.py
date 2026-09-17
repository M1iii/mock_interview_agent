"""知识库管理 API 单测：建库 / 列表 / 上传校验 / 重试 / 删除级联（隔离真实数据目录）。"""

from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.store.knowledge import FAILED, READY, KnowledgeStore

CONTENT = "# 面试知识库\n\n多态是面向对象的三大特性之一。\n"


def _kb_dir(tmp_path) -> str:
    return "kb_files"


async def _client(tmp_path, monkeypatch, embed_model="bge-large-zh-v1.5"):
    """隔离的知识库 API 客户端：数据目录/元数据库落到 tmp_path，入库任务不真正执行。"""
    monkeypatch.setattr("app.api.knowledge.PROJECT_ROOT", tmp_path)
    async with app.router.lifespan_context(app):
        app.state.knowledge_store = KnowledgeStore(tmp_path / "kb.db")
        app.state.config.retrieval.kb_dir = _kb_dir(tmp_path)

        async def _noop(*args, **kwargs):
            return None

        monkeypatch.setattr("app.api.knowledge.ingest_file_async", _noop)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, app.state.knowledge_store


async def _create_kb(client: AsyncClient, name: str = "Java 面试"):
    resp = await client.post("/api/knowledge", json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_create_kb_binds_current_embedding(tmp_path, monkeypatch):
    async for client, _store in _client(tmp_path, monkeypatch):
        data = await _create_kb(client)
        assert data["id"].startswith("kb-")
        assert data["name"] == "Java 面试"
        # 绑定当前生效的 Embedding 模型（model_id/dims 来自 app.state）
        assert data["model_id"] == app.state.embedding.model_id
        assert data["dims"] == app.state.embedding.dims
        assert data["files"] == []
        assert data["created_at"]


async def test_create_kb_name_validation(tmp_path, monkeypatch):
    async for client, _store in _client(tmp_path, monkeypatch):
        resp = await client.post("/api/knowledge", json={"name": ""})
        assert resp.status_code == 422


async def test_list_kbs_empty_and_after_create(tmp_path, monkeypatch):
    async for client, _store in _client(tmp_path, monkeypatch):
        assert (await client.get("/api/knowledge")).json() == []
        await _create_kb(client, "A")
        await _create_kb(client, "B")
        data = (await client.get("/api/knowledge")).json()
        assert [kb["name"] for kb in data] == ["B", "A"]


async def test_upload_file_success(tmp_path, monkeypatch):
    async for client, store in _client(tmp_path, monkeypatch):
        kb = await _create_kb(client)
        resp = await client.post(
            f"/api/knowledge/{kb['id']}/files",
            files={"file": ("kb.md", CONTENT.encode("utf-8"), "text/markdown")},
        )
        assert resp.status_code == 200, resp.text
        rec = resp.json()["file"]
        assert rec["status"] == "processing"
        assert rec["name"] == "kb.md"
        assert rec["size"] == len(CONTENT.encode("utf-8"))
        assert rec["block_count"] is None
        # 原文件落盘，元数据入库
        saved = store.get_file(rec["id"])
        assert saved is not None
        assert (tmp_path / saved.path).exists()


async def test_upload_unknown_kb_404(tmp_path, monkeypatch):
    async for client, _store in _client(tmp_path, monkeypatch):
        resp = await client.post(
            "/api/knowledge/kb-nope/files",
            files={"file": ("kb.md", b"x", "text/markdown")},
        )
        assert resp.status_code == 404


async def test_upload_unsupported_ext_400(tmp_path, monkeypatch):
    async for client, _store in _client(tmp_path, monkeypatch):
        kb = await _create_kb(client)
        resp = await client.post(
            f"/api/knowledge/{kb['id']}/files",
            files={"file": ("kb.exe", b"x", "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "仅支持" in resp.json()["detail"]


async def test_upload_empty_file_400(tmp_path, monkeypatch):
    async for client, _store in _client(tmp_path, monkeypatch):
        kb = await _create_kb(client)
        resp = await client.post(
            f"/api/knowledge/{kb['id']}/files",
            files={"file": ("empty.md", b"", "text/markdown")},
        )
        assert resp.status_code == 400
        assert "为空" in resp.json()["detail"]


async def test_retry_failed_file(tmp_path, monkeypatch):
    async for client, store in _client(tmp_path, monkeypatch):
        kb = await _create_kb(client)
        rec = (
            await client.post(
                f"/api/knowledge/{kb['id']}/files",
                files={"file": ("kb.md", CONTENT.encode("utf-8"), "text/markdown")},
            )
        ).json()["file"]
        store.update_file_status(rec["id"], FAILED, error="boom")

        resp = await client.post(f"/api/knowledge/{kb['id']}/files/{rec['id']}/retry")
        assert resp.status_code == 200
        assert resp.json()["file"]["status"] == "processing"
        assert resp.json()["file"]["error"] is None


async def test_retry_ready_file_rejected(tmp_path, monkeypatch):
    async for client, store in _client(tmp_path, monkeypatch):
        kb = await _create_kb(client)
        rec = (
            await client.post(
                f"/api/knowledge/{kb['id']}/files",
                files={"file": ("kb.md", CONTENT.encode("utf-8"), "text/markdown")},
            )
        ).json()["file"]
        store.update_file_status(rec["id"], READY, block_count=3)

        resp = await client.post(f"/api/knowledge/{kb['id']}/files/{rec['id']}/retry")
        assert resp.status_code == 400
        assert "失败状态" in resp.json()["detail"]


async def test_retry_missing_file_404(tmp_path, monkeypatch):
    async for client, _store in _client(tmp_path, monkeypatch):
        kb = await _create_kb(client)
        resp = await client.post(f"/api/knowledge/{kb['id']}/files/f-nope/retry")
        assert resp.status_code == 404


async def test_delete_kb_cascade(tmp_path, monkeypatch):
    delete_document = MagicMock()
    monkeypatch.setattr("app.api.knowledge.delete_document", delete_document)

    async for client, store in _client(tmp_path, monkeypatch):
        kb = await _create_kb(client)
        rec = (
            await client.post(
                f"/api/knowledge/{kb['id']}/files",
                files={"file": ("kb.md", CONTENT.encode("utf-8"), "text/markdown")},
            )
        ).json()["file"]
        saved_path = tmp_path / store.get_file(rec["id"]).path
        assert saved_path.exists()

        resp = await client.delete(f"/api/knowledge/{kb['id']}")
        assert resp.status_code == 200
        assert resp.json() == {"deleted": 1, "cleaned": 1, "id": kb["id"]}
        # Qdrant/ES 级联清理按 file_id 逐文件调用
        delete_document.assert_called_once()
        assert delete_document.call_args.args[0] == rec["file_id"]
        # 元数据 + 原文件物理删
        assert (await client.get("/api/knowledge")).json() == []
        assert not saved_path.exists()
        assert store.list_all_files() == []


async def test_delete_kb_degrades_when_retrieval_down(tmp_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("retrieval unavailable")

    monkeypatch.setattr("app.api.knowledge.delete_document", _boom)

    async for client, store in _client(tmp_path, monkeypatch):
        kb = await _create_kb(client)
        rec = (
            await client.post(
                f"/api/knowledge/{kb['id']}/files",
                files={"file": ("kb.md", CONTENT.encode("utf-8"), "text/markdown")},
            )
        ).json()["file"]
        saved_path = tmp_path / store.get_file(rec["id"]).path

        resp = await client.delete(f"/api/knowledge/{kb['id']}")
        assert resp.status_code == 200
        assert resp.json()["cleaned"] == 0
        # 降级不阻塞：元数据与文件照删
        assert (await client.get("/api/knowledge")).json() == []
        assert not saved_path.exists()


async def test_delete_kb_not_found(tmp_path, monkeypatch):
    async for client, _store in _client(tmp_path, monkeypatch):
        resp = await client.delete("/api/knowledge/kb-nope")
        assert resp.status_code == 404
