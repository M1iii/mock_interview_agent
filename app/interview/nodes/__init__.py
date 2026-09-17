"""面试节点函数：opening / ask_question / evaluate / follow_up / report。

每个节点接收 state + llm_client（DeepSeekClient），返回 state 增量 dict。
opening 不调 LLM（固定文案）；其余 4 个节点调 LLM 并解析输出。"""

import json
import re

from langchain_core.messages import AIMessage, HumanMessage

from app.interview.prompts.ask_question import ASK_QUESTION
from app.interview.prompts.evaluate import EVALUATE
from app.interview.prompts.follow_up import FOLLOW_UP
from app.interview.prompts.opening import OPENING_TEXT
from app.interview.prompts.report import REPORT
from app.interview.state import InterviewState, Score
from app.llm.client import DeepSeekClient
from app.retrieval.retrieve import DECLINE, FALLBACK, RetrievalResult, retrieve

# 引用数量上限（Tip 7 决策 3）：题干过长会稀释核心问题
MAX_CITATIONS = 3

# fallback 级提示语（Tip 7 决策 4）：弱提示不干扰面试
_FALLBACK_NOTE = "_以下内容基于有限资料生成，仅供参考_"

# 检索片段不截断：父块全文（≤800 字）直接注入 prompt，token 体积可控
_SNIPPET_LEN = 0


def _extract_answer(state: InterviewState) -> str:
    """从 messages 中提取候选人最新一轮回答（最后一条 HumanMessage）。"""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage) or (isinstance(msg, dict) and msg.get("role") == "user"):
            return msg.content if hasattr(msg, "content") else str(msg)
    return ""


def _get_topic_list(state: InterviewState) -> str:
    """从 scores 中提取已问主题列表。"""
    topics = [s.get("topic", "") for s in state.get("scores", []) if s.get("topic")]
    return "、".join(topics) if topics else "无"


def _build_search_query(state: InterviewState) -> str:
    """构造出题检索查询词：优先已问主题（延续方向），首题用场景默认词。"""
    asked = _get_topic_list(state)
    if asked != "无":
        return asked
    scene = state.get("scene", "fulltime")
    return "面试 技术 基础概念" if scene == "intern" else "系统设计 架构 原理"


def _build_reference_block(result: RetrievalResult) -> str:
    """构造 prompt 参考资料区块：带 [n] 角标 + 使用指令（fallback 加弱提示）。"""
    lines = ["【参考资料】"]
    for i, c in enumerate(result.citations[:MAX_CITATIONS], start=1):
        snippet = c.text.strip().replace("\n", " ")
        if _SNIPPET_LEN and len(snippet) > _SNIPPET_LEN:
            snippet = snippet[:_SNIPPET_LEN] + "…"
        lines.append(f"[{i}]《{c.file_name}》：{snippet}")
    if result.level == FALLBACK:
        lines.append("注意：以下资料与本次面试主题相关性有限，仅作参考，题目仍应考察通用知识。")
    lines.append(
        "请优先基于参考资料出题；若题目直接取材于某条资料，请在题干末尾标注对应角标，"
        "例如：请解释缓存穿透的解决方案[1]。"
    )
    return "\n".join(lines)


def _citation_dict(c) -> dict:
    """Citation → 前端可序列化 dict（省略 parent_id 内部细节）。"""
    return {
        "file_name": c.file_name,
        "text": c.text,
        "score": c.score,
    }


def _parse_question(raw: str) -> tuple[str, str]:
    """解析出题输出：兼容旧 JSON 格式与新「题干 + 【主题】标记行」格式。"""
    try:
        parsed = json.loads(raw)
        return parsed.get("question", raw), parsed.get("topic", "")
    except json.JSONDecodeError, TypeError:
        if "【主题】" in raw:
            question, _, topic = raw.partition("【主题】")
            return question.strip(), topic.strip()
        return raw, ""


def opening_node(state: InterviewState, llm: DeepSeekClient) -> dict:
    """开场白：固定文案，不调 LLM。"""
    return {"messages": [AIMessage(content=OPENING_TEXT)]}


