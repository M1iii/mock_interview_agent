import json

import pytest

from app.verify.bocha import BochaClient, BochaError


def _payload(pages):
    return {"code": 200, "data": {"webPages": {"value": pages}}}


def test_search_returns_results(monkeypatch):
    client = BochaClient("bocha-key")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                _payload(
                    [
                        {"name": "Redis 官网", "url": "https://redis.io", "snippet": "Redis 简介"},
                        {"name": "缓存穿透", "url": "https://x.com/1", "summary": "解决方案"},
                    ]
                )
            ).encode()

    captured = {}

    def _urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data)
        captured["auth"] = req.headers["Authorization"]
        return _Resp()

    monkeypatch.setattr("app.verify.bocha.urllib.request.urlopen", _urlopen)
    results = client.search("缓存穿透", count=2)
    assert len(results) == 2
    assert results[0].title == "Redis 官网"
    assert results[0].url == "https://redis.io"
    assert captured["auth"] == "Bearer bocha-key"
    assert captured["body"]["count"] == 2


def test_search_without_key_raises():
    client = BochaClient("")
    with pytest.raises(BochaError):
        client.search("什么")


def test_search_network_error_raises(monkeypatch):
    client = BochaClient("key")

    def _boom(*a, **k):
        raise OSError("timeout")

    monkeypatch.setattr("app.verify.bocha.urllib.request.urlopen", _boom)
    with pytest.raises(BochaError):
        client.search("什么")
