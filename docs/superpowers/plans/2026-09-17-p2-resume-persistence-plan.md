# P2 简历解析与题库 + 跨重启持久化 + web_verify 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** P2 五项交付——简历解析入库（P2-1）、双来源出题（P2-2）、SqliteSaver 跨重启持久化（P2-3）、web_verify 联网核验（P2-4）、端到端链路（P2-5）。

**Architecture:** 存储先行（sessions 落 SQLite + checkpointer 换 SqliteSaver，图代码零改动），随后新增简历域（parse → LLM extract → 后台任务状态机），再改造出题节点为双来源配比分支，最后接入 web_verify（博查搜索 + LLM 判定）。`resume` 与 `verify` 为被 `interview` 依赖的叶子模块，依赖方向保持 `api → interview → llm/store`。

**Tech Stack:** LangGraph `SqliteSaver`（langgraph-checkpoint-sqlite）、SQLite（interview.db / resume.db）、pdfplumber + python-docx（复用 P1 解析）、DeepSeek（抽取/判定）、博查 Web Search API、FastAPI BackgroundTasks + Vue 3。

**上游设计文档：** `docs/superpowers/specs/2026-09-17-p2-resume-persistence-design.md`（§1 范围 / §3 模块结构 / §4 数据模型 / §5 配比 / §6 web_verify / §7 验收 / §8 文档漂移 / §11 实施顺序）

**实施前须知（与设计文档的一致性确认，已核对代码）：**
- 「面试类型（技术面/行为面/综合面）」是 PRD §4 已规划但**代码尚未实现**的字段——设计文档 §2 决策 1「复用现有字段、无新增 UI」应理解为「复用 PRD 已有概念、无新增页面」。本计划新建该字段（technical/behavioral/comprehensive），前端仅在新建会话表单加一个下拉（非新页面）。
- `SqliteSaver` 需要新增依赖 `langgraph-checkpoint-sqlite`（当前环境验证 `from langgraph.checkpoint.sqlite import SqliteSaver` 报 ModuleNotFoundError）。
- P2-3「重启后完整恢复」的隐含前提：KeyStore 是内存态，重启后会话 Key 快照丢失。本计划在 lifespan 用 `.env` 的 LLM_API_KEY 恢复全局 Key，并让 `KeyStore.get` 在会话快照缺失时回退全局 Key（语义与 P0「沿用旧 Key」一致，仅影响重启后场景）。

**提交约定：** 每个 Task 完成后 `git add` 该 Task 涉及的全部文件并提交（pre-commit 钩子会跑 ruff；若临时目录报错，设 `PRE_COMMIT_HOME`、`TMP`、`TEMP` 指向项目 `.tmp/`）。

---

## 文件结构总览

| 文件 | 动作 | 职责 |
|---|---|---|
| `pyproject.toml` | 修改 | 新增 `langgraph-checkpoint-sqlite` 依赖 |
| `app/config.py` | 修改 | 新增 `interview` / `resume` / `verify` 三配置节 + env 覆盖 |
| `.env.example` | 修改 | 新增对应 env 变量示例 |
| `app/store/sessions.py` | 修改 | 新增 `SqliteSessionStore`；SessionMeta/Protocol 增加 `interview_type`、`resume_id` |
| `app/store/checkpointer.py` | 修改 | `create_checkpointer(cfg)` 返回 SqliteSaver |
| `app/main.py` | 修改 | lifespan 换 store/checkpointer，恢复全局 Key，挂载 resume 路由 |
| `app/llm/keys.py` | 修改 | 新增可选填的 verify key（博查，非 sk- 校验） |
| `app/store/resume.py` | 新建 | 简历域 SQLite（resumes / resume_points 两表 + 级联删除） |
| `app/resume/parsers.py` | 新建 | 复用 `app/retrieval/parsers.py` 的 `parse_document` |
| `app/resume/extract.py` | 新建 | LLM 结构化抽取：基本信息/技能/项目经历 + 考点清单 ≥10 项 |
| `app/resume/tasks.py` | 新建 | 后台解析任务（processing→ready/failed 状态机） |
| `app/api/resume.py` | 新建 | 上传 / 列表 / 删除 / 重试 API（≤20MB） |
| `app/api/deps.py` | 修改 | 新增 `get_resume_store` |
| `app/interview/state.py` | 修改 | InterviewState / initial_state 增加 `interview_type`、`resume_id` |
| `app/interview/ratio.py` | 新建 | 配比换算纯函数（`resume_question_indices` / `is_resume_question`） |
| `app/interview/prompts/resume_question.py` | 新建 | 简历出题 prompt（{points_block} 占位） |
| `app/interview/nodes/__init__.py` | 修改 | ask_question 双来源分支 + 降级链；evaluate 接入核验 |
| `app/interview/graph.py` | 修改 | build_graph 注入 resume_store / verify_ctx / cfg |
| `app/api/sessions.py` | 修改 | CreateSessionRequest/SessionResponse 增加 interview_type、resume_id |
| `app/api/settings.py` | 修改 | 新增 GET/PUT `/settings/verify-key` |
| `app/api/chat.py` | 修改 | initial_state 传 resume_id/interview_type；assess 事件加 verification |
| `app/verify/bocha.py` | 新建 | 博查搜索客户端（Key 缺失/失败抛 BochaError） |
| `app/verify/verify.py` | 新建 | 事实性判定 + 核验结论（VerifyContext） |
| `app/interview/prompts/report.py` | 修改 | 新增 {verification_block} 占位 |
| `web/src/api/types.ts` / `client.ts` | 修改 | 简历/核验/搜索 Key 类型与 API 封装 |
| `web/src/views/ResumeView.vue` | 新建 | 简历管理页（上传/列表/删除/重试/状态） |
| `web/src/router/index.ts` | 修改 | 注册简历路由 |
| `web/src/views/HomeView.vue` | 修改 | 新建会话表单：面试类型下拉 + 简历下拉 |
| `web/src/views/ChatView.vue` | 修改 | 评估面板核验徽标 + 信源链接 |
| `web/src/views/SettingsView.vue` | 修改 | 联网搜索 Key 配置 |
| `web/src/views/ReportView.vue` | 修改 | 报告核验汇总展示 |
| `tests/*` | 修改/新建 | 各 Task 对应测试（见各 Task） |
| `tests/acceptance/resumes/` + `resume_gold.json` | 新建 | P2 验收语料 |
| `_acceptance_p2.py` | 新建 | P2-1~P2-5 验收脚本 |
| `docs/prd.md` / `docs/project-status.md` / `CHANGELOG.md` | 修改 | 三处文档漂移修订 + 落档 |

---

## Task 1: 依赖 + 配置扩展（interview / resume / verify 配置节）

**Files:**
- Modify: `pyproject.toml:6-19`（dependencies 列表）
- Modify: `app/config.py`（_DEFAULTS + load_config 环境覆盖）
- Modify: `.env.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_config.py` 追加：

```python
def test_config_has_interview_resume_verify_sections():
    cfg = load_config(config_path=Path("nonexistent.yaml"), env_path=Path("nonexistent.env"))
    assert cfg.interview.db == "data/interview.db"
    assert cfg.resume.db == "data/resume.db"
    assert cfg.resume.upload_dir == "data/resumes"
    assert cfg.resume.max_upload_mb == 20
    assert cfg.resume.ratio.technical == 0.3
    assert cfg.resume.ratio.behavioral == 0.8
    assert cfg.resume.ratio.comprehensive == 0.5
    assert cfg.verify.base_url == "https://api.bochaai.com/v1/web-search"
    assert cfg.verify.api_key == ""
    assert cfg.verify.top_k == 3
    assert cfg.verify.timeout == 10
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_config.py::test_config_has_interview_resume_verify_sections -v`
Expected: FAIL（`AttributeError: 'DictConfig' object has no attribute 'interview'`）

- [ ] **Step 3: 实现配置**

`pyproject.toml` dependencies 追加 `"langgraph-checkpoint-sqlite>=0.2",`（放在 `langgraph>=0.2` 后）。

`app/config.py` `_DEFAULTS` 在 `"retrieval"` 节后追加：

```python
    "interview": {
        "db": "data/interview.db",
    },
    "resume": {
        "db": "data/resume.db",
        "upload_dir": "data/resumes",
        "max_upload_mb": 20,
        "ratio": {"technical": 0.3, "behavioral": 0.8, "comprehensive": 0.5},
    },
    "verify": {
        "enabled": True,
        "base_url": "https://api.bochaai.com/v1/web-search",
        "api_key": "",
        "timeout": 10,
        "top_k": 3,
    },
```

`load_config` 的 `overrides` 追加（在 retrieval 后）：

```python
            "interview": {
                "db": os.getenv("INTERVIEW_DB", base.interview.db),
            },
            "resume": {
                "db": os.getenv("RESUME_DB", base.resume.db),
                "upload_dir": os.getenv("RESUME_UPLOAD_DIR", base.resume.upload_dir),
                "max_upload_mb": _env_int("RESUME_MAX_MB", base.resume.max_upload_mb),
                "ratio": {
                    "technical": float(
                        os.getenv("RESUME_RATIO_TECHNICAL", str(base.resume.ratio.technical))
                    ),
                    "behavioral": float(
                        os.getenv("RESUME_RATIO_BEHAVIORAL", str(base.resume.ratio.behavioral))
                    ),
                    "comprehensive": float(
                        os.getenv("RESUME_RATIO_COMPREHENSIVE", str(base.resume.ratio.comprehensive))
                    ),
                },
            },
            "verify": {
                "enabled": os.getenv("VERIFY_ENABLED", str(base.verify.enabled)).lower()
                in ("1", "true", "yes"),
                "base_url": os.getenv("VERIFY_BASE_URL", base.verify.base_url),
                "api_key": os.getenv("VERIFY_API_KEY", base.verify.api_key),
                "timeout": _env_int("VERIFY_TIMEOUT", base.verify.timeout),
                "top_k": _env_int("VERIFY_TOP_K", base.verify.top_k),
            },
```

`.env.example` 追加：

```
# --- P2 ---
# 会话/检查点 SQLite 库
INTERVIEW_DB=data/interview.db
# 简历域
RESUME_DB=data/resume.db
RESUME_UPLOAD_DIR=data/resumes
RESUME_MAX_MB=20
RESUME_RATIO_TECHNICAL=0.3
RESUME_RATIO_BEHAVIORAL=0.8
RESUME_RATIO_COMPREHENSIVE=0.5
# web_verify 联网搜索（博查，可选填）
VERIFY_ENABLED=true
VERIFY_BASE_URL=https://api.bochaai.com/v1/web-search
VERIFY_API_KEY=
VERIFY_TIMEOUT=10
VERIFY_TOP_K=3
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS（含既有用例 + 新用例）

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml app/config.py .env.example tests/test_config.py
git commit -m "feat(p2): add interview/resume/verify config sections and langgraph-checkpoint-sqlite dep"
```

---

## Task 2: 会话元数据落 SQLite（SqliteSessionStore + interview_type / resume_id）

**Files:**
- Modify: `app/store/sessions.py`（SessionMeta、Protocol、新增 SqliteSessionStore）
- Modify: `app/llm/keys.py`（KeyStore.get 快照缺失回退全局 Key）
- Test: `tests/test_sessions.py`（新增）、`tests/test_keys.py`（新增回退用例）

- [ ] **Step 1: 写失败测试**

在 `tests/test_sessions.py` 追加：

