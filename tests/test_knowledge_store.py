"""KnowledgeStore（SQLite kb.db）单测：CRUD / 状态流转 / 删除级联 / 绑定模型。"""

import sqlite3

import pytest

from app.store.knowledge import FAILED, PROCESSING, READY, KnowledgeStore


@pytest.fixture()
def store(tmp_path):
    s = KnowledgeStore(tmp_path / "kb.db")
    yield s
    s._conn.close()


def test_create_and_get_kb(store):
    kb = store.create_kb("kb-1", "Java 面试", "bge-large-zh-v1.5", 1024)
    assert kb.id == "kb-1"
    assert kb.name == "Java 面试"
    assert kb.model_id == "bge-large-zh-v1.5"
    assert kb.dims == 1024
    got = store.get_kb("kb-1")
    assert got is not None
    assert got.name == "Java 面试"
    assert got.files == []


def test_get_kb_missing(store):
    assert store.get_kb("kb-nope") is None


def test_list_kbs_order_and_files(store):
    store.create_kb("kb-1", "A", "m1", 1024)
    store.create_kb("kb-2", "B", "m1", 1024)
    store.add_file("kb-1", "file-a", "a.md", "data/kb_files/a.md", 10)
    store.add_file("kb-1", "file-b", "b.md", "data/kb_files/b.md", 20)

    kbs = store.list_kbs()
    assert [kb.id for kb in kbs] == ["kb-2", "kb-1"]  # 创建时间倒序
    kb1 = next(kb for kb in kbs if kb.id == "kb-1")
    assert [f.file_id for f in kb1.files] == ["file-b", "file-a"]  # 文件时间倒序


def test_add_file_initial_processing(store):
    store.create_kb("kb-1", "A", "m1", 1024)
    record = store.add_file("kb-1", "file-a", "a.md", "data/kb_files/a.md", 42)
    assert record.id == "f-file-a"
    assert record.status == PROCESSING
    assert record.block_count is None
    got = store.get_file(record.id)
    assert got is not None
    assert got.kb_id == "kb-1"
    assert got.size == 42


def test_update_file_status_transitions(store):
    store.create_kb("kb-1", "A", "m1", 1024)
    record = store.add_file("kb-1", "file-a", "a.md", "data/kb_files/a.md", 10)

    store.update_file_status(record.id, READY, block_count=12)
    got = store.get_file(record.id)
    assert got.status == READY
    assert got.block_count == 12
    assert got.error is None

    store.update_file_status(record.id, FAILED, error="解析失败")
    got = store.get_file(record.id)
    assert got.status == FAILED
    assert got.error == "解析失败"

    # failed 可重试回 processing（错误信息清空）
    store.update_file_status(record.id, PROCESSING, error=None)
    got = store.get_file(record.id)
    assert got.status == PROCESSING
    assert got.error is None


def test_list_all_files(store):
    store.create_kb("kb-1", "A", "m1", 1024)
    store.add_file("kb-1", "file-a", "a.md", "data/kb_files/a.md", 10)
    store.create_kb("kb-2", "B", "m1", 1024)
    store.add_file("kb-2", "file-b", "b.md", "data/kb_files/b.md", 20)
    assert [f.file_id for f in store.list_all_files()] == ["file-a", "file-b"]


def test_delete_kb_returns_files_and_clears(store):
    store.create_kb("kb-1", "A", "m1", 1024)
    store.add_file("kb-1", "file-a", "a.md", "data/kb_files/a.md", 10)
    store.add_file("kb-1", "file-b", "b.md", "data/kb_files/b.md", 20)

    files = store.delete_kb("kb-1")
    assert [f.file_id for f in files] == ["file-a", "file-b"]
    assert store.get_kb("kb-1") is None
    assert store.list_all_files() == []


def test_delete_kb_without_files(store):
    store.create_kb("kb-1", "A", "m1", 1024)
    assert store.delete_kb("kb-1") == []
    assert store.list_kbs() == []


def test_delete_kb_cascade_via_foreign_key(store):
    store.create_kb("kb-1", "A", "m1", 1024)
    store.add_file("kb-1", "file-a", "a.md", "data/kb_files/a.md", 10)
    with store._lock:
        store._conn.execute("DELETE FROM knowledge_bases WHERE id = ?", ("kb-1",))
        store._conn.commit()
    assert store.list_all_files() == []


def test_bind_model_updates_kb(store):
    store.create_kb("kb-1", "A", "m1", 1024)
    store.bind_model("kb-1", "new-model", 768)
    got = store.get_kb("kb-1")
    assert got.model_id == "new-model"
    assert got.dims == 768


def test_to_dict_shape(store):
    store.create_kb("kb-1", "A", "m1", 1024)
    store.add_file("kb-1", "file-a", "a.md", "data/kb_files/a.md", 10)
    kb = store.list_kbs()[0]
    d = kb.to_dict()
    assert set(d) == {"id", "name", "model_id", "dims", "created_at", "files"}
    assert d["files"][0]["file_id"] == "file-a"
    assert d["files"][0]["status"] == PROCESSING


def test_schema_recreated_on_reopen(tmp_path):
    path = tmp_path / "kb.db"
    store = KnowledgeStore(path)
    store.create_kb("kb-1", "A", "m1", 1024)
    store.add_file("kb-1", "file-a", "a.md", "data/kb_files/a.md", 10)
    store._conn.close()

    # 跨实例重开（模拟重启）：数据仍在
    store2 = KnowledgeStore(path)
    assert store2.get_kb("kb-1") is not None
    assert len(store2.list_all_files()) == 1
    store2._conn.close()


def test_file_id_unique_constraint(store):
    store.create_kb("kb-1", "A", "m1", 1024)
    store.add_file("kb-1", "file-a", "a.md", "data/kb_files/a.md", 10)
    with pytest.raises(sqlite3.IntegrityError):
        store.add_file("kb-1", "file-a", "b.md", "data/kb_files/b.md", 20)
