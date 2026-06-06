import importlib, config

def test_defaults_when_env_absent(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    importlib.reload(config)
    assert config.MODEL == "gpt-4.1-mini"

def test_reads_env(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    importlib.reload(config)
    assert config.MODEL == "gpt-4o-mini"
