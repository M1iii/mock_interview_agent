"""EmbeddingProvider 抽象：OpenAI-compatible embedding 客户端。

方案 A（2026-09-16 确认）：本地 bge-large-zh-v1.5 复用本机电商问数 TEI 服务
（默认 http://127.0.0.1:8081/v1，OpenAI-compatible /v1/embeddings 端点），本地与
外部 API 共用同一 HTTP 实现，仅 base_url/api_key 不同。服务缺失时 is_available()
返回 False（探测结果缓存 30s），知识库功能降级，不阻塞核心对话。
"""

import time

import httpx
from loguru import logger
from omegaconf import DictConfig

from app.retrieval import RetrievalUnavailable

# 内置 model_id → 维度映射；未收录模型由配置 dims 指定
KNOWN_DIMS: dict[str, int] = {"bge-large-zh-v1.5": 1024}


class EmbeddingProvider:
    """Embedding 抽象：批量/单条向量化 + model_id/dims 元数据 + 可用性探测。

    知识库入库时以 model_id + dims 绑定（见 architecture v0.4 §4.3），
    查询模型 ≠ 库绑定模型时由上层拒绝。
    """

    @property
    def model_id(self) -> str:
        raise NotImplementedError

    @property
    def dims(self) -> int:
        raise NotImplementedError

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError


class OpenAICompatEmbedding(EmbeddingProvider):
    """OpenAI-compatible /v1/embeddings 客户端（本地 TEI 与外部 API 共用）。"""

    _PROBE_TTL = 30.0

    def __init__(self, cfg: DictConfig) -> None:
        emb = cfg.retrieval.embedding
        self._provider = emb.provider
        self._base_url = emb.base_url.rstrip("/")
        self._api_key = emb.api_key
        self._timeout = emb.timeout
        self._configured_model = emb.model_id
        self._configured_dims = emb.dims
        self._available: bool | None = None
        self._probed_at = 0.0

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def timeout(self) -> int:
        return self._timeout

    @property
    def model_id(self) -> str:
        return self._configured_model

    @property
    def dims(self) -> int:
        if self._configured_dims:
            return self._configured_dims
        return KNOWN_DIMS.get(self._configured_model, 0)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = self._post({"model": self.model_id, "input": texts})
        items = sorted(data["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in items]

    def embed_query(self, text: str) -> list[float]:
        data = self._post({"model": self.model_id, "input": [text]})
        return data["data"][0]["embedding"]

    def is_available(self) -> bool:
        if self._available is not None and time.monotonic() - self._probed_at < self._PROBE_TTL:
            return self._available
        self._available = self._probe()
        self._probed_at = time.monotonic()
        if not self._available:
            logger.warning("embedding unavailable: {url}", url=self._base_url)
        return self._available

    def _post(self, payload: dict) -> dict:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(f"{self._base_url}/embeddings", json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.error("embedding request failed: {err}", err=repr(e))
            raise RetrievalUnavailable(f"Embedding 服务不可用：{self._base_url}") from e

    def _probe(self) -> bool:
        try:
            vec = self.embed_query("ping")
            if self.dims and len(vec) != self.dims:
                logger.warning(
                    "embedding dims mismatch: model={m} expect={e} got={g}",
                    m=self.model_id,
                    e=self.dims,
                    g=len(vec),
                )
            return True
        except Exception as e:  # noqa: BLE001 - 探测吞掉一切异常，仅降级
            logger.debug("embedding probe failed: {err}", err=repr(e))
            return False
