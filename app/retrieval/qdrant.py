"""Qdrant 客户端管理：懒加载单例 + 连通性探测（结果缓存）+ 缺失降级。"""

import time

from loguru import logger
from qdrant_client import QdrantClient

from app.config import DictConfig
from app.retrieval import RetrievalUnavailable


class QdrantManager:
    """Qdrant 懒加载 manager。服务不可用时 is_available() 返回 False，不抛异常。"""

    _PROBE_TTL = 30.0

    def __init__(self, cfg: DictConfig):
        self._url = cfg.retrieval.qdrant_url
        self._timeout = cfg.retrieval.qdrant_timeout
        self._collection = cfg.retrieval.qdrant_collection
        self._client: QdrantClient | None = None
        self._available: bool | None = None
        self._probed_at = 0.0

    @property
    def collection(self) -> str:
        return self._collection

    def ensure_collection(self, dims: int) -> None:
        """按需创建 collection（向量维度 = embedding dims）。"""
        client = self.get_client()
        if client.collection_exists(self._collection):
            return
        client.create_collection(
            collection_name=self._collection,
            vectors_config={"size": dims, "distance": "Cosine"},
        )
        logger.info("qdrant collection created: {c} (dims={d})", c=self._collection, d=dims)

    def is_available(self) -> bool:
        if self._available is not None and time.monotonic() - self._probed_at < self._PROBE_TTL:
            return self._available
        self._available = self._probe()
        self._probed_at = time.monotonic()
        if not self._available:
            logger.warning("qdrant unavailable: {url}", url=self._url)
        return self._available

    def get_client(self) -> QdrantClient:
        if not self.is_available():
            raise RetrievalUnavailable(f"Qdrant 不可用：{self._url}")
        assert self._client is not None
        return self._client

    def _probe(self) -> bool:
        try:
            self._connect()
            return True
        except Exception as e:  # noqa: BLE001 - 连通性探测吞掉一切异常，仅降级
            logger.debug("qdrant probe failed: {err}", err=repr(e))
            return False

    def _connect(self) -> QdrantClient:
        if self._client is None:
            # check_compatibility=False：本地固定版本服务，跳过版本检查（失败路径零噪音）
            client = QdrantClient(url=self._url, timeout=self._timeout, check_compatibility=False)
            client.get_collections()
            self._client = client
        return self._client
