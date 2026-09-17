"""简历结构化抽取：纯文本 → LLM JSON（基本信息 / 技能 / 项目经历 + 考点清单 ≥10 项）。

P2 决策 2/3：轻量组合解析 + LLM 抽取，持久化「素材」而非「题目」——
题面由出题节点实时生成；考点清单独立成表支撑 COUNT 验收与按项出题。
"""

import json
import re
from dataclasses import dataclass

from app.llm.client import DeepSeekClient

EXTRACT_PROMPT = """\
你是简历解析助手，请从候选人的简历文本中抽取结构化信息。

【简历文本】
{resume_text}

请只输出一个 JSON 对象（不要输出其他任何内容），结构如下：
{{
  "basic": {{"name": "...", "title": "...", "years": "...", "email": "...", "phone": "..."}},
  "skills": ["技能1", "技能2", "..."],
  "projects": [
    {{"name": "项目名", "role": "担任角色", "description": "项目简介与职责",
      "tech": ["技术"], "highlights": ["亮点/难点"]}}
  ],
  "points": [
    {{"category": "项目|技能|基础", "title": "考点标题", "detail": "考点说明（供面试出题）",
      "source_snippet": "简历原文片段"}}
  ]
}}

要求：
- basic 中缺省的字段填空字符串
- skills 至少 5 项
- points 至少 10 项，覆盖「项目经历 / 技术技能 / 基础知识」三类，按重要性排序
- source_snippet 必须是简历原文片段（≤80 字），供出题时回溯依据
"""


@dataclass
class Point:
    """单个考点：category/title/detail/source_snippet（支持属性访问，便于出题节点消费）。"""

    category: str
    title: str
    detail: str
    source_snippet: str

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "title": self.title,
            "detail": self.detail,
            "source_snippet": self.source_snippet,
        }


@dataclass
class ExtractedProfile:
    profile_json: str  # basic + skills + projects（JSON 字符串）
    points: list[Point]  # 考点清单（Point 列表）


def _parse_profile(raw: str) -> dict:
    """容错解析 LLM 输出：支持 ```json 代码块包裹 / 纯 JSON；失败抛 ValueError。"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    payload = m.group(1) if m else raw
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"简历抽取输出不是合法 JSON：{e}") from e
    if not isinstance(data, dict):
        raise ValueError("简历抽取输出不是 JSON 对象")
    return data


def extract_profile(text: str, llm: DeepSeekClient, api_key: str, cfg) -> ExtractedProfile:
    """调用 LLM 抽取结构化简历 + 考点清单（后台任务内执行，完整同步调用）。"""
    raw, _ = llm.complete_sync(
        api_key=api_key, prompt=EXTRACT_PROMPT.format(resume_text=text[:8000])
    )
    data = _parse_profile(raw)
    profile_json = json.dumps(
        {
            "basic": data.get("basic", {}),
            "skills": data.get("skills", []),
            "projects": data.get("projects", []),
        },
        ensure_ascii=False,
    )
    points = [
        Point(
            category=_norm_category(p.get("category", "")),
            title=str(p.get("title", "")).strip(),
            detail=str(p.get("detail", "")).strip(),
            source_snippet=str(p.get("source_snippet", "")).strip()[:80],
        )
        for p in (data.get("points") or [])
        if str(p.get("title", "")).strip()
    ]
    return ExtractedProfile(profile_json=profile_json, points=points)


def _norm_category(category: str) -> str:
    """考点分类归一：项目/技能/基础，未知归入基础。"""
    if category in ("项目", "技能", "基础"):
        return category
    return "基础"
