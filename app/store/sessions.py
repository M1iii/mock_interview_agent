"""会话元数据管理：P0 内存 dict / P2 SQLite 表。

架构原则：存储抽象先行，图代码零改动切换。"""

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


class SessionMeta(dict):
    """会话元数据（非 LangGraph 状态，仅用于列表/管理）。"""

    id: str
    title: str
    scene: str
    status: str
    created_at: datetime
    question_count: int
    skip_opening: bool
    kb_id: str | None
    resume_id: str | None  # P2：关联简历（可空）
    interview_type: str  # P2：technical / behavioral / comprehensive


class SessionStore(Protocol):
    """会话元数据存储抽象。"""

    def create(
        self,
        session_id: str,
        scene: str,
        question_count: int,
        skip_opening: bool = False,
        kb_id: str | None = None,
        resume_id: str | None = None,
        interview_type: str = "technical",
    ) -> SessionMeta: ...

    def get(self, session_id: str) -> SessionMeta | None: ...

    def list(self) -> list[SessionMeta]: ...

    def update_status(self, session_id: str, status: str) -> None: ...

    def delete(self, session_id: str) -> None: ...


class InMemorySessionStore:
    """P0 内存实现。"""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionMeta] = {}

    def create(
        self,
        session_id: str,
        scene: str,
        question_count: int,
        skip_opening: bool = False,
        kb_id: str | None = None,
        resume_id: str | None = None,
        interview_type: str = "technical",
    ) -> SessionMeta:
        meta: SessionMeta = {
            "id": session_id,
            "title": f"{'实习' if scene == 'intern' else '全职'}面试",
            "scene": scene,
            "status": "ongoing",
            "created_at": datetime.now(UTC),
            "question_count": question_count,
            "skip_opening": skip_opening,
            "kb_id": kb_id,
            "resume_id": resume_id,
            "interview_type": interview_type,
        }
        self._sessions[session_id] = meta
        return meta

    def get(self, session_id: str) -> SessionMeta | None:
        return self._sessions.get(session_id)

    def list(self) -> list[SessionMeta]:
        return sorted(self._sessions.values(), key=lambda s: s["created_at"], reverse=True)

    def update_status(self, session_id: str, status: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id]["status"] = status

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


class SqliteSessionStore:
    """P2 会话元数据 SQLite 实现（interview.db sessions 表，与 SqliteSaver 同库异表）。

    与 KnowledgeStore 同模式：单连接 + threading.Lock，线程安全。
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    scene TEXT NOT NULL,
                    interview_type TEXT NOT NULL DEFAULT 'technical',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    question_count INTEGER NOT NULL,
                    skip_opening INTEGER NOT NULL DEFAULT 0,
                    kb_id TEXT,
                    resume_id TEXT
                );
                """
            )
            self._conn.commit()

    def create(
        self,
        session_id: str,
        scene: str,
        question_count: int,
        skip_opening: bool = False,
        kb_id: str | None = None,
        resume_id: str | None = None,
        interview_type: str = "technical",
    ) -> SessionMeta:
        now = datetime.now(UTC).isoformat()
        title = f"{'实习' if scene == 'intern' else '全职'}面试"
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions"
                " (id, title, scene, interview_type, status, created_at, question_count,"
                "  skip_opening, kb_id, resume_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    title,
                    scene,
                    interview_type,
                    "ongoing",
                    now,
                    question_count,
                    int(skip_opening),
                    kb_id,
                    resume_id,
                ),
            )
            self._conn.commit()
        return SessionMeta(
            id=session_id,
            title=title,
            scene=scene,
            interview_type=interview_type,
            status="ongoing",
            created_at=datetime.fromisoformat(now),
            question_count=question_count,
            skip_opening=skip_opening,
            kb_id=kb_id,
            resume_id=resume_id,
        )

    def get(self, session_id: str) -> SessionMeta | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return self._row_to_meta(row) if row else None

    def list(self) -> list[SessionMeta]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [self._row_to_meta(r) for r in rows]

    def update_status(self, session_id: str, status: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE sessions SET status = ? WHERE id = ?", (status, session_id))
            self._conn.commit()

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._conn.commit()

    @staticmethod
    def _row_to_meta(row: sqlite3.Row) -> SessionMeta:
        return SessionMeta(
            id=row["id"],
            title=row["title"],
            scene=row["scene"],
            interview_type=row["interview_type"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            question_count=row["question_count"],
            skip_opening=bool(row["skip_opening"]),
            kb_id=row["kb_id"],
            resume_id=row["resume_id"],
        )