```python
from datetime import datetime

from app.store.sessions import SqliteSessionStore


def _sqlite_store(tmp_path):
    return SqliteSessionStore(tmp_path / "interview.db")


def test_sqlite_create_and_get(tmp_path):
    store = _sqlite_store(tmp_path)
    meta = store.create("s1", "intern", 5, interview_type="technical", resume_id="r-1")
    assert meta["id"] == "s1"
    assert meta["interview_type"] == "technical"
    assert meta["resume_id"] == "r-1"
    got = store.get("s1")
    assert got is not None
    assert got["title"] == "实习面试"
    assert got["status"] == "ongoing"
    assert isinstance(got["created_at"], datetime)


def test_sqlite_persistence_across_reopen(tmp_path):
    """重启模拟：新实例读同一 SQLite 文件，会话完整恢复（P2-3 数据面）。"""
    db = tmp_path / "interview.db"
    SqliteSessionStore(db).create("s1", "fulltime", 10, interview_type="comprehensive")
    store2 = SqliteSessionStore(db)
    got = store2.get("s1")
    assert got is not None
    assert got["interview_type"] == "comprehensive"
    assert got["question_count"] == 10
    assert store2.list()[0]["id"] == "s1"


def test_sqlite_update_and_delete(tmp_path):
    store = _sqlite_store(tmp_path)
    store.create("s1", "intern", 5)
    store.update_status("s1", "finished")
    assert store.get("s1")["status"] == "finished"
    store.delete("s1")
    assert store.get("s1") is None
    assert store.list() == []
```

在 `tests/test_keys.py` 追加：

```python
def test_get_falls_back_to_global_key():
    store = KeyStore()
    store.set_global_key("sk-abc123")
    assert store.get("unknown-session") == "sk-abc123"
    store.set_global_key("sk-new456")
    assert store.get("unknown-session") == "sk-new456"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_sessions.py tests/test_keys.py -v`
Expected: FAIL（`ImportError: cannot import name 'SqliteSessionStore'` / 回退断言失败）

- [ ] **Step 3: 实现**

`app/store/sessions.py`：SessionMeta 增加两个字段、Protocol.create 增加参数、新增 `SqliteSessionStore`（与 `KnowledgeStore` 同模式：单连接 + threading.Lock）：

```python
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
```

`InMemorySessionStore.create` 同步更新签名与字段：

```python
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
```

文件末尾追加：

```python
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
```

`app/llm/keys.py` 的 `get` 改为快照缺失时回退全局 Key（P2-3 重启恢复前提）：

```python
    def get(self, session_id: str) -> str | None:
        """会话快照优先；重启后快照丢失时回退当前全局 Key（P2-3 恢复续聊）。"""
        return self._keys.get(session_id) or self._global_key
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_sessions.py tests/test_keys.py tests/test_api_sessions.py -v`
Expected: PASS（若 test_api_sessions 依赖 KeyStore 语义，确认回退不影响既有用例）

- [ ] **Step 5: 提交**

```bash
git add app/store/sessions.py app/llm/keys.py tests/test_sessions.py tests/test_keys.py
git commit -m "feat(p2): persist session metadata to SQLite with interview_type/resume_id, key fallback for restart recovery"
```

---

## Task 3: checkpointer 换 SqliteSaver（P2-3 完成）

**Files:**
- Modify: `app/store/checkpointer.py`
- Modify: `app/main.py`（lifespan：SqliteSessionStore + create_checkpointer(cfg) + 恢复全局 Key）
- Modify: `app/api/deps.py`（get_session_store 返回类型）
- Test: `tests/test_checkpointer.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_checkpointer.py`：

```python
from omegaconf import OmegaConf

from app.interview.graph import compile_graph
from app.interview.state import initial_state
from app.llm.client import DeepSeekClient
from app.store.checkpointer import create_checkpointer, delete_thread

LLM_CFG = OmegaConf.create(
    {
        "llm": {
            "model_id": "test-model",
            "base_url": "https://api.example.com",
            "timeout": 60,
            "max_retries": 2,
        }
    }
)


def _cfg(db: str) -> OmegaConf:
    return OmegaConf.create({"interview": {"db": db}})


def _fake_llm():
    return DeepSeekClient(LLM_CFG)


def test_sqlite_checkpointer_persists_across_restart(tmp_path):
    """P2-3 核心：图状态落盘，重建 checkpointer 后状态完整恢复。"""
    db = tmp_path / "interview.db"
    c1 = create_checkpointer(_cfg(str(db)))
    graph = compile_graph(_fake_llm(), checkpointer=c1)
    config = {"configurable": {"thread_id": "s-1"}}
    init = initial_state(scene="fulltime", question_count=10, kb_id="kb-1")
    init["_api_key"] = "sk-test123"
    graph.invoke(init, config)

    # 模拟重启：新建 checkpointer 读同一文件
    c2 = create_checkpointer(_cfg(str(db)))
    graph2 = compile_graph(_fake_llm(), checkpointer=c2)
    values = graph2.get_state(config).values
    assert values is not None
    assert values["kb_id"] == "kb-1"
    assert values["question_count"] == 10


def test_sqlite_checkpointer_delete_thread(tmp_path):
    db = tmp_path / "interview.db"
    c1 = create_checkpointer(_cfg(str(db)))
    graph = compile_graph(_fake_llm(), checkpointer=c1)
    config = {"configurable": {"thread_id": "s-2"}}
    graph.invoke(initial_state(scene="intern", question_count=5), config)
    delete_thread(c1, "s-2")
    values = graph.get_state(config).values
    assert not values or not values.get("messages")


def test_checkpointer_fallback_memory():
    """未传 cfg 时回退 MemorySaver（既有 P0 测试兼容）。"""
    c = create_checkpointer()
    from langgraph.checkpoint.memory import MemorySaver

    assert isinstance(c, MemorySaver)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_checkpointer.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'langgraph.checkpoint.sqlite'` 或 create_checkpointer 缺少 cfg 参数）

- [ ] **Step 3: 安装依赖 + 实现**

Run: `uv add "langgraph-checkpoint-sqlite>=0.2"`（若 Step 1 中 pyproject 已手写依赖，此命令会同步 uv.lock）

`app/store/checkpointer.py` 整体替换：

```python
"""checkpointer 抽象：P0 MemorySaver / P2 SqliteSaver 无缝替换。

图代码不感知 P0/P2 实现差异。P2 起默认 SqliteSaver（interview.db），
MemorySaver 仅保留为测试/无配置回退。"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from omegaconf import DictConfig

from app.config import PROJECT_ROOT


def create_checkpointer(cfg: DictConfig | None = None):
    """创建持久化 checkpointer。

    P2：传入 cfg（含 interview.db 路径）时返回 SqliteSaver（跨重启持久化）；
    未传 cfg（纯测试/无配置）时回退 MemorySaver（内存态）。
    """
    if cfg is None:
        return MemorySaver()
    db_path = PROJECT_ROOT / cfg.interview.db
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver.from_conn_string(str(db_path))


def delete_thread(checkpointer, thread_id: str) -> None:
    """删除指定 thread 的状态数据（N-8：删除会话时存储三处同步清）。

    MemorySaver / SqliteSaver 均实现 delete_thread（langgraph 1.x per-thread 接口）。
    """
    checkpointer.delete_thread(thread_id)
```

`app/main.py` lifespan 更新：

```python
    cfg = load_config()
    setup_logging(cfg)

    app.state.config = cfg
    app.state.llm_client = DeepSeekClient(cfg)
    app.state.key_store = KeyStore()
    if cfg.llm.api_key:
        # P2-3：重启后用 .env 的 LLM_API_KEY 恢复全局 Key，会话快照缺失时回退它
        app.state.key_store.set_global_key(cfg.llm.api_key)
    app.state.session_store = SqliteSessionStore(PROJECT_ROOT / cfg.interview.db)
    app.state.knowledge_store = KnowledgeStore(PROJECT_ROOT / cfg.retrieval.kb_db)
    app.state.checkpointer = create_checkpointer(cfg)
```

> **Pre-flight 裁定（见 ledger）**：`ResumeStore` 在 Task 4 才实现，此处不引用；`app.state.resume_store` 的注入延迟到 Task 6（main.py 挂载 resume 路由时一并完成）。

对应 import 更新：`from app.store.checkpointer import create_checkpointer`（不变）、新增 `from app.store.sessions import SqliteSessionStore`（替换 InMemorySessionStore）。`app.store.resume` 的 import 在 Task 6 添加。

`app/api/deps.py`：`get_session_store` 返回类型改为 `SqliteSessionStore`：

```python
from app.store.sessions import SessionMeta, SqliteSessionStore


def get_session_store(request: Request) -> SqliteSessionStore:
    return request.app.state.session_store
```

`get_session` 依赖类型同步改为 `SqliteSessionStore`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_checkpointer.py -v && uv run pytest tests -x -q`
Expected: 新测试 PASS + 全量回归通过（`delete_thread`/`get_state` 接口在 SqliteSaver 与 MemorySaver 间无差异，图代码零改动）

- [ ] **Step 5: 提交**

```bash
git add app/store/checkpointer.py app/main.py app/api/deps.py tests/test_checkpointer.py uv.lock pyproject.toml
git commit -m "feat(p2): switch checkpointer to SqliteSaver for cross-restart persistence (P2-3)"
```

---

## Task 4: 简历域存储（store/resume）

**Files:**
- Create: `app/store/resume.py`
- Test: `tests/test_resume_store.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_resume_store.py`：

```python
from app.store.resume import FAILED, PROCESSING, READY, ResumeStore


def _store(tmp_path):
    return ResumeStore(tmp_path / "resume.db")


def test_add_and_get(tmp_path):
    store = _store(tmp_path)
    r = store.add_resume("r-1", "zhangsan.pdf", "data/resumes/zhangsan.pdf", 1024)
    assert r.id == "r-1"
    assert r.status == PROCESSING
    got = store.get_resume("r-1")
    assert got is not None
    assert got.file_name == "zhangsan.pdf"


def test_update_ready_with_points_and_count(tmp_path):
    store = _store(tmp_path)
    store.add_resume("r-1", "a.md", "data/resumes/a.md", 10)
    store.update_ready(
        "r-1",
        '{"basic": {"name": "张三"}, "skills": [], "projects": []}',
        [
            {"category": "项目", "title": "缓存设计", "detail": "说明", "source_snippet": "原文"},
            {"category": "技能", "title": "Redis", "detail": "说明", "source_snippet": "原文"},
        ],
    )
    got = store.get_resume("r-1")
    assert got.status == READY
    assert got.point_count == 2
    assert '"name": "张三"' in got.profile_json
    points = store.list_points("r-1")
    assert len(points) == 2
    assert points[0].category == "项目"
    assert store.count_points("r-1") == 2


def test_update_failed(tmp_path):
    store = _store(tmp_path)
    store.add_resume("r-1", "a.pdf", "data/resumes/a.pdf", 10)
    store.update_failed("r-1", "PDF 无文字层")
    got = store.get_resume("r-1")
    assert got.status == FAILED
    assert "无文字层" in got.error


def test_delete_resume_cascades_points(tmp_path):
    store = _store(tmp_path)
    store.add_resume("r-1", "a.md", "data/resumes/a.md", 10)
    store.update_ready(
        "r-1", "{}", [{"category": "技能", "title": "T", "detail": "D", "source_snippet": "S"}]
    )
    path = store.delete_resume("r-1")
    assert path == "data/resumes/a.md"
    assert store.get_resume("r-1") is None
    assert store.list_points("r-1") == []
    assert store.count_points("r-1") == 0


