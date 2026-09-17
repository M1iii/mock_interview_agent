import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from omegaconf import OmegaConf

from app.llm.client import DeepSeekClient, LLMError
from app.logging import setup_logging

CFG = OmegaConf.create(
    {
        "llm": {
            "model_id": "test-model",
            "base_url": "https://api.example.com",
            "timeout": 60,
            "max_retries": 2,
        },
        "logging": {
            "level": "INFO",
            "rotation": "10 MB",
            "retention": "14 days",
            "warn_ttft_ms": 5000,
        },
    }
)


def _chunk(text: str, usage: dict | None = None) -> AIMessageChunk:
    meta = {"usage": usage} if usage else {}
    return AIMessageChunk(content=text, response_metadata=meta)


class FakeChat:
    instances: list[tuple[str, dict]] = []

    def __init__(self, **kwargs) -> None:
        FakeChat.instances.append((kwargs["api_key"], kwargs))

    async def astream(self, messages, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, messages):
        raise NotImplementedError

    def stream(self, messages, **kwargs):
        raise NotImplementedError


@pytest.fixture
def fake_chat(monkeypatch):
    FakeChat.instances.clear()
    monkeypatch.setattr("app.llm.client.ChatDeepSeek", FakeChat)
    return FakeChat


def _collector():
    lines: list[str] = []

    def sink(message: str) -> None:
        lines.append(message)

    return lines, sink


def _last_json(lines: list[str]) -> dict:
    return json.loads(lines[-1])


async def test_stream_yields_tokens(fake_chat):
    async def astream(messages, **kwargs):
        yield _chunk("你好")
        yield _chunk("，世界")

    fake_chat.astream = staticmethod(astream)
    client = DeepSeekClient(CFG)
    out = [tok async for tok in client.stream("sk-aaa", [HumanMessage("hi")], session_id="s1")]
    assert out == ["你好", "，世界"]


async def test_stream_ttft_and_usage_logged(fake_chat):
    lines, sink = _collector()
    setup_logging(CFG, sinks=[{"sink": sink}])
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    async def astream(messages, **kwargs):
        yield _chunk("", usage=usage)
        yield _chunk("首")

    fake_chat.astream = staticmethod(astream)
    client = DeepSeekClient(CFG)
    out = [tok async for tok in client.stream("sk-aaa", [HumanMessage("hi")], session_id="s1")]
    assert out == ["首"]
    payloads = [json.loads(line) for line in lines]
    ttft = next(p for p in payloads if p["msg"].startswith("TTFT"))
    assert ttft["level"] == "INFO"
    assert ttft["component"] == "llm"
    done = next(p for p in payloads if p["msg"] == "llm stream done")
    assert done["usage"] == usage
    assert done["session_id"] == "s1"
    assert done["duration_ms"] >= 0


async def test_stream_failure_raises_llm_error(fake_chat):
    async def astream(messages, **kwargs):
        raise TimeoutError("boom")
        yield  # 使 fake 为 async generator（与真实 ChatDeepSeek 形态一致）

    fake_chat.astream = staticmethod(astream)
    client = DeepSeekClient(CFG)
    with pytest.raises(LLMError):
        async for _ in client.stream("sk-aaa", [HumanMessage("hi")]):
            pass


async def test_complete_returns_content_and_usage(fake_chat):
    async def ainvoke(messages):
        return AIMessage(
            content="完整回答",
            response_metadata={"usage": {"total_tokens": 42}},
        )

    fake_chat.ainvoke = staticmethod(ainvoke)
    client = DeepSeekClient(CFG)
    content, usage = await client.complete("sk-aaa", [HumanMessage("hi")], session_id="s1")
    assert content == "完整回答"
    assert usage == {"total_tokens": 42}


async def test_complete_failure_raises_llm_error(fake_chat):
    async def ainvoke(messages):
        raise ConnectionError("down")

    fake_chat.ainvoke = staticmethod(ainvoke)
    client = DeepSeekClient(CFG)
    with pytest.raises(LLMError):
        await client.complete("sk-aaa", [HumanMessage("hi")])


def test_complete_sync_returns_content_and_usage(fake_chat):
    def stream(messages, **kwargs):
        yield _chunk("同步回答", usage={"total_tokens": 7})

    fake_chat.stream = staticmethod(stream)
    client = DeepSeekClient(CFG)
    content, usage = client.complete_sync("sk-aaa", "hi")
    assert content == "同步回答"
    assert usage == {"total_tokens": 7}


def test_complete_sync_passes_explicit_callbacks(fake_chat):
    """callbacks 显式传入时通过 config 交给 LLM（skip 出题流式场景）。"""

    def stream(messages, config=None, **kwargs):
        assert config and config.get("callbacks")
        yield _chunk("带回调回答")

    fake_chat.stream = staticmethod(stream)
    client = DeepSeekClient(CFG)
    content, _ = client.complete_sync("sk-aaa", "hi", callbacks=[object()])
    assert content == "带回调回答"


def test_complete_sync_failure_raises_llm_error(fake_chat):
    def stream(messages, **kwargs):
        raise ConnectionError("down")
        yield

    fake_chat.stream = staticmethod(stream)
    client = DeepSeekClient(CFG)
    with pytest.raises(LLMError):
        client.complete_sync("sk-aaa", "hi")


async def test_instances_cached_per_key(fake_chat):
    async def astream(messages, **kwargs):
        yield _chunk("ok")

    fake_chat.astream = staticmethod(astream)
    client = DeepSeekClient(CFG)
    async for _ in client.stream("sk-aaa", [HumanMessage("hi")]):
        pass
    async for _ in client.stream("sk-aaa", [HumanMessage("hi")]):
        pass
    async for _ in client.stream("sk-bbb", [HumanMessage("hi")]):
        pass
    keys = [api_key for api_key, _ in FakeChat.instances]
    assert keys == ["sk-aaa", "sk-bbb"]
