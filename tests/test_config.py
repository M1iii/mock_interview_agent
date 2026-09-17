from pathlib import Path

from omegaconf import DictConfig

from app.config import load_config, mask_secret


def test_defaults(monkeypatch):
    for key in ("PORT", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL_ID", "LLM_TIMEOUT"):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config(env_path=Path("nonexistent.env"))
    assert isinstance(cfg, DictConfig)
    assert cfg.app.host == "127.0.0.1"
    assert cfg.app.port == 8000
    assert cfg.app.title == "AI 面试官"
    assert cfg.llm.api_key == ""
    assert cfg.llm.base_url == "https://api.deepseek.com"
    assert cfg.llm.model_id == "deepseek-chat"
    assert cfg.llm.timeout == 60
    assert cfg.logging.warn_ttft_ms == 5000


def test_env_injection(monkeypatch, tmp_path):
    for key in ("PORT", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL_ID", "LLM_TIMEOUT"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "LLM_API_KEY=sk-test123456789012345678\n"
        "LLM_BASE_URL=https://api.example.com\n"
        "LLM_MODEL_ID=test-model\n"
        "LLM_TIMEOUT=120\n"
        "PORT=9000\n",
        encoding="utf-8",
    )
    cfg = load_config(env_path=env)
    assert cfg.app.port == 9000
    assert cfg.llm.api_key == "sk-test123456789012345678"
    assert cfg.llm.base_url == "https://api.example.com"
    assert cfg.llm.model_id == "test-model"
    assert cfg.llm.timeout == 120


def test_config_file_overrides(monkeypatch, tmp_path):
    for key in ("PORT", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    conf = tmp_path / "config.yaml"
    conf.write_text("app:\n  port: 7000\n", encoding="utf-8")
    cfg = load_config(config_path=conf, env_path=Path("nonexistent.env"))
    assert cfg.app.port == 7000
    assert cfg.llm.api_key == ""


def test_env_overrides_config_file(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "9000")
    conf = tmp_path / "config.yaml"
    conf.write_text("app:\n  port: 7000\n", encoding="utf-8")
    cfg = load_config(config_path=conf, env_path=Path("nonexistent.env"))
    assert cfg.app.port == 9000


def test_invalid_env_int_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_TIMEOUT", "abc")
    cfg = load_config(env_path=Path("nonexistent.env"))
    assert cfg.llm.timeout == 60


def test_mask_secret():
    assert mask_secret("") == ""
    assert mask_secret("sk-a7ed48d6072f4b2f") == "sk-•••"
    assert mask_secret("plain-text") == "•••"