def test_list_sorted_by_created_desc(tmp_path):
    store = _store(tmp_path)
    store.add_resume("r-1", "a.md", "data/resumes/a.md", 10)
    store.add_resume("r-2", "b.md", "data/resumes/b.md", 10)
    ids = [r.id for r in store.list_resumes()]
    assert ids == ["r-2", "r-1"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_resume_store.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.store.resume'`）

- [ ] **Step 3: 实现**

新建 `app/store/resume.py`（仿 `store/knowledge.py` 模式）：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_resume_store.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/store/resume.py tests/test_resume_store.py
git commit -m "feat(p2): resume domain SQLite store with point list and cascade delete"
```

---

## Task 5: 简历解析 + LLM 结构化抽取（resume/parsers + extract）

**Files:**
- Create: `app/resume/__init__.py`、`app/resume/parsers.py`
- Create: `app/resume/extract.py`
- Test: `tests/test_resume_parsers.py`、`tests/test_resume_extract.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_resume_extract.py`（parsers 复用 P1 已验证逻辑，重点测 extract 的容错解析与考点构造）：

```python
import json
from types import SimpleNamespace

import pytest

from app.resume.extract import EXTRACT_PROMPT, ExtractedProfile, extract_profile, _parse_profile


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
```

新建 `tests/test_resume_parsers.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_resume_parsers.py tests/test_resume_extract.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.resume'`）

- [ ] **Step 3: 实现**

新建 `app/resume/__init__.py`（空文件）。

新建 `app/resume/parsers.py`：

```python
"""简历解析：复用知识库解析链路（pdfplumber + python-docx，P1 已验证）。

支持 MD/TXT/DOCX/PDF；PDF 无文字层抛 ParseError（后台任务置 failed）。
"""

from app.retrieval.parsers import ParseError, parse_document

__all__ = ["ParseError", "parse_document"]
```

新建 `app/resume/extract.py`：

```python
"""简历结构化抽取：纯文本 → LLM JSON（基本信息 / 技能 / 项目经历 + 考点清单 ≥10 项）。

P2 决策 2/3：轻量组合解析 + LLM 抽取，持久化「素材」而非「题目」——
题面由出题节点实时生成；考点清单独立成表支撑 COUNT 验收与按项出题。
"""

import json
import re
from dataclasses import dataclass

from app.llm.client import DeepSeekClient

EXTRACT_PROMPT = """\
你是简历解析助手，请从候选人的简历文本中抽取结构化信息。

【简历文本】
{resume_text}

请只输出一个 JSON 对象（不要输出其他任何内容），结构如下：
{{
  "basic": {{"name": "...", "title": "...", "years": "...", "email": "...", "phone": "..."}},
  "skills": ["技能1", "技能2", "..."],
  "projects": [
    {{"name": "项目名", "role": "担任角色", "description": "项目简介与职责", "tech": ["技术"], "highlights": ["亮点/难点"]}}
  ],
  "points": [
    {{"category": "项目|技能|基础", "title": "考点标题", "detail": "考点说明（供面试出题）", "source_snippet": "简历原文片段"}}
  ]
}}

要求：
- basic 中缺省的字段填空字符串
- skills 至少 5 项
- points 至少 10 项，覆盖「项目经历 / 技术技能 / 基础知识」三类，按重要性排序
- source_snippet 必须是简历原文片段（≤80 字），供出题时回溯依据
"""


@dataclass
class ExtractedProfile:
    profile_json: str  # basic + skills + projects（JSON 字符串）
    points: list[dict]  # 考点清单（category/title/detail/source_snippet）


def _parse_profile(raw: str) -> dict:
    """容错解析 LLM 输出：支持 ```json 代码块包裹 / 纯 JSON；失败抛 ValueError。"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    payload = m.group(1) if m else raw
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"简历抽取输出不是合法 JSON：{e}") from e
    if not isinstance(data, dict):
        raise ValueError("简历抽取输出不是 JSON 对象")
    return data


def extract_profile(text: str, llm: DeepSeekClient, api_key: str, cfg) -> ExtractedProfile:
    """调用 LLM 抽取结构化简历 + 考点清单（后台任务内执行，完整同步调用）。"""
    raw, _ = llm.complete_sync(
        api_key=api_key, prompt=EXTRACT_PROMPT.format(resume_text=text[:8000])
    )
    data = _parse_profile(raw)
    profile_json = json.dumps(
        {
            "basic": data.get("basic", {}),
            "skills": data.get("skills", []),
            "projects": data.get("projects", []),
        },
        ensure_ascii=False,
    )
    points = [
        {
            "category": _norm_category(p.get("category", "")),
            "title": str(p.get("title", "")).strip(),
            "detail": str(p.get("detail", "")).strip(),
            "source_snippet": str(p.get("source_snippet", "")).strip()[:80],
        }
        for p in (data.get("points") or [])
        if str(p.get("title", "")).strip()
    ]
    return ExtractedProfile(profile_json=profile_json, points=points)


def _norm_category(category: str) -> str:
    """考点分类归一：项目/技能/基础，未知归入基础。"""
    if category in ("项目", "技能", "基础"):
        return category
    return "基础"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_resume_parsers.py tests/test_resume_extract.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/resume/ tests/test_resume_parsers.py tests/test_resume_extract.py
git commit -m "feat(p2): resume parsing (reuse P1) and LLM structured extraction with point list"
```

---

## Task 6: 简历后台任务 + 简历 API（P2-1 完成）

**Files:**
- Create: `app/resume/tasks.py`
- Create: `app/api/resume.py`
- Modify: `app/main.py`（挂载 resume_router）
- Modify: `app/api/deps.py`（get_resume_store）
- Test: `tests/test_resume_tasks.py`、`tests/test_resume_api.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_resume_tasks.py`：

```python
from types import SimpleNamespace

from app.resume.tasks import process_resume_background
from app.store.resume import FAILED, READY, ResumeStore


def _store(tmp_path):
    return ResumeStore(tmp_path / "resume.db")


def _llm(profile):
    return SimpleNamespace(
        complete_sync=lambda api_key, prompt, callbacks=None: (
            '{"basic": {}, "skills": [], "projects": [], "points": [{"category": "技能",'
            ' "title": "Redis", "detail": "缓存", "source_snippet": "使用 Redis"}]}',
            {},
        )
    )


def test_process_success(tmp_path, monkeypatch):
    (tmp_path / "data" / "resumes").mkdir(parents=True)
    (tmp_path / "data" / "resumes" / "a.md").write_text("# 张三\n技能：Python", encoding="utf-8")
    monkeypatch.setattr("app.resume.tasks.PROJECT_ROOT", tmp_path)
    store = _store(tmp_path)
    record = store.add_resume("r-1", "a.md", "data/resumes/a.md", 10)

    process_resume_background(store, record, _llm(None), "sk-test123", None)

    got = store.get_resume("r-1")
    assert got.status == READY
    assert got.point_count == 1
    assert store.count_points("r-1") == 1


def test_process_failure_sets_failed(tmp_path, monkeypatch):
    (tmp_path / "data" / "resumes").mkdir(parents=True)
    (tmp_path / "data" / "resumes" / "a.pdf").write_bytes(b"%PDF-fake")
    monkeypatch.setattr("app.resume.tasks.PROJECT_ROOT", tmp_path)
    store = _store(tmp_path)
    record = store.add_resume("r-1", "a.pdf", "data/resumes/a.pdf", 10)

    def _boom(*a, **k):
        raise ValueError("PDF 无文字层")

    monkeypatch.setattr("app.resume.tasks.extract_profile", _boom)
    process_resume_background(store, record, _llm(None), "sk-test123", None)

    got = store.get_resume("r-1")
    assert got.status == FAILED
    assert "无文字层" in got.error
```

新建 `tests/test_resume_api.py`：

```python
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.resume import router
from app.config import PROJECT_ROOT
from app.store.resume import FAILED, READY, ResumeStore


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.resume.PROJECT_ROOT", tmp_path)
    application = FastAPI()
    application.include_router(router)
    application.state.resume_store = ResumeStore(tmp_path / "resume.db")
    application.state.llm_client = _FakeLLM()
    application.state.key_store = _FakeKeys()
    application.state.config = _cfg()
    return application


def _cfg():
    from omegaconf import OmegaConf

    return OmegaConf.create({"resume": {"upload_dir": "data/resumes", "max_upload_mb": 20}})


class _FakeLLM:
    def complete_sync(self, api_key, prompt, callbacks=None):
        return (
            '{"basic": {}, "skills": ["Python"], "projects": [],'
            ' "points": [{"category": "技能", "title": "Python", "detail": "语法",'
            ' "source_snippet": "精通 Python"}]}',
            {},
        )


class _FakeKeys:
    def get_global_key(self):
        return "sk-test123"


def test_upload_and_status_flow(app, tmp_path):
    client = TestClient(app)
    (tmp_path / "data" / "resumes").mkdir(parents=True, exist_ok=True)
    resp = client.post(
        "/resumes",
        files={"file": ("a.md", io.BytesIO("# 张三\n技能：Python".encode()), "text/markdown")},
    )
    assert resp.status_code == 200
    rid = resp.json()["resume"]["id"]
    status = resp.json()["resume"]["status"]

    assert status in ("processing", "ready")
    # 后台任务同步完成 → 直接轮询到 ready
    got = client.get("/resumes").json()
    assert len(got) == 1
    assert got[0]["id"] == rid


