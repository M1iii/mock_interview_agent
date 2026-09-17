"""checkpointer 抽象：P0 MemorySaver / P2 SqliteSaver 无缝替换。

图代码不感知 P0/P2 实现差异。"""

from langgraph.checkpoint.memory import MemorySaver


def create_checkpointer():
    """P0：返回 MemorySaver（内存态，刷新可恢复，后端重启丢失）。"""
    return MemorySaver()


def delete_thread(checkpointer, thread_id: str) -> None:
    """删除指定 thread 的状态数据（N-8：删除会话时存储三处同步清）。

    P0: MemorySaver.delete_thread（langgraph 1.x 提供按 thread 删除接口）。
    P2: SqliteSaver 同样实现 delete_thread，可无缝替换。
    """
    checkpointer.delete_thread(thread_id)
