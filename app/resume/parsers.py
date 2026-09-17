"""简历解析：复用知识库解析链路（pdfplumber + python-docx，P1 已验证）。

支持 MD/TXT/DOCX/PDF；PDF 无文字层抛 ParseError（后台任务置 failed）。
"""

from app.retrieval.parsers import ParseError, parse_document

__all__ = ["ParseError", "parse_document"]