def test_upload_rejects_too_large(app, tmp_path):
    client = TestClient(app)
    (tmp_path / "data" / "resumes").mkdir(parents=True, exist_ok=True)
    big = b"x" * (21 * 1024 * 1024)
    resp = client.post("/resumes", files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")})
    assert resp.status_code == 400
    assert "20MB" in resp.json()["detail"]


def test_upload_rejects_bad_ext(app, tmp_path):
    client = TestClient(app)
    resp = client.post(
        "/resumes", files={"file": ("a.exe", io.BytesIO(b"x"), "application/octet-stream")}
    )
    assert resp.status_code == 400


def test_delete_resume(app, tmp_path):
    (tmp_path / "data" / "resumes").mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    up = client.post(
        "/resumes", files={"file": ("a.md", io.BytesIO(b"# x"), "text/markdown")}
    ).json()["resume"]
    rid = up["id"]
    resp = client.delete(f"/resumes/{rid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert client.get("/resumes").json() == []
```

> 注：`app/api/resume.py` 的上传端点使用 `BackgroundTasks`；TestClient 在同步上下文会先执行完后台任务再返回响应，因此上传后直接可见 ready 或 processing→ready 已轮询到位。若采用 `asyncio.to_thread` 的 async 任务，TestClient 中行为等价（事件循环内同步执行）。如上传端点返回 processing 而测试期望 ready，可将断言改为「轮询 GET /resumes 直到 status == ready」（上限 2s）。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_resume_tasks.py tests/test_resume_api.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.resume.tasks'` / `app.api.resume`）

- [ ] **Step 3: 实现**

新建 `app/resume/tasks.py`：

```python
"""后台简历解析任务：解析 → LLM 抽取 → 落库 + 状态流转（processing→ready/failed）。

由 FastAPI BackgroundTasks 经 asyncio.to_thread 调度（不阻塞事件循环）；
失败保留原文件（R6），状态置 failed，重试接口重新入队。
LLM 抽取使用全局 API Key（无会话上下文）。
"""

import asyncio
from pathlib import Path

from loguru import logger

from app.config import PROJECT_ROOT
from app.llm.client import DeepSeekClient
from app.resume.extract import extract_profile
from app.resume.parsers import parse_document
from app.store.resume import Resume, ResumeStore


def _abs_path(record: Resume) -> Path:
    return PROJECT_ROOT / record.path


def process_resume_background(
    store: ResumeStore,
    record: Resume,
    llm: DeepSeekClient,
    api_key: str,
    cfg,
) -> None:
    """解析并抽取单份简历；任何异常置 failed（保留原文件供重试）。"""
    try:
        if not api_key:
            raise ValueError("全局 API Key 未设置，无法解析简历")
        text = parse_document(_abs_path(record))
        profile = extract_profile(text, llm, api_key, cfg)
        store.update_ready(record.id, profile.profile_json, profile.points)
        logger.info(
            "resume ready: {name} r={rid} points={n}",
            name=record.file_name,
            rid=record.id,
            n=len(profile.points),
        )
    except Exception as e:  # noqa: BLE001 - 后台任务兜底：异常写入状态，不向外抛
        store.update_failed(record.id, str(e)[:500])
        logger.error("resume process failed: {name} err={err}", name=record.file_name, err=repr(e))


async def process_resume_async(
    store: ResumeStore,
    record: Resume,
    llm: DeepSeekClient,
    api_key: str,
    cfg,
) -> None:
    await asyncio.to_thread(process_resume_background, store, record, llm, api_key, cfg)
```

新建 `app/api/resume.py`：

```python
"""简历管理 API：上传 / 列表 / 删除 / 重试（P2-1）。

澄清决策（2026-09-17）：简历解析走轻量组合（pdfplumber + python-docx）+ LLM 抽取；
上传即返 processing，后台任务解析，前端轮询至 ready/failed；
删除级联清 DB 行（含考点清单）+ 原文件；支持 PDF/DOCX/MD/TXT，≤20MB。
"""

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from loguru import logger
from pydantic import BaseModel

from app.api.deps import get_key_store, get_llm_client, get_resume_store
from app.config import PROJECT_ROOT
from app.llm.client import DeepSeekClient
from app.llm.keys import KeyStore
from app.resume.tasks import process_resume_async
from app.store.resume import FAILED, PROCESSING, Resume, ResumeStore

router = APIRouter(prefix="/resumes", tags=["resumes"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # PRD §6 N-9 修订：简历 ≤20MB
SUPPORTED_EXTS = {".md", ".txt", ".docx", ".pdf"}
_SAFE_NAME = re.compile(r"[^\w.\-]", flags=re.UNICODE)


def _sanitize_name(name: str) -> str:
    base = Path(name).name.strip()
    return _SAFE_NAME.sub("_", base) or "resume"


def _resume_dir(request: Request) -> Path:
    base = PROJECT_ROOT / request.app.state.config.resume.upload_dir
    base.mkdir(parents=True, exist_ok=True)
    return base


@router.post("")
async def upload_resume(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile,
    store: ResumeStore = Depends(get_resume_store),
    llm: DeepSeekClient = Depends(get_llm_client),
    key_store: KeyStore = Depends(get_key_store),
) -> dict:
    """上传简历（≤20MB，md/txt/docx/pdf）：保存原文件 → processing → 后台解析抽取。"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTS:
        supported = "/".join(sorted(e.lstrip(".") for e in SUPPORTED_EXTS))
        raise HTTPException(status_code=400, detail=f"仅支持 {supported} 格式")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="文件超过 20MB 上限")

    resume_id = f"r-{uuid.uuid4().hex[:8]}"
    dest_dir = _resume_dir(request)
    stored = dest_dir / f"{resume_id}_{_sanitize_name(file.filename or 'resume')}"
    stored.write_bytes(data)

    record = store.add_resume(
        resume_id, file.filename or stored.name, str(stored.relative_to(PROJECT_ROOT)), len(data)
    )
    background.add_task(
        process_resume_async,
        store,
        record,
        llm,
        key_store.get_global_key(),
        request.app.state.config,
    )
    logger.info(
        "resume uploaded: {name} size={size} → processing", name=record.file_name, size=record.size
    )
    return {"resume": record.to_dict()}


@router.get("")
async def list_resumes(
    store: ResumeStore = Depends(get_resume_store),
) -> list[dict]:
    """列出全部简历（含状态，按创建时间倒序）。"""
    return [r.to_dict() for r in store.list_resumes()]


@router.post("/{resume_id}/retry")
async def retry_resume(
    resume_id: str,
    request: Request,
    background: BackgroundTasks,
    store: ResumeStore = Depends(get_resume_store),
    llm: DeepSeekClient = Depends(get_llm_client),
    key_store: KeyStore = Depends(get_key_store),
) -> dict:
    """失败简历重试：failed → processing → 重新解析（原文件保留，R6）。"""
    record = _get_or_404(store, resume_id)
    if record.status != FAILED:
        raise HTTPException(status_code=400, detail="仅失败状态的简历可重试")
    store.update_processing(resume_id)
    background.add_task(
        process_resume_async,
        store,
        record,
        llm,
        key_store.get_global_key(),
        request.app.state.config,
    )
    return {"resume": store.get_resume(resume_id).to_dict()}


@router.delete("/{resume_id}")
async def delete_resume(
    resume_id: str,
    store: ResumeStore = Depends(get_resume_store),
) -> dict:
    """删除简历：DB 行（含考点清单 CASCADE）+ 原文件物理删（R5）。"""
    record = _get_or_404(store, resume_id)
    path = store.delete_resume(resume_id)
    if path:
        (PROJECT_ROOT / path).unlink(missing_ok=True)
    logger.info("resume deleted: {name} r={rid}", name=record.file_name, rid=resume_id)
    return {"status": "deleted", "id": resume_id}


def _get_or_404(store: ResumeStore, resume_id: str) -> Resume:
    record = store.get_resume(resume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="简历不存在")
    return record
```

`app/api/deps.py` 新增：

```python
from app.store.resume import ResumeStore


def get_resume_store(request: Request) -> ResumeStore:
    return request.app.state.resume_store
```

`app/main.py`：
1. import `from app.api.resume import router as resume_router`，`from app.store.resume import ResumeStore`（后者补齐 Task 3 延迟的注入）
2. lifespan 中 `app.state.knowledge_store = ...` 之后追加：

```python
    app.state.resume_store = ResumeStore(PROJECT_ROOT / cfg.resume.db)
```

3. `app.include_router(resume_router, prefix="/api")`

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_resume_tasks.py tests/test_resume_api.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/resume/tasks.py app/api/resume.py app/api/deps.py app/main.py tests/test_resume_tasks.py tests/test_resume_api.py
git commit -m "feat(p2): resume background processing task and CRUD API (P2-1)"
```

---

## Task 7: 双来源出题（interview_type 字段 + 配比换算 + ask_question 分支）

**Files:**
- Create: `app/interview/ratio.py`
- Create: `app/interview/prompts/resume_question.py`
- Modify: `app/interview/state.py`（interview_type / resume_id）
- Modify: `app/interview/nodes/__init__.py`（ask_question 双来源 + 降级链）
- Modify: `app/interview/graph.py`（注入 resume_store / cfg）
- Modify: `app/api/sessions.py`（CreateSessionRequest / SessionResponse）
- Modify: `app/api/chat.py`（initial_state 传 resume_id / interview_type；skip 路径传新参数）
- Test: `tests/test_ratio.py`（新建）、`tests/test_nodes.py`（更新）、`tests/test_graph.py`（更新）、`tests/test_api_sessions.py`（更新）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_ratio.py`：

```python
from app.interview.ratio import is_resume_question, resume_question_indices


def test_resume_indices_technical_10q():
    """技术面 10 题、简历占比 0.3 → 3 道简历题，均匀交错在前中后段。"""
    indices = resume_question_indices(10, 0.3)
    assert indices == [1, 4, 7]
    assert len(indices) == 3


def test_resume_indices_comprehensive_10q():
    indices = resume_question_indices(10, 0.5)
    assert indices == [1, 3, 5, 7, 9]


def test_resume_indices_behavioral_10q():
    indices = resume_question_indices(10, 0.8)
    assert len(indices) == 8
    assert 5 not in indices  # 知识库题号
    assert 10 not in indices


def test_resume_indices_ratio_zero():
    assert resume_question_indices(10, 0.0) == []


def test_resume_indices_ratio_one():
    assert resume_question_indices(10, 1.0) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_is_resume_question():
    assert is_resume_question(0, 10, 0.3) is True  # 第 1 题
    assert is_resume_question(1, 10, 0.3) is False  # 第 2 题
    assert is_resume_question(6, 10, 0.3) is True  # 第 7 题
```

在 `tests/test_nodes.py` 追加（先看该文件现有 helper，保持一致；以下为独立新增）：

```python
from types import SimpleNamespace

from app.interview.nodes import ask_question_node
from app.interview.state import initial_state


def _fake_llm(raw='{"question": "请介绍你的项目", "topic": "项目经历"}'):
    return SimpleNamespace(complete_sync=lambda api_key, prompt, callbacks=None: (raw, {}))


def _resume_store(points=3):
    store = SimpleNamespace()
    store.list_points = lambda resume_id: [
        {
            "id": f"rp-{i}",
            "resume_id": "r-1",
            "seq": i,
            "category": "项目",
            "title": f"考点{i}",
            "detail": f"详情{i}",
            "source_snippet": f"原文{i}",
        }
        for i in range(points)
    ]
    return store


def _cfg(ratio=0.3):
    from omegaconf import OmegaConf

    return OmegaConf.create({"resume": {"ratio": {"technical": ratio}}})


def test_ask_resume_question_when_resume_round(tmp_path):
    """技术面第 1 题（简历题号 1）：优先走简历考点出题，注入考点块。"""
    state = initial_state(scene="fulltime", question_count=10, kb_id="kb-1")
    state.update(
        {
            "question_index": 0,
            "interview_type": "technical",
            "resume_id": "r-1",
            "_api_key": "sk-test123",
        }
    )
    llm = _fake_llm()
    updates = ask_question_node(
        state, llm, retrieval=None, resume_store=_resume_store(), cfg=_cfg(0.3)
    )
    # 简历出题：无 citations，但 reference_block 含考点信息
    assert updates["_citations"] == []
    assert "考点0" in updates["_reference_block"] or "简历" in updates["_reference_block"]


def test_ask_kb_question_when_not_resume_round():
    """技术面第 2 题（知识库题号）：无简历注入，P1 行为不变（retrieval=None → 纯通用出题）。"""
    state = initial_state(scene="fulltime", question_count=10, kb_id="kb-1")
    state.update(
        {
            "question_index": 1,
            "interview_type": "technical",
            "resume_id": "r-1",
            "_api_key": "sk-test123",
        }
    )
    updates = ask_question_node(
        state, _fake_llm(), retrieval=None, resume_store=_resume_store(), cfg=_cfg(0.3)
    )
    assert updates["_reference_block"] == ""
    assert updates["_citations"] == []


def test_ask_resume_degrades_to_generic_without_resume():
    """简历题号但简历不可用（无 resume_id）→ 降级纯通用出题，不报错。"""
    state = initial_state(scene="fulltime", question_count=10)
    state.update({"question_index": 0, "interview_type": "technical", "_api_key": "sk-test123"})
    updates = ask_question_node(
        state, _fake_llm(), retrieval=None, resume_store=_resume_store(), cfg=_cfg(0.3)
    )
    assert updates["current_question"].startswith("请介绍你的项目")
    assert updates["_reference_block"] == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_ratio.py tests/test_nodes.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.interview.ratio'`；`TypeError: ask_question_node() got an unexpected keyword argument 'resume_store'`；`TypeError: initial_state() got an unexpected keyword argument 'interview_type'`）

- [ ] **Step 3: 实现**

新建 `app/interview/ratio.py`：

```python
"""双来源出题配比：按面试类型换算简历题落位（P2 决策 1/7，方案 A 单节点分支）。

落位规则（P2 设计 §5）：简历题均匀交错分散在前中后段，取整余数补知识库侧；
计数可逐题核对（P2-2 验收：技术面 3 道 / 行为面 8 道 / 综合面 5 道，按 10 题计）。
"""

RESUME_RATIO_DEFAULTS = {"technical": 0.3, "behavioral": 0.8, "comprehensive": 0.5}


def resume_question_indices(question_count: int, resume_ratio: float) -> list[int]:
    """返回 1-based 简历题号列表（均匀交错分散，覆盖前中后段）。

    R = int(N*ratio + 0.5)（四舍五入，夹在 [0, N]）；第 i 个简历题落在 floor(i*N/R)+1。
    例：N=10, R=3 → [1,4,7]；N=10, R=5 → [1,3,5,7,9]；N=10, R=8 → [1,2,3,4,6,7,8,9]。
    """
    n = int(question_count)
    r = min(n, max(0, int(n * resume_ratio + 0.5)))
    if r == 0:
        return []
    return [int(i * n / r) + 1 for i in range(r)]


def is_resume_question(question_index: int, question_count: int, resume_ratio: float) -> bool:
    """当前题（0-based question_index）是否走简历出题。"""
    return (question_index + 1) in resume_question_indices(question_count, resume_ratio)
```

新建 `app/interview/prompts/resume_question.py`：

```python
"""简历出题 prompt：基于考点清单出题（P2 决策 3——题面实时生成，非题库命中）。"""

RESUME_QUESTION = """\
你是「AI 面试官」，正在进行一场基于候选人简历的模拟面试。

【当前题号】第 {question_index} 题，共 {question_count} 题
【面试类型】{interview_type}
【已问主题】{asked_topics}（避免重复）

【简历考点清单】（含原文片段，供出题回溯）
{points_block}

出题要求：
1. 从上方考点清单中选择一个尚未问过的考点出题，题目应能考察候选人的真实经历与掌握程度
2. 题面应贴近简历实际（技术选型、实现细节、难点复盘），避免泛泛而谈
3. 难度匹配当前档位 {difficulty_stage}（1=入门 2=基础 3=进阶 4=深入）
4. 只输出题干本身，不要编号、前缀、解释

输出格式：
先直接输出题干本身（一段话，不要编号、前缀、解释），
然后在最后单独一行输出主题标签：
【主题】主题标签\
"""
```

`app/interview/state.py`：InterviewState 增加字段 + initial_state 增加参数：

```python
    kb_id: str | None  # P1 关联知识库 ID（会话级，出题检索范围）
    resume_id: str | None  # P2 关联简历 ID（会话级，双来源出题）
    interview_type: str  # P2 面试类型：technical / behavioral / comprehensive
```

`initial_state` 签名与 body：

```python
def initial_state(
    scene: str = "fulltime",
    question_count: int = 10,
    skip_opening: bool = False,
    kb_id: str | None = None,
    resume_id: str | None = None,
    interview_type: str = "technical",
) -> InterviewState:
    return InterviewState(
        messages=[],
        scene=scene,
        question_count=question_count,
        question_index=0,
        current_question=None,
        hints_used=0,
        followups=0,
        scores=[],
        status="ongoing",
        skip_opening=skip_opening,
        difficulty_stage=1,
        question_bank=[],
        asked_ids=[],
        answered_qa=[],
        kb_id=kb_id,
        resume_id=resume_id,
        interview_type=interview_type,
    )
```

`app/interview/nodes/__init__.py` 改造：

- import 追加：`from app.interview.prompts.resume_question import RESUME_QUESTION`、`from app.interview.ratio import is_resume_question`
- 新增辅助函数：

```python
def _build_points_block(points: list[dict]) -> str:
    """构造简历考点区块：带 [n] 序号 + 原文片段（出题依据）。"""
    lines = ["【简历考点清单】"]
    for i, p in enumerate(points, start=1):
        snippet = p["source_snippet"].strip().replace("\n", " ")
        lines.append(f"[{i}]（{p['category']}）{p['title']}：{p['detail']}（原文：{snippet}）")
    return "\n".join(lines)
```

- `ask_question_node` 签名扩展 + 双来源分支：

```python
def ask_question_node(
    state: InterviewState,
    llm: DeepSeekClient,
    callbacks: list | None = None,
    retrieval=None,
    resume_store=None,
    cfg=None,
) -> dict:
    """出题：双来源（简历考点 / 知识库检索）按面试类型配比混合（P2 决策 1/7）。

    落位：题号命中简历题集合 → 简历出题；否则知识库检索出题（P1 逻辑）。
    降级链：简历不可用 → 知识库；知识库不可用 → 纯通用（P0）；两者皆无 → 纯通用。
    callbacks: 透传给 LLM 用于逐 token 流式（skip 出题不走图时的转发）。
    retrieval: RetrievalContext 或 None。resume_store: ResumeStore 或 None。cfg: 应用配置。
    """
    scene = state.get("scene", "fulltime")
    template = ASK_QUESTION.get(scene, ASK_QUESTION["fulltime"])

    qi = state.get("question_index", 0) + 1  # 1-based
    qcount = state.get("question_count", 10)
    interview_type = state.get("interview_type", "technical")
    ratio = 0.3
    if cfg is not None:
        ratio = float(getattr(cfg.resume.ratio, interview_type, 0.3))
    resume_id = state.get("resume_id")

    points: list[dict] = []
    resume_usable = resume_store is not None and resume_id is not None
    if resume_usable:
        points = resume_store.list_points(resume_id)
        resume_usable = bool(points)

    use_resume = resume_usable and is_resume_question(qi - 1, qcount, ratio)
    kb_id = state.get("kb_id")

    reference_block = ""
    citations: list[dict] = []
    level: str | None = None

    if use_resume:
        # 简历出题：考点块写入 reference_block（评估节点复用做事实校准）
        reference_block = _build_points_block(points)
        prompt = RESUME_QUESTION.format(
            question_index=qi,
            question_count=qcount,
            interview_type=_interview_type_label(interview_type),
            asked_topics=_get_topic_list(state),
            points_block=reference_block,
            difficulty_stage=state.get("difficulty_stage", 1),
        )
    else:
        if kb_id and retrieval is not None:
            result = retrieve(
                query=_build_search_query(state),
                kb_id=kb_id,
                cfg=retrieval.cfg,
                qdrant=retrieval.qdrant,
                es=retrieval.es,
                embedding=retrieval.embedding,
            )
            if result.level != DECLINE and result.citations:
                reference_block = _build_reference_block(result)
                citations = [_citation_dict(c) for c in result.citations[:MAX_CITATIONS]]
                level = result.level
        prompt = template.format(
            question_index=qi,
            question_count=qcount,
            difficulty_stage=state.get("difficulty_stage", 1),
            asked_topics=_get_topic_list(state),
            reference_block=reference_block,
        )

    raw, _ = llm.complete_sync(api_key=state["_api_key"], prompt=prompt, callbacks=callbacks)
    question, topic = _parse_question(raw)
    if level == FALLBACK:
        question = f"{_FALLBACK_NOTE}\n{question}"
    updates = {
        "current_question": question,
        "hints_used": 0,
        "followups": 0,
        "messages": [AIMessage(content=question)],
        "_topic": topic,
        "_citations": citations,  # 无条件写入：未命中为 []
        "_reference_block": reference_block,  # 无条件写入：未命中为 ""
    }
    return updates
```

- 新增辅助：

```python
def _interview_type_label(interview_type: str) -> str:
    return {
        "technical": "技术面",
        "behavioral": "行为面",
        "comprehensive": "综合面",
    }.get(interview_type, "技术面")
```

`app/interview/graph.py`：

```python
def build_graph(llm: DeepSeekClient, retrieval=None, resume_store=None, cfg=None) -> StateGraph:
    ...
    graph.add_node(
        "ask_question",
        partial(
            ask_question_node, llm=llm, retrieval=retrieval, resume_store=resume_store, cfg=cfg
        ),
    )
```

`compile_graph` 透传新参数：`def compile_graph(llm, checkpointer=None, retrieval=None, resume_store=None, cfg=None)` → `build_graph(llm, retrieval, resume_store, cfg).compile(checkpointer=checkpointer)`。

`app/api/sessions.py`：

```python
class CreateSessionRequest(BaseModel):
    scene: str = Field(..., pattern="^(intern|fulltime)$")
    question_count: int = Field(default=10, ge=5, le=30)
    skip_opening: bool = False
    kb_id: str | None = None
    resume_id: str | None = None
    interview_type: str = Field(default="technical", pattern="^(technical|behavioral|comprehensive)$")


class SessionResponse(BaseModel):
    ...
    kb_id: str | None = None
    resume_id: str | None = None
    interview_type: str = "technical"


def _to_response(meta: SessionMeta) -> SessionResponse:
    return SessionResponse(
        ...
        kb_id=meta.get("kb_id"),
        resume_id=meta.get("resume_id"),
        interview_type=meta.get("interview_type", "technical"),
    )


async def create_session(...):
    meta = store.create(
        session_id, req.scene, req.question_count, req.skip_opening,
        req.kb_id, req.resume_id, req.interview_type,
    )
```

`app/api/chat.py` 首次调用与 skip 路径：

```python
                    init = initial_state(
                        scene=session["scene"],
                        question_count=session["question_count"],
                        skip_opening=session.get("skip_opening", False),
                        kb_id=session.get("kb_id"),
                        resume_id=session.get("resume_id"),
                        interview_type=session.get("interview_type", "technical"),
                    )
```

skip 出题路径（调用 ask_question_node 处）追加参数：

```python
                    task = asyncio.create_task(
                        asyncio.to_thread(
                            ask_question_node,
                            state,
                            llm,
                            handler,
                            request.app.state.retrieval,
                            request.app.state.resume_store,
                            request.app.state.config,
                        )
                    )
```

`app/main.py`：`compile_graph(..., retrieval=retrieval_ctx, resume_store=app.state.resume_store, cfg=cfg)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_ratio.py tests/test_nodes.py tests/test_graph.py tests/test_api_sessions.py -v && uv run ruff format app/ tests/ && uv run ruff check app/ tests/`
Expected: 新用例 PASS + 既有用例回归通过 + ruff 干净

- [ ] **Step 5: 提交**

```bash
git add app/interview/ratio.py app/interview/prompts/resume_question.py app/interview/state.py app/interview/nodes/__init__.py app/interview/graph.py app/api/sessions.py app/api/chat.py app/main.py tests/test_ratio.py tests/test_nodes.py tests/test_graph.py tests/test_api_sessions.py
git commit -m "feat(p2): dual-source question generation with interview-type ratio and degrade chain (P2-2)"
```

---

## Task 8: web_verify 后端（bocha + verify + evaluate 接入 + settings Key）

**Files:**
- Create: `app/verify/__init__.py`、`app/verify/bocha.py`、`app/verify/verify.py`
- Modify: `app/llm/keys.py`（verify key 字段）
- Modify: `app/api/settings.py`（GET/PUT /settings/verify-key）
- Modify: `app/interview/nodes/__init__.py`（evaluate_node 接入 VerifyContext）
- Modify: `app/interview/graph.py`（注入 verify_ctx）
- Modify: `app/api/chat.py`（assess 事件加 verification）
- Modify: `app/api/deps.py`（get_key_store 已存在，无新增；verify 由 VerifyContext 持有）
- Modify: `app/main.py`（构建 VerifyContext）
- Test: `tests/test_bocha.py`、`tests/test_verify.py`（新建）、`tests/test_nodes.py` / `tests/test_chat.py`（更新）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_bocha.py`：

```python
import json

import pytest

from app.verify.bocha import BochaClient, BochaError, SearchResult


def _payload(pages):
    return {"code": 200, "data": {"webPages": {"value": pages}}}


def test_search_returns_results(monkeypatch):
    client = BochaClient("bocha-key")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                _payload(
                    [
                        {"name": "Redis 官网", "url": "https://redis.io", "snippet": "Redis 简介"},
                        {"name": "缓存穿透", "url": "https://x.com/1", "summary": "解决方案"},
                    ]
                )
            ).encode()

    captured = {}

    def _urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data)
        captured["auth"] = req.headers["Authorization"]
        return _Resp()

    monkeypatch.setattr("app.verify.bocha.urllib.request.urlopen", _urlopen)
    results = client.search("缓存穿透", count=2)
    assert len(results) == 2
    assert results[0].title == "Redis 官网"
    assert results[0].url == "https://redis.io"
    assert captured["auth"] == "Bearer bocha-key"
    assert captured["body"]["count"] == 2


