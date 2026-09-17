"""API Key 校验 / 掩码 / 会话级快照：新会话新 Key，进行中会话沿用旧 Key。"""

from app.config import mask_secret


class APIKeyError(ValueError):
    """API Key 非法（空 / 非 sk- 前缀）。"""


def validate_api_key(api_key: str) -> str:
    if not api_key or not api_key.startswith("sk-") or len(api_key) <= 3:
        raise APIKeyError("API Key 必须以 sk- 开头且包含有效内容")
    return api_key


class KeyStore:
    """全局 Key + 会话级快照。

    全局 Key：用户在配置页设置，所有新会话共用。
    会话快照：新建会话时从全局 Key 快照一份，后续会话内不变。
    """

    def __init__(self) -> None:
        self._global_key: str | None = None
        self._keys: dict[str, str] = {}

    # --- 全局 Key ---

    def set_global_key(self, api_key: str) -> None:
        self._global_key = validate_api_key(api_key)

    def get_global_key(self) -> str | None:
        return self._global_key

    def get_global_masked(self) -> str:
        return mask_secret(self._global_key) if self._global_key else ""

    # --- 会话级快照 ---

    def register(self, session_id: str, api_key: str) -> None:
        self._keys[session_id] = validate_api_key(api_key)

    def snapshot_from_global(self, session_id: str) -> str:
        """从全局 Key 快照一份绑定到会话（新建会话时调用）。"""
        if not self._global_key:
            raise APIKeyError("全局 API Key 未设置")
        key = self._global_key
        self._keys[session_id] = key
        return key

    def get(self, session_id: str) -> str | None:
        """会话快照优先；重启后快照丢失时回退当前全局 Key（P2-3 恢复续聊）。"""
        return self._keys.get(session_id) or self._global_key

    def masked(self, session_id: str) -> str:
        key = self.get(session_id)
        return mask_secret(key) if key else ""

    def delete(self, session_id: str) -> None:
        self._keys.pop(session_id, None)
