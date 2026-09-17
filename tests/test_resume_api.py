import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.resume import router
from app.store.resume import ResumeStore


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.resume.PROJECT_ROOT", tmp_path)
    application = FastAPI()
    application.include_router(router)
    application.state.resume_store = ResumeStore(tmp_path / "resume.db")
    application.state.llm_client = _FakeLLM()
    application.state.key_store = _FakeKeys()
    application.state.config = _cfg()
    return application


def _cfg():
    from omegaconf import OmegaConf

    return OmegaConf.create({"resume": {"upload_dir": "data/resumes", "max_upload_mb": 20}})


class _FakeLLM:
    def complete_sync(self, api_key, prompt, callbacks=None):
        return (
            '{"basic": {}, "skills": ["Python"], "projects": [],'
            ' "points": [{"category": "技能", "title": "Python", "detail": "语法",'
            ' "source_snippet": "精通 Python"}]}',
            {},
        )


class _FakeKeys:
    def get_global_key(self):
        return "sk-test123"


def test_upload_and_status_flow(app, tmp_path):
    client = TestClient(app)
    (tmp_path / "data" / "resumes").mkdir(parents=True, exist_ok=True)
    resp = client.post(
        "/resumes",
        files={"file": ("a.md", io.BytesIO("# 张三\n技能：Python".encode()), "text/markdown")},
    )
    assert resp.status_code == 200
    rid = resp.json()["resume"]["id"]
    status = resp.json()["resume"]["status"]

    assert status in ("processing", "ready")
    # 后台任务同步完成 → 直接轮询到 ready
    got = client.get("/resumes").json()
    assert len(got) == 1
    assert got[0]["id"] == rid


def test_upload_rejects_too_large(app, tmp_path):
    client = TestClient(app)
    (tmp_path / "data" / "resumes").mkdir(parents=True, exist_ok=True)
    big = b"x" * (21 * 1024 * 1024)
    resp = client.post("/resumes", files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")})
    assert resp.status_code == 400
    assert "20MB" in resp.json()["detail"]


def test_upload_rejects_bad_ext(app, tmp_path):
    client = TestClient(app)
    resp = client.post(
        "/resumes", files={"file": ("a.exe", io.BytesIO(b"x"), "application/octet-stream")}
    )
    assert resp.status_code == 400


def test_delete_resume(app, tmp_path):
    (tmp_path / "data" / "resumes").mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    up = client.post(
        "/resumes", files={"file": ("a.md", io.BytesIO(b"# x"), "text/markdown")}
    ).json()["resume"]
    rid = up["id"]
    resp = client.delete(f"/resumes/{rid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert client.get("/resumes").json() == []
