from app.interview.ratio import is_resume_question, resume_question_indices


def test_resume_indices_technical_10q():
    """技术面 10 题、简历占比 0.3 → 3 道简历题，均匀交错在前中后段。"""
    indices = resume_question_indices(10, 0.3)
    assert indices == [1, 4, 7]
    assert len(indices) == 3


def test_resume_indices_comprehensive_10q():
    indices = resume_question_indices(10, 0.5)
    assert indices == [1, 3, 5, 7, 9]


def test_resume_indices_behavioral_10q():
    indices = resume_question_indices(10, 0.8)
    assert len(indices) == 8
    assert 5 not in indices  # 知识库题号
    assert 10 not in indices


def test_resume_indices_ratio_zero():
    assert resume_question_indices(10, 0.0) == []


def test_resume_indices_ratio_one():
    assert resume_question_indices(10, 1.0) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_is_resume_question():
    assert is_resume_question(0, 10, 0.3) is True  # 第 1 题
    assert is_resume_question(1, 10, 0.3) is False  # 第 2 题
    assert is_resume_question(6, 10, 0.3) is True  # 第 7 题
