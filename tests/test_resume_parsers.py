import pytest

from app.resume.parsers import ParseError, parse_document


def test_parse_md(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("# 张三\n## 技能\nPython", encoding="utf-8")
    text = parse_document(p)
    assert "张三" in text and "Python" in text


def test_parse_unsupported_ext(tmp_path):
    p = tmp_path / "r.xlsx"
    p.write_bytes(b"x")
    with pytest.raises(ParseError):
        parse_document(p)


def test_parse_empty_raises(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("   ", encoding="utf-8")
    with pytest.raises(ParseError):
        parse_document(p)
