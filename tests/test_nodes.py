from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from app.interview import nodes
from app.interview.nodes import (
    _FALLBACK_NOTE,
    MAX_CITATIONS,
    _build_reference_block,
    ask_question_node,
    evaluate_node,
    follow_up_node,
    opening_node,
    report_node,
)
from app.interview.prompts.opening import OPENING_TEXT
from app.interview.state import initial_state
from app.retrieval.retrieve import (
    DECLINE,
    FALLBACK,
    NORMAL,
    WEAK,
    Citation,
    RetrievalResult,
)


def _make_llm(response: str = "ok"):
    llm = MagicMock()
    llm.complete_sync = MagicMock(return_value=(response, {"total_tokens": 10}))
    return llm


# --- opening ---


def test_opening_returns_fixed_text():
    state = initial_state()
    result = opening_node(state, _make_llm())
    assert len(result["messages"]) == 1
    assert result["messages"][0].content == OPENING_TEXT


# --- ask_question ---


def test_ask_question_intern():
    state = initial_state(scene="intern", question_count=5)
    state["_api_key"] = "sk-test"
    llm = _make_llm('{"question": "请介绍一下你的项目", "topic": "项目经验"}')
    result = ask_question_node(state, llm)
    assert "请介绍一下你的项目" in result["current_question"]
    assert result["hints_used"] == 0
    assert result["followups"] == 0
    assert result["_topic"] == "项目经验"
    assert len(result["messages"]) == 1


def test_ask_question_fulltime():
    state = initial_state(scene="fulltime", question_count=10)
    state["_api_key"] = "sk-test"
    llm = _make_llm('{"question": "请解释 CAP 理论", "topic": "分布式"}')
    result = ask_question_node(state, llm)
    assert "CAP" in result["current_question"]
    assert result["_topic"] == "分布式"


def test_ask_question_invalid_json_fallback():
    state = initial_state(scene="fulltime")
    state["_api_key"] = "sk-test"
    llm = _make_llm("这不是 JSON，直接是题目文本")
    result = ask_question_node(state, llm)
    assert result["current_question"] == "这不是 JSON，直接是题目文本"
    assert result["_topic"] == ""


def test_ask_question_passes_correct_prompt():
    state = initial_state(scene="intern", question_count=5)
    state["_api_key"] = "sk-test"
    state["difficulty_stage"] = 2
    state["scores"] = [{"topic": "网络基础"}]
    llm = _make_llm('{"question": "test", "topic": "OS"}')
    ask_question_node(state, llm)
    call_args = llm.complete_sync.call_args
    prompt_text = call_args.kwargs["prompt"]
    assert "实习" in prompt_text
    assert "第 1 题" in prompt_text
    assert "共 5 题" in prompt_text
    assert "网络基础" in prompt_text


# --- ask_question + 知识库检索注入（Tip 7）---


def _fake_retrieval(result: RetrievalResult):
    """构造 fake RetrievalContext 并 monkeypatch retrieve 返回固定结果。"""

    class FakeCtx:
        cfg = None
        qdrant = None
        es = None
        embedding = None

    ctx = FakeCtx()
    nodes.retrieve = MagicMock(return_value=result)
    return ctx


def _result(level: str, n: int = 3) -> RetrievalResult:
    r = RetrievalResult(level=level)
    r.citations = [
        Citation(
            file_id=f"f{i}",
            file_name=f"doc{i}.md",
            parent_id=f"p{i}",
            text=f"Redis 缓存穿透的内容片段 {i}，用于构造题目背景信息。",
            score=round(0.95 - i * 0.1, 2),
        )
        for i in range(n)
    ]
    return r


def _ask_with_kb(level: str, n: int = 3, scene: str = "fulltime"):
    """带 kb_id 调用出题节点，返回 (result, llm, prompt_text)。"""
    state = initial_state(scene=scene, question_count=5, kb_id="kb-1")
    state["_api_key"] = "sk-test"
    llm = _make_llm('{"question": "请解释缓存穿透的解决方案", "topic": "缓存"}')
    ctx = _fake_retrieval(_result(level, n))
    result = ask_question_node(state, llm, retrieval=ctx)
    prompt_text = llm.complete_sync.call_args.kwargs["prompt"]
    return result, llm, prompt_text


def test_ask_question_no_kb_pure_generic():
    """未关联知识库：prompt 无参考资料，无引用输出。"""
    state = initial_state(scene="fulltime", question_count=5)
    state["_api_key"] = "sk-test"
    llm = _make_llm('{"question": "q", "topic": "t"}')
    result = ask_question_node(state, llm)
    prompt_text = llm.complete_sync.call_args.kwargs["prompt"]
    assert "【参考资料】" not in prompt_text
    assert result["_citations"] == []
    assert result["_reference_block"] == ""


