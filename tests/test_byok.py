import importlib
import os


def _reload_config(monkeypatch, **env):
    for k in ("ALLOW_ENV_KEY", "DEMO_MODE", "ALLOW_ENV_KEY_PUBLIC", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config
    return importlib.reload(config)


def test_flags_default_off(monkeypatch):
    cfg = _reload_config(monkeypatch)
    assert cfg.ALLOW_ENV_KEY is False
    assert cfg.DEMO_MODE is False
    # existing names untouched
    assert hasattr(cfg, "API_KEY") and hasattr(cfg, "MODEL")
    assert hasattr(cfg, "EMBED_MODEL") and cfg.MAX_TOOL_CALLS_PER_TURN == 6


def test_flags_truthy_env(monkeypatch):
    cfg = _reload_config(monkeypatch, ALLOW_ENV_KEY="1", DEMO_MODE="true")
    assert cfg.ALLOW_ENV_KEY is True
    assert cfg.DEMO_MODE is True


def test_flags_falsey_strings(monkeypatch):
    cfg = _reload_config(monkeypatch, ALLOW_ENV_KEY="0", DEMO_MODE="false")
    assert cfg.ALLOW_ENV_KEY is False
    assert cfg.DEMO_MODE is False
