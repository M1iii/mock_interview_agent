"""DeepSeek 客户端：流式 / 完整回复 / 超时重试 / TTFT 与用量打点。"""

import time
from collections.abc import AsyncIterator

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_deepseek import ChatDeepSeek
from omegaconf import DictConfig

from app.logging import log_ttft, logger


class LLMError(RuntimeError):
    """LLM 调用失败（超时 / 重试耗尽 / 网络），上层转业务文案（N-3）。"""


class DeepSeekClient:
    """按 API Key 缓存 LLM 实例：不同会话（不同 Key）互不串用。"""

    def __init__(self, cfg: DictConfig) -> None:
        self._cfg = cfg
        self._instances: dict[str, ChatDeepSeek] = {}

    def _instance(self, api_key: str) -> ChatDeepSeek:
        if api_key not in self._instances:
            self._instances[api_key] = ChatDeepSeek(
                model=self._cfg.llm.model_id,
                base_url=self._cfg.llm.base_url,
                api_key=api_key,
                timeout=self._cfg.llm.timeout,
                max_retries=self._cfg.llm.max_retries,
            )
        return self._instances[api_key]

    async def stream(
        self, api_key: str, messages: list[BaseMessage], session_id: str | None = None
    ) -> AsyncIterator[str]:
        """逐 token 流式产出文本；记录 TTFT（首 token）与用量明细。"""
        llm = self._instance(api_key)
        started = time.monotonic()
        ttft_logged = False
        usage: dict | None = None
        try:
            async for chunk in llm.astream(messages, stream_options={"include_usage": True}):
                if not ttft_logged and chunk.content:
                    ttft_ms = (time.monotonic() - started) * 1000
                    log_ttft(ttft_ms, component="llm", session_id=session_id)
                    ttft_logged = True
                meta = chunk.response_metadata or {}
                if "usage" in meta:
                    usage = meta["usage"]
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            logger.error("llm stream failed: {err}", err=repr(e))
            raise LLMError("LLM 请求失败（超时或网络异常）") from e
        finally:
            duration_ms = (time.monotonic() - started) * 1000
            logger.bind(
                component="llm",
                session_id=session_id,
                duration_ms=round(duration_ms, 1),
                usage=usage,
            ).info("llm stream done")

    async def complete(
        self, api_key: str, messages: list[BaseMessage], session_id: str | None = None
    ) -> tuple[str, dict]:
        """非流式完整回复，返回 (文本, 用量)。"""
        llm = self._instance(api_key)
        started = time.monotonic()
        try:
            resp = await llm.ainvoke(messages)
        except Exception as e:
            logger.error("llm complete failed: {err}", err=repr(e))
            raise LLMError("LLM 请求失败（超时或网络异常）") from e
        finally:
            duration_ms = (time.monotonic() - started) * 1000
            logger.bind(
                component="llm",
                session_id=session_id,
                duration_ms=round(duration_ms, 1),
            ).info("llm complete done")
        usage = (resp.response_metadata or {}).get("usage") or {}
        return resp.content, usage

    def complete_sync(
        self, api_key: str, prompt: str, callbacks: list | None = None
    ) -> tuple[str, dict]:
        """同步回复（节点函数用，独立于 async 路径避免跨事件循环）。

        走同步 stream 逐块聚合：无 callbacks 时同非流式；有 callbacks 时逐 token
        触发回调（题干/追问的 SSE 转发）。callbacks 为空时由 langchain 从父级
        config 上下文继承（图内节点即经此把 token 路由到请求级处理器）。
        """
        llm = self._instance(api_key)
        started = time.monotonic()
        try:
            if callbacks:
                chunks = llm.stream([HumanMessage(content=prompt)], config={"callbacks": callbacks})
            else:
                chunks = llm.stream([HumanMessage(content=prompt)])
            parts: list[str] = []
            usage: dict | None = None
            for chunk in chunks:
                content = chunk.content
                if content:
                    parts.append(content)
                meta = chunk.response_metadata or {}
                if "usage" in meta:
                    usage = meta["usage"]
            content = "".join(parts)
        except Exception as e:
            logger.error("llm complete_sync failed: {err}", err=repr(e))
            raise LLMError("LLM 请求失败（超时或网络异常）") from e
        finally:
            duration_ms = (time.monotonic() - started) * 1000
            logger.bind(
                component="llm",
                duration_ms=round(duration_ms, 1),
            ).info("llm complete_sync done")
        return content, usage or {}
