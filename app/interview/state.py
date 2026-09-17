"""面试编排状态：InterviewState + Score，P0 核心字段 + P1/P2 预留。"""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class Score(TypedDict):
    """单题评分记录。"""

    question: str
    answer: str
    score: float
    comment: str
    dimensions: dict[str, float]
    citations: list[dict]  # P1 Tip 8：本题引用元数据（评估面板 & 报告展示用）


class InterviewState(TypedDict, total=False):
    """LangGraph 面试状态（经 checkpointer 存取，唯一真源）。"""

    # --- P0 核心 ---
    messages: Annotated[list[BaseMessage], add_messages]
    scene: str  # "intern" | "fulltime"
    question_count: int  # 5–30，默认 10
    question_index: int  # 0-based
    current_question: str | None
    hints_used: int  # 当前题已用提示次数（≤1）
    followups: int  # 当前题追问轮次（≤2）
    scores: list[Score]
    status: str  # "ongoing" | "finished"
    skip_opening: bool  # 跳过开场白
    # --- P1/P2 预留（默认空值，不影响 P0 运行）---
    difficulty_stage: int  # 难度档位，默认 1
    question_bank: list  # P2 题库
    asked_ids: list[str]  # P2 已问 ID
    answered_qa: list  # P2 对错记录
    kb_id: str | None  # P1 关联知识库 ID（会话级，出题检索范围）
    resume_id: str | None  # P2 关联简历 ID（会话级，双来源出题）
    interview_type: str  # P2 面试类型：technical / behavioral / comprehensive
    # --- 运行时注入（不持久化，每次 invoke 时注入）---
    _api_key: str  # 会话级 API Key 快照
    _topic: str  # 当前题主题标签
    _needs_followup: bool  # evaluate 输出：是否需要追问
    _followup_reason: str  # evaluate 输出：追问原因
    _report: str  # report 输出：Markdown 报告
    _report_summary: dict | None  # report 输出：结构化摘要（含 verified 预留位，P0 为 null）
    _citations: list[dict]  # 当前题引用元数据（出题检索命中，前端来源折叠）
    _reference_block: str  # 当前题参考资料文本（出题节点写入，评估节点复用）


def initial_state(
    scene: str = "fulltime",
    question_count: int = 10,
    skip_opening: bool = False,
    kb_id: str | None = None,
    resume_id: str | None = None,
    interview_type: str = "technical",
) -> InterviewState:
    """创建会话初始状态。"""
    return InterviewState(
        messages=[],
        scene=scene,
        question_count=question_count,
        question_index=0,
        current_question=None,
        hints_used=0,
        followups=0,
        scores=[],
        status="ongoing",
        skip_opening=skip_opening,
        difficulty_stage=1,
        question_bank=[],
        asked_ids=[],
        answered_qa=[],
        kb_id=kb_id,
        resume_id=resume_id,
        interview_type=interview_type,
    )
