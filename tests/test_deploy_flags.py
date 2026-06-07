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


def test_install_log_redaction_redacts_named_logger_through_handler():
    """End-to-end: a key logged via a NAMED/child logger (whose record propagates
    to the root logger's handlers) must reach the output stream REDACTED.

    A filter-only control attached to the root logger does NOT cover this path —
    root-logger filters are skipped when a child logger propagates a record — so
    this is the test that catches the real leak (R6: scrub sk- from every log
    line, process-wide, regardless of which logger emits it)."""
    import io
    from fe.keyauth import install_log_redaction

    install_log_redaction()

    root = logging.getLogger()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    root.addHandler(handler)
    prev_level = root.level
    root.setLevel(logging.INFO)
    try:
        logging.getLogger("rb.boot").warning(
            "child sk-abcdefghijklmnopqrstuvwxyz012345"
        )
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)

    out = buf.getvalue()
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in out
    assert "sk-***REDACTED***" in out


def test_install_log_redaction_is_idempotent_with_create_app():
    """install_log_redaction() and create_app() share one R6 mechanism, so
    mixing them must not stack a second redaction filter on the root logger."""
    from fe.keyauth import KeyRedactionFilter, install_log_redaction
    from fe.app import create_app

    class _SS:
        def get_or_create(self, *a, **k):
            return (None, None)

        def lock_for(self, *a, **k):
            import threading
            return threading.Lock()

    install_log_redaction()
    create_app(None, memory=_SS(), corpus_cache=object())
    root = logging.getLogger()
    n = sum(isinstance(f, KeyRedactionFilter) for f in root.filters)
    assert n == 1


# ---- wsgi: BYOK-aware boot without a real key ------------------------------

def test_wsgi_boots_without_real_key(monkeypatch):
    # No OPENAI_API_KEY in env: importing wsgi must still produce an app.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import importlib
    import wsgi
    importlib.reload(wsgi)
    assert wsgi.app is not None


def test_wsgi_app_debug_is_false(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import importlib
    import wsgi
    importlib.reload(wsgi)
    assert wsgi.app.debug is False


def test_wsgi_is_byok_mode(monkeypatch):
    # production must NOT carry a preset orchestrator (R1/R4/R7 enforcement lives in
    # the BYOK branch only; a positional orchestrator would silently bypass it).
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import importlib
    import wsgi
    importlib.reload(wsgi)
    assert wsgi.app.config["ORCH"] is None
