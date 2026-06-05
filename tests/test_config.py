import importlib, config

def test_defaults_when_env_absent(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    importlib.reload(config)
    assert config.MODEL == "gemini-2.0-flash"

def test_reads_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-pro")
    importlib.reload(config)
    assert config.MODEL == "gemini-2.0-pro"
