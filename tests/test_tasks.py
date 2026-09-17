"""后台入库/重建任务单测：状态流转 processing→ready/failed + 失败不中断全库重建。"""

from types import SimpleNamespace

import pytest

from app.retrieval.tasks import ingest_file_background, rebuild_all_background
from app.store.knowledge import FAILED, READY, KnowledgeStore


@pytest.fixture()
def store(tmp_path):
    s = KnowledgeStore(tmp_path / "kb.db")
    s.create_kb("kb-1", "A", "bge-large-zh-v1.5", 1024)
    yield s
    s._conn.close()


def _managers():
    return SimpleNamespace(), SimpleNamespace(), SimpleNamespace()


def _record(store, name="kb.md", file_id="file-a"):
    p = f"data/kb_files/{name}"
    return store.add_file("kb-1", file_id, name, p, 10)


def test_ingest_file_background_success(store, tmp_path, monkeypatch):
    (tmp_path / "data" / "kb_files").mkdir(parents=True)
    (tmp_path / "data" / "kb_files" / "kb.md").write_text("# t", encoding="utf-8")
    monkeypatch.setattr("app.retrieval.tasks.PROJECT_ROOT", tmp_path)
    result = SimpleNamespace(file_id="file-a", child_count=7)
    monkeypatch.setattr("app.retrieval.tasks.ingest_document", lambda *a, **k: result)
    qdrant, es, embedding = _managers()

    ingest_file_background(store, _record(store), qdrant, es, embedding, None)

    got = store.get_file("f-file-a")
    assert got.status == READY
    assert got.block_count == 7


def test_ingest_file_background_failure_sets_failed(store, tmp_path, monkeypatch):
    (tmp_path / "data" / "kb_files").mkdir(parents=True)
    (tmp_path / "data" / "kb_files" / "kb.md").write_text("# t", encoding="utf-8")
    monkeypatch.setattr("app.retrieval.tasks.PROJECT_ROOT", tmp_path)

    def _boom(*args, **kwargs):
        raise ValueError("解析失败")

    monkeypatch.setattr("app.retrieval.tasks.ingest_document", _boom)
    qdrant, es, embedding = _managers()

    ingest_file_background(store, _record(store), qdrant, es, embedding, None)

    got = store.get_file("f-file-a")
    assert got.status == FAILED
    assert "解析失败" in got.error
    assert got.block_count is None


def test_rebuild_all_background_mixed(store, tmp_path, monkeypatch):
    (tmp_path / "data" / "kb_files").mkdir(parents=True)
    for name in ("a.md", "b.md"):
        (tmp_path / "data" / "kb_files" / name).write_text("# t", encoding="utf-8")
    monkeypatch.setattr("app.retrieval.tasks.PROJECT_ROOT", tmp_path)
    store.add_file("kb-1", "file-a", "a.md", "data/kb_files/a.md", 10)
    store.add_file("kb-1", "file-b", "b.md", "data/kb_files/b.md", 10)

    calls = {"n": 0}

    def _mixed(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return SimpleNamespace(file_id="file-a", child_count=5)
        raise ValueError("bad file")

    monkeypatch.setattr("app.retrieval.tasks.ingest_document", _mixed)
    qdrant, es, embedding = _managers()
    embedding.model_id = "new-model"
    embedding.dims = 768

    stats = rebuild_all_background(store, qdrant, es, embedding, None)

    assert stats == {"ok": 1, "failed": 1}
    a = store.get_file("f-file-a")
    b = store.get_file("f-file-b")
    assert a.status == READY and a.block_count == 5
    assert b.status == FAILED and "bad file" in b.error
    # 全部库绑定新模型（P1-7）
    kb = store.get_kb("kb-1")
    assert kb.model_id == "new-model"
    assert kb.dims == 768