def test_ask_question_kb_but_no_retrieval_ctx():
    """有关联知识库但未注入检索上下文：纯通用，不报错。"""
    state = initial_state(scene="fulltime", question_count=5, kb_id="kb-1")
    state["_api_key"] = "sk-test"
    llm = _make_llm('{"question": "q", "topic": "t"}')
    result = ask_question_node(state, llm, retrieval=None)
    prompt_text = llm.complete_sync.call_args.kwargs["prompt"]
    assert "【参考资料】" not in prompt_text
    assert result["_citations"] == []
    assert result["_reference_block"] == ""


@pytest.mark.parametrize("level", [NORMAL, WEAK])
def test_ask_question_normal_weak_injects(level):
    """normal/weak：注入参考资料 + 角标，无 fallback 提示语。"""
    result, llm, prompt_text = _ask_with_kb(level)
    assert "【参考资料】" in prompt_text
    assert "[1]" in prompt_text and "[3]" in prompt_text
    assert "请优先基于参考资料出题" in prompt_text
    assert "doc0.md" in prompt_text
    assert "相关性有限" not in prompt_text
    assert len(result["_citations"]) == 3
    assert result["_citations"][0]["file_name"] == "doc0.md"
    assert "redis 缓存穿透的内容片段 0" in result["_citations"][0]["text"].lower()
    assert result["_reference_block"]
    assert "【参考资料】" in result["_reference_block"]
    assert "[1]" in result["_reference_block"]


def test_ask_question_fallback_injects_with_note():
    """fallback：注入参考资料 + 弱提示语（题干前置）。"""
    result, llm, prompt_text = _ask_with_kb(FALLBACK)
    assert "【参考资料】" in prompt_text
    assert "相关性有限" in prompt_text
    assert result["current_question"].startswith(_FALLBACK_NOTE)
    assert "请解释缓存穿透的解决方案" in result["current_question"]


def test_ask_question_decline_pure():
    """decline：不注入，纯通用出题。"""
    result, llm, prompt_text = _ask_with_kb(DECLINE)
    assert "【参考资料】" not in prompt_text
    assert result["_citations"] == []
    assert result["_reference_block"] == ""
    assert not result["current_question"].startswith(_FALLBACK_NOTE)


def test_ask_question_hit_then_miss_clears_citations():
    """回归（Critical）：上一题命中 → 本题 DECLINE，必须清空 _citations / _reference_block，
    防止 LangGraph 状态合并把上一题引用残留到本题评估（decline 须完全降级为纯 LLM 评估）。"""
    state = initial_state(scene="fulltime", question_count=5, kb_id="kb-1")
    state["_api_key"] = "sk-test"
    state["scores"] = [{"topic": "缓存"}]
    # 模拟 Q1 命中：state 残留上一题的引用
    state["_citations"] = [
        {"file_name": "doc1.md", "text": "参考内容 1", "score": 0.9},
        {"file_name": "doc2.md", "text": "参考内容 2", "score": 0.8},
        {"file_name": "doc3.md", "text": "参考内容 3", "score": 0.7},
    ]
    state["_reference_block"] = "【参考资料】\n[1]《doc1.md》：缓存穿透指查询不存在的数据..."
    # Q2 检索 DECLINE：不注入任何引用
    ctx = _fake_retrieval(_result(DECLINE))
    llm = _make_llm('{"question": "请解释分布式事务", "topic": "分布式"}')
    updates = ask_question_node(state, llm, retrieval=ctx)
    # 无条件写入空值 → 残留被清空
    assert updates["_citations"] == []
    assert updates["_reference_block"] == ""
    # 模拟 LangGraph 合并后的状态，评估必须完全降级为纯 LLM
    merged = {**state, **updates}
    eval_llm = _make_llm(
        '{"score": {"技术深度": 7, "表达清晰度": 7, "问题解决": 7, "项目经验": 6}, '
        '"comment": "回答清晰", "needs_followup": false, "followup_reason": ""}'
    )
    eval_result = evaluate_node(merged, eval_llm)
    call_prompt = eval_llm.complete_sync.call_args.kwargs["prompt"]
    assert "【参考资料】" not in call_prompt
    assert "citations" not in eval_result["scores"][0]


def test_ask_question_citations_capped():
    """引用数量上限：检索 5 条，只注入前 3 条。"""
    result, llm, prompt_text = _ask_with_kb(NORMAL, n=5)
    assert len(result["_citations"]) == MAX_CITATIONS == 3
    # prompt 只含 [1][2][3]，不含 [4][5]
    assert "[4]" not in prompt_text
    assert "[5]" not in prompt_text


