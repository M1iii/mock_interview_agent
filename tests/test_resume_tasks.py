from types import SimpleNamespace

from app.resume.tasks import process_resume_background
from app.store.resume import FAILED, READY, ResumeStore


def _store(tmp_path):
    return ResumeStore(tmp_path / "resume.db")


def _llm(profile):
    return SimpleNamespace(
        complete_sync=lambda api_key, prompt, callbacks=None: (
            '{"basic": {}, "skills": [], "projects": [], "points": [{"category": "技能",'
            ' "title": "Redis", "detail": "缓存", "source_snippet": "使用 Redis"}]}',
            {},
        )
    )


def test_process_success(tmp_path, monkeypatch):
    (tmp_path / "data" / "resumes").mkdir(parents=True)
    (tmp_path / "data" / "resumes" / "a.md").write_text("# 张三\n技能：Python", encoding="utf-8")
    monkeypatch.setattr("app.resume.tasks.PROJECT_ROOT", tmp_path)
    store = _store(tmp_path)
    record = store.add_resume("r-1", "a.md", "data/resumes/a.md", 10)

    process_resume_background(store, record, _llm(None), "sk-test123", None)

    got = store.get_resume("r-1")
    assert got.status == READY
    assert got.point_count == 1
    assert store.count_points("r-1") == 1


def test_process_failure_sets_failed(tmp_path, monkeypatch):
    (tmp_path / "data" / "resumes").mkdir(parents=True)
    (tmp_path / "data" / "resumes" / "a.pdf").write_bytes(b"%PDF-fake")
    monkeypatch.setattr("app.resume.tasks.PROJECT_ROOT", tmp_path)
    store = _store(tmp_path)
    record = store.add_resume("r-1", "a.pdf", "data/resumes/a.pdf", 10)

    def _boom(*a, **k):
        raise ValueError("PDF 无文字层")

    monkeypatch.setattr("app.resume.tasks.extract_profile", _boom)
    process_resume_background(store, record, _llm(None), "sk-test123", None)

    got = store.get_resume("r-1")
    assert got.status == FAILED
    assert "无文字层" in got.error
