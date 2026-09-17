from datetime import datetime

from app.store.sessions import InMemorySessionStore


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
