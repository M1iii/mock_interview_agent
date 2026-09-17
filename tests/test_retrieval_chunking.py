from app.config import load_config
from app.retrieval.chunking import chunk_document


def _cfg(**overrides):
    cfg = load_config()
    for key, value in overrides.items():
        setattr(cfg.retrieval.chunking, key, value)
    return cfg


def test_short_paragraph_single_block():
    parents, blocks = chunk_document("什么是多态", _cfg())
    assert len(blocks) == 1
    assert blocks[0].text == "什么是多态"
    assert len(parents) == 1
    assert parents[0].text == "什么是多态"
    assert parents[0].id == blocks[0].parent_id


def test_sentence_split_for_long_paragraph():
    para = "第一句。第二句！第三句？第四句；第五句"
    parents, blocks = chunk_document(para, _cfg(child_max_chars=4))
    texts = [b.raw_text for b in blocks]
    assert texts == ["第一句。", "第二句！", "第三句？", "第四句；", "第五句"]


def test_sentence_assembly_under_child_max():
    para = "第一句。第二句。第三句。第四句。"
    parents, blocks = chunk_document(para, _cfg(child_max_chars=12))
    # 每句 4-5 字，12 字内可装 2 句左右
    assert len(blocks) >= 2
    assert all(len(b.raw_text) <= 12 for b in blocks)
    assert "".join(b.raw_text for b in blocks) == para


def test_slide_cut_for_overlong_sentence():
    long_sentence = "这" * 500 + "。"
    parents, blocks = chunk_document(long_sentence, _cfg(child_max_chars=50))
    assert len(blocks) >= 2
    assert all(len(b.raw_text) <= 50 for b in blocks)


def test_overlap_compensation_within_paragraph():
    para = "第一句。第二句。第三句。第四句。第五句。"
    cfg = _cfg(child_max_chars=12, overlap_chars=4)
    parents, blocks = chunk_document(para, cfg)
    assert len(blocks) >= 2
    # 子块 i 的 text 以子块 i-1 末尾 4 字开头（overlap 补偿）
    assert blocks[1].text.startswith(blocks[0].raw_text[-4:])
    # 父块聚合用 raw_text，不含 overlap 补偿
    assert all(b.parent_id for b in blocks)


def test_no_overlap_by_default():
    para = "第一句。第二句。第三句。第四句。第五句。"
    parents, blocks = chunk_document(para, _cfg(child_max_chars=12))
    assert blocks[0].text == blocks[0].raw_text
    assert blocks[1].text == blocks[1].raw_text


def test_parent_aggregation_caps_at_800():
    text = "\n\n".join(f"第{i}段。" + "内容内容内容内容" for i in range(80))
    parents, blocks = chunk_document(text, _cfg())
    assert len(parents) >= 2
    assert all(len(p.text) <= 800 for p in parents)
    # 父块由子块 raw_text 顺序拼接而成
    for parent in parents:
        seqs = parent.child_seqs
        expected = "".join(blocks[s].raw_text for s in seqs)
        assert parent.text == expected


def test_paragraphs_split_by_blank_lines():
    text = "第一段内容\n\n第二段内容\n\n\n第三段内容"
    parents, blocks = chunk_document(text, _cfg())
    raws = [b.raw_text for b in blocks]
    assert raws == ["第一段内容", "第二段内容", "第三段内容"]


def test_empty_text_returns_empty():
    parents, blocks = chunk_document("   \n\n  ", _cfg())
    assert parents == []
    assert blocks == []
