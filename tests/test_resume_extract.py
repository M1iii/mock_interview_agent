import json
from types import SimpleNamespace

import pytest

from app.resume.extract import EXTRACT_PROMPT, ExtractedProfile, _parse_profile, extract_profile


def _llm(raw: str):
    return SimpleNamespace(complete_sync=lambda api_key, prompt, callbacks=None: (raw, {}))


def test_parse_profile_plain_json():
    raw = json.dumps(
        {
            "basic": {"name": "张三"},
            "skills": ["Python", "Redis"],
            "projects": [
                {"name": "商城", "role": "后端", "description": "x", "tech": [], "highlights": []}
            ],
            "points": [
                {
                    "category": "技能",
                    "title": "Redis 缓存",
                    "detail": "缓存穿透",
                    "source_snippet": "使用 Redis 缓存",
                }
            ],
        }
    )
    data = _parse_profile(raw)
    assert data["basic"]["name"] == "张三"
    assert len(data["points"]) == 1


def test_parse_profile_json_codeblock():
    raw = '```json\n{"basic": {}, "skills": [], "projects": [], "points": []}\n```'
    data = _parse_profile(raw)
    assert data["points"] == []


def test_parse_profile_malformed_raises():
    with pytest.raises(ValueError):
        _parse_profile("这不是 JSON")


def test_extract_profile_builds_points():
    raw = json.dumps(
        {
            "basic": {"name": "李四", "title": "Java 开发"},
            "skills": ["Java", "Spring"],
            "projects": [
                {
                    "name": "订单系统",
                    "role": "开发",
                    "description": "高并发下单",
                    "tech": ["Java"],
                    "highlights": ["压测优化"],
                }
            ],
            "points": [
                {
                    "category": "项目",
                    "title": "订单链路",
                    "detail": "扣库存一致性",
                    "source_snippet": "订单与库存一致性设计",
                },
                {
                    "category": "技能",
                    "title": "JVM 调优",
                    "detail": "GC 参数",
                    "source_snippet": "JVM 调优经验",
                },
            ],
        }
    )
    profile = extract_profile("简历文本", _llm(raw), "sk-test123", None)
    assert isinstance(profile, ExtractedProfile)
    parsed = json.loads(profile.profile_json)
    assert parsed["basic"]["name"] == "李四"
    assert len(profile.points) == 2
    assert profile.points[0].category == "项目"
    assert profile.points[0].source_snippet == "订单与库存一致性设计"


def test_extract_prompt_contains_placeholders():
    assert "{resume_text}" in EXTRACT_PROMPT
    assert "points" in EXTRACT_PROMPT
