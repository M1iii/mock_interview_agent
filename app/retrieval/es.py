"""Elasticsearch 客户端管理：懒加载单例 + 连通性探测（结果缓存）+ 缺失降级。"""

import time

from elasticsearch import Elasticsearch
from loguru import logger

from app.config import DictConfig
from app.retrieval import RetrievalUnavailable


class ESManager:
    """ES 懒加载 manager（ik 分词全文检索）。服务不可用时 is_available() 返回 False。"""

    _PROBE_TTL = 30.0

    def __init__(self, cfg: DictConfig):
        self._url = cfg.retrieval.es_url
        self._timeout = cfg.retrieval.es_timeout
        self._index = cfg.retrieval.es_index
        self._client: Elasticsearch | None = None
        self._available: bool | None = None
        self._probed_at = 0.0

    @property
    def index(self) -> str:
        return self._index

    def ensure_index(self) -> None:
        """按需创建索引（ik_max_word 分词 + 中文最佳实践）。"""
        client = self.get_client()
        if client.indices.exists(index=self._index):
            return
        client.indices.create(
            index=self._index,
            settings={
                "analysis": {
                    "analyzer": {"ik_analyzer": {"type": "custom", "tokenizer": "ik_max_word"}}
                }
            },
            mappings={
                "properties": {
                    "parent_id": {"type": "keyword"},
                    "file_id": {"type": "keyword"},
                    "file_name": {"type": "keyword"},
                    "kb_id": {"type": "keyword"},
                    "text": {
                        "type": "text",
                        "analyzer": "ik_analyzer",
                        "search_analyzer": "ik_smart",
                    },
                }
            },
        )
        logger.info("es index created: {i}", i=self._index)

    def is_available(self) -> bool:
        if self._available is not None and time.monotonic() - self._probed_at < self._PROBE_TTL:
            return self._available
        self._available = self._probe()
        self._probed_at = time.monotonic()
        if not self._available:
            logger.warning("es unavailable: {url}", url=self._url)
        return self._available

    def get_client(self) -> Elasticsearch:
        if not self.is_available():
            raise RetrievalUnavailable(f"Elasticsearch 不可用：{self._url}")
        assert self._client is not None
        return self._client

    def _probe(self) -> bool:
        try:
            self._connect()
            return True
        except Exception as e:  # noqa: BLE001 - 连通性探测吞掉一切异常，仅降级
            logger.debug("es probe failed: {err}", err=repr(e))
            return False

    def _connect(self) -> Elasticsearch:
        if self._client is None:
            client = Elasticsearch(hosts=[self._url], request_timeout=self._timeout)
            if not client.options(request_timeout=self._timeout).ping():
                raise RetrievalUnavailable(f"Elasticsearch ping 失败：{self._url}")
            self._client = client
        return self._client
