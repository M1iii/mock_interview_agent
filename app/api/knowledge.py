"""知识库管理 API：建库 / 列表 / 上传（后台入库）/ 失败重试 / 删除级联（P1-5）。

澄清决策（2026-09-17）：元数据 SQLite kb.db；上传即返 processing，后台任务入库，
前端轮询至 ready/failed；删除级联清 Qdrant+ES+元数据+原文件；先建库后传文件。
"""

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from loguru import logger
from pydantic import BaseModel, Field

from app.api.deps import get_embedding, get_es, get_knowledge_store, get_qdrant
from app.config import PROJECT_ROOT
from app.retrieval.embedding import EmbeddingProvider
from app.retrieval.es import ESManager
from app.retrieval.ingest import delete_document, file_id_of
from app.retrieval.qdrant import QdrantManager
from app.retrieval.tasks import ingest_file_async
from app.store.knowledge import FAILED, PROCESSING, KbFile, KnowledgeStore

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # P1 F4：≤50MB
SUPPORTED_EXTS = {".md", ".txt", ".docx", ".pdf"}
_SAFE_NAME = re.compile(r"[^\w.\-]", flags=re.UNICODE)


class CreateKBRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


def _sanitize_name(name: str) -> str:
    base = Path(name).name.strip()
    return _SAFE_NAME.sub("_", base) or "file"


def _kb_dir(request: Request, kb_id: str) -> Path:
    base = PROJECT_ROOT / request.app.state.config.retrieval.kb_dir
    return base / kb_id


@router.post("")
async def create_kb(
    req: CreateKBRequest,
    store: KnowledgeStore = Depends(get_knowledge_store),
    embedding: EmbeddingProvider = Depends(get_embedding),
) -> dict:
    """新建知识库：命名 + 绑定当前 Embedding 模型（model_id/dims）。"""
    kb_id = f"kb-{uuid.uuid4().hex[:8]}"
    kb = store.create_kb(kb_id, req.name.strip(), embedding.model_id, embedding.dims)
    logger.info("knowledge base created: {id} name={name}", id=kb_id, name=kb.name)
    return kb.to_dict()


@router.get("")
async def list_kbs(
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> list[dict]:
    """列出全部知识库（含文件条目与状态，按创建时间倒序）。"""
    return [kb.to_dict() for kb in store.list_kbs()]


@router.post("/{kb_id}/files")
async def upload_file(
    kb_id: str,
    request: Request,
    background: BackgroundTasks,
    file: UploadFile,
    store: KnowledgeStore = Depends(get_knowledge_store),
    qdrant: QdrantManager = Depends(get_qdrant),
    es: ESManager = Depends(get_es),
    embedding: EmbeddingProvider = Depends(get_embedding),
) -> dict:
    """上传文档入库（≤50MB，md/txt/docx/pdf）：保存原文件 → processing → 后台入库。"""
    if store.get_kb(kb_id) is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTS:
        supported = "/".join(sorted(e.lstrip(".") for e in SUPPORTED_EXTS))
        raise HTTPException(status_code=400, detail=f"仅支持 {supported} 格式")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="文件超过 50MB 上限")

    dest_dir = _kb_dir(request, kb_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored = dest_dir / f"{uuid.uuid4().hex[:8]}_{_sanitize_name(file.filename or 'file')}"
    stored.write_bytes(data)

    file_id = file_id_of(stored)
    record = store.add_file(
        kb_id,
        file_id,
        file.filename or stored.name,
        str(stored.relative_to(PROJECT_ROOT)),
        len(data),
    )
    background.add_task(
        ingest_file_async, store, record, qdrant, es, embedding, request.app.state.config
    )
    logger.info(
        "kb file uploaded: {name} size={size} → processing", name=record.name, size=record.size
    )
    return {"file": record.to_dict()}


@router.post("/{kb_id}/files/{record_id}/retry")
async def retry_file(
    kb_id: str,
    record_id: str,
    request: Request,
    background: BackgroundTasks,
    store: KnowledgeStore = Depends(get_knowledge_store),
    qdrant: QdrantManager = Depends(get_qdrant),
    es: ESManager = Depends(get_es),
    embedding: EmbeddingProvider = Depends(get_embedding),
) -> dict:
    """失败文件重试：failed → processing → 重新入库（原文件保留，R6）。"""
    record = _get_file_or_404(store, kb_id, record_id)
    if record.status != FAILED:
        raise HTTPException(status_code=400, detail="仅失败状态的文件可重试")

    store.update_file_status(record.id, PROCESSING, error=None)
    background.add_task(
        ingest_file_async, store, record, qdrant, es, embedding, request.app.state.config
    )
    return {"file": store.get_file(record_id).to_dict()}


@router.delete("/{kb_id}")
async def delete_kb(
    kb_id: str,
    store: KnowledgeStore = Depends(get_knowledge_store),
    qdrant: QdrantManager = Depends(get_qdrant),
    es: ESManager = Depends(get_es),
) -> dict:
    """删除知识库：级联清理 Qdrant 子块 + ES 父块 + 元数据 + 原文件（R5 物理删）。

    检索服务缺失时降级：元数据与文件照删，残留向量记警告日志（无法级联清理）。
    """
    if store.get_kb(kb_id) is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    files = store.delete_kb(kb_id)
    cleaned = 0
    for f in files:
        try:
            delete_document(f.file_id, qdrant, es)
            cleaned += 1
        except Exception as e:  # noqa: BLE001 - 服务缺失降级：不阻塞删除
            logger.warning(
                "kb cascade delete skipped: {name} file={fid} err={err}",
                name=f.name,
                fid=f.file_id,
                err=repr(e),
            )
        (PROJECT_ROOT / f.path).unlink(missing_ok=True)
    logger.info(
        "knowledge base deleted: {id} files={n} cleaned={c}", id=kb_id, n=len(files), c=cleaned
    )
    return {"deleted": len(files), "cleaned": cleaned, "id": kb_id}


def _get_file_or_404(store: KnowledgeStore, kb_id: str, record_id: str) -> KbFile:
    record = store.get_file(record_id)
    if record is None or record.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文件不存在")
    return record
