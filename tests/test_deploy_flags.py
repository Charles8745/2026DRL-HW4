import importlib
import logging

import config


def _reload_config(monkeypatch, **env):
    """Reload config.py with a controlled environment so module-level
    flag parsing is exercised fresh each test."""
    for k in ("OPENAI_API_KEY", "ALLOW_ENV_KEY", "ALLOW_ENV_KEY_PUBLIC", "DEMO_MODE"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(config)


# ---- R1 guard: ALLOW_ENV_KEY must NOT authorize fallback on a public bind ----

def test_no_env_key_fallback_on_public(monkeypatch):
    cfg = _reload_config(monkeypatch, ALLOW_ENV_KEY="1", OPENAI_API_KEY="sk-fakefakefakefakefake")
    # localhost binds may fall back...
    assert cfg.env_fallback_allowed("127.0.0.1") is True
    assert cfg.env_fallback_allowed("localhost") is True
    # ...but a public bind must NOT, without the explicit public override.
    assert cfg.env_fallback_allowed("0.0.0.0") is False
    assert cfg.env_fallback_allowed("203.0.113.7") is False


def test_public_override_re_enables_fallback(monkeypatch):
    cfg = _reload_config(
        monkeypatch,
        ALLOW_ENV_KEY="1",
        ALLOW_ENV_KEY_PUBLIC="1",
        OPENAI_API_KEY="sk-fakefakefakefakefake",
    )
    assert cfg.env_fallback_allowed("0.0.0.0") is True


def test_allow_env_key_off_never_falls_back(monkeypatch):
    cfg = _reload_config(monkeypatch, ALLOW_ENV_KEY="0", OPENAI_API_KEY="sk-fakefakefakefakefake")
    assert cfg.env_fallback_allowed("127.0.0.1") is False
    assert cfg.env_fallback_allowed("0.0.0.0") is False


def test_demo_mode_does_not_authorize_env_key(monkeypatch):
    # DEMO_MODE is UI-only and must never enable the .env key fallback.
    cfg = _reload_config(monkeypatch, DEMO_MODE="1", OPENAI_API_KEY="sk-fakefakefakefakefake")
    assert cfg.DEMO_MODE is True
    assert cfg.ALLOW_ENV_KEY is False
    assert cfg.env_fallback_allowed("127.0.0.1") is False


def test_dangerous_combo_emits_warning(monkeypatch, caplog):
    cfg = _reload_config(
        monkeypatch,
        ALLOW_ENV_KEY="1",
        ALLOW_ENV_KEY_PUBLIC="1",
        OPENAI_API_KEY="sk-fakefakefakefakefake",
    )
    with caplog.at_level(logging.WARNING):
        warnings = cfg.boot_flag_warnings("0.0.0.0")
    assert any("ALLOW_ENV_KEY" in w and "0.0.0.0" in w for w in warnings)
    # WARNING text must never contain the key literal.
    assert "sk-fakefakefakefakefake" not in " ".join(warnings)
    assert "sk-fakefakefakefakefake" not in caplog.text


def test_safe_combo_no_warning(monkeypatch):
    cfg = _reload_config(monkeypatch, ALLOW_ENV_KEY="0")
    assert cfg.boot_flag_warnings("127.0.0.1") == []


# ---- process-level logging redaction filter --------------------------------

def test_redaction_filter_scrubs_sk_in_message():
    from fe.keyauth import KeyRedactionFilter

    flt = KeyRedactionFilter()
    rec = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1,
        msg="leaking sk-abcdefghijklmnopqrstuvwxyz012345 here", args=(), exc_info=None,
    )
    assert flt.filter(rec) is True  # filter never drops records
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in rec.getMessage()
    assert "sk-***REDACTED***" in rec.getMessage()


def test_redaction_filter_scrubs_sk_in_args():
    from fe.keyauth import KeyRedactionFilter

    flt = KeyRedactionFilter()
    rec = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1,
        msg="key=%s", args=("sk-abcdefghijklmnopqrstuvwxyz012345",), exc_info=None,
    )
    flt.filter(rec)
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in rec.getMessage()
    assert "sk-***REDACTED***" in rec.getMessage()


def test_install_log_redaction_is_idempotent():
    from fe.keyauth import KeyRedactionFilter, install_log_redaction

    install_log_redaction()
    install_log_redaction()  # second call must not double-add
    root = logging.getLogger()
    n = sum(isinstance(f, KeyRedactionFilter) for f in root.filters)
    assert n == 1
