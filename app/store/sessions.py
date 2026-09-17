"""会话元数据管理：P0 内存 dict / P2 SQLite 表。

架构原则：存储抽象先行，图代码零改动切换。"""

from datetime import UTC, datetime
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


class SessionStore(Protocol):
    """会话元数据存储抽象。"""

    def create(
        self,
        session_id: str,
        scene: str,
        question_count: int,
        skip_opening: bool = False,
        kb_id: str | None = None,
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