def test_ask_question_intern_search_query_default():
    """实习场景首题：检索查询词为场景默认词。"""
    state = initial_state(scene="intern", question_count=5, kb_id="kb-1")
    state["_api_key"] = "sk-test"
    llm = _make_llm('{"question": "q", "topic": "t"}')
    ctx = _fake_retrieval(_result(NORMAL, 1))
    ask_question_node(state, llm, retrieval=ctx)
    query = nodes.retrieve.call_args.kwargs["query"]
    assert "基础概念" in query
    assert nodes.retrieve.call_args.kwargs["kb_id"] == "kb-1"


def test_build_reference_block_no_truncation():
    """父块全文不截断（_SNIPPET_LEN=0），完整注入 prompt。"""
    r = RetrievalResult(level=NORMAL)
    r.citations = [
        Citation(
            file_id="f1",
            file_name="doc.md",
            parent_id="p1",
            text="长" * 500,
            score=0.9,
        )
    ]
    block = _build_reference_block(r)
    assert "【参考资料】" in block
    assert "…" not in block
    assert "[1]《doc.md》" in block
    assert len("长" * 500) <= len(block)


# --- evaluate ---


def test_evaluate_no_followup():
    state = initial_state(scene="fulltime", question_count=10)
    state["_api_key"] = "sk-test"
    state["current_question"] = "什么是多态"
    state["messages"] = [HumanMessage(content="多态是同一接口不同实现")]
    llm = _make_llm(
        '{"score": {"技术深度": 8, "表达清晰度": 7, "问题解决": 7, "项目经验": 6}, '
        '"comment": "回答正确", "needs_followup": false, "followup_reason": ""}'
    )
    result = evaluate_node(state, llm)
    assert result["_needs_followup"] is False
    assert result["question_index"] == 1
    assert len(result["scores"]) == 1
    assert result["scores"][0]["score"] == 7.0


def test_evaluate_with_followup():
    state = initial_state(scene="fulltime", question_count=10)
    state["_api_key"] = "sk-test"
    state["current_question"] = "什么是多态"
    state["messages"] = [HumanMessage(content="不知道")]
    llm = _make_llm(
        '{"score": {"技术深度": 2, "表达清晰度": 3, "问题解决": 2, "项目经验": 1}, '
        '"comment": "回答不充分", "needs_followup": true, "followup_reason": "需要补充"}'
    )
    result = evaluate_node(state, llm)
    assert result["_needs_followup"] is True
    assert "question_index" not in result
    assert result["_followup_reason"] == "需要补充"


def test_evaluate_invalid_json_fallback():
    state = initial_state(scene="fulltime")
    state["_api_key"] = "sk-test"
    state["current_question"] = "Q1"
    state["messages"] = [HumanMessage(content="A1")]
    llm = _make_llm("解析失败")
    result = evaluate_node(state, llm)
    assert result["_needs_followup"] is False
    assert result["scores"][0]["comment"] == "解析失败"


# --- follow_up ---


def test_follow_up_increments_count():
    state = initial_state(scene="fulltime")
    state["_api_key"] = "sk-test"
    state["current_question"] = "什么是多态"
    state["messages"] = [HumanMessage(content="不太确定")]
    state["followups"] = 1
    state["_followup_reason"] = "需要更详细解释"
    llm = _make_llm("你能举一个多态的例子吗？")
    result = follow_up_node(state, llm)
    assert result["followups"] == 2
    assert "多态" in result["messages"][0].content


# --- report ---


def test_report_returns_markdown():
    state = initial_state(scene="fulltime", question_count=3)
    state["_api_key"] = "sk-test"
    state["scores"] = [
        {
            "question": "Q1",
            "answer": "A1",
            "score": 8,
            "comment": "good",
            "dimensions": {"技术深度": 8},
        }
    ]
    llm = _make_llm("# 面试报告\n\n总分：80分")
    result = report_node(state, llm)
    assert result["status"] == "finished"
    assert "# 面试报告" in result["_report"]
    assert len(result["messages"]) == 1
    # 无 ```json 摘要块 → 降级为 None
    assert result["_report_summary"] is None


def test_report_parses_summary_block():
    """报告末尾 ```json 摘要块被解析为结构化摘要（含 verified 预留位）。"""
    state = initial_state(scene="fulltime", question_count=3)
    state["_api_key"] = "sk-test"
    state["scores"] = [
        {
            "question": "Q1",
            "answer": "A1",
            "score": 8,
            "comment": "good",
            "dimensions": {"技术深度": 8},
        }
    ]
    raw = (
        "# 面试报告\n\n总分：82分\n\n"
        "```json\n"
        '{"total_score": 82, "dimensions": {"技术深度": 85, "沟通表达": 78}, '
        '"strengths": ["基础扎实"], "weaknesses": ["深度不足"], '
        '"review": [{"question": "Q1", "answer": "A1", "comment": "good"}], "verified": null}\n'
        "```\n"
    )
    llm = _make_llm(raw)
    result = report_node(state, llm)
    summary = result["_report_summary"]
    assert summary is not None
    assert summary["total_score"] == 82
    assert summary["dimensions"] == {"技术深度": 85, "沟通表达": 78}
    assert summary["strengths"] == ["基础扎实"]
    assert summary["review"] == [{"question": "Q1", "answer": "A1", "comment": "good"}]
    assert summary["verified"] is None


