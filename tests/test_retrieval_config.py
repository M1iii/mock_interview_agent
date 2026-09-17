from app.config import load_config


def test_retrieval_config_defaults(tmp_path, monkeypatch):
    for key in (
        "QDRANT_URL",
        "ES_URL",
        "ES_INDEX",
        "RETRIEVAL_ENABLED",
        "QDRANT_TIMEOUT",
        "ES_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config(env_path=tmp_path / ".env")
    assert cfg.retrieval.enabled is True
    assert cfg.retrieval.qdrant_url == "http://127.0.0.1:6333"
    assert cfg.retrieval.qdrant_timeout == 5
    assert cfg.retrieval.es_url == "http://127.0.0.1:9200"
    assert cfg.retrieval.es_timeout == 5
    assert cfg.retrieval.es_index == "kb_blocks"
    assert cfg.retrieval.semantic_weight == 0.6
    assert cfg.retrieval.threshold == 0.6
    assert cfg.retrieval.top_k == 5


def test_retrieval_config_env_overrides(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:16333")
    monkeypatch.setenv("QDRANT_TIMEOUT", "3")
    monkeypatch.setenv("ES_URL", "http://127.0.0.1:19200")
    monkeypatch.setenv("ES_INDEX", "my_kb")
    monkeypatch.setenv("RETRIEVAL_ENABLED", "false")
    cfg = load_config()
    assert cfg.retrieval.enabled is False
    assert cfg.retrieval.qdrant_url == "http://127.0.0.1:16333"
    assert cfg.retrieval.qdrant_timeout == 3
    assert cfg.retrieval.es_url == "http://127.0.0.1:19200"
    assert cfg.retrieval.es_index == "my_kb"