def test_search_without_key_raises():
    client = BochaClient("")
    with pytest.raises(BochaError):
        client.search("什么")


def test_search_network_error_raises(monkeypatch):
    client = BochaClient("key")

    def _boom(*a, **k):
        raise OSError("timeout")

    monkeypatch.setattr("app.verify.bocha.urllib.request.urlopen", _boom)
    with pytest.raises(BochaError):
        client.search("什么")
```

新建 `tests/test_verify.py`：

```python
import json
from types import SimpleNamespace

from app.verify.verify import VerifyContext


def _llm(raw):
    return SimpleNamespace(complete_sync=lambda api_key, prompt, callbacks=None: (raw, {}))


def _bocha(results):
    return SimpleNamespace(search=lambda query, count=3: results)


def _cfg():
    from omegaconf import OmegaConf

    return OmegaConf.create({"verify": {"top_k": 3, "enabled": True}})


class _Keys:
    def __init__(self, key="bocha-key"):
        self._key = key

    def get_verify_key(self):
        return self._key


def test_skip_when_no_key():
    ctx = VerifyContext(_llm("{}"), _cfg(), _Keys(key=""))
    assert ctx.verify("sk-llm", "你好") is None


def test_skip_when_not_factual():
    judge = json.dumps({"is_factual": False, "claims": []})
    ctx = VerifyContext(_llm(judge), _cfg(), _Keys())
    assert ctx.verify("sk-llm", "我觉得自己很适合这个岗位") is None


