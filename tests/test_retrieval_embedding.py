from unittest.mock import MagicMock, patch

import pytest

from app.config import load_config
from app.retrieval import RetrievalUnavailable
from app.retrieval.embedding import KNOWN_DIMS, OpenAICompatEmbedding


def _cfg(**overrides):
    cfg = load_config()
    for key, value in overrides.items():
        setattr(cfg.retrieval.embedding, key, value)
    return cfg


def _resp_json(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=data)
    return resp


def _embedding_response(vectors: list[list[float]]) -> dict:
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": vec} for i, vec in enumerate(vectors)
        ],
        "model": "bge-large-zh-v1.5",
        "usage": {"prompt_tokens": 3, "total_tokens": 3},
    }


def test_dims_from_known_mapping():
    emb = OpenAICompatEmbedding(_cfg(dims=0))
    assert emb.dims == KNOWN_DIMS["bge-large-zh-v1.5"]
    assert emb.dims == 1024


def test_dims_from_config_override():
    emb = OpenAICompatEmbedding(_cfg(model_id="custom-model", dims=768))
    assert emb.dims == 768


def test_model_id_and_provider():
    emb = OpenAICompatEmbedding(_cfg(provider="external", model_id="text-embedding-3-small"))
    assert emb.provider == "external"
    assert emb.model_id == "text-embedding-3-small"


def test_embed_documents_sorted_by_index():
    emb = OpenAICompatEmbedding(_cfg())
    vectors = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    # 响应乱序，断言按 index 重排
    data = {
        "object": "list",
        "data": [
            {"object": "embedding", "index": 2, "embedding": vectors[2]},
            {"object": "embedding", "index": 0, "embedding": vectors[0]},
            {"object": "embedding", "index": 1, "embedding": vectors[1]},
        ],
        "model": "bge-large-zh-v1.5",
    }
    fake_client = MagicMock()
    fake_client.__enter__.return_value.post.return_value = _resp_json(data)
    with patch("app.retrieval.embedding.httpx.Client", return_value=fake_client):
        result = emb.embed_documents(["a", "b", "c"])
    assert result == vectors


def test_embed_query_single():
    emb = OpenAICompatEmbedding(_cfg())
    fake_client = MagicMock()
    fake_client.__enter__.return_value.post.return_value = _resp_json(
        _embedding_response([[0.9, 0.8]])
    )
    with patch("app.retrieval.embedding.httpx.Client", return_value=fake_client):
        result = emb.embed_query("什么是多态")
    assert result == [0.9, 0.8]


def test_embed_documents_empty_returns_empty():
    emb = OpenAICompatEmbedding(_cfg())
    assert emb.embed_documents([]) == []


def test_external_api_sends_bearer_header():
    emb = OpenAICompatEmbedding(_cfg(provider="external", api_key="sk-embed"))
    fake_client = MagicMock()
    fake_client.__enter__.return_value.post.return_value = _resp_json(_embedding_response([[0.1]]))
    with patch("app.retrieval.embedding.httpx.Client", return_value=fake_client):
        emb.embed_query("ping")
    _, kwargs = fake_client.__enter__.return_value.post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer sk-embed"


def test_unavailable_raises_on_embed():
    emb = OpenAICompatEmbedding(_cfg(base_url="http://127.0.0.1:1/v1", timeout=1))
    assert emb.is_available() is False
    with pytest.raises(RetrievalUnavailable):
        emb.embed_query("ping")


def test_probe_result_cached():
    emb = OpenAICompatEmbedding(_cfg(base_url="http://127.0.0.1:1/v1", timeout=1))
    with patch.object(emb, "_probe", wraps=emb._probe) as probe:
        assert emb.is_available() is False
        assert emb.is_available() is False
    assert probe.call_count == 1
