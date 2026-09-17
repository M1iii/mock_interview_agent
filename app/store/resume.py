"""简历域元数据：SQLite resume.db（2026-09-17 P2 设计定稿）。

两表：resumes（文件条目 + profile_json + 状态）+ resume_points（考点清单，独立成表支撑
`SELECT COUNT(*)` 验收）。删除级联（R5 物理删）：resume_points 随 resumes 级联，
原文件由 API 层按返回 path 物理删除。
线程安全：单连接 + threading.Lock（与 KnowledgeStore 同模式）。
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
class Resume:
    id: str
    file_name: str
    path: str  # 存储路径（相对项目根），保留原件供失败重试
    size: int
    status: str
    error: str | None = None
    profile_json: str | None = None  # 结构化简历 JSON 字符串（basic/skills/projects）
    point_count: int | None = None
    created_at: datetime = None  # type: ignore[assignment]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file_name": self.file_name,
            "path": self.path,
            "size": self.size,
            "status": self.status,
            "error": self.error,
            "point_count": self.point_count,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


@dataclass
class ResumePoint:
    id: str
    resume_id: str
    seq: int
    category: str  # 项目 / 技能 / 基础
    title: str
    detail: str
    source_snippet: str  # 简历原文片段（出题回溯依据）

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "resume_id": self.resume_id,
            "seq": self.seq,
            "category": self.category,
            "title": self.title,
            "detail": self.detail,
            "source_snippet": self.source_snippet,
        }


class ResumeStore:
    """SQLite 简历元数据层（单连接 + 锁，线程安全）。"""

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
                CREATE TABLE IF NOT EXISTS resumes (
                    id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'processing',
                    error TEXT,
                    profile_json TEXT,
                    point_count INTEGER,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resume_points (
                    id TEXT PRIMARY KEY,
                    resume_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    source_snippet TEXT NOT NULL,
                    FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE CASCADE
                );
                """
            )
            self._conn.commit()

    def add_resume(self, resume_id: str, file_name: str, path: str, size: int) -> Resume:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO resumes (id, file_name, path, size, status, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (resume_id, file_name, path, size, PROCESSING, now),
            )
            self._conn.commit()
        return Resume(
            resume_id,
            file_name,
            path,
            size,
            PROCESSING,
            created_at=datetime.fromisoformat(now),
        )

    def get_resume(self, resume_id: str) -> Resume | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
        return self._row_to_resume(row) if row else None

    def list_resumes(self) -> list[Resume]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM resumes ORDER BY created_at DESC").fetchall()
        return [self._row_to_resume(r) for r in rows]

    def update_ready(self, resume_id: str, profile_json: str, points: list[dict]) -> None:
        """抽取成功：写 profile_json + 全量替换考点清单（幂等）。"""
        with self._lock:
            self._conn.execute("DELETE FROM resume_points WHERE resume_id = ?", (resume_id,))
            for i, p in enumerate(points):
                self._conn.execute(
                    "INSERT INTO resume_points"
                    " (id, resume_id, seq, category, title, detail, source_snippet)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (
                        f"rp-{resume_id}-{i}",
                        resume_id,
                        i,
                        p["category"],
                        p["title"],
                        p["detail"],
                        p["source_snippet"],
                    ),
                )
            self._conn.execute(
                "UPDATE resumes SET status = ?, error = NULL, profile_json = ?, point_count = ?"
                " WHERE id = ?",
                (READY, profile_json, len(points), resume_id),
            )
            self._conn.commit()

    def update_failed(self, resume_id: str, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE resumes SET status = ?, error = ? WHERE id = ?",
                (FAILED, error[:500], resume_id),
            )
            self._conn.commit()

    def update_processing(self, resume_id: str) -> None:
        """重试入口：failed → processing，清错误信息。"""
        with self._lock:
            self._conn.execute(
                "UPDATE resumes SET status = ?, error = NULL WHERE id = ?",
                (PROCESSING, resume_id),
            )
            self._conn.commit()

    def list_points(self, resume_id: str) -> list[ResumePoint]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM resume_points WHERE resume_id = ? ORDER BY seq",
                (resume_id,),
            ).fetchall()
        return [
            ResumePoint(
                id=r["id"],
                resume_id=r["resume_id"],
                seq=r["seq"],
                category=r["category"],
                title=r["title"],
                detail=r["detail"],
                source_snippet=r["source_snippet"],
            )
            for r in rows
        ]

    def count_points(self, resume_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM resume_points WHERE resume_id = ?", (resume_id,)
            ).fetchone()
        return int(row["n"])

    def delete_resume(self, resume_id: str) -> str | None:
        """删除简历：返回原文件相对路径供 API 物理删（FK CASCADE 清考点）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT path FROM resumes WHERE id = ?", (resume_id,)
            ).fetchone()
            if row is None:
                return None
            path = row["path"]
            self._conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
            self._conn.commit()
        return path

    @staticmethod
    def _row_to_resume(row: sqlite3.Row) -> Resume:
        return Resume(
            id=row["id"],
            file_name=row["file_name"],
            path=row["path"],
            size=row["size"],
            status=row["status"],
            error=row["error"],
            profile_json=row["profile_json"],
            point_count=row["point_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
