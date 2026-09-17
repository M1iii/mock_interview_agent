from datetime import datetime

from app.store.sessions import InMemorySessionStore, SqliteSessionStore


def test_create_and_get():
    store = InMemorySessionStore()
    meta = store.create("s1", "intern", 5)
    assert meta["id"] == "s1"
    assert meta["scene"] == "intern"
    assert meta["title"] == "实习面试"
    assert meta["status"] == "ongoing"
    assert meta["question_count"] == 5
    assert isinstance(meta["created_at"], datetime)

    got = store.get("s1")
    assert got is not None
    assert got["id"] == "s1"


def test_get_missing():
    store = InMemorySessionStore()
    assert store.get("nonexistent") is None


def test_list_sorted_by_created_desc():
    store = InMemorySessionStore()
    store.create("s1", "intern", 5)
    store.create("s2", "fulltime", 10)
    sessions = store.list()
    assert len(sessions) == 2
    assert sessions[0]["created_at"] >= sessions[1]["created_at"]


def test_update_status():
    store = InMemorySessionStore()
    store.create("s1", "fulltime", 10)
    store.update_status("s1", "finished")
    assert store.get("s1")["status"] == "finished"


def test_delete():
    store = InMemorySessionStore()
    store.create("s1", "intern", 5)
    store.delete("s1")
    assert store.get("s1") is None
    assert store.list() == []


def test_delete_missing_no_error():
    store = InMemorySessionStore()
    store.delete("nonexistent")


def _sqlite_store(tmp_path):
    return SqliteSessionStore(tmp_path / "interview.db")


def test_sqlite_create_and_get(tmp_path):
    store = _sqlite_store(tmp_path)
    meta = store.create("s1", "intern", 5, interview_type="technical", resume_id="r-1")
    assert meta["id"] == "s1"
    assert meta["interview_type"] == "technical"
    assert meta["resume_id"] == "r-1"
    got = store.get("s1")
    assert got is not None
    assert got["title"] == "实习面试"
    assert got["status"] == "ongoing"
    assert isinstance(got["created_at"], datetime)


def test_sqlite_persistence_across_reopen(tmp_path):
    """重启模拟：新实例读同一 SQLite 文件，会话完整恢复（P2-3 数据面）。"""
    db = tmp_path / "interview.db"
    SqliteSessionStore(db).create("s1", "fulltime", 10, interview_type="comprehensive")
    store2 = SqliteSessionStore(db)
    got = store2.get("s1")
    assert got is not None
    assert got["interview_type"] == "comprehensive"
    assert got["question_count"] == 10
    assert store2.list()[0]["id"] == "s1"


def test_sqlite_update_and_delete(tmp_path):
    store = _sqlite_store(tmp_path)
    store.create("s1", "intern", 5)
    store.update_status("s1", "finished")
    assert store.get("s1")["status"] == "finished"
    store.delete("s1")
    assert store.get("s1") is None
    assert store.list() == []
