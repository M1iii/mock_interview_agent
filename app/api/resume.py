"""简历管理 API：上传 / 列表 / 删除 / 重试（P2-1）。

澄清决策（2026-09-17）：简历解析走轻量组合（pdfplumber + python-docx）+ LLM 抽取；
上传即返 processing，后台任务解析，前端轮询至 ready/failed；
删除级联清 DB 行（含考点清单）+ 原文件；支持 PDF/DOCX/MD/TXT，≤20MB。
"""

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from loguru import logger

from app.api.deps import get_key_store, get_llm_client, get_resume_store
from app.config import PROJECT_ROOT
from app.llm.client import DeepSeekClient
from app.llm.keys import KeyStore
from app.resume.tasks import process_resume_async
from app.store.resume import FAILED, Resume, ResumeStore

router = APIRouter(prefix="/resumes", tags=["resumes"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # PRD §6 N-9 修订：简历 ≤20MB
SUPPORTED_EXTS = {".md", ".txt", ".docx", ".pdf"}
_SAFE_NAME = re.compile(r"[^\w.\-]", flags=re.UNICODE)


def _sanitize_name(name: str) -> str:
    base = Path(name).name.strip()
    return _SAFE_NAME.sub("_", base) or "resume"


def _resume_dir(request: Request) -> Path:
    base = PROJECT_ROOT / request.app.state.config.resume.upload_dir
    base.mkdir(parents=True, exist_ok=True)
    return base


@router.post("")
async def upload_resume(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile,
    store: ResumeStore = Depends(get_resume_store),
    llm: DeepSeekClient = Depends(get_llm_client),
    key_store: KeyStore = Depends(get_key_store),
) -> dict:
    """上传简历（≤20MB，md/txt/docx/pdf）：保存原文件 → processing → 后台解析抽取。"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTS:
        supported = "/".join(sorted(e.lstrip(".") for e in SUPPORTED_EXTS))
        raise HTTPException(status_code=400, detail=f"仅支持 {supported} 格式")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="文件超过 20MB 上限")

    resume_id = f"r-{uuid.uuid4().hex[:8]}"
    dest_dir = _resume_dir(request)
    stored = dest_dir / f"{resume_id}_{_sanitize_name(file.filename or 'resume')}"
    stored.write_bytes(data)

    record = store.add_resume(
        resume_id, file.filename or stored.name, str(stored.relative_to(PROJECT_ROOT)), len(data)
    )
    background.add_task(
        process_resume_async,
        store,
        record,
        llm,
        key_store.get_global_key(),
        request.app.state.config,
    )
    logger.info(
        "resume uploaded: {name} size={size} → processing", name=record.file_name, size=record.size
    )
    return {"resume": record.to_dict()}


@router.get("")
async def list_resumes(
    store: ResumeStore = Depends(get_resume_store),
) -> list[dict]:
    """列出全部简历（含状态，按创建时间倒序）。"""
    return [r.to_dict() for r in store.list_resumes()]


@router.post("/{resume_id}/retry")
async def retry_resume(
    resume_id: str,
    request: Request,
    background: BackgroundTasks,
    store: ResumeStore = Depends(get_resume_store),
    llm: DeepSeekClient = Depends(get_llm_client),
    key_store: KeyStore = Depends(get_key_store),
) -> dict:
    """失败简历重试：failed → processing → 重新解析（原文件保留，R6）。"""
    record = _get_or_404(store, resume_id)
    if record.status != FAILED:
        raise HTTPException(status_code=400, detail="仅失败状态的简历可重试")
    store.update_processing(resume_id)
    background.add_task(
        process_resume_async,
        store,
        record,
        llm,
        key_store.get_global_key(),
        request.app.state.config,
    )
    return {"resume": store.get_resume(resume_id).to_dict()}


@router.delete("/{resume_id}")
async def delete_resume(
    resume_id: str,
    store: ResumeStore = Depends(get_resume_store),
) -> dict:
    """删除简历：DB 行（含考点清单 CASCADE）+ 原文件物理删（R5）。"""
    record = _get_or_404(store, resume_id)
    path = store.delete_resume(resume_id)
    if path:
        (PROJECT_ROOT / path).unlink(missing_ok=True)
    logger.info("resume deleted: {name} r={rid}", name=record.file_name, rid=resume_id)
    return {"status": "deleted", "id": resume_id}


def _get_or_404(store: ResumeStore, resume_id: str) -> Resume:
    record = store.get_resume(resume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="简历不存在")
    return record