def ask_question_node(
    state: InterviewState,
    llm: DeepSeekClient,
    callbacks: list | None = None,
    retrieval=None,
) -> dict:
    """出题：按场景选 prompt，LLM 生成 JSON {question, topic}。

    callbacks: 透传给 LLM 用于逐 token 流式（skip 出题不走图时的转发）。
    retrieval: RetrievalContext 或 None——会话关联知识库时检索注入参考资料
    （Tip 7：normal/weak/fallback 注入，decline 与未关联知识库时纯通用出题）。
    """
    scene = state.get("scene", "fulltime")
    template = ASK_QUESTION.get(scene, ASK_QUESTION["fulltime"])

    reference_block = ""
    citations: list[dict] = []
    level: str | None = None
    kb_id = state.get("kb_id")
    if kb_id and retrieval is not None:
        result = retrieve(
            query=_build_search_query(state),
            kb_id=kb_id,
            cfg=retrieval.cfg,
            qdrant=retrieval.qdrant,
            es=retrieval.es,
            embedding=retrieval.embedding,
        )
        if result.level != DECLINE and result.citations:
            reference_block = _build_reference_block(result)
            citations = [_citation_dict(c) for c in result.citations[:MAX_CITATIONS]]
            level = result.level

    prompt = template.format(
        question_index=state.get("question_index", 0) + 1,
        question_count=state.get("question_count", 10),
        difficulty_stage=state.get("difficulty_stage", 1),
        asked_topics=_get_topic_list(state),
        reference_block=reference_block,
    )
    raw, _ = llm.complete_sync(api_key=state["_api_key"], prompt=prompt, callbacks=callbacks)
    question, topic = _parse_question(raw)
    if level == FALLBACK:
        question = f"{_FALLBACK_NOTE}\n{question}"
    updates = {
        "current_question": question,
        "hints_used": 0,
        "followups": 0,
        "messages": [AIMessage(content=question)],
        "_topic": topic,
        "_citations": citations,  # 无条件写入：未命中为 []（LangGraph 不写则残留上一题）
        "_reference_block": reference_block,  # 无条件写入：未命中为 ""（同上）
    }
    return updates


def evaluate_node(state: InterviewState, llm: DeepSeekClient) -> dict:
    """评估：LLM 打分 + 判断是否追问。"""
    scene = state.get("scene", "fulltime")
    answer = _extract_answer(state)
    prompt = EVALUATE.format(
        scene=scene,
        current_question=state.get("current_question", ""),
        candidate_answer=answer,
        reference_block=state.get("_reference_block", ""),
    )
    raw, _ = llm.complete_sync(api_key=state["_api_key"], prompt=prompt)
    try:
        parsed = json.loads(raw)
        score_dict = parsed.get("score", {})
        comment = parsed.get("comment", "")
        needs_followup = parsed.get("needs_followup", False)
        followup_reason = parsed.get("followup_reason", "")
    except json.JSONDecodeError, TypeError:
        score_dict = {}
        comment = raw
        needs_followup = False
        followup_reason = ""
    score_entry: Score = {
        "question": state.get("current_question", ""),
        "answer": answer,
        "score": sum(score_dict.values()) / len(score_dict) if score_dict else 0,
        "comment": comment,
        "dimensions": score_dict,
        "topic": state.get("_topic", ""),
    }
    if state.get("_citations"):
        # Tip 8：原样透传出题节点的引用元数据（不重新检索）
        score_entry["citations"] = state["_citations"]
    new_scores = [*state.get("scores", []), score_entry]
    # 不需要追问时推进题号（进入下一题或进 report）
    updates = {
        "scores": new_scores,
        "_needs_followup": needs_followup,
        "_followup_reason": followup_reason,
    }
    if not needs_followup:
        updates["question_index"] = state.get("question_index", 0) + 1
    return updates


def follow_up_node(state: InterviewState, llm: DeepSeekClient) -> dict:
    """追问：基于评估结果生成追问内容。"""
    scene = state.get("scene", "fulltime")
    answer = _extract_answer(state)
    prompt = FOLLOW_UP.format(
        scene=scene,
        current_question=state.get("current_question", ""),
        candidate_answer=answer,
        followups=state.get("followups", 0) + 1,
        followup_reason=state.get("_followup_reason", ""),
    )
    raw, _ = llm.complete_sync(api_key=state["_api_key"], prompt=prompt)
    return {
        "followups": state.get("followups", 0) + 1,
        "messages": [AIMessage(content=raw)],
    }


def _parse_report_summary(raw: str) -> dict | None:
    """从报告输出提取结构化摘要 JSON（```json 代码块），失败返回 None（前端降级为纯 Markdown）。"""
    m = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.S)
    payload = m.group(1) if m else raw
    try:
        data = json.loads(payload)
    except json.JSONDecodeError, TypeError:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "total_score": data.get("total_score"),
        "dimensions": data.get("dimensions"),
        "strengths": data.get("strengths"),
        "weaknesses": data.get("weaknesses"),
        "review": data.get("review"),
        "verified": data.get("verified"),
    }


def report_node(state: InterviewState, llm: DeepSeekClient) -> dict:
    """报告：LLM 生成 Markdown 面试报告 + 末尾结构化摘要 JSON。"""
    scene = state.get("scene", "fulltime")
    prompt = REPORT.format(
        scene=scene,
        question_count=state.get("question_count", 10),
        scores=state.get("scores", []),
    )
    raw, _ = llm.complete_sync(api_key=state["_api_key"], prompt=prompt)
    return {
        "status": "finished",
        "messages": [AIMessage(content=raw)],
        "_report": raw,
        "_report_summary": _parse_report_summary(raw),
    }
