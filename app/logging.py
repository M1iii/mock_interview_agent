"""loguru 结构化 JSON 日志：ISO8601 / 耗时明细 / TTFT 告警 / Key 脱敏。"""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from omegaconf import DictConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]{16,}")


def _record_to_json(record: dict) -> str:
    """单条日志 -> 单行 JSON（干净输出，不含 loguru 模板转义）。"""
    ts = datetime.fromtimestamp(record["time"].timestamp(), tz=UTC).isoformat()
    payload = {
        "ts": ts,
        "level": record["level"].name,
        "logger": record["name"] or "app",
        "msg": record["message"],
    }
    payload.update(record["extra"])
    return _SECRET_PATTERN.sub("sk-•••", json.dumps(payload, ensure_ascii=False))


def _json_formatter(record: dict) -> str:
    """loguru format 入口：loguru 会把 callable 返回值当模板再做 format_map，
    故先转义花括号，让模板化后无损还原为合法 JSON。"""
    return _record_to_json(record).replace("{", "{{").replace("}", "}}")


def setup_logging(cfg: DictConfig, sinks: list[dict] | None = None) -> None:
    """配置全局 logger。sinks 为空时输出到 stderr + logs/app_YYYYMMDD.log（滚动保留）。"""
    logger.remove()
    level = cfg.logging.level
    targets = (
        sinks
        if sinks is not None
        else [
            {"sink": sys.stderr},
            {
                "sink": str(PROJECT_ROOT / "logs" / "app_{time:YYYYMMDD}.log"),
                "rotation": cfg.logging.rotation,
                "retention": cfg.logging.retention,
                "encoding": "utf-8",
            },
        ]
    )
    for target in targets:
        logger.add(format=_json_formatter, level=level, **target)


def log_ttft(ttft_ms: float, warn_ms: int = 5000, **extra) -> None:
    """TTFT 打点：超过阈值记 WARNING（慢请求告警），否则 INFO。"""
    bind = logger.bind(ttft_ms=ttft_ms, **extra)
    if ttft_ms > warn_ms:
        bind.warning("TTFT slow: {ttft_ms}ms")
    else:
        bind.info("TTFT ok: {ttft_ms}ms")
