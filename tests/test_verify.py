import json
from types import SimpleNamespace

from app.verify.bocha import BochaError
from app.verify.verify import VerifyContext


def _llm(raw):
    return SimpleNamespace(complete_sync=lambda api_key, prompt, callbacks=None: (raw, {}))


def _bocha(results):
    return SimpleNamespace(search=lambda query, count=3: results)


def _cfg():
    from omegaconf import OmegaConf

    return OmegaConf.create({"verify": {"top_k": 3, "enabled": True}})


class _Keys:
    def __init__(self, key="bocha-key"):
        self._key = key

    def get_verify_key(self):
        return self._key


def test_skip_when_no_key():
    ctx = VerifyContext(_llm("{}"), _cfg(), _Keys(key=""))
    assert ctx.verify("sk-llm", "你好") is None


def test_skip_when_not_factual():
    judge = json.dumps({"is_factual": False, "claims": []})
    ctx = VerifyContext(_llm(judge), _cfg(), _Keys())
    assert ctx.verify("sk-llm", "我觉得自己很适合这个岗位") is None


def test_verified_flow():
    judge = json.dumps({"is_factual": True, "claims": ["Redis 支持持久化"]})
    verdict = json.dumps({"status": "verified", "reason": "信源一致"})

    class _SeqLLM:
        def __init__(self):
            self._calls = 0

        def complete_sync(self, api_key, prompt, callbacks=None):
            self._calls += 1
            return (judge if self._calls == 1 else verdict, {})

    bocha = _bocha(
        [SimpleNamespace(title="Redis 持久化", url="https://redis.io", snippet="支持 RDB/AOF")]
    )
    ctx = VerifyContext(_SeqLLM(), _cfg(), _Keys(), bocha=bocha)
    v = ctx.verify("sk-llm", "Redis 支持持久化")
    assert v is not None
    assert v.status == "verified"
    assert v.sources[0]["url"] == "https://redis.io"
    assert v.to_dict()["claims"] == ["Redis 支持持久化"]


def test_search_failure_degrades_to_unconfirmed():
    judge = json.dumps({"is_factual": True, "claims": ["X 公司成立于 2001 年"]})

    class _Boom:
        def search(self, query, count=3):
            raise BochaError("网络失败")

    ctx = VerifyContext(_llm(judge), _cfg(), _Keys(), bocha=_Boom())
    v = ctx.verify("sk-llm", "X 公司成立于 2001 年")
    assert v is not None
    assert v.status == "unconfirmed"
    assert v.skipped is False


# --- 最终审查修复轮（BLOCKER：配置页 Key 必须真正到达搜索客户端）---

JUDGE = json.dumps({"is_factual": True, "claims": ["Redis 支持持久化"]})
VERDICT = json.dumps({"status": "verified", "reason": "信源一致"})


class _RoutingLLM:
    """按 prompt 内容返回判定 / 二次判定响应，并记录调用次数。"""

    def __init__(self, judge: str = JUDGE, verdict: str = VERDICT) -> None:
        self._judge = judge
        self._verdict = verdict
        self.calls = 0

    def complete_sync(self, api_key, prompt, callbacks=None):
        self.calls += 1
        return (self._judge if "事实性陈述判定助手" in prompt else self._verdict, {})


def _cfg_with_api_key(api_key: str, enabled: bool = True):
    from omegaconf import OmegaConf

    return OmegaConf.create(
        {"verify": {"top_k": 3, "enabled": enabled, "api_key": api_key, "timeout": 10}}
    )


