# tests/test_secret_safety.py
import json
import logging

import config as _cfg
from be.harness.llm import FakeLLM, LLMResponse, ToolCall
from be.harness.orchestrator import Orchestrator
from be.harness.memory import SessionStore
from de.data.store import DataStore
from fe.app import create_app
from fe.keyauth import redact_key
from tests._sse_util import parse_sse

CANARY = "sk-LEAKCANARYxxxxxxxxxxxxxx"   # 24 chars after sk- ; passes format + generic redaction


def _byok_app(monkeypatch, scripted):
    import fe.app as appmod
    monkeypatch.setattr(_cfg, "DEMO_MODE", False, raising=False)
    monkeypatch.setattr(_cfg, "ALLOW_ENV_KEY", False, raising=False)
    shared_mem = SessionStore()

    def _fake_build(key, *, model, embed_model, memory, corpus_cache):
        return Orchestrator(FakeLLM(list(scripted)), DataStore(seed=42), memory)

    monkeypatch.setattr(appmod, "build_request_orchestrator", _fake_build)
    return create_app(None, memory=shared_mem, corpus_cache=object())


def _fallback_script():
    return [LLMResponse(text="嗨", total_tokens=1),
            LLMResponse(text="閒聊範圍外", total_tokens=1),
            LLMResponse(text="我是重機客服", total_tokens=1)]


# --- A. redact_key unit contract -------------------------------------------------
def test_redact_key_literal_and_generic():
    assert redact_key(f"head {CANARY} tail", CANARY) == "head sk-***REDACTED*** tail"
    # generic branch (key=None): any sk-[A-Za-z0-9_-]{20,} is redacted
    assert redact_key(f"x {CANARY} y", None) == "x sk-***REDACTED*** y"
    assert redact_key("nothing here", None) == "nothing here"


# --- B. canary header never echoed into JSON turn --------------------------------
def test_canary_key_absent_from_chat_json(monkeypatch):
    app = _byok_app(monkeypatch, _fallback_script())
    r = app.test_client().post("/api/chat", json={"message": "嗨"},
                               headers={"X-RideButler-Key": CANARY})
    assert r.status_code == 200
    raw = r.get_data(as_text=True)
    assert "sk-LEAKCANARY" not in raw
    body = r.get_json()
    assert "sk-LEAKCANARY" not in json.dumps(body, ensure_ascii=False)


# --- C. canary key never appears in any SSE frame -------------------------------
def test_canary_key_absent_from_every_sse_frame(monkeypatch):
    app = _byok_app(monkeypatch, _fallback_script())
    r = app.test_client().post("/api/chat/stream", json={"message": "嗨", "session_id": "S"},
                               headers={"X-RideButler-Key": CANARY})
    raw = r.get_data(as_text=True)
    assert "sk-LEAKCANARY" not in raw
    for f in parse_sse(raw):
        assert "sk-LEAKCANARY" not in json.dumps(f, ensure_ascii=False)


# --- D. key mis-typed INTO the message -> scrubbed from raw_input/rewritten_query
def test_key_in_message_scrubbed_from_trace(monkeypatch):
    # user accidentally pastes their key into the chat message
    script = [LLMResponse(text=f"我的金鑰是 {CANARY} 幫我推薦", total_tokens=1),   # rewrite echoes it
              LLMResponse(text="閒聊範圍外", total_tokens=1),
              LLMResponse(text="我是重機客服", total_tokens=1)]
    app = _byok_app(monkeypatch, script)
    r = app.test_client().post("/api/chat/stream",
                               json={"message": f"我的金鑰是 {CANARY} 幫我推薦", "session_id": "M"},
                               headers={"X-RideButler-Key": CANARY})
    raw = r.get_data(as_text=True)
    # M0 _scrub strips sk- literals from emitted payloads (raw_input/rewritten_query)
    assert "sk-LEAKCANARY" not in raw
    final = [f for f in parse_sse(raw) if f["event"] == "final"][0]
    blob = json.dumps(final, ensure_ascii=False)
    assert "sk-LEAKCANARY" not in blob


# --- D2. same key-in-message case on the NON-streamed /api/chat JSON turn --------
# Plan intent (line 3817): the key-in-message scrub is asserted on BOTH the streamed
# `final` frame AND the /api/chat JSON. The returned trace (raw_input/rewritten_query)
# must be scrubbed too — not only the _emit path.
def test_key_in_message_scrubbed_from_chat_json(monkeypatch):
    script = [LLMResponse(text=f"我的金鑰是 {CANARY} 幫我推薦", total_tokens=1),   # rewrite echoes it
              LLMResponse(text="閒聊範圍外", total_tokens=1),
              LLMResponse(text="我是重機客服", total_tokens=1)]
    app = _byok_app(monkeypatch, script)
    r = app.test_client().post("/api/chat",
                               json={"message": f"我的金鑰是 {CANARY} 幫我推薦", "session_id": "MJ"},
                               headers={"X-RideButler-Key": CANARY})
    assert r.status_code == 200
    raw = r.get_data(as_text=True)
    assert "sk-LEAKCANARY" not in raw
    assert "sk-LEAKCANARY" not in json.dumps(r.get_json(), ensure_ascii=False)


# --- E. trace carries no key-shaped key NAMES -----------------------------------
def test_trace_has_no_keylike_field_names(monkeypatch):
    from be.harness.llm import ToolCall
    script = [LLMResponse(text="推薦30萬sport", total_tokens=2),
              LLMResponse(text="找車推薦", total_tokens=1),
              LLMResponse(tool_calls=[ToolCall("recommend", {"budget": 300000, "usage": "sport"})], total_tokens=5),
              LLMResponse(text="為您推薦這幾台", total_tokens=4)]
    app = _byok_app(monkeypatch, script)
    r = app.test_client().post("/api/chat", json={"message": "30萬sport"},
                               headers={"X-RideButler-Key": CANARY})
    blob = json.dumps(r.get_json(), ensure_ascii=False).lower()
    for forbidden in ("api_key", "openai_key", "authorization", "x-ridebutler-key"):
        assert forbidden not in blob


# --- F. caplog never leaks the canary (redaction filter installed by create_app) -
def test_canary_absent_from_caplog(monkeypatch, caplog):
    create_app(None, memory=SessionStore(), corpus_cache=object())
    logger = logging.getLogger("rb.secret")
    with caplog.at_level(logging.INFO):
        logger.info("debug dump key=%s ok", CANARY)
    assert "sk-LEAKCANARY" not in caplog.text
    assert "sk-***REDACTED***" in caplog.text
