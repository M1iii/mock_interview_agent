"""依赖注入：从 app.state 获取 LLM 客户端、会话存储、Key 快照、checkpointer、检索组件。

全局单例在 main.py lifespan 中初始化，API 层通过 Depends 获取。"""

from fastapi import Depends, HTTPException, Request

from app.llm.client import DeepSeekClient
from app.llm.keys import KeyStore
from app.retrieval.embedding import EmbeddingProvider
from app.retrieval.es import ESManager
from app.retrieval.qdrant import QdrantManager
from app.store.knowledge import KnowledgeStore
from app.store.sessions import InMemorySessionStore, SessionMeta


def get_llm_client(request: Request) -> DeepSeekClient:
    return request.app.state.llm_client


def get_key_store(request: Request) -> KeyStore:
    return request.app.state.key_store


def get_session_store(request: Request) -> InMemorySessionStore:
    return request.app.state.session_store


def get_knowledge_store(request: Request) -> KnowledgeStore:
    return request.app.state.knowledge_store


def get_qdrant(request: Request) -> QdrantManager:
    return request.app.state.qdrant


def get_es(request: Request) -> ESManager:
    return request.app.state.es


def get_embedding(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding


def get_session(
    session_id: str,
    store: InMemorySessionStore = Depends(get_session_store),
) -> SessionMeta:
    meta = store.get(session_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return meta
