"""应用配置：默认值 + conf/config.yaml（可选） + .env 三层合并。"""

import os
from pathlib import Path

from dotenv import load_dotenv
from omegaconf import DictConfig, OmegaConf

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_DEFAULTS = {
    "app": {
        "host": "127.0.0.1",
        "port": 8000,
        "title": "AI 面试官",
        "max_sessions": 30,
    },
    "llm": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model_id": "deepseek-chat",
        "timeout": 60,
        "max_retries": 2,
    },
    "logging": {
        "level": "INFO",
        "rotation": "10 MB",
        "retention": "14 days",
        "warn_ttft_ms": 5000,
    },
    "retrieval": {
        "enabled": True,
        "qdrant_url": "http://127.0.0.1:6333",
        "qdrant_timeout": 5,
        "qdrant_collection": "kb_blocks",
        "es_url": "http://127.0.0.1:9200",
        "es_timeout": 5,
        "es_index": "kb_blocks",
        "semantic_weight": 0.6,
        "threshold": 0.6,
        "weak_threshold": 0.45,
        "score_threshold": 0.0,
        "min_should_match": "25%",
        "top_k": 5,
        "kb_dir": "data/kb_files",
        "kb_db": "data/kb.db",
        "chunking": {
            "parent_max_chars": 800,
            "child_max_chars": 200,
            "overlap_chars": 0,
            "slide_window": 180,
            "slide_overlap": 20,
        },
        "embedding": {
            "provider": "local",
            "base_url": "http://127.0.0.1:8081/v1",
            "api_key": "",
            "model_id": "bge-large-zh-v1.5",
            "dims": 1024,
            "timeout": 10,
        },
    },
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
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def load_config(config_path: Path | None = None, env_path: Path | None = None) -> DictConfig:
    """默认值 < conf/config.yaml（如存在） < 环境变量/.env，优先级递增。"""
    load_dotenv(env_path or PROJECT_ROOT / ".env")
    base = OmegaConf.create(_DEFAULTS)
    path = config_path or PROJECT_ROOT / "conf" / "config.yaml"
    if path.exists():
        base = OmegaConf.merge(base, OmegaConf.load(path))
    overrides = OmegaConf.create(
        {
            "app": {"port": _env_int("PORT", base.app.port)},
            "llm": {
                "api_key": os.getenv("LLM_API_KEY", base.llm.api_key),
                "base_url": os.getenv("LLM_BASE_URL", base.llm.base_url),
                "model_id": os.getenv("LLM_MODEL_ID", base.llm.model_id),
                "timeout": _env_int("LLM_TIMEOUT", base.llm.timeout),
            },
            "retrieval": {
                "enabled": os.getenv("RETRIEVAL_ENABLED", str(base.retrieval.enabled)).lower()
                in ("1", "true", "yes"),
                "qdrant_url": os.getenv("QDRANT_URL", base.retrieval.qdrant_url),
                "qdrant_timeout": _env_int("QDRANT_TIMEOUT", base.retrieval.qdrant_timeout),
                "es_url": os.getenv("ES_URL", base.retrieval.es_url),
                "es_timeout": _env_int("ES_TIMEOUT", base.retrieval.es_timeout),
                "es_index": os.getenv("ES_INDEX", base.retrieval.es_index),
                "semantic_weight": float(
                    os.getenv("SEMANTIC_WEIGHT", str(base.retrieval.semantic_weight))
                ),
                "threshold": float(os.getenv("RETRIEVAL_THRESHOLD", str(base.retrieval.threshold))),
                "weak_threshold": float(
                    os.getenv("RETRIEVAL_WEAK_THRESHOLD", str(base.retrieval.weak_threshold))
                ),
                "score_threshold": float(
                    os.getenv("RETRIEVAL_SCORE_THRESHOLD", str(base.retrieval.score_threshold))
                ),
                "min_should_match": os.getenv(
                    "RETRIEVAL_MIN_SHOULD_MATCH", base.retrieval.min_should_match
                ),
                "top_k": _env_int("TOP_K", base.retrieval.top_k),
                "kb_dir": os.getenv("KB_DIR", base.retrieval.kb_dir),
                "kb_db": os.getenv("KB_DB", base.retrieval.kb_db),
                "chunking": {
                    "parent_max_chars": _env_int(
                        "CHUNK_PARENT_MAX", base.retrieval.chunking.parent_max_chars
                    ),
                    "child_max_chars": _env_int(
                        "CHUNK_CHILD_MAX", base.retrieval.chunking.child_max_chars
                    ),
                    "overlap_chars": _env_int(
                        "CHUNK_OVERLAP", base.retrieval.chunking.overlap_chars
                    ),
                    "slide_window": _env_int(
                        "CHUNK_SLIDE_WINDOW", base.retrieval.chunking.slide_window
                    ),
                    "slide_overlap": _env_int(
                        "CHUNK_SLIDE_OVERLAP", base.retrieval.chunking.slide_overlap
                    ),
                },
                "embedding": {
                    "provider": os.getenv("EMBEDDING_PROVIDER", base.retrieval.embedding.provider),
                    "base_url": os.getenv("EMBEDDING_BASE_URL", base.retrieval.embedding.base_url),
                    "api_key": os.getenv("EMBEDDING_API_KEY", base.retrieval.embedding.api_key),
                    "model_id": os.getenv("EMBEDDING_MODEL_ID", base.retrieval.embedding.model_id),
                    "dims": _env_int("EMBEDDING_DIMS", base.retrieval.embedding.dims),
                    "timeout": _env_int("EMBEDDING_TIMEOUT", base.retrieval.embedding.timeout),
                },
            },
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
                        os.getenv(
                            "RESUME_RATIO_COMPREHENSIVE", str(base.resume.ratio.comprehensive)
                        )
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
        }
    )
    return OmegaConf.merge(base, overrides)


def mask_secret(value: str) -> str:
    """展示/日志用掩码：sk- 前缀 Key 统一显示为 sk-•••，其余一律 •••。"""
    if not value:
        return ""
    if value.startswith("sk-"):
        return "sk-•••"
    return "•••"
