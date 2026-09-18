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

import json
import sqlite3
from pathlib import Path
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


def _cleanse_sensitive(value: Any) -> Any:
    """递归剔除敏感项（既删字典**键**也删列表**项**），用于历史库自愈。

    运行时 `strip_sensitive` 只删字典键（`updated_channels` 由 put() 单独清洗）；
    历史脏数据可能在 `updated_channels` 等**列表**里残留 `_api_key` 通道名，
    故自愈需同时删键与列表项。不修改入参，返回新对象。
    """
    if isinstance(value, dict):
        return {k: _cleanse_sensitive(v) for k, v in value.items() if k not in SENSITIVE_STATE_KEYS}
    if isinstance(value, list):
        return [
            _cleanse_sensitive(v)
            for v in value
            if not (isinstance(v, str) and v in SENSITIVE_STATE_KEYS)
        ]
    return value


def scrub_history_db(db_path: str | Path) -> dict[str, int]:
    """启动自愈：清理由修复前旧版写入的明文 API Key（data/ 本地历史库，幂等）。

    `SanitizingSqliteSaver` 修复后新写不再落盘 `_api_key`；但修复前的历史数据
    仍残留在 SQLite：`writes` 表存在 `channel='_api_key'` 的行（该通道值即裸 Key），
    `checkpoints` 表的 checkpoint 页里也有含 `_api_key` 的旧页。本函数：
    1. 删除 `writes` 中 `_api_key` 通道的行——读回端 Key 由 `KeyStore` 每次重新注入，
       该通道无需落盘，删除安全；
    2. 对 checkpoint 做 serde 往返，经 `strip_sensitive` 剔除 `_api_key` 后重写，
       同步清洗 metadata 的敏感键与 `updated_channels` 通道名。

    传入 db 不存在或单行解析失败均不阻断（返回/跳过），保证启动路径不因脏历史崩溃。
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return {"deleted_writes": 0, "rewritten_checkpoints": 0}
    serde = SanitizedSerde()
    conn = sqlite3.connect(str(db_path))
    stats = {"deleted_writes": 0, "rewritten_checkpoints": 0}
    try:
        stats["deleted_writes"] = conn.execute(
            "DELETE FROM writes WHERE channel = '_api_key'"
        ).rowcount
        rows = conn.execute("SELECT rowid, type, checkpoint, metadata FROM checkpoints").fetchall()
        for rid, typ, blob, meta in rows:
            changed = False
            try:
                decoded = serde.loads_typed((typ, blob))
            except Exception:  # noqa: BLE001 - 无法解析的旧行跳过，不阻断自愈
                continue
            stripped = _cleanse_sensitive(decoded)
            if stripped != decoded:
                new_blob = serde.dumps_typed((typ, stripped))[1]
                conn.execute("UPDATE checkpoints SET checkpoint=? WHERE rowid=?", (new_blob, rid))
                changed = True
            try:
                meta_text = meta if isinstance(meta, str) else meta.decode("utf-8")
                meta_obj = json.loads(meta_text)
                meta_old = dict(meta_obj)
                meta_obj = strip_sensitive(meta_obj)
                if isinstance(meta_obj.get("updated_channels"), list):
                    meta_obj["updated_channels"] = [
                        c for c in meta_obj["updated_channels"] if c not in SENSITIVE_STATE_KEYS
                    ]
                if meta_obj != meta_old:
                    conn.execute(
                        "UPDATE checkpoints SET metadata=? WHERE rowid=?",
                        (json.dumps(meta_obj, ensure_ascii=False), rid),
                    )
                    changed = True
            except Exception:  # noqa: BLE001 - metadata 解析失败跳过
                pass
            if changed:
                stats["rewritten_checkpoints"] += 1
        conn.commit()
    except Exception:  # noqa: BLE001 - 自愈失败不阻断启动（交由上层提示）
        conn.rollback()
        raise
    finally:
        conn.close()
    return stats
