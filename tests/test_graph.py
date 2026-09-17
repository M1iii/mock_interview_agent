from omegaconf import OmegaConf

from app.interview.graph import build_graph, compile_graph, route_after_evaluate, route_after_start
from app.interview.state import initial_state
from app.llm.client import DeepSeekClient

CFG = OmegaConf.create(
    {
        "llm": {
            "model_id": "test-model",
            "base_url": "https://api.example.com",
            "timeout": 60,
            "max_retries": 2,
        }
    }
)


def _make_llm():
    return DeepSeekClient(CFG)


def test_route_after_start_normal():
    s = initial_state()
    assert route_after_start(s) == "opening"


def test_route_after_start_skip():
    s = initial_state(skip_opening=True)
    assert route_after_start(s) == "ask_question"


def test_route_after_evaluate_followup():
    s = initial_state()
    s["_needs_followup"] = True
    s["followups"] = 0
    s["question_index"] = 1
    s["question_count"] = 10
    assert route_after_evaluate(s) == "follow_up"


def test_route_after_evaluate_followup_at_limit():
    s = initial_state()
    s["_needs_followup"] = True
    s["followups"] = 2
    s["question_index"] = 1
    s["question_count"] = 10
    assert route_after_evaluate(s) == "ask_question"


def test_route_after_evaluate_next_question():
    s = initial_state()
    s["_needs_followup"] = False
    s["question_index"] = 5
    s["question_count"] = 10
    assert route_after_evaluate(s) == "ask_question"


def test_route_after_evaluate_report():
    s = initial_state()
    s["_needs_followup"] = False
    s["question_index"] = 10
    s["question_count"] = 10
    assert route_after_evaluate(s) == "report"


def test_route_after_evaluate_followup_on_last_question():
    """最后一题仍允许追问——追问完成后再评估才进 report。"""
    s = initial_state()
    s["_needs_followup"] = True
    s["followups"] = 0
    s["question_index"] = 10
    s["question_count"] = 10
    assert route_after_evaluate(s) == "follow_up"


def test_route_after_evaluate_report_after_followup_exhausted_on_last():
    """最后一题追问耗尽后进 report。"""
    s = initial_state()
    s["_needs_followup"] = True
    s["followups"] = 2
    s["question_index"] = 10
    s["question_count"] = 10
    assert route_after_evaluate(s) == "report"


def test_build_graph():
    g = build_graph(_make_llm())
    nodes = set(g.nodes.keys())
    assert nodes == {"opening", "ask_question", "evaluate", "follow_up", "report"}


def test_compile_graph():
    compiled = compile_graph(_make_llm())
    assert compiled is not None
