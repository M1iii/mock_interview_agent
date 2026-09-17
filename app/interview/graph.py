"""LangGraph 面试编排图：节点（从 nodes 注入）+ 条件路由 + 编译。

节点函数需要 DeepSeekClient 注入——用 functools.partial 绑定。
调用方：compile_graph(llm_client)。"""

from functools import partial

from langgraph.graph import END, START, StateGraph

from app.interview.nodes import (
    ask_question_node,
    evaluate_node,
    follow_up_node,
    opening_node,
    report_node,
)
from app.interview.state import InterviewState
from app.llm.client import DeepSeekClient

# --- 条件路由 ---


def route_after_start(state: InterviewState) -> str:
    """START 后三分支：首次（无题）→ 开场/出题；有题等回答 → 直接评估。

    current_question 非空表示上一步 ask_question/follow_up 已出内容并暂停，
    用户回答后重新 invoke 时进入 evaluate，而不是重新出题。
    """
    if state.get("current_question"):
        return "evaluate"
    if state.get("skip_opening", False):
        return "ask_question"
    return "opening"


def route_after_evaluate(state: InterviewState) -> str:
    """evaluate 后三向分支：追问 / 下一题 / 报告。

    evaluate 不直连 END——它由用户回答后重新调用图触发，
    评估完成后立即路由到下一节点（无暂停）。
    evaluate 已在不需要追问时推进 question_index（+1），
    故此处检查推进后的值：== question_count 表示已超出最后一题 → report。
    """
    followups = state.get("followups", 0)
    question_index = state.get("question_index", 0)
    question_count = state.get("question_count", 10)
    needs_followup = state.get("_needs_followup", False)

    if needs_followup and followups < 2:
        return "follow_up"
    if question_index >= question_count:
        return "report"
    return "ask_question"


# --- 图构建 ---


def build_graph(llm: DeepSeekClient, retrieval=None, resume_store=None, cfg=None) -> StateGraph:
    """构建面试编排图（未编译，供调用方 compile）。

    暂停点（→ END）：ask_question / follow_up 生成内容后暂停，等用户回答后
    由调用方重新 invoke 触发 evaluate。
    非暂停节点（opening / evaluate / report）执行后立即路由到下一节点。
    retrieval: RetrievalContext——注入出题节点做知识库检索（可 None）。
    resume_store: ResumeStore——双来源出题的简历考点来源（可 None）。
    cfg: 应用配置——面试类型配比来源（可 None，缺省回落 P1 行为）。
    """
    graph = StateGraph(InterviewState)
    graph.add_node("opening", partial(opening_node, llm=llm))
    graph.add_node(
        "ask_question",
        partial(
            ask_question_node, llm=llm, retrieval=retrieval, resume_store=resume_store, cfg=cfg
        ),
    )
    graph.add_node("evaluate", partial(evaluate_node, llm=llm))
    graph.add_node("follow_up", partial(follow_up_node, llm=llm))
    graph.add_node("report", partial(report_node, llm=llm))

    # START → 首次（opening/ask_question）或回答后（evaluate）
    graph.add_conditional_edges(
        START,
        route_after_start,
        {
            "opening": "opening",
            "ask_question": "ask_question",
            "evaluate": "evaluate",
        },
    )
    graph.add_edge("opening", "ask_question")
    # ask_question 生成题干后暂停，等待用户回答
    graph.add_edge("ask_question", END)
    # evaluate 由用户回答后重新调用图触发，评估后立即路由（不暂停）
    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {"follow_up": "follow_up", "ask_question": "ask_question", "report": "report"},
    )
    # follow_up 生成追问后暂停，等待用户回答
    graph.add_edge("follow_up", END)
    # report 生成报告后结束
    graph.add_edge("report", END)
    return graph


def compile_graph(
    llm: DeepSeekClient, checkpointer=None, retrieval=None, resume_store=None, cfg=None
):
    """编译面试编排图，返回可执行图。

    checkpointer: P0 MemorySaver / P2 SqliteSaver，不传则无持久化。
    retrieval: RetrievalContext，出题节点知识库检索注入（可 None）。
    resume_store: ResumeStore，双来源出题注入（可 None）。
    cfg: 应用配置，面试类型配比注入（可 None）。
    """
    return build_graph(llm, retrieval, resume_store, cfg).compile(checkpointer=checkpointer)