def test_verified_flow():
    judge = json.dumps({"is_factual": True, "claims": ["Redis 支持持久化"]})
    verdict = json.dumps({"status": "verified", "reason": "信源一致"})

    class _SeqLLM:
        def __init__(self):
            self._calls = 0

        def complete_sync(self, api_key, prompt, callbacks=None):
            self._calls += 1
            return (judge if self._calls == 1 else verdict, {})

    bocha = _bocha(
        [SimpleNamespace(title="Redis 持久化", url="https://redis.io", snippet="支持 RDB/AOF")]
    )
    ctx = VerifyContext(_SeqLLM(), _cfg(), _Keys())
    v = ctx.verify("sk-llm", "Redis 支持持久化")
    assert v is not None
    assert v.status == "verified"
    assert v.sources[0]["url"] == "https://redis.io"
    assert v.to_dict()["claims"] == ["Redis 支持持久化"]


def test_search_failure_degrades_to_unconfirmed():
    judge = json.dumps({"is_factual": True, "claims": ["X 公司成立于 2001 年"]})

    class _Boom:
        def search(self, query, count=3):
            raise RuntimeError("网络失败")

    ctx = VerifyContext(_llm(judge), _cfg(), _Keys(), bocha=_Boom())
    v = ctx.verify("sk-llm", "X 公司成立于 2001 年")
    assert v is not None
    assert v.status == "unconfirmed"
    assert v.skipped is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_bocha.py tests/test_verify.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.verify'`）

- [ ] **Step 3: 实现**

新建 `app/verify/__init__.py`（空文件）。

新建 `app/verify/bocha.py`：

```python
"""博查 Web Search 客户端（国内备案、中文友好；Key 可选填，未配置优雅降级）。

失败语义：Key 缺失 / 网络异常 / 非 200 → 抛 BochaError（上层静默跳过核验）。
"""

import json
import urllib.request
from dataclasses import dataclass

from loguru import logger

DEFAULT_BASE_URL = "https://api.bochaai.com/v1/web-search"


class BochaError(RuntimeError):
    """搜索失败（Key 缺失 / 网络 / 非 200）。"""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class BochaClient:
    """同步搜索客户端（核验在后台线程执行，无需 async）。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout

    def search(self, query: str, count: int = 3) -> list[SearchResult]:
        if not self._api_key:
            raise BochaError("联网搜索 Key 未配置")
        body = json.dumps({"query": query, "count": count, "freshness": "noLimit"}).encode("utf-8")
        req = urllib.request.Request(
            self._base_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - 网络/超时/解析统一转业务异常
            raise BochaError(f"搜索请求失败：{e!r}") from e
        pages = ((payload.get("data") or {}).get("webPages") or {}).get("value") or []
        results = [
            SearchResult(
                title=str(p.get("name", "")),
                url=str(p.get("url", "")),
                snippet=str(p.get("snippet") or p.get("summary") or "")[:200],
            )
            for p in pages
        ][:count]
        logger.info("bocha search done: q={query} hits={n}", query=query[:40], n=len(results))
        return results
```

新建 `app/verify/verify.py`：

```python
"""事实性陈述联网核验：LLM 判定 → 博查搜索 → LLM 二次判定。

结论三态：verified（已核验）/ uncertain（存疑）/ unconfirmed（无法确认）。
降级与边界（P2 设计 §6）：未配置 Key / 请求失败 / 超时 → 静默跳过（不阻断评估）。
核验结果并入 SSE assess 事件 payload（不新增事件类型）。
"""

import json
import re
from dataclasses import dataclass, field

from loguru import logger

from app.llm.client import DeepSeekClient
from app.verify.bocha import BochaClient, BochaError

JUDGE_PROMPT = """\
你是事实性陈述判定助手。判断以下候选人回答是否包含可联网核验的事实性陈述（如公司、日期、
技术特性、公开数据等）。主观感受、观点、个人经历不算事实性陈述。

【回答】
{answer}

只输出一个 JSON 对象：
{{"is_factual": true/false, "claims": ["事实性陈述1", "事实性陈述2"]}}

要求：
- claims 仅列事实性陈述（≤3 条），每条是独立的、可检索的短句
- 没有事实性陈述时 is_factual=false，claims 为空数组
"""

VERIFY_PROMPT = """\
你是事实核验助手。基于搜索结果判断以下事实性陈述是否成立。

【陈述】
{claims}

【搜索结果】
{search_block}

只输出一个 JSON 对象：
{{"status": "verified|uncertain|unconfirmed", "reason": "判定理由（结合信源说明）"}}

判定规则：
- 搜索结果显示有信源支持陈述 → verified
- 搜索结果显示存在矛盾或证据不足 → uncertain
- 搜索失败或完全没有相关信源 → unconfirmed
"""


@dataclass
class Verification:
    status: str  # verified / uncertain / unconfirmed
    reason: str
    claims: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)  # [{title, url, snippet}]
    skipped: bool = False  # 跳过核验（Key 缺失等）

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "claims": self.claims,
            "sources": self.sources,
            "skipped": self.skipped,
        }


class VerifyContext:
    """评估节点核验注入组件（图构建时注入，测试可替换为 fake）。"""

    def __init__(self, llm: DeepSeekClient, cfg, key_store, bocha=None) -> None:
        self._llm = llm
        self._cfg = cfg
        self._key_store = key_store
        self._bocha = bocha or BochaClient(
            key_store.get_verify_key() or "",
            base_url=cfg.verify.base_url,
            timeout=float(cfg.verify.timeout),
        )

    def verify(self, api_key: str, answer: str) -> Verification | None:
        """核验一条回答；返回 None 表示跳过（无 Key / 非事实性）。

        异常（搜索失败/LLM 失败）一律降级：返回 unconfirmed 或 None，不向评估抛错。
        """
        verify_key = self._key_store.get_verify_key()
        if not verify_key:
            return None  # 未配置搜索 Key → 静默跳过（设计 §6 降级）
        if not answer or not answer.strip():
            return None

        try:
            judge_raw, _ = self._llm.complete_sync(
                api_key=api_key, prompt=JUDGE_PROMPT.format(answer=answer[:2000])
            )
            judge = _parse_json(judge_raw)
        except Exception as e:  # noqa: BLE001 - 判定失败视为无事实性陈述
            logger.warning("verify judge failed: {err}", err=repr(e))
            return None

        if not judge.get("is_factual"):
            return None
        claims = [str(c).strip() for c in (judge.get("claims") or []) if str(c).strip()][:3]
        if not claims:
            return None

        sources: list[dict] = []
        for claim in claims:
            try:
                for r in self._bocha.search(claim, count=int(self._cfg.verify.top_k)):
                    if r.url:
                        sources.append({"title": r.title, "url": r.url, "snippet": r.snippet})
            except BochaError as e:
                logger.warning("verify search failed: {err}", err=repr(e))
        if not sources:
            return Verification(status="unconfirmed", reason="搜索无可用信源", claims=claims)

        search_block = "\n".join(
            f"[{i + 1}] {s['title']}（{s['url']}）：{s['snippet']}" for i, s in enumerate(sources)
        )
        try:
            verdict_raw, _ = self._llm.complete_sync(
                api_key=api_key,
                prompt=VERIFY_PROMPT.format(
                    claims="\n".join(f"- {c}" for c in claims), search_block=search_block
                ),
            )
            verdict = _parse_json(verdict_raw)
            status = verdict.get("status")
            if status not in ("verified", "uncertain", "unconfirmed"):
                status = "unconfirmed"
            reason = str(verdict.get("reason", "")).strip() or "无法确认"
        except Exception as e:  # noqa: BLE001 - 二次判定失败降级
            logger.warning("verify verdict failed: {err}", err=repr(e))
            status, reason = "unconfirmed", "核验判定失败"
        return Verification(status=status, reason=reason, claims=claims, sources=sources)


def _parse_json(raw: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    payload = m.group(1) if m else raw
    data = json.loads(payload)
    return data if isinstance(data, dict) else {}
```

`app/llm/keys.py` 增加 verify key（可选填，博查 key 非 sk- 前缀，仅校验非空）：

```python
def __init__(self) -> None:
    self._global_key: str | None = None
    self._keys: dict[str, str] = {}
    self._verify_key: str | None = None  # P2：联网搜索 Key（博查，可选填）


def set_verify_key(self, api_key: str) -> None:
    if not api_key or not api_key.strip():
        self._verify_key = None
        return
    self._verify_key = api_key.strip()


def get_verify_key(self) -> str | None:
    return self._verify_key


def get_verify_masked(self) -> str:
    return mask_secret(self._verify_key) if self._verify_key else ""
```

`app/api/settings.py` 新增端点：

```python
class VerifyKeyRequest(BaseModel):
    verify_key: str = Field(default="", max_length=256)


@router.put("/verify-key", response_model=KeyResponse)
async def set_verify_key(
    req: VerifyKeyRequest,
    key_store: KeyStore = Depends(get_key_store),
) -> KeyResponse:
    """设置联网搜索 Key（博查，可选填；传空串清除）。"""
    key_store.set_verify_key(req.verify_key.strip())
    return KeyResponse(
        masked_key=key_store.get_verify_masked(), is_set=key_store.get_verify_key() is not None
    )


@router.get("/verify-key", response_model=KeyResponse)
async def get_verify_key(
    key_store: KeyStore = Depends(get_key_store),
) -> KeyResponse:
    """获取联网搜索 Key 掩码（不返回明文）。"""
    key = key_store.get_verify_key()
    return KeyResponse(masked_key=key_store.get_verify_masked(), is_set=key is not None)
```

`app/interview/nodes/__init__.py` 的 evaluate_node 接入：

```python
def evaluate_node(state: InterviewState, llm: DeepSeekClient, verify_ctx=None) -> dict:
    """评估：LLM 打分 + 追问判断 + （P2）事实性陈述联网核验。"""
    scene = state.get("scene", "fulltime")
    answer = _extract_answer(state)
    prompt = EVALUATE.format(...)  # 不变
    raw, _ = llm.complete_sync(api_key=state["_api_key"], prompt=prompt)
    try:
        parsed = json.loads(raw)
        ...
    score_entry: Score = {...}
    if state.get("_citations"):
        score_entry["citations"] = state["_citations"]
    verification = None
    if verify_ctx is not None:
        try:
            verification = verify_ctx.verify(state["_api_key"], answer)
        except Exception as e:  # noqa: BLE001 - 核验异常不阻断评估
            logger.warning("evaluate verify skipped: {err}", err=repr(e))
    score_entry["verification"] = verification.to_dict() if verification else None
    ...
```

`app/interview/graph.py`：`build_graph(llm, retrieval=None, resume_store=None, cfg=None, verify_ctx=None)`，evaluate 节点 `partial(evaluate_node, llm=llm, verify_ctx=verify_ctx)`；`compile_graph` 透传。

`app/main.py`：构建 VerifyContext 并传入：

```python
from app.verify.verify import VerifyContext
...
    verify_ctx = VerifyContext(app.state.llm_client, cfg, app.state.key_store)
    app.state.compiled_graph = compile_graph(
        app.state.llm_client, app.state.checkpointer,
        retrieval=retrieval_ctx, resume_store=app.state.resume_store,
        cfg=cfg, verify_ctx=verify_ctx,
    )
```

`app/api/chat.py` 的 assess 事件加 verification：

```python
                        yield _sse_event(
                            "assess",
                            {
                                "dimensions": last.get("dimensions", {}),
                                "comment": last.get("comment", ""),
                                "score": last.get("score", 0),
                                "citations": last.get("citations", []),
                                "verification": last.get("verification"),
                            },
                        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_bocha.py tests/test_verify.py tests/test_nodes.py tests/test_chat.py tests/test_settings.py -v && uv run ruff format app/ tests/ && uv run ruff check app/ tests/`
Expected: PASS + ruff 干净

> 注意：`tests/test_nodes.py` 中既有的 evaluate 相关用例若直接调用 `evaluate_node(state, llm)`，新参数 `verify_ctx=None` 有默认值，不受影响。

- [ ] **Step 5: 提交**

