"""知识库元数据：SQLite kb.db（2026-09-17 澄清确认）。

两表：knowledge_bases（库 + 绑定 model_id/dims）+ kb_files（文件条目/状态）。
删除级联（P1-5）与 Embedding 切换重建（P1-7）均由本层文件清单驱动。
线程安全：单连接 + threading.Lock（FastAPI 后台任务与请求线程共享）。
"""

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# 文件状态机：processing → ready / failed（failed 可重试回 processing）
PROCESSING = "processing"
READY = "ready"
FAILED = "failed"


@dataclass
class KnowledgeBase:
    id: str
    name: str
    model_id: str
    dims: int
    created_at: datetime
    files: list = None  # KbFile，list_kbs 时填充

    def __post_init__(self) -> None:
        if self.files is None:
            self.files = []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "model_id": self.model_id,
            "dims": self.dims,
            "created_at": self.created_at.isoformat(),
            "files": [f.to_dict() for f in self.files],
        }


@dataclass
class KbFile:
    id: str
    kb_id: str
    file_id: str  # 路径哈希（Qdrant/ES 归属键）
    name: str
    path: str  # 存储路径（相对项目根），保留原件供失败重试
    size: int
    status: str
    error: str | None = None
    block_count: int | None = None
    created_at: datetime = None  # type: ignore[assignment]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kb_id": self.kb_id,
            "file_id": self.file_id,
            "name": self.name,
            "size": self.size,
            "status": self.status,
            "error": self.error,
            "block_count": self.block_count,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class KnowledgeStore:
    """SQLite 知识库元数据层（单连接 + 锁，线程安全）。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    dims INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS kb_files (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    file_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'processing',
                    error TEXT,
                    block_count INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
                );
                """
            )
            self._conn.commit()

    # ---- 知识库 ----

    def create_kb(self, kb_id: str, name: str, model_id: str, dims: int) -> KnowledgeBase:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO knowledge_bases (id, name, model_id, dims, created_at)"
                " VALUES (?,?,?,?,?)",
                (kb_id, name, model_id, dims, now),
            )
            self._conn.commit()
        return KnowledgeBase(kb_id, name, model_id, dims, datetime.fromisoformat(now))

    def get_kb(self, kb_id: str) -> KnowledgeBase | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)
            ).fetchone()
        return self._row_to_kb(row) if row else None

    def list_kbs(self) -> list[KnowledgeBase]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM knowledge_bases ORDER BY created_at DESC"
            ).fetchall()
            file_rows = self._conn.execute(
                "SELECT * FROM kb_files ORDER BY created_at DESC"
            ).fetchall()
        files_by_kb: dict[str, list[KbFile]] = {}
        for frow in file_rows:
            files_by_kb.setdefault(frow["kb_id"], []).append(self._row_to_file(frow))
        return [self._row_to_kb(r, files_by_kb.get(r["id"], [])) for r in rows]

    def delete_kb(self, kb_id: str) -> list[KbFile]:
        """删除库：返回该库全部文件条目（调用方据此级联清理 Qdrant/ES + 原文件）。"""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM kb_files WHERE kb_id = ?", (kb_id,)).fetchall()
            files = [self._row_to_file(r) for r in rows]
            self._conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
            self._conn.commit()
        return files

    def bind_model(self, kb_id: str, model_id: str, dims: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE knowledge_bases SET model_id = ?, dims = ? WHERE id = ?",
                (model_id, dims, kb_id),
            )
            self._conn.commit()

    # ---- 文件条目 ----

    def add_file(self, kb_id: str, file_id: str, name: str, path: str, size: int) -> KbFile:
        now = datetime.now(UTC).isoformat()
        record_id = f"f-{file_id}"
        with self._lock:
            self._conn.execute(
                "INSERT INTO kb_files (id, kb_id, file_id, name, path, size, status, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (record_id, kb_id, file_id, name, path, size, PROCESSING, now),
            )
            self._conn.commit()
        return KbFile(
            record_id,
            kb_id,
            file_id,
            name,
            path,
            size,
            PROCESSING,
            created_at=datetime.fromisoformat(now),
        )

    def get_file(self, record_id: str) -> KbFile | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM kb_files WHERE id = ?", (record_id,)).fetchone()
        return self._row_to_file(row) if row else None

    def list_all_files(self) -> list[KbFile]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM kb_files ORDER BY created_at").fetchall()
        return [self._row_to_file(r) for r in rows]

    def update_file_status(
        self,
        record_id: str,
        status: str,
        error: str | None = None,
        block_count: int | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE kb_files SET status = ?, error = ?, block_count = ? WHERE id = ?",
                (status, error, block_count, record_id),
            )
            self._conn.commit()

    # ---- 内部 ----

    @staticmethod
    def _row_to_kb(row: sqlite3.Row, files: list | None = None) -> KnowledgeBase:
        return KnowledgeBase(
            id=row["id"],
            name=row["name"],
            model_id=row["model_id"],
            dims=row["dims"],
            created_at=datetime.fromisoformat(row["created_at"]),
            files=files or [],
        )

    @staticmethod
    def _row_to_file(row: sqlite3.Row) -> KbFile:
        return KbFile(
            id=row["id"],
            kb_id=row["kb_id"],
            file_id=row["file_id"],
            name=row["name"],
            path=row["path"],
            size=row["size"],
            status=row["status"],
            error=row["error"],
            block_count=row["block_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
