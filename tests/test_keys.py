import pytest

from app.llm.keys import APIKeyError, KeyStore, validate_api_key


def test_validate_ok():
    assert (
        validate_api_key("sk-a7ed48d6072f4b2f8269713d345d6b7c")
        == "sk-a7ed48d6072f4b2f8269713d345d6b7c"
    )


@pytest.mark.parametrize("bad", ["", "a7ed48d6072f4b2f", "SK-xxx", "sk-"])
def test_validate_rejects(bad):
    with pytest.raises(APIKeyError):
        validate_api_key(bad)


def test_store_register_get():
    store = KeyStore()
    store.register("s1", "sk-aaa")
    assert store.get("s1") == "sk-aaa"


def test_store_session_isolated():
    store = KeyStore()
    store.register("s1", "sk-aaa")
    store.register("s2", "sk-bbb")
    assert store.get("s1") == "sk-aaa"
    assert store.get("s2") == "sk-bbb"


def test_store_register_invalid_raises():
    store = KeyStore()
    with pytest.raises(APIKeyError):
        store.register("s1", "bad-key")


def test_store_masked_and_delete():
    store = KeyStore()
    store.register("s1", "sk-aaa")
    assert store.masked("s1") == "sk-•••"
    assert store.masked("missing") == ""
    store.delete("s1")
    assert store.get("s1") is None


def test_get_falls_back_to_global_key():
    store = KeyStore()
    store.set_global_key("sk-abc123")
    assert store.get("unknown-session") == "sk-abc123"
    store.set_global_key("sk-new456")
    assert store.get("unknown-session") == "sk-new456"