# --- evaluate + 引用注入（Tip 8）---


def test_evaluate_normal_injects_reference():
    state = initial_state()
    state["_api_key"] = "sk-test"
    state["current_question"] = "请解释缓存穿透"
    state["_reference_block"] = "【参考资料】\n[1]《redis.md》：缓存穿透指查询不存在的数据..."
    state["_citations"] = [
        {"file_name": "doc1.md", "text": "参考内容 1", "score": 0.9},
        {"file_name": "doc2.md", "text": "参考内容 2", "score": 0.8},
    ]
    llm = _make_llm(
        '{"score": {"技术深度": 8, "表达清晰度": 7, "问题解决": 7, "项目经验": 6}, '
        '"comment": "回答准确，与资料一致[1]", "needs_followup": false, "followup_reason": ""}'
    )
    result = evaluate_node(state, llm)
    call_prompt = llm.complete_sync.call_args.kwargs["prompt"]
    assert "【参考资料】" in call_prompt
    assert "[1]" in call_prompt
    scores = result["scores"]
    assert len(scores) == 1
    assert scores[0]["citations"] == state["_citations"]
    assert "[1]" in scores[0]["comment"]


def test_evaluate_fallback_injects_with_note():
    state = initial_state()
    state["_api_key"] = "sk-test"
    state["current_question"] = "什么是分布式事务"
    state["_reference_block"] = (
        "【参考资料】\n[1]《misc.md》：一些零散内容\n"
        "注意：以下资料与本次面试主题相关性有限，仅作参考，题目仍应考察通用知识。"
    )
    state["_citations"] = [{"file_name": "misc.md", "text": "一些零散内容", "score": 0.4}]
    llm = _make_llm(
        '{"score": {"技术深度": 6, "表达清晰度": 7, "问题解决": 6, "项目经验": 5}, '
        '"comment": "回答基本正确", "needs_followup": true, "followup_reason": "可深入"}'
    )
    result = evaluate_node(state, llm)
    call_prompt = llm.complete_sync.call_args.kwargs["prompt"]
    assert "相关性有限" in call_prompt
    assert len(result["scores"]) == 1
    assert len(result["scores"][0]["citations"]) == 1


def test_evaluate_decline_pure_generic():
    state = initial_state()
    state["_api_key"] = "sk-test"
    state["current_question"] = "什么是 RESTful"
    # 无 _reference_block / _citations（decline 时出题节点写入空值，评估侧降级为纯 LLM）
    llm = _make_llm(
        '{"score": {"技术深度": 7, "表达清晰度": 8, "问题解决": 7, "项目经验": 6}, '
        '"comment": "回答清晰", "needs_followup": false, "followup_reason": ""}'
    )
    result = evaluate_node(state, llm)
    call_prompt = llm.complete_sync.call_args.kwargs["prompt"]
    assert "【参考资料】" not in call_prompt
    assert "citations" not in result["scores"][0]


def test_evaluate_no_kb_pure_generic():
    state = initial_state()  # 无 kb_id
    state["_api_key"] = "sk-test"
    state["current_question"] = "介绍一下你的项目"
    # 无 _reference_block
    llm = _make_llm(
        '{"score": {"技术深度": 7, "表达清晰度": 8, "问题解决": 7, "项目经验": 7}, '
        '"comment": "项目经验丰富", "needs_followup": false, "followup_reason": ""}'
    )
    result = evaluate_node(state, llm)
    call_prompt = llm.complete_sync.call_args.kwargs["prompt"]
    assert "【参考资料】" not in call_prompt
    assert "citations" not in result["scores"][0]


def test_evaluate_citations_passthrough_identity():
    """评估节点原样传递出题节点的 citations（同一对象引用，不重新检索）。"""
    state = initial_state()
    state["_api_key"] = "sk-test"
    state["current_question"] = "什么是缓存雪崩"
    cites = [{"file_name": "redis.md", "text": "雪崩...", "score": 0.85}]
    state["_reference_block"] = "【参考资料】\n[1]《redis.md》：缓存雪崩指大量 Key 同时失效..."
    state["_citations"] = cites
    llm = _make_llm(
        '{"score": {"技术深度": 7, "表达清晰度": 7, "问题解决": 7, "项目经验": 6}, '
        '"comment": "回答基本正确[1]", "needs_followup": false, "followup_reason": ""}'
    )
    result = evaluate_node(state, llm)
    assert result["scores"][0]["citations"] is cites  # 同一引用（不重新检索）