def _patch_urlopen(monkeypatch):
    """把 bocha 的 urlopen 替换为假响应，捕获真实请求的 Authorization 头。

    修复前 `_api_key` 恒为空 → BochaClient.search 直接抛 BochaError，
    请求根本不会发出，`captured` 为空 → 断言失败（即缺陷的可复现证据）。
    """
    import app.verify.bocha as bocha_mod

    captured: dict[str, str] = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self) -> bytes:
            payload = {
                "data": {
                    "webPages": {
                        "value": [
                            {
                                "name": "Redis 持久化",
                                "url": "https://redis.io",
                                "snippet": "支持 RDB/AOF",
                            }
                        ]
                    }
                }
            }
            return json.dumps(payload).encode("utf-8")

    def _fake_urlopen(req, timeout=None):
        captured["authorization"] = req.headers.get("Authorization", "")
        captured["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(bocha_mod.urllib.request, "urlopen", _fake_urlopen)
    return captured


def test_runtime_key_reaches_search_client(monkeypatch):
    """运行期设置的 Key 必须真正到达搜索客户端（Authorization: Bearer <Key>）。

    场景同 lifespan：构造 VerifyContext 时 KeyStore 无 verify key，随后用户在配置页
    PUT /api/settings/verify-key 写入 Key —— 此时搜索请求头必须带上该 Key。
    """
    from app.llm.keys import KeyStore

    captured = _patch_urlopen(monkeypatch)
    keys = KeyStore()  # 初始无 Key（等价于 lifespan 启动时 .env 未配置 VERIFY_API_KEY）
    ctx = VerifyContext(_RoutingLLM(), _cfg(), keys)

    keys.set_verify_key("bocha-real")  # 运行期写入（配置页）
    v = ctx.verify("sk-llm", "Redis 支持持久化")

    assert captured.get("authorization") == "Bearer bocha-real"
    assert v is not None
    assert v.status == "verified"
    assert v.sources and v.sources[0]["url"] == "https://redis.io"


def test_client_rebuilt_only_when_key_changes(monkeypatch):
    """Key 变化 → 重建客户端（新 Key 生效）；Key 不变 → 复用缓存实例。"""
    from app.llm.keys import KeyStore

    captured = _patch_urlopen(monkeypatch)
    keys = KeyStore()
    ctx = VerifyContext(_RoutingLLM(), _cfg(), keys)

    keys.set_verify_key("bocha-1")
    assert ctx.verify("sk-llm", "Redis 支持持久化") is not None
    assert captured["authorization"] == "Bearer bocha-1"
    cached = ctx._search_client()
    assert ctx._search_client() is cached  # 同一 Key → 复用，避免每题重建

    keys.set_verify_key("bocha-2")
    assert ctx.verify("sk-llm", "Redis 支持持久化") is not None
    assert captured["authorization"] == "Bearer bocha-2"
    assert ctx._search_client() is not cached  # Key 变化 → 重建


def test_cfg_api_key_used_when_keystore_empty(monkeypatch):
    """KeyStore 无 verify key 时回退 cfg.verify.api_key（.env VERIFY_API_KEY）。"""
    captured = _patch_urlopen(monkeypatch)
    ctx = VerifyContext(_RoutingLLM(), _cfg_with_api_key("bocha-env"), _Keys(key=""))
    v = ctx.verify("sk-llm", "Redis 支持持久化")
    assert captured.get("authorization") == "Bearer bocha-env"
    assert v is not None


def test_disabled_by_config_skips_without_any_call(monkeypatch):
    """verify.enabled=False → 直接跳过（不调用 LLM / 搜索）。"""
    captured = _patch_urlopen(monkeypatch)
    llm = _RoutingLLM()
    ctx = VerifyContext(llm, _cfg_with_api_key("bocha-x", enabled=False), _Keys())
    assert ctx.verify("sk-llm", "Redis 支持持久化") is None
    assert llm.calls == 0
    assert captured == {}


def test_missing_key_and_disabled_returns_none_without_http(monkeypatch):
    """既无 Key 又未启用时同样静默跳过（不抛错、不发请求）。"""
    captured = _patch_urlopen(monkeypatch)
    from app.llm.keys import KeyStore

    ctx = VerifyContext(_RoutingLLM(), _cfg_with_api_key(""), KeyStore())
    assert ctx.verify("sk-llm", "Redis 支持持久化") is None
    assert captured == {}