```bash
git add app/verify/ app/llm/keys.py app/api/settings.py app/interview/nodes/__init__.py app/interview/graph.py app/api/chat.py app/main.py tests/test_bocha.py tests/test_verify.py
git commit -m "feat(p2): web_verify backend (bocha search + LLM verdict) wired into evaluate node (P2-4)"
```

---

## Task 9: 前端·简历管理页 + 会话关联（P2-1/P2-2 UI）

**Files:**
- Modify: `web/src/api/types.ts`、`web/src/api/client.ts`
- Create: `web/src/views/ResumeView.vue`
- Modify: `web/src/router/index.ts`
- Modify: `web/src/views/HomeView.vue`（面试类型下拉 + 简历下拉）

- [ ] **Step 1: 更新 API 类型与封装**

`web/src/api/types.ts` 追加：

```ts
export type InterviewType = 'technical' | 'behavioral' | 'comprehensive'
export type ResumeStatus = 'processing' | 'ready' | 'failed'

export interface Resume {
  id: string
  file_name: string
  size: number
  status: ResumeStatus
  error: string | null
  point_count: number | null
  created_at: string
}
```

`SessionMeta` / `CreateSessionRequest` 追加字段：

```ts
export interface SessionMeta {
  ...
  kb_id?: string
  resume_id?: string
  interview_type: InterviewType
}

export interface CreateSessionRequest {
  scene: Scene
  question_count?: number
  skip_opening?: boolean
  kb_id?: string
  resume_id?: string
  interview_type?: InterviewType
}
```

`AssessPayload` 追加核验类型：

```ts
export interface Verification {
  status: 'verified' | 'uncertain' | 'unconfirmed'
  reason: string
  claims: string[]
  sources: { title: string; url: string; snippet: string }[]
  skipped: boolean
}

export interface AssessPayload {
  ...
  verification?: Verification | null
}
```

`web/src/api/client.ts` 追加：

```ts
export async function listResumes(): Promise<Resume[]> {
  return request<Resume[]>('/api/resumes')
}

export async function uploadResume(file: File): Promise<{ resume: Resume }> {
  const form = new FormData()
  form.append('file', file)
  return request<{ resume: Resume }>('/api/resumes', { method: 'POST', body: form })
}

export async function deleteResume(id: string): Promise<void> {
  await request(`/api/resumes/${id}`, { method: 'DELETE' })
}

export async function retryResume(id: string): Promise<{ resume: Resume }> {
  return request<{ resume: Resume }>(`/api/resumes/${id}/retry`, { method: 'POST' })
}

export async function getVerifyKey(): Promise<KeyInfo> {
  return request<KeyInfo>('/api/settings/verify-key')
}

export async function setVerifyKey(verifyKey: string): Promise<KeyInfo> {
  return request<KeyInfo>('/api/settings/verify-key', {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ verify_key: verifyKey }),
  })
}
```

（import 列表同步加入 `Resume`。）

- [ ] **Step 2: 新建简历管理页**

创建 `web/src/views/ResumeView.vue`（结构仿 KnowledgeView.vue：上传区 + 列表卡片 + 状态徽标 + 删除/重试按钮 + 轮询 processing→ready/failed）：

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { deleteResume, listResumes, retryResume, uploadResume } from '../api/client'
import type { Resume } from '../api/types'

const resumes = ref<Resume[]>([])
const uploading = ref(false)
const error = ref('')
const fileInput = ref<HTMLInputElement>()

const STATUS_LABEL: Record<string, string> = {
  processing: '解析中',
  ready: '就绪',
  failed: '失败',
}

async function load() {
  resumes.value = await listResumes()
}

function poll() {
  if (resumes.value.some((r) => r.status === 'processing')) {
    setTimeout(async () => {
      await load()
      poll()
    }, 1500)
  }
}

async function onUpload() {
  const file = fileInput.value?.files?.[0]
  if (!file) return
  uploading.value = true
  error.value = ''
  try {
    await uploadResume(file)
    if (fileInput.value) fileInput.value.value = ''
    await load()
    poll()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '上传失败'
  } finally {
    uploading.value = false
  }
}

async function onRetry(id: string) {
  await retryResume(id)
  await load()
  poll()
}

async function onDelete(id: string) {
  if (!confirm('删除后不可恢复，确定删除该简历？')) return
  await deleteResume(id)
  await load()
}
</script>

<template>
  <div class="page">
    <h2>简历管理</h2>
    <p class="hint">上传简历（PDF / DOCX / MD / TXT，≤20MB），自动解析并抽取考点清单，供面试出题使用。</p>

    <div class="upload-row">
      <input ref="fileInput" type="file" accept=".pdf,.docx,.md,.txt" />
      <button :disabled="uploading" @click="onUpload">{{ uploading ? '上传中…' : '上传简历' }}</button>
    </div>
    <p v-if="error" class="err">{{ error }}</p>

    <div v-if="resumes.length" class="cards">
      <div v-for="r in resumes" :key="r.id" class="card">
        <div class="row">
          <strong>{{ r.file_name }}</strong>
          <span class="badge" :class="r.status">{{ STATUS_LABEL[r.status] }}</span>
        </div>
        <div class="meta">
          {{ (r.size / 1024).toFixed(1) }} KB · 考点 {{ r.point_count ?? '-' }} 项 ·
          {{ new Date(r.created_at).toLocaleString() }}
        </div>
        <div v-if="r.status === 'failed' && r.error" class="err">{{ r.error }}</div>
        <div class="actions">
          <button v-if="r.status === 'failed'" @click="onRetry(r.id)">重试</button>
          <button class="danger" @click="onDelete(r.id)">删除</button>
        </div>
      </div>
    </div>
    <p v-else class="empty">暂无简历，上传一份开始。</p>
  </div>
</template>

