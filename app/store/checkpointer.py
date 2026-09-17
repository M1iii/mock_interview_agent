"""checkpointer 抽象：P0 MemorySaver / P2 SqliteSaver 无缝替换。

图代码不感知 P0/P2 实现差异。P2 起默认 SqliteSaver（interview.db），
MemorySaver 仅保留为测试/无配置回退。"""

import sqlite3

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from omegaconf import DictConfig

from app.config import PROJECT_ROOT


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
    return SqliteSaver(conn)


def delete_thread(checkpointer, thread_id: str) -> None:
    """删除指定 thread 的状态数据（N-8：删除会话时存储三处同步清）。

    MemorySaver / SqliteSaver 均实现 delete_thread（langgraph 1.x per-thread 接口）。
    """
    checkpointer.delete_thread(thread_id)
