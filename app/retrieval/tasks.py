"""后台入库任务：解析→切块→嵌入→双写 + 状态流转（processing→ready/failed）。

由 FastAPI BackgroundTasks 经 asyncio.to_thread 调度（不阻塞事件循环）；
失败保留原文件（R6），状态置 failed，重试接口重新入队。
"""

import asyncio
from pathlib import Path

from loguru import logger
from omegaconf import DictConfig

from app.config import PROJECT_ROOT
from app.retrieval.embedding import EmbeddingProvider
from app.retrieval.es import ESManager
from app.retrieval.ingest import ingest_document
from app.retrieval.qdrant import QdrantManager
from app.store.knowledge import FAILED, READY, KbFile, KnowledgeStore


def _abs_path(record: KbFile) -> Path:
    return PROJECT_ROOT / record.path


def ingest_file_background(
    store: KnowledgeStore,
    record: KbFile,
    qdrant: QdrantManager,
    es: ESManager,
    embedding: EmbeddingProvider,
    cfg: DictConfig,
) -> None:
    """入库单文件并更新状态；任何异常置 failed（保留原文件供重试）。"""
    try:
        result = ingest_document(_abs_path(record), qdrant, es, embedding, cfg, kb_id=record.kb_id)
        store.update_file_status(record.id, READY, block_count=result.child_count)
        logger.info(
            "kb file ready: {name} file={fid} blocks={n}",
            name=record.name,
            fid=result.file_id,
            n=result.child_count,
        )
    except Exception as e:  # noqa: BLE001 - 后台任务兜底：异常写入状态，不向外抛
        store.update_file_status(record.id, FAILED, error=str(e)[:500])
        logger.error("kb file ingest failed: {name} err={err}", name=record.name, err=repr(e))


async def ingest_file_async(
    store: KnowledgeStore,
    record: KbFile,
    qdrant: QdrantManager,
    es: ESManager,
    embedding: EmbeddingProvider,
    cfg: DictConfig,
) -> None:
    await asyncio.to_thread(ingest_file_background, store, record, qdrant, es, embedding, cfg)


def rebuild_all_background(
    store: KnowledgeStore,
    qdrant: QdrantManager,
    es: ESManager,
    embedding: EmbeddingProvider,
    cfg: DictConfig,
) -> dict[str, int]:
    """Embedding 切换后全库重建（P1-7）：逐文件重新入库 + 更新全部库绑定 model_id/dims。

    返回 (ok, failed) 计数；失败文件保留原文件，可单独重试。
    """
    ok = failed = 0
    for record in store.list_all_files():
        try:
            result = ingest_document(
                _abs_path(record), qdrant, es, embedding, cfg, kb_id=record.kb_id
            )
            store.update_file_status(record.id, READY, block_count=result.child_count)
            ok += 1
        except Exception as e:  # noqa: BLE001 - 后台任务兜底：单文件失败不中断全库重建
            store.update_file_status(record.id, FAILED, error=str(e)[:500])
            failed += 1
            logger.error("kb rebuild file failed: {name} err={err}", name=record.name, err=repr(e))
    for kb in store.list_kbs():
        store.bind_model(kb.id, embedding.model_id, embedding.dims)
    logger.info("kb rebuild done: ok={ok} failed={failed}", ok=ok, failed=failed)
    return {"ok": ok, "failed": failed}


async def rebuild_all_async(
    store: KnowledgeStore,
    qdrant: QdrantManager,
    es: ESManager,
    embedding: EmbeddingProvider,
    cfg: DictConfig,
) -> dict[str, int]:
    return await asyncio.to_thread(rebuild_all_background, store, qdrant, es, embedding, cfg)
