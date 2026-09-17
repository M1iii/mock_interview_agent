"""双来源出题配比：按面试类型换算简历题落位（P2 决策 1/7，方案 A 单节点分支）。

落位规则（P2 设计 §5）：简历题均匀交错分散在前中后段，取整余数补知识库侧；
计数可逐题核对（P2-2 验收：技术面 3 道 / 行为面 8 道 / 综合面 5 道，按 10 题计）。
"""

RESUME_RATIO_DEFAULTS = {"technical": 0.3, "behavioral": 0.8, "comprehensive": 0.5}


def resume_question_indices(question_count: int, resume_ratio: float) -> list[int]:
    """返回 1-based 简历题号列表（均匀交错分散，覆盖前中后段）。

    R = int(N*ratio + 0.5)（四舍五入，夹在 [0, N]）；第 i 个简历题落在 floor(i*N/R)+1。
    例：N=10, R=3 → [1,4,7]；N=10, R=5 → [1,3,5,7,9]；N=10, R=8 → [1,2,3,4,6,7,8,9]。
    """
    n = int(question_count)
    r = min(n, max(0, int(n * resume_ratio + 0.5)))
    if r == 0:
        return []
    return [int(i * n / r) + 1 for i in range(r)]


def is_resume_question(question_index: int, question_count: int, resume_ratio: float) -> bool:
    """当前题（0-based question_index）是否走简历出题。"""
    return (question_index + 1) in resume_question_indices(question_count, resume_ratio)
