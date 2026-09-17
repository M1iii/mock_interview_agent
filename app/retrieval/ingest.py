"""文档入库：解析 → 父子切块 → Qdrant（子块向量）+ ES（父块全文）双写，按文件幂等重建。

存储映射（2026-09-17 确认）：Qdrant 存子块（向量 + text/parent_id/file_id/file_name/kb_id/seq），
ES 存父块（全文 ik 索引，文档 id = parent_id，含 file_id/file_name/kb_id）。
"""

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from omegaconf import DictConfig
from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.retrieval.chunking import chunk_document
from app.retrieval.embedding import EmbeddingProvider
from app.retrieval.es import ESManager
from app.retrieval.parsers import parse_document
from app.retrieval.qdrant import QdrantManager

_BATCH = 64


@dataclass
class IngestResult:
    file_id: str
    parent_count: int
    child_count: int


def file_id_of(path: str | Path) -> str:
    """文件指纹：路径哈希前 16 位（幂等重建的归属键）。"""
    return hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:16]


def ingest_document(
    path: str | Path,
    qdrant: QdrantManager,
    es: ESManager,
    embedding: EmbeddingProvider,
    cfg: DictConfig,
    kb_id: str | None = None,
) -> IngestResult:
    """入库单文件：先清旧（同 file_id）再双写。服务不可用时抛 RetrievalUnavailable。

    kb_id：关联知识库 ID（检索时按库过滤，P1 按库粒度关联）。
    """
    p = Path(path)
    text = parse_document(p)
    parents, children = chunk_document(text, cfg)
    if not children:
        raise ValueError(f"文档切块结果为空：{p.name}")

    file_id = file_id_of(p)
    file_name = p.name
    qdrant.ensure_collection(embedding.dims)
    es.ensure_index()
    _delete_old(file_id, qdrant, es)

    if parents:
        _upsert_parents(parents, file_id, file_name, kb_id, es)
        _upsert_children(children, file_id, file_name, kb_id, qdrant, embedding)
    logger.info(
        "ingested {name}: file={fid} parents={p} children={c}",
        name=p.name,
        fid=file_id,
        p=len(parents),
        c=len(children),
    )
    return IngestResult(file_id=file_id, parent_count=len(parents), child_count=len(children))


def delete_document(file_id: str, qdrant: QdrantManager, es: ESManager) -> None:
    """删除某文件全部块（Qdrant 子块 + ES 父块），供知识库删除级联调用。"""
    _delete_old(file_id, qdrant, es)


def _delete_old(file_id: str, qdrant: QdrantManager, es: ESManager) -> None:
    qdrant.get_client().delete(
        collection_name=qdrant.collection,
        points_selector=Filter(
            must=[FieldCondition(key="file_id", match=MatchValue(value=file_id))]
        ),
    )
    es.get_client().delete_by_query(
        index=es.index,
        query={"term": {"file_id": file_id}},
        refresh=True,
    )


def _upsert_parents(
    parents: list,
    file_id: str,
    file_name: str,
    kb_id: str | None,
    es: ESManager,
) -> None:
    client = es.get_client()
    for parent in parents:
        doc = {
            "parent_id": parent.id,
            "file_id": file_id,
            "file_name": file_name,
            "text": parent.text,
        }
        if kb_id:
            doc["kb_id"] = kb_id
        client.index(
            index=es.index,
            id=parent.id,
            document=doc,
        )
    client.indices.refresh(index=es.index)


def _upsert_children(
    children: list,
    file_id: str,
    file_name: str,
    kb_id: str | None,
    qdrant: QdrantManager,
    embedding: EmbeddingProvider,
) -> None:
    client = qdrant.get_client()
    for start in range(0, len(children), _BATCH):
        batch = children[start : start + _BATCH]
        vectors = embedding.embed_documents([c.text for c in batch])
        payloads = []
        for c in batch:
            p = {**c.as_dict(), "file_id": file_id, "file_name": file_name}
            if kb_id:
                p["kb_id"] = kb_id
            payloads.append(p)
        client.upsert(
            collection_name=qdrant.collection,
            points=[
                {"id": _point_id(c), "vector": vec, "payload": payload}
                for c, vec, payload in zip(batch, vectors, payloads, strict=True)
            ],
        )


def _point_id(child) -> int:
    return uuid.uuid4().int & ((1 << 63) - 1)
