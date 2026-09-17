"""父子切块（混合算法，2026-09-17 确认）：
段落优先主切分 → 句子边界细切 → 超长单句滑动窗口兜底 → 段内相邻子块可选 overlap 补偿
→ 相邻子块聚合父块（≤800 字引用单元）。子块 ≤200 字为召回单元（Qdrant 向量），父块为引用单元。
"""

import re
import uuid
from dataclasses import dataclass

from omegaconf import DictConfig

SENTENCE_ENDS = "。！？!?；;\n"


@dataclass
class Block:
    """子块（召回单元）。

    text 为向量文本（含可选 overlap 补偿），raw_text 为原始文本（父块聚合用）。
    """

    parent_id: str
    text: str
    raw_text: str
    seq: int

    def as_dict(self) -> dict:
        return {"parent_id": self.parent_id, "text": self.text, "seq": self.seq}


@dataclass
class ParentBlock:
    """父块（引用单元）。text = 子块原始文本顺序拼接（≤800 字）。"""

    id: str
    text: str
    child_seqs: list[int]


def chunk_document(text: str, cfg: DictConfig) -> tuple[list[ParentBlock], list[Block]]:
    """将整篇文本切为（父块, 子块）。cfg 传 retrieval.chunking 节。"""
    chunk_cfg = cfg.retrieval.chunking
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return [], []

    # 1+2+3+4：段落 → 子块（句子细切 / 滑动窗口兜底 / 段内 overlap）
    child_texts: list[tuple[str, str]] = []  # (text, raw_text)
    for para in paragraphs:
        raw_chunks = _chunk_paragraph(para, chunk_cfg)
        if not raw_chunks:
            continue
        overlap = int(chunk_cfg.overlap_chars)
        if overlap > 0 and len(raw_chunks) > 1:
            chunks = _apply_overlap(raw_chunks, overlap)
        else:
            chunks = raw_chunks
        child_texts.extend(zip(chunks, raw_chunks, strict=True))

    # 5：相邻子块聚合父块（≤800 字）
    parents: list[ParentBlock] = []
    blocks: list[Block] = []
    cur_parent_id = uuid.uuid4().hex
    cur_parent_parts: list[str] = []
    cur_parent_len = 0
    cur_seqs: list[int] = []
    parent_max = int(chunk_cfg.parent_max_chars)

    for seq, (text, raw) in enumerate(child_texts):
        if cur_parent_parts and cur_parent_len + len(raw) > parent_max:
            parents.append(ParentBlock(cur_parent_id, "".join(cur_parent_parts), cur_seqs))
            cur_parent_id = uuid.uuid4().hex
            cur_parent_parts = []
            cur_parent_len = 0
            cur_seqs = []
        blocks.append(Block(cur_parent_id, text, raw, seq))
        cur_parent_parts.append(raw)
        cur_parent_len += len(raw)
        cur_seqs.append(seq)

    if cur_parent_parts:
        parents.append(ParentBlock(cur_parent_id, "".join(cur_parent_parts), cur_seqs))
    return parents, blocks


def _split_paragraphs(text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text)]
    return [p for p in paras if p]


def _chunk_paragraph(para: str, cfg: DictConfig) -> list[str]:
    """段落 → ≤child_max 的子块文本列表（纯原始文本，不含 overlap 补偿）。"""
    child_max = int(cfg.child_max_chars)
    if len(para) <= child_max:
        return [para]

    sents = _split_sentences(para)
    chunks: list[str] = []
    cur = ""
    for sent in sents:
        if len(sent) > child_max:
            if cur:
                chunks.append(cur)
                cur = ""
            window = min(int(cfg.slide_window), child_max)
            chunks.extend(_slide_cut(sent, window, int(cfg.slide_overlap)))
        elif len(cur) + len(sent) <= child_max:
            cur += sent
        else:
            chunks.append(cur)
            cur = sent
    if cur:
        chunks.append(cur)
    return chunks


def _split_sentences(para: str) -> list[str]:
    sents = re.split(rf"(?<=[{SENTENCE_ENDS}])", para)
    out = []
    for s in sents:
        s = s.strip()
        if s:
            out.append(s)
    return out


def _slide_cut(text: str, window: int, overlap: int) -> list[str]:
    """超长单句兜底：滑动窗口切分（默认窗口 180 / 重叠 20）。"""
    if len(text) <= window:
        return [text]
    step = max(1, window - overlap)
    parts = [text[i : i + window] for i in range(0, len(text), step)]
    return [p for p in parts if p]


def _apply_overlap(chunks: list[str], n: int) -> list[str]:
    """段内相邻子块 overlap 补偿：子块 i 文本末尾补下个子块开头 n 字。"""
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        tail = prev[-n:] if n > 0 else ""
        out.append(tail + chunks[i])
    return out
