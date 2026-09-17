"""全局设置 API：API Key 设置/掩码 + Embedding 配置（切换即重建，P1-7）。"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from omegaconf import OmegaConf
from pydantic import BaseModel, Field

from app.api.deps import get_embedding, get_es, get_key_store, get_knowledge_store, get_qdrant
from app.config import PROJECT_ROOT, mask_secret
from app.llm.keys import APIKeyError, KeyStore
from app.retrieval.embedding import OpenAICompatEmbedding
from app.retrieval.es import ESManager
from app.retrieval.qdrant import QdrantManager
from app.retrieval.tasks import rebuild_all_async
from app.store.knowledge import KnowledgeStore

router = APIRouter(prefix="/settings", tags=["settings"])

_ENV_KEYS = {
    "provider": "EMBEDDING_PROVIDER",
    "base_url": "EMBEDDING_BASE_URL",
    "api_key": "EMBEDDING_API_KEY",
    "model_id": "EMBEDDING_MODEL_ID",
    "dims": "EMBEDDING_DIMS",
    "timeout": "EMBEDDING_TIMEOUT",
}


class SetKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=3)


class KeyResponse(BaseModel):
    masked_key: str
    is_set: bool


class EmbeddingConfigRequest(BaseModel):
    provider: str = Field(..., pattern="^(local|external)$")
    base_url: str = Field(..., min_length=4)
    api_key: str = ""
    model_id: str = Field(..., min_length=1)
    dims: int = Field(..., ge=1)
    timeout: int = Field(default=10, ge=1, le=120)


class EmbeddingConfigResponse(BaseModel):
    provider: str
    base_url: str
    model_id: str
    dims: int
    timeout: int
    masked_api_key: str
    available: bool
    rebuilding: bool = False


@router.put("/api-key", response_model=KeyResponse)
async def set_api_key(
    req: SetKeyRequest,
    key_store: KeyStore = Depends(get_key_store),
) -> KeyResponse:
    """设置全局 API Key（sk- 前缀校验；变更后新会话生效，进行中沿用旧 Key）。"""
    try:
        key_store.set_global_key(req.api_key)
    except APIKeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return KeyResponse(masked_key=key_store.get_global_masked(), is_set=True)


@router.get("/api-key", response_model=KeyResponse)
async def get_api_key(
    key_store: KeyStore = Depends(get_key_store),
) -> KeyResponse:
    """获取全局 API Key 掩码（不返回明文）。"""
    is_set = key_store.get_global_key() is not None
    return KeyResponse(masked_key=key_store.get_global_masked(), is_set=is_set)


class VerifyKeyRequest(BaseModel):
    verify_key: str = Field(default="", max_length=256)


@router.put("/verify-key", response_model=KeyResponse)
async def set_verify_key(
    req: VerifyKeyRequest,
    key_store: KeyStore = Depends(get_key_store),
) -> KeyResponse:
    """设置联网搜索 Key（博查，可选填；传空串清除）。"""
    key_store.set_verify_key(req.verify_key.strip())
    return KeyResponse(
        masked_key=key_store.get_verify_masked(), is_set=key_store.get_verify_key() is not None
    )


@router.get("/verify-key", response_model=KeyResponse)
async def get_verify_key(
    key_store: KeyStore = Depends(get_key_store),
) -> KeyResponse:
    """获取联网搜索 Key 掩码（不返回明文）。"""
    key = key_store.get_verify_key()
    return KeyResponse(masked_key=key_store.get_verify_masked(), is_set=key is not None)


@router.get("/embedding", response_model=EmbeddingConfigResponse)
async def get_embedding_config(
    embedding: OpenAICompatEmbedding = Depends(get_embedding),
) -> EmbeddingConfigResponse:
    """获取当前 Embedding 配置（api_key 掩码返回，不泄露明文）。"""
    return EmbeddingConfigResponse(
        provider=embedding.provider,
        base_url=embedding.base_url,
        model_id=embedding.model_id,
        dims=embedding.dims,
        timeout=embedding.timeout,
        masked_api_key=mask_secret(embedding.api_key),
        available=embedding.is_available(),
    )


@router.put("/embedding", response_model=EmbeddingConfigResponse)
async def set_embedding_config(
    req: EmbeddingConfigRequest,
    request: Request,
    background: BackgroundTasks,
    store: KnowledgeStore = Depends(get_knowledge_store),
    qdrant: QdrantManager = Depends(get_qdrant),
    es: ESManager = Depends(get_es),
) -> EmbeddingConfigResponse:
    """保存 Embedding 配置：探测可用性 → 持久化 .env → 切换生效 → 后台全库重建（P1-7）。"""
    values = req.model_dump()
    provider = OpenAICompatEmbedding(OmegaConf.create({"retrieval": {"embedding": values}}))
    if not provider.is_available():
        raise HTTPException(status_code=400, detail="Embedding 服务不可用，请检查地址/模型")

    _persist_env(values)
    _apply_to_config(request, values)
    request.app.state.embedding = provider

    has_files = bool(store.list_all_files())
    if has_files:
        background.add_task(
            rebuild_all_async, store, qdrant, es, provider, request.app.state.config
        )

    return EmbeddingConfigResponse(
        provider=provider.provider,
        base_url=provider.base_url,
        model_id=provider.model_id,
        dims=provider.dims,
        timeout=provider.timeout,
        masked_api_key=mask_secret(values["api_key"]),
        available=True,
        rebuilding=has_files,
    )


def _persist_env(values: dict) -> None:
    """明文写入 .env（P0 决策：Key 存储明文 .env + python-dotenv）。"""
    from dotenv import set_key

    env_path = PROJECT_ROOT / ".env"
    for field, env_name in _ENV_KEYS.items():
        set_key(str(env_path), env_name, str(values[field]))


def _apply_to_config(request: Request, values: dict) -> None:
    """同步到 app.state.config，供后续构建的 provider/后台任务使用。"""
    emb = request.app.state.config.retrieval.embedding
    for field, value in values.items():
        setattr(emb, field, value)
