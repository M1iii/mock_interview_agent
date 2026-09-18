"""会话管理 API：新建 / 列表 / 删除 / 提前结束 / 导出报告 / 消息历史。"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from app.api.deps import get_key_store, get_llm_client, get_session, get_session_store
from app.interview.nodes import report_node
from app.llm.client import DeepSeekClient
from app.llm.keys import APIKeyError, KeyStore
from app.store.checkpointer import delete_thread
from app.store.sessions import InMemorySessionStore, SessionMeta

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    scene: str = Field(..., pattern="^(intern|fulltime)$")
    question_count: int = Field(default=10, ge=5, le=30)
    skip_opening: bool = False
    kb_id: str | None = None
    resume_id: str | None = None
    interview_type: str = Field(
        default="technical", pattern="^(technical|behavioral|comprehensive)$"
    )


class SessionResponse(BaseModel):
    id: str
    title: str
    scene: str
    status: str
    question_count: int
    created_at: str
    message_count: int = 0
    question_index: int = 0
    kb_id: str | None = None
    resume_id: str | None = None
    interview_type: str = "technical"


class ReportResponse(BaseModel):
    report: str
    status: str
    summary: dict | None = None


class MessageItem(BaseModel):
    role: str  # "ai" | "user"
    content: str


class MessagesResponse(BaseModel):
    messages: list[MessageItem]
    hints_used: int = 0
    status: str = "ongoing"
    question_index: int = 0


def _to_response(meta: SessionMeta) -> SessionResponse:
    return SessionResponse(
        id=meta["id"],
        title=meta["title"],
        scene=meta["scene"],
        status=meta["status"],
        question_count=meta["question_count"],
        created_at=meta["created_at"].isoformat(),
        kb_id=meta.get("kb_id"),
        resume_id=meta.get("resume_id"),
        interview_type=meta.get("interview_type", "technical"),
    )


@router.post("", response_model=SessionResponse)
async def create_session(
    req: CreateSessionRequest,
    request: Request,
    store: InMemorySessionStore = Depends(get_session_store),
    key_store: KeyStore = Depends(get_key_store),
) -> SessionResponse:
    """新建会话：校验全局 Key → 快照绑定 → 创建元数据。"""
    max_sessions = int(getattr(request.app.state.config.app, "max_sessions", 30))
    current_count = len(store.list())
    if current_count >= max_sessions:
        raise HTTPException(
            status_code=400,
            detail=f"会话数量已达上限（{max_sessions} 条），请先删除旧会话后再创建",
        )

    session_id = str(uuid.uuid4())
    try:
        key_store.snapshot_from_global(session_id)
    except APIKeyError:
        raise HTTPException(
            status_code=400, detail="全局 API Key 未设置，请先在配置页设置"
        ) from None

    meta = store.create(
        session_id,
        req.scene,
        req.question_count,
        req.skip_opening,
        req.kb_id,
        req.resume_id,
        req.interview_type,
    )
    return _to_response(meta)


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    request: Request,
    store: InMemorySessionStore = Depends(get_session_store),
) -> list[SessionResponse]:
    """列出所有会话（按创建时间倒序），附消息数与当前题号（实时读 checkpointer）。"""
    compiled = request.app.state.compiled_graph
    metas = store.list()

    async def _with_progress(meta: SessionMeta) -> SessionResponse:
        base = _to_response(meta)
        state_snapshot = await asyncio.to_thread(
            compiled.get_state, {"configurable": {"thread_id": meta["id"]}}
        )
        values = state_snapshot.values or {}
        return base.model_copy(
            update={
                "message_count": len(values.get("messages", [])),
                "question_index": values.get("question_index", 0),
            }
        )

    return list(await asyncio.gather(*[_with_progress(m) for m in metas]))


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    request: Request,
    store: InMemorySessionStore = Depends(get_session_store),
    key_store: KeyStore = Depends(get_key_store),
) -> dict[str, str]:
    """删除会话：checkpointer 状态 + SessionStore + KeyStore 三处同步物理删（N-8）。

    顺序（最终审查修复轮）：**先删 checkpointer 状态，再删会话行/Key**。
    原顺序会在 `delete_thread` 抛错时留下「会话行已删 → 重试 404」的不可重试不一致态；
    现在无论哪一步失败，都可整体重试（`delete_thread` 幂等），保持「三处全删或全不删」。
    """
    meta = store.get(session_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    await asyncio.to_thread(delete_thread, request.app.state.checkpointer, session_id)
    store.delete(session_id)
    key_store.delete(session_id)
    return {"status": "deleted", "id": session_id}


@router.post("/{session_id}/finish", response_model=ReportResponse)
async def finish_session(
    session_id: str,
    request: Request,
    session: SessionMeta = Depends(get_session),
    llm: DeepSeekClient = Depends(get_llm_client),
    key_store: KeyStore = Depends(get_key_store),
    store: InMemorySessionStore = Depends(get_session_store),
) -> ReportResponse:
    """提前结束面试：从 checkpointer 取 state → 调 report_node 生成报告 → 更新状态。"""
    if session["status"] == "finished":
        raise HTTPException(status_code=400, detail="面试已结束")

    api_key = key_store.get(session_id)
    if not api_key:
        raise HTTPException(status_code=400, detail="会话 Key 缺失")

    compiled = request.app.state.compiled_graph
    config = {"configurable": {"thread_id": session_id}}

    state_snapshot = await asyncio.to_thread(compiled.get_state, config)
    state = state_snapshot.values

    if not state or not state.get("scores"):
        raise HTTPException(status_code=400, detail="无评分记录，无法生成报告")

    state["_api_key"] = api_key

    result = await asyncio.to_thread(report_node, state, llm)
    # 方案 A：report_node 直接调用（不走图），需把输出写回 checkpointer 供导出
    await asyncio.to_thread(compiled.update_state, config, result)
    report = result.get("_report", "报告生成失败")
    status = result.get("status", "finished")

    store.update_status(session_id, status)

    return ReportResponse(report=report, status=status, summary=result.get("_report_summary"))


@router.get("/{session_id}/messages", response_model=MessagesResponse)
async def get_messages(
    session_id: str,
    request: Request,
    session: SessionMeta = Depends(get_session),
) -> MessagesResponse:
    """读取会话消息历史（来自 checkpointer，支持刷新后恢复对话）。"""
    compiled = request.app.state.compiled_graph
    config = {"configurable": {"thread_id": session_id}}

    state_snapshot = await asyncio.to_thread(compiled.get_state, config)
    values = state_snapshot.values or {}
    raw_messages = values.get("messages", [])

    items: list[MessageItem] = []
    for msg in raw_messages:
        if isinstance(msg, AIMessage):
            role, content = "ai", msg.content
        elif isinstance(msg, HumanMessage):
            role, content = "user", msg.content
        elif isinstance(msg, dict):
            role = "ai" if msg.get("role") == "assistant" else "user"
            content = msg.get("content", "")
        else:
            continue
        if content:
            items.append(MessageItem(role=role, content=content))

    return MessagesResponse(
        messages=items,
        hints_used=values.get("hints_used", 0),
        status=values.get("status", "ongoing"),
        question_index=values.get("question_index", 0),
    )


@router.get("/{session_id}/report", response_model=ReportResponse)
async def get_report(
    session_id: str,
    request: Request,
    session: SessionMeta = Depends(get_session),
) -> ReportResponse:
    """获取面试报告：Markdown 全文 + 结构化摘要（前端可视化渲染）。"""
    if session["status"] != "finished":
        raise HTTPException(status_code=400, detail="面试未结束，无法导出报告")

    compiled = request.app.state.compiled_graph
    config = {"configurable": {"thread_id": session_id}}

    state_snapshot = await asyncio.to_thread(compiled.get_state, config)
    values = state_snapshot.values or {}
    report = values.get("_report")

    if not report:
        raise HTTPException(status_code=404, detail="报告内容不存在")

    return ReportResponse(
        report=report,
        status="finished",
        summary=values.get("_report_summary"),
    )
