"""博查 Web Search 客户端（国内备案、中文友好；Key 可选填，未配置优雅降级）。

失败语义：Key 缺失 / 网络异常 / 非 200 → 抛 BochaError（上层静默跳过核验）。
"""

import json
import urllib.request
from dataclasses import dataclass

from loguru import logger

DEFAULT_BASE_URL = "https://api.bochaai.com/v1/web-search"


class BochaError(RuntimeError):
    """搜索失败（Key 缺失 / 网络 / 非 200）。"""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class BochaClient:
    """同步搜索客户端（核验在后台线程执行，无需 async）。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout

    def search(self, query: str, count: int = 3) -> list[SearchResult]:
        if not self._api_key:
            raise BochaError("联网搜索 Key 未配置")
        body = json.dumps({"query": query, "count": count, "freshness": "noLimit"}).encode("utf-8")
        req = urllib.request.Request(
            self._base_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - 网络/超时/解析统一转业务异常
            raise BochaError(f"搜索请求失败：{e!r}") from e
        pages = ((payload.get("data") or {}).get("webPages") or {}).get("value") or []
        results = [
            SearchResult(
                title=str(p.get("name", "")),
                url=str(p.get("url", "")),
                snippet=str(p.get("snippet") or p.get("summary") or "")[:200],
            )
            for p in pages
        ][:count]
        logger.info("bocha search done: q={query} hits={n}", query=query[:40], n=len(results))
        return results
