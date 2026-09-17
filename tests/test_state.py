from app.interview.state import InterviewState, Score, initial_state


def test_initial_state_defaults():
    s = initial_state()
    assert s["scene"] == "fulltime"
    assert s["question_count"] == 10
    assert s["question_index"] == 0
    assert s["current_question"] is None
    assert s["hints_used"] == 0
    assert s["followups"] == 0
    assert s["scores"] == []
    assert s["status"] == "ongoing"
    assert s["skip_opening"] is False
    assert s["difficulty_stage"] == 1
    assert s["question_bank"] == []
    assert s["asked_ids"] == []
    assert s["answered_qa"] == []


def test_initial_state_intern_skip():
    s = initial_state(scene="intern", question_count=5, skip_opening=True)
    assert s["scene"] == "intern"
    assert s["question_count"] == 5
    assert s["skip_opening"] is True


def test_state_is_typeddict():

    assert hasattr(InterviewState, "__annotations__")
    assert "messages" in InterviewState.__annotations__
    assert "scene" in InterviewState.__annotations__
    assert "skip_opening" in InterviewState.__annotations__
    assert "difficulty_stage" in InterviewState.__annotations__
    assert "question_bank" in InterviewState.__annotations__


def test_score_type():
    s: Score = {
        "question": "Q1",
        "answer": "A1",
        "score": 8.5,
        "comment": "good",
        "dimensions": {"技术深度": 9.0},
    }
    assert s["score"] == 8.5
    assert s["dimensions"]["技术深度"] == 9.0
