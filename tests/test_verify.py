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
