"""知识库检索基础设施（P1）：Embedding / Qdrant / ES 客户端管理。

服务缺失时降级（is_available()==False），不阻塞应用启动与核心对话。
"""


class RetrievalUnavailable(RuntimeError):
    """检索服务不可用（Qdrant/ES 未启动、连不上或超时）。调用方捕获后降级。"""
