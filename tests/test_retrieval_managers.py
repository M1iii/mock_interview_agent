from unittest.mock import MagicMock, patch

import pytest

from app.config import load_config
from app.retrieval import RetrievalUnavailable
from app.retrieval.es import ESManager
from app.retrieval.qdrant import QdrantManager


def _cfg():
    return load_config()


def test_qdrant_manager_unavailable():
    cfg = _cfg()
    cfg.retrieval.qdrant_url = "http://127.0.0.1:1"
    cfg.retrieval.qdrant_timeout = 1
    mgr = QdrantManager(cfg)
    assert mgr.is_available() is False
    with pytest.raises(RetrievalUnavailable):
        mgr.get_client()


def test_es_manager_unavailable():
    cfg = _cfg()
    cfg.retrieval.es_url = "http://127.0.0.1:1"
    cfg.retrieval.es_timeout = 1
    mgr = ESManager(cfg)
    assert mgr.is_available() is False
    with pytest.raises(RetrievalUnavailable):
        mgr.get_client()


def test_qdrant_manager_available():
    cfg = _cfg()
    cfg.retrieval.qdrant_url = "http://127.0.0.1:16333"
    mgr = QdrantManager(cfg)
    fake = MagicMock()
    with patch("app.retrieval.qdrant.QdrantClient", return_value=fake):
        assert mgr.is_available() is True
        assert mgr.get_client() is fake
    fake.get_collections.assert_called_once()


def test_es_manager_available():
    cfg = _cfg()
    cfg.retrieval.es_url = "http://127.0.0.1:19200"
    mgr = ESManager(cfg)
    fake = MagicMock()
    fake.ping.return_value = True
    fake.options.return_value = fake  # ES 8.x options() 返回新实例，链式调用 mock 到自身
    with patch("app.retrieval.es.Elasticsearch", return_value=fake):
        assert mgr.is_available() is True
        assert mgr.get_client() is fake
    fake.ping.assert_called_once()


def test_qdrant_probe_result_cached():
    cfg = _cfg()
    cfg.retrieval.qdrant_url = "http://127.0.0.1:1"
    cfg.retrieval.qdrant_timeout = 1
    mgr = QdrantManager(cfg)
    with patch.object(mgr, "_probe", wraps=mgr._probe) as probe:
        assert mgr.is_available() is False
        assert mgr.is_available() is False
    assert probe.call_count == 1


def test_es_probe_result_cached():
    cfg = _cfg()
    cfg.retrieval.es_url = "http://127.0.0.1:1"
    cfg.retrieval.es_timeout = 1
    mgr = ESManager(cfg)
    with patch.object(mgr, "_probe", wraps=mgr._probe) as probe:
        assert mgr.is_available() is False
        assert mgr.is_available() is False
    assert probe.call_count == 1