<style scoped>
.page { padding: 24px; max-width: 860px; margin: 0 auto; }
.hint { color: #888; font-size: 13px; }
.upload-row { display: flex; gap: 12px; margin: 16px 0; align-items: center; }
.cards { display: flex; flex-direction: column; gap: 12px; }
.card { border: 1px solid var(--border, #e5e7eb); border-radius: 12px; padding: 14px 16px; }
.row { display: flex; justify-content: space-between; align-items: center; }
.meta { color: #888; font-size: 12px; margin-top: 6px; }
.actions { display: flex; gap: 8px; margin-top: 10px; }
.badge { font-size: 12px; padding: 2px 10px; border-radius: 999px; }
.badge.ready { background: #dcfce7; color: #166534; }
.badge.processing { background: #fef9c3; color: #854d0e; }
.badge.failed { background: #fee2e2; color: #991b1b; }
.err { color: #b91c1c; font-size: 12px; margin-top: 6px; }
.empty { color: #aaa; margin-top: 24px; }
.danger { color: #b91c1c; border-color: #fecaca; }
</style>
```

- [ ] **Step 3: 注册路由**

`web/src/router/index.ts`：新增 `/resumes` 路由（懒加载，命名与现有页面一致）。

```ts
import ResumeView from '../views/ResumeView.vue'
...
  {
    path: '/resumes',
    name: 'resumes',
    component: ResumeView,
  },
```

并在导航菜单（App.vue 或路由所在导航组件）加入「简历」入口。若导航在 `App.vue` 或 `HomeView.vue` 中维护，同步加一个 `RouterLink to="/resumes"` 菜单项。

- [ ] **Step 4: 新建会话表单增加面试类型 + 简历下拉**

`web/src/views/HomeView.vue` 的新建会话表单（scene / question_count / skip_opening / kb_id 之后）追加：

```html
<div class="field">
  <label>面试类型</label>
  <select v-model="form.interview_type">
    <option value="technical">技术面</option>
    <option value="behavioral">行为面</option>
    <option value="comprehensive">综合面</option>
  </select>
</div>
<div class="field">
  <label>关联简历（可选）</label>
  <select v-model="form.resume_id">
    <option value="">不关联</option>
    <option v-for="r in resumes" :key="r.id" :value="r.id" :disabled="r.status !== 'ready'">
      {{ r.file_name }}{{ r.status === 'ready' ? '' : '（解析中/失败）' }}
    </option>
  </select>
</div>
```

script 部分：`form` 增加 `interview_type: 'technical'`、`resume_id: ''`；`createSession` 调用时过滤空值：

```ts
const form = ref({
  scene: 'fulltime',
  question_count: 10,
  skip_opening: false,
  kb_id: '',
  resume_id: '',
  interview_type: 'technical',
})
const resumes = ref<Resume[]>([])

async function loadResumes() {
  resumes.value = await listResumes()
}

async function onCreate() {
  const req: CreateSessionRequest = {
    scene: form.value.scene,
    question_count: form.value.question_count,
    skip_opening: form.value.skip_opening,
    interview_type: form.value.interview_type,
  }
  if (form.value.kb_id) req.kb_id = form.value.kb_id
  if (form.value.resume_id) req.resume_id = form.value.resume_id
  const session = await createSession(req)
  router.push(`/chat/${session.id}`)
}

onMounted(loadResumes)
```

- [ ] **Step 5: 构建验证**

Run: `cd web && npm run build`
Expected: 构建成功（tsc 无类型错误 + vite 产物生成）

- [ ] **Step 6: 提交**

```bash
git add web/src/api/types.ts web/src/api/client.ts web/src/views/ResumeView.vue web/src/router/index.ts web/src/views/HomeView.vue
git commit -m "feat(p2): resume management page and session link (interview type + resume select)"
```

---

## Task 10: 前端·核验展示 + 搜索 Key 配置 + 报告汇总（P2-4 UI）

**Files:**
- Modify: `app/interview/prompts/report.py`（{verification_block} 占位）
- Modify: `app/interview/nodes/__init__.py`（report_node 汇总核验）
- Modify: `web/src/views/ChatView.vue`（评估面板核验徽标 + 信源链接）
- Modify: `web/src/views/SettingsView.vue`（搜索 Key 配置）
- Modify: `web/src/views/ReportView.vue`（报告核验汇总展示）

- [ ] **Step 1: 后端：报告注入核验汇总**

`app/interview/prompts/report.py` 的 REPORT 模板在合适位置加占位（保持其余结构不变）：

```python
{verification_block}
```

`report_node` 构造汇总块并填充：

```python
def _build_verification_block(scores: list) -> str:
    """汇总每题核验结论供报告生成（无核验时返回空串）。"""
    rows = []
    for s in scores:
        v = s.get("verification") or {}
        if not v or v.get("skipped"):
            continue
        status_label = {"verified": "已核验", "uncertain": "存疑", "unconfirmed": "无法确认"}.get(
            v.get("status"), "无法确认"
        )
        rows.append(f"- {s.get('question', '')[:60]}：{status_label}（{v.get('reason', '')}）")
    return "\n".join(rows)


def report_node(state: InterviewState, llm: DeepSeekClient) -> dict:
    scene = state.get("scene", "fulltime")
    verification_block = _build_verification_block(state.get("scores", []))
    prompt = REPORT.format(
        scene=scene,
        question_count=state.get("question_count", 10),
        scores=state.get("scores", []),
        verification_block=verification_block,
    )
    ...
    # _report_summary 的 verified 字段填充为核验结论列表（前端 ReportView 直接消费）
    summary = _parse_report_summary(raw) or {}
    verified = []
    for s in state.get("scores", []):
        v = s.get("verification") or {}
        if v and not v.get("skipped") and v.get("status") == "verified":
            verified.append({"question": s.get("question", ""), "reason": v.get("reason", "")})
    summary["verified"] = verified if verified else None
    return {
        "status": "finished",
        "messages": [AIMessage(content=raw)],
        "_report": raw,
        "_report_summary": summary,
    }
```

> 注意：`_parse_report_summary` 已预留 `verified` 键（P0 返回 None），此处直接覆盖。

- [ ] **Step 2: 前端·ChatView 评估面板核验展示**

`web/src/views/ChatView.vue` 评估面板（已有 dimensions / comment / citations 折叠区）追加核验区（定位到 assess 渲染处，插入）：

```html
<div v-if="assess.verification" class="verify-box">
  <div class="verify-head">
    <span class="verify-badge" :class="assess.verification.status">
      {{
        assess.verification.status === 'verified' ? '已核验' :
        assess.verification.status === 'uncertain' ? '存疑' : '无法确认'
      }}
    </span>
    <span v-if="assess.verification.skipped" class="verify-skip">（已跳过核验）</span>
  </div>
  <p v-if="assess.verification.reason" class="verify-reason">{{ assess.verification.reason }}</p>
  <ul v-if="assess.verification.sources.length" class="verify-sources">
    <li v-for="(src, i) in assess.verification.sources" :key="i">
      <a :href="src.url" target="_blank" rel="noopener">{{ src.title || src.url }}</a>
    </li>
  </ul>
</div>
```

样式（跟随既有 Soft UI 变量）：

```css
.verify-box { margin-top: 10px; padding: 10px 12px; border-radius: 10px; background: #f8fafc; font-size: 12px; }
.verify-badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; }
.verify-badge.verified { background: #dcfce7; color: #166534; }
.verify-badge.uncertain { background: #fef9c3; color: #854d0e; }
.verify-badge.unconfirmed { background: #f1f5f9; color: #475569; }
.verify-sources { margin: 6px 0 0; padding-left: 16px; }
.verify-sources a { color: #6d28d9; }
```

script：`assess` 响应式对象已存在（SSE `assess` 事件写入），无需改动事件处理，`verification` 字段随 payload 自动进入。

- [ ] **Step 3: 前端·SettingsView 搜索 Key 配置**

`web/src/views/SettingsView.vue` 在 API Key 区块后追加「联网搜索 Key（博查，可选填）」区块（仿现有 API Key 表单：输入 + 保存 + 掩码回显）：

```html
<div class="card">
  <h3>联网搜索 Key（博查）</h3>
  <p class="hint">可选填。用于评估环节对事实性回答进行联网核验；未配置时自动跳过核验。</p>
  <div class="row">
    <input
      v-model="verifyKey"
      type="password"
      :placeholder="verifyMasked || '输入博查 API Key（留空保存可清除）'"
    />
    <button @click="saveVerifyKey">保存</button>
  </div>
  <p v-if="verifyMasked && !verifyKey" class="hint">当前已配置：{{ verifyMasked }}</p>
</div>
```

script：

```ts
const verifyKey = ref('')
const verifyMasked = ref('')

async function loadVerifyKey() {
  const info = await getVerifyKey()
  verifyMasked.value = info.masked_key
}

async function saveVerifyKey() {
  const info = await setVerifyKey(verifyKey.value.trim())
  verifyMasked.value = info.masked_key
  verifyKey.value = ''
}

onMounted(loadVerifyKey)
```

- [ ] **Step 4: 前端·ReportView 核验汇总展示**

`web/src/views/ReportView.vue` 摘要区（已有 verified 字段的预留渲染逻辑）确认渲染 `summary.verified`：若无渲染逻辑，在摘要区追加：

```html
<div v-if="report.summary?.verified?.length" class="card">
  <h3>事实核验</h3>
  <ul>
    <li v-for="(v, i) in report.summary.verified" :key="i">{{ v.question }} — {{ v.reason }}</li>
  </ul>
</div>
```

（若该文件已存在 verified 渲染，Step 跳过。）

- [ ] **Step 5: 构建 + 后端回归验证**

Run: `cd web && npm run build && cd .. && uv run pytest tests -q`
Expected: 前端构建成功 + 全量 pytest 通过

- [ ] **Step 6: 提交**

```bash
git add app/interview/prompts/report.py app/interview/nodes/__init__.py web/src/views/ChatView.vue web/src/views/SettingsView.vue web/src/views/ReportView.vue
git commit -m "feat(p2): verification badges in assess panel, search key config, report verify summary"
```

---

## Task 11: 端到端验收 + 语料 + 文档落档（P2-5）

**Files:**
- Create: `tests/acceptance/resumes/`（20 份简历语料）、`tests/acceptance/resume_gold.json`
- Create: `_acceptance_p2.py`
- Modify: `docs/prd.md`（§4 F3 / §6 P2-2 / §6 N-9 / §8 移除待确认项）
- Modify: `docs/project-status.md`、`CHANGELOG.md`

- [ ] **Step 1: 生成验收语料**

新建 `tests/acceptance/resumes/`，自建 20 份简历（MD 为主 + 少量 PDF/DOCX 混合；PDF 用真实文字层文件；覆盖不同字段完整度与版式）。文件命名 `resume_01.md` … `resume_20.md`（PDF/DOCX 对应 `resume_03.pdf`、`resume_07.docx` 等）。每份简历结构统一：基本信息 / 技能清单（≥6 项）/ 2–3 段项目经历（含技术选型、难点）/ 工作经历。内容为虚构人物，避免真实个人信息。

新建 `tests/acceptance/resume_gold.json`：每题记录 `resume_id`、`file_name`、关键字段（`name`、核心技能 ≥5）、`points` 关键词列表（≥10 个考点关键词），作为 P2-1/P2-2 判定依据。结构：

```json
{
  "resume_01": {
    "file_name": "resume_01.md",
    "basic": {"name": "张三"},
    "skills": ["Python", "Redis", "MySQL"],
    "points": ["缓存设计", "Redis", "MySQL 索引", "高并发"]
  }
}
```

- [ ] **Step 2: 编写验收脚本 `_acceptance_p2.py`**

仿 P1 脚本 `_acceptance_p1.py` 结构（`--only` / `--keep` / 全量串行），实现：

- **P2-1 简历解析成功率**：`POST /api/resumes` 上传 20 份 → 轮询全部 ready/failed → 断言 ready ≥ 18（≥90%）；对 ready 简历调用抽取结果（store 读取）校验 `profile_json` 关键字段命中率 ≥85%（按 `resume_gold.json` 的 name/skills 关键词比对，关键字段命中率 = 命中字段数 / 金标字段数）。
- **P2-2 考点清单与配比出题**：每份 ready 简历 `count_points ≥ 10`；按配比规则断言（纯逻辑复算）：技术面 10 题简历题号 = `[1,4,7]`（3 道）、行为面 10 题 = 8 道、综合面 10 题 = 5 道；对 3 道简历来源题调用 ask_question_node 输出，≥80% 与考点清单关键词对应（LLM 判定或关键词交集）。
- **P2-3 跨重启恢复**：真实服务重启后端进程（子进程启动 uvicorn → 建会话 + 对话 2 轮 → kill → 重启 → GET /sessions 列表与 /messages 历史恢复；或进程内模拟：关闭 store/checkpointer 重建实例读同一 db 文件）。
- **P2-4 web_verify**：配置搜索 Key（mock BochaClient 或真实 Key）→ 提交含事实性陈述的回答 → 断言 SSE `assess` 事件 payload 含 `verification` 且 `status ∈ {verified, uncertain, unconfirmed}`、`sources` 非空（Key 缺失时断言 skipped/无 verification）。
- **P2-5 端到端**：上传简历 → 建会话（resume_id + kb_id + interview_type）→ 对话至报告 → 报告含核验/引用展示字段。

脚本头部 argparse：`--only P2-1,P2-2`、`--keep`（保留数据不清理）。日志输出「标准 / 实测 / 结论」表。脚本以 `uv run python _acceptance_p2.py` 执行，不参与 pytest 收集（位于项目根，testpaths 限 tests/）。

- [ ] **Step 3: 执行验收**

Run: `uv run python _acceptance_p2.py`
Expected: P2-1~P2-5 全部 PASS（或记录 FAIL 项待用户裁决，沿用 P1 处理流程）

- [ ] **Step 4: PRD 三处文档漂移修订**

`docs/prd.md`：
1. §4 F3：「Docling 解析 → 结构化抽取 → 自动构建题库（≥10 题）」→「轻量解析（pdfplumber + python-docx）→ LLM 结构化抽取（基本信息/技能/项目经历）+ 考点清单 ≥10 项；题面由出题节点实时生成」
2. §6 P2-2：「每份简历 ≥10 题且 ≥80% 相关」→「考点清单 ≥10 项；按配比产生的简历来源题目（技术面 3 道 / 行为面 8 道 / 综合面 5 道，按 10 题计）≥80% 与清单对应且相关」
3. §6 N-9：「上传 ≤10MB」→ 分档：知识库 ≤50MB / 简历 ≤20MB
4. §8 待确认项移除「P2 web_verify 触发方式」（已确认：评估节点自动核验）

- [ ] **Step 5: 文档落档**

`docs/project-status.md`：更新「当前阶段」为 P2 完成、已完成事项追加 P2 条目。
`CHANGELOG.md`：追加 P2 交付记录（含验收结果、P2-1~P2-5 结论、文档漂移修订说明），遵循既有格式（日期 · 标题 · 描述 · 变更 · 验证结果 · 结构更新）。

- [ ] **Step 6: 全量回归 + 提交**

Run: `uv run pytest tests -q && uv run ruff check app/ tests/ && cd web && npm run build && cd .. && uv run python _acceptance_p1.py`
Expected: 全量 pytest 通过 + ruff 干净 + 前端构建成功 + P1 验收复跑无回归（P1-3/P1-4 搁置项按既有记录维持 FAIL 不影响）

```bash
git add tests/acceptance/resumes/ tests/acceptance/resume_gold.json _acceptance_p2.py docs/prd.md docs/project-status.md CHANGELOG.md
git commit -m "feat(p2): acceptance corpus/script P2-1~P2-5, doc drift fixes, changelog"
```

---

## 自检记录（writing-plans Self-Review）

**1. 设计文档覆盖核对：**
- §3 模块结构：parsers/extract/tasks ✓（Task 5/6）、store/resume ✓（Task 4）、store/sessions ✓（Task 2）、checkpointer ✓（Task 3）、api/resume ✓（Task 6）、nodes 改造 ✓（Task 7/8）、verify/bocha ✓（Task 8）
- §4 数据模型：resumes/resume_points ✓（Task 4）、sessions+resume_id ✓（Task 2）、checkpoints 关联 thread_id ✓（Task 3）
- §5 配比与降级链 ✓（Task 7 ratio.py + 分支 + 降级用例）
- §6 web_verify 流程 + 降级 ✓（Task 8）；SSE assess 并入 ✓；前端徽标/信源 ✓（Task 10）；F6 配置页 Key ✓（Task 10）
- §7 验收五项 ✓（Task 11）；语料 20 份 + resume_gold.json ✓（Task 11）
- §8 文档漂移 3 处 + §8 待确认项移除 ✓（Task 11）
- §9 测试策略：单测/集成/端到端/回归 ✓（各 Task 测试 + Task 11）
- §11 实施顺序 ✓（1 存储 → 2 简历域 → 3 双来源 → 4 web_verify → 5 端到端）

**2. 占位符扫描：** 无「TBD/TODO/implement later」；前端两个大文件（ChatView/SettingsView/ReportView）给出精确修改点 + 完整代码块；后端全部给出完整代码。

**3. 类型一致性：**
- `create_checkpointer(cfg)` 在 Task 3 定义，main.py 调用一致；`delete_thread` 签名不变。
- `initial_state(..., resume_id=None, interview_type="technical")` 在 Task 7 定义，chat.py 调用一致。
- `ask_question_node(state, llm, callbacks=None, retrieval=None, resume_store=None, cfg=None)` Task 7 定义，graph.py / chat.py / tests 调用一致。
- `evaluate_node(state, llm, verify_ctx=None)` Task 8 定义，graph.py 一致。
- `ResumeStore.update_ready(resume_id, profile_json, points)` Task 4 定义，tasks.py / api 调用一致。
- `Verification.to_dict()` Task 8 定义，nodes 消费一致；前端 `Verification` 类型与 SSE payload 字段名一致（status/reason/claims/sources/skipped）。
- SessionStore Protocol 与 SqliteSessionStore / InMemorySessionStore 签名在 Task 2 同步更新。

**4. 计划外的实现前确认项（已在文首记录）：** interview_type 字段新建（PRD 已规划）、langgraph-checkpoint-sqlite 依赖、KeyStore.get 回退全局 Key（P2-3 恢复前提）。
