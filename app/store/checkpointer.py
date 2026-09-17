"""checkpointer 抽象：P0 MemorySaver / P2 SqliteSaver 无缝替换。

图代码不感知 P0/P2 实现差异。P2 起默认 SqliteSaver（interview.db），
MemorySaver 仅保留为测试/无配置回退。

安全（最终审查修复轮，MAJOR）：运行时 API Key（state 的 `_api_key` 通道）**不得落盘**。
两层拦截（SqliteSaver 的三条写盘路径全覆盖）：
1. `SanitizingSqliteSaver.put_writes`：按通道名丢弃 `_api_key` 的写入——该通道的
   写入值是**裸字符串 Key**（不是 dict），只在 serde 里递归删键抓不到，且通道名本身
   会写进 `writes.channel` 列；
2. `SanitizingSqliteSaver.put` + `SanitizedSerde`：从 checkpoint 里剔除 `_api_key`
   （`channel_values` / `channel_versions` / `versions_seen` 的键）与
   `updated_channels` 列表项，收口 metadata 与 msgpack blob 里的残留通道名。
读回端无需补偿：`KeyStore.get` 设计上「会话快照缺失时回退全局 Key」（P2-3），
且所有调用方（chat / finish / skip-last）每次都会重新注入 Key。
"""

import sqlite3
from typing import Any

from langgraph.checkpoint.base import ChannelVersions, Checkpoint, CheckpointMetadata
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from omegaconf import DictConfig

from app.config import PROJECT_ROOT

# 落盘前必须剔除的运行时密钥通道（见 app/interview/state.py「运行时注入」段）
SENSITIVE_STATE_KEYS = frozenset({"_api_key"})


def strip_sensitive(value: Any) -> Any:
    """递归剔除 state 中的敏感键（保留其余结构不变；不修改入参，返回新对象）。"""
    if isinstance(value, dict):
        return {k: strip_sensitive(v) for k, v in value.items() if k not in SENSITIVE_STATE_KEYS}
    if isinstance(value, list):
        return [strip_sensitive(v) for v in value]
    return value


def _without_sensitive_channels(names: Any) -> Any:
    """从通道名列表（updated_channels）中剔除敏感通道名。"""
    if isinstance(names, list):
        return [n for n in names if n not in SENSITIVE_STATE_KEYS]
    return names


class SanitizedSerde:
    """写盘脱敏的 serde 包装器：`dumps*` 前剔除 `_api_key`，`loads*` 直接委托。"""

    def __init__(self, inner: Any | None = None) -> None:
        self._inner = inner or JsonPlusSerializer()

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        return self._inner.dumps_typed(strip_sensitive(obj))

    def loads_typed(self, data: tuple[str, bytes]) -> Any:
        return self._inner.loads_typed(data)

    def dumps(self, obj: Any) -> bytes:
        return self._inner.dumps(strip_sensitive(obj))

    def loads(self, data: bytes) -> Any:
        return self._inner.loads(data)


class SanitizingSqliteSaver(SqliteSaver):
    """SqliteSaver + 运行时密钥通道脱敏（值不落盘、通道名不进 blob/列）。"""

    def put(
        self,
        config: Any,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> Any:
        checkpoint = dict(checkpoint)
        if "updated_channels" in checkpoint:
            checkpoint["updated_channels"] = _without_sensitive_channels(
                checkpoint["updated_channels"]
            )
        metadata = dict(metadata)
        if "updated_channels" in metadata:
            metadata["updated_channels"] = _without_sensitive_channels(metadata["updated_channels"])
        return super().put(config, checkpoint, metadata, new_versions)

    def put_writes(
        self,
        config: Any,
        writes: Any,
        task_id: str,
        task_path: str = "",
    ) -> None:
        writes = [
            (channel, value) for channel, value in writes if channel not in SENSITIVE_STATE_KEYS
        ]
        super().put_writes(config, writes, task_id, task_path)


def create_checkpointer(cfg: DictConfig | None = None):
    """创建持久化 checkpointer。

    P2：传入 cfg（含 interview.db 路径）时返回 SqliteSaver（跨重启持久化）；
    未传 cfg（纯测试/无配置）时回退 MemorySaver（内存态）。
    """
    if cfg is None:
        return MemorySaver()
    db_path = PROJECT_ROOT / cfg.interview.db
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # 注意：本版本 langgraph-checkpoint-sqlite 的 from_conn_string 是 contextmanager
    # （with 块退出即关连接），不适合应用级长生命周期 checkpointer；
    # 自行持有连接构造 SqliteSaver（与 SqliteSessionStore 单连接模式一致）。
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SanitizingSqliteSaver(conn, serde=SanitizedSerde())


def delete_thread(checkpointer, thread_id: str) -> None:
    """删除指定 thread 的状态数据（N-8：删除会话时存储三处同步清）。

    MemorySaver / SqliteSaver 均实现 delete_thread（langgraph 1.x per-thread 接口）。
    """
    checkpointer.delete_thread(thread_id)
