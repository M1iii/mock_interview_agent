"""FastAPI 应用入口：lifespan 初始化 + 路由挂载 + 前端静态托管。"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.knowledge import router as knowledge_router
from app.api.resume import router as resume_router
from app.api.sessions import router as sessions_router
from app.api.settings import router as settings_router
from app.config import PROJECT_ROOT, load_config
from app.interview.graph import compile_graph
from app.llm.client import DeepSeekClient
from app.llm.keys import KeyStore
from app.logging import logger, setup_logging
from app.retrieval.embedding import OpenAICompatEmbedding
from app.retrieval.es import ESManager
from app.retrieval.qdrant import QdrantManager
from app.retrieval.retrieve import RetrievalContext
from app.store.checkpointer import create_checkpointer, scrub_history_db
from app.store.knowledge import KnowledgeStore
from app.store.resume import ResumeStore
from app.store.sessions import SqliteSessionStore
from app.verify.verify import VerifyContext

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    setup_logging(cfg)

    app.state.config = cfg
    # 启动自愈：清除修复前旧版写入的明文 API Key（幂等）。在任何存储连接建立前执行，
    # 避免并发写锁；失败仅告警，不阻断启动。
    try:
        scrub_stats = scrub_history_db(PROJECT_ROOT / cfg.interview.db)
        if any(scrub_stats.values()):
            logger.info(
                "history scrub done: deleted_writes={dw} rewritten_checkpoints={rc}",
                dw=scrub_stats["deleted_writes"],
                rc=scrub_stats["rewritten_checkpoints"],
            )
    except Exception as e:  # noqa: BLE001 - 自愈失败不阻断启动
        logger.warning("history scrub skipped: {err}", err=repr(e))
    app.state.llm_client = DeepSeekClient(cfg)
    app.state.key_store = KeyStore()
    if cfg.llm.api_key:
        # P2-3：重启后用 .env 的 LLM_API_KEY 恢复全局 Key，会话快照缺失时回退它
        app.state.key_store.set_global_key(cfg.llm.api_key)
    if cfg.verify.get("api_key"):
        # 修复轮：同样用 .env 的 VERIFY_API_KEY 种子搜索 Key（运行期仍可被配置页覆盖）
        app.state.key_store.set_verify_key(cfg.verify.api_key)
    app.state.session_store = SqliteSessionStore(PROJECT_ROOT / cfg.interview.db)
    app.state.knowledge_store = KnowledgeStore(PROJECT_ROOT / cfg.retrieval.kb_db)
    app.state.resume_store = ResumeStore(PROJECT_ROOT / cfg.resume.db)
    app.state.checkpointer = create_checkpointer(cfg)
    # P1 检索服务：懒加载 manager，启动不探测不阻塞；缺失时知识库功能降级
    app.state.qdrant = QdrantManager(cfg)
    app.state.es = ESManager(cfg)
    app.state.embedding = OpenAICompatEmbedding(cfg)
    retrieval_ctx = RetrievalContext(
        cfg=cfg, qdrant=app.state.qdrant, es=app.state.es, embedding=app.state.embedding
    )
    app.state.retrieval = retrieval_ctx
    verify_ctx = VerifyContext(app.state.llm_client, cfg, app.state.key_store)
    app.state.verify_ctx = verify_ctx  # 供验收/诊断断言 Key 通路（图用的是同一实例）
    app.state.compiled_graph = compile_graph(
        app.state.llm_client,
        app.state.checkpointer,
        retrieval=retrieval_ctx,
        resume_store=app.state.resume_store,
        cfg=cfg,
        verify_ctx=verify_ctx,
    )

    yield


app = FastAPI(title="AI 面试官", version="0.1.0", lifespan=lifespan)
app.include_router(chat_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(resume_router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# 前端静态托管（web/dist）：/assets 静态文件 + SPA 兜底（排除 /api）
if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        file = WEB_DIST / full_path
        if full_path and file.is_file():
            return FileResponse(file)
        return FileResponse(WEB_DIST / "index.html")
