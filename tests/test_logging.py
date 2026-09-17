import json
from datetime import UTC

from loguru import logger
from omegaconf import OmegaConf

from app.logging import _record_to_json, log_ttft, setup_logging

CFG = OmegaConf.create(
    {
        "logging": {
            "level": "INFO",
            "rotation": "10 MB",
            "retention": "14 days",
            "warn_ttft_ms": 5000,
        },
    }
)


def _make_sink():
    lines: list[str] = []

    def sink(message: str) -> None:
        lines.append(message)

    return lines, sink


def _last_json(lines: list[str]) -> dict:
    return json.loads(lines[-1])


def test_setup_logging_emits_json():
    lines, sink = _make_sink()
    setup_logging(CFG, sinks=[{"sink": sink}])
    logger.info("hello {name}", name="world")
    payload = _last_json(lines)
    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"
    assert "ts" in payload
    assert payload["logger"]


def test_extra_fields_flat_into_json():
    lines, sink = _make_sink()
    setup_logging(CFG, sinks=[{"sink": sink}])
    logger.bind(component="llm", duration_ms=123.4).info("llm call done")
    payload = _last_json(lines)
    assert payload["component"] == "llm"
    assert payload["duration_ms"] == 123.4


def test_secret_masked_in_log():
    lines, sink = _make_sink()
    setup_logging(CFG, sinks=[{"sink": sink}])
    secret = "sk-" + "a" * 24
    logger.info("calling with key {key}", key=secret)
    line = lines[-1]
    assert "sk-•••" in line
    assert secret not in line


def test_ttft_below_threshold_is_info():
    lines, sink = _make_sink()
    setup_logging(CFG, sinks=[{"sink": sink}])
    log_ttft(3000, component="llm")
    payload = _last_json(lines)
    assert payload["level"] == "INFO"
    assert payload["ttft_ms"] == 3000


def test_ttft_above_threshold_warns():
    lines, sink = _make_sink()
    setup_logging(CFG, sinks=[{"sink": sink}])
    log_ttft(6000, component="llm")
    payload = _last_json(lines)
    assert payload["level"] == "WARNING"
    assert payload["ttft_ms"] == 6000


def test_record_to_json_iso8601():
    from datetime import datetime

    record = {
        "time": datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC),
        "level": type("L", (), {"name": "INFO"})(),
        "name": None,
        "message": "x",
        "extra": {},
    }
    payload = json.loads(_record_to_json(record))
    assert payload["ts"] == "2026-09-16T12:00:00+00:00"
