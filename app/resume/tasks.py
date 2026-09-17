"""后台简历解析任务：解析 → LLM 抽取 → 落库 + 状态流转（processing→ready/failed）。

由 FastAPI BackgroundTasks 经 asyncio.to_thread 调度（不阻塞事件循环）；
失败保留原文件（R6），状态置 failed，重试接口重新入队。
LLM 抽取使用全局 API Key（无会话上下文）。
"""

import asyncio
from pathlib import Path

from loguru import logger

from app.config import PROJECT_ROOT
from app.llm.client import DeepSeekClient
from app.resume.extract import extract_profile
from app.resume.parsers import parse_document
from app.store.resume import Resume, ResumeStore


def _abs_path(record: Resume) -> Path:
    return PROJECT_ROOT / record.path


def process_resume_background(
    store: ResumeStore,
    record: Resume,
    llm: DeepSeekClient,
    api_key: str,
    cfg,
) -> None:
    """解析并抽取单份简历；任何异常置 failed（保留原文件供重试）。"""
    try:
        if not api_key:
            raise ValueError("全局 API Key 未设置，无法解析简历")
        text = parse_document(_abs_path(record))
        profile = extract_profile(text, llm, api_key, cfg)
        # ★ 适配裁定：update_ready 用下标访问 dict，Point → to_dict 转换
        store.update_ready(record.id, profile.profile_json, [p.to_dict() for p in profile.points])
        logger.info(
            "resume ready: {name} r={rid} points={n}",
            name=record.file_name,
            rid=record.id,
            n=len(profile.points),
        )
    except Exception as e:  # noqa: BLE001 - 后台任务兜底：异常写入状态，不向外抛
        store.update_failed(record.id, str(e)[:500])
        logger.error("resume process failed: {name} err={err}", name=record.file_name, err=repr(e))


async def process_resume_async(
    store: ResumeStore,
    record: Resume,
    llm: DeepSeekClient,
    api_key: str,
    cfg,
) -> None:
    await asyncio.to_thread(process_resume_background, store, record, llm, api_key, cfg)
