# tests/test_app_sse.py
import json
from fe.sse import sse_frame, sse_comment


def test_sse_frame_format_and_ensure_ascii_false():
    out = sse_frame("route", {"label": "找車推薦", "tokens": 3})
    assert out == 'event: route\ndata: {"label": "找車推薦", "tokens": 3}\n\n'
    # zh-Hant must NOT be \u-escaped (ensure_ascii=False)
    assert "找車推薦" in out
    assert "\\u" not in out


def test_sse_frame_ends_with_blank_line():
    out = sse_frame("done", {"session_id": "abc", "elapsed_ms": 12})
    assert out.endswith("\n\n")
    assert out.startswith("event: done\n")


def test_sse_comment_is_ping():
    assert sse_comment() == ": ping\n\n"


import time
from tests._sse_util import parse_sse, event_types
from fe.streaming import StreamRunner


class _GoodOrch:
    """Minimal fake orchestrator: emits two events then returns. on_step is the
    queue.put passed by StreamRunner."""
    def __init__(self):
        self.dropped = False
    def process(self, sid, user_input, on_step=None):
        on_step("guard", {"blocked": False, "reason": None})
        on_step("final", {"reply": "嗨", "blocked": False, "awaiting_confirmation": False,
                          "router_label": "閒聊範圍外", "resolved_listing_id": None,
                          "tokens": 0, "trace": {"steps": []}})
        return {"reply": "嗨", "blocked": False, "awaiting_confirmation": False,
                "trace": {"steps": []}}


class _RaisingOrch:
    """Raises mid-turn: the generator must still finish with error + done."""
    def process(self, sid, user_input, on_step=None):
        on_step("guard", {"blocked": False, "reason": None})
        raise RuntimeError("boom sk-LEAKCANARYxxxxxxxxxxxxxx leaked")


def test_streamrunner_emits_events_then_done():
    runner = StreamRunner()
    gen = runner.run(_GoodOrch(), "sid1", "嗨", request_key=None)
    raw = "".join(gen)
    frames = parse_sse(raw)
    types = event_types(frames)
    assert "guard" in types and "final" in types
    assert types[-1] == "done"
    done = [f for f in frames if f["event"] == "done"][0]
    assert done["data"]["session_id"] == "sid1"
    assert "elapsed_ms" in done["data"]


def test_streamrunner_always_ends_with_done_on_exception():
    runner = StreamRunner()
    gen = runner.run(_RaisingOrch(), "sid2", "嗨", request_key="sk-LEAKCANARYxxxxxxxxxxxxxx")
    raw = "".join(gen)
    frames = parse_sse(raw)
    types = event_types(frames)
    # finally sentinel: error then done, never hang
    assert "error" in types
    assert types[-1] == "done"
    # redacted: the sentinel key must NOT appear anywhere in the stream
    assert "sk-LEAKCANARY" not in raw


def test_streamrunner_drops_orch_reference_in_finally():
    runner = StreamRunner()
    orch = _GoodOrch()
    gen = runner.run(orch, "sid3", "嗨", request_key=None)
    "".join(gen)  # fully drain
    assert runner._orch is None  # ref dropped in finally (key in-heap life == this turn)


def test_streamrunner_partial_consume_then_close_is_clean():
    # client disconnect: consume one frame, then close the generator. The yield-in-
    # finally must NOT raise 'generator ignored GeneratorExit', and the orch ref must
    # be dropped (GeneratorExit cooperative-cancel coverage — R5/R19).
    runner = StreamRunner()
    gen = runner.run(_GoodOrch(), "sidX", "嗨", request_key=None)
    next(gen)            # partial consume (first frame only)
    gen.close()          # simulate client disconnect; must not raise RuntimeError
    assert runner._orch is None  # ref dropped on GeneratorExit unwind


from be.harness.llm import FakeLLM, LLMResponse
from de.data.store import DataStore
from be.harness.memory import SessionStore
from be.harness.orchestrator import Orchestrator


def test_overshort_fakellm_ends_with_error_and_done_within_budget():
    # FakeLLM with only ONE response: rewrite consumes it, route() then IndexErrors.
    # The worker must catch it, emit error, then done -> the generator must NOT hang.
    llm = FakeLLM([LLMResponse(text="嗨", total_tokens=1)])
    orch = Orchestrator(llm, DataStore(seed=42), SessionStore())
    runner = StreamRunner(heartbeat_s=0.2, wall_clock_s=5.0)
    sid = orch.memory.new_session()
    gen = runner.run(orch, sid, "嗨", request_key=None)
    t0 = time.monotonic()
    raw = "".join(gen)          # full drain
    elapsed = time.monotonic() - t0
    frames = parse_sse(raw)
    types = event_types(frames)
    assert "error" in types and types[-1] == "done"
    assert elapsed < 5.0        # finished well within the drain/wall-clock budget


def test_wall_clock_cap_aborts_a_stuck_worker():
    class _StuckOrch:
        def process(self, sid, user_input, on_step=None):
            on_step("guard", {"blocked": False, "reason": None})
            time.sleep(10)      # simulate a hung OpenAI call
    runner = StreamRunner(heartbeat_s=0.1, wall_clock_s=0.5)
    gen = runner.run(_StuckOrch(), "sidWC", "嗨", request_key=None)
    t0 = time.monotonic()
    raw = "".join(gen)
    elapsed = time.monotonic() - t0
    frames = parse_sse(raw)
    types = event_types(frames)
    assert "error" in types and types[-1] == "done"
    assert elapsed < 3.0        # wall-clock fired ~0.5s, did not wait for the 10s sleep


import config as _cfg
from fe.app import create_app
from be.harness.memory import SessionStore as _SS


def _byok_app(monkeypatch, scripted, *, demo=False, allow_env=False):
    """BYOK-mode app whose per-request orchestrator runs a FakeLLM script.
    We monkeypatch build_request_orchestrator so no real key/network is needed."""
    import fe.app as appmod
    from be.harness.orchestrator import Orchestrator
    from be.harness.llm import FakeLLM
    monkeypatch.setattr(_cfg, "DEMO_MODE", demo, raising=False)
    monkeypatch.setattr(_cfg, "ALLOW_ENV_KEY", allow_env, raising=False)

    shared_mem = _SS()

    def _fake_build(key, *, model, embed_model, memory, corpus_cache):
        return Orchestrator(FakeLLM(list(scripted)), DataStore(seed=42), memory)

    monkeypatch.setattr(appmod, "build_request_orchestrator", _fake_build)
    app = create_app(None, memory=shared_mem, corpus_cache=object())
    return app


def _fallback_script():
    return [LLMResponse(text="嗨", total_tokens=1),
            LLMResponse(text="閒聊範圍外", total_tokens=1),
            LLMResponse(text="我是重機客服", total_tokens=1)]


def test_chat_missing_key_returns_401(monkeypatch):
    app = _byok_app(monkeypatch, _fallback_script(), demo=False)
    r = app.test_client().post("/api/chat", json={"message": "嗨"})
    assert r.status_code == 401
    assert r.get_json()["error"] == "missing_key"


def test_chat_invalid_key_format_returns_401(monkeypatch):
    app = _byok_app(monkeypatch, _fallback_script(), demo=False)
    r = app.test_client().post("/api/chat", json={"message": "嗨"},
                               headers={"X-RideButler-Key": "not-a-key"})
    assert r.status_code == 401
    assert r.get_json()["error"] == "invalid_key"


def test_chat_valid_key_returns_reply_and_no_store(monkeypatch):
    app = _byok_app(monkeypatch, _fallback_script(), demo=False)
    r = app.test_client().post("/api/chat", json={"message": "嗨"},
                               headers={"X-RideButler-Key": "sk-validvalidvalidvalid01"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["reply"] == "我是重機客服"
    assert "session_id" in body and "trace" in body
    assert "no-store" in r.headers.get("Cache-Control", "")
    assert r.headers.get("Pragma") == "no-cache"


def test_chat_strips_body_api_key_before_process(monkeypatch):
    # a body api_key/authorization must never reach process() as part of the message
    captured = {}
    import fe.app as appmod
    from be.harness.orchestrator import Orchestrator
    from be.harness.llm import FakeLLM
    monkeypatch.setattr(_cfg, "DEMO_MODE", False, raising=False)

    class _SpyOrch(Orchestrator):
        def process(self, sid, user_input, on_step=None):
            captured["msg"] = user_input
            return {"reply": "ok", "blocked": False, "awaiting_confirmation": False,
                    "trace": {"raw_input": user_input}}

    def _fake_build(key, *, model, embed_model, memory, corpus_cache):
        return _SpyOrch(FakeLLM([]), DataStore(seed=42), memory)

    monkeypatch.setattr(appmod, "build_request_orchestrator", _fake_build)
    app = create_app(None, memory=_SS(), corpus_cache=object())
    r = app.test_client().post("/api/chat",
                               json={"message": "嗨", "api_key": "sk-LEAKCANARYxxxxxxxxxxxxxx",
                                     "authorization": "Bearer sk-LEAKCANARYxxxxxxxxxxxxxx"},
                               headers={"X-RideButler-Key": "sk-validvalidvalidvalid01"})
    assert r.status_code == 200
    # only message reached process(); the stripped fields are gone
    assert captured["msg"] == "嗨"
    assert "sk-LEAKCANARY" not in json.dumps(r.get_json())


def test_legacy_create_app_with_orchestrator_unchanged(monkeypatch):
    # regression canary parity: create_app(orch) needs NO key (frozen test_app.py path)
    from be.harness.orchestrator import Orchestrator
    from be.harness.llm import FakeLLM
    orch = Orchestrator(FakeLLM(_fallback_script()), DataStore(seed=42), _SS())
    app = create_app(orch)
    r = app.test_client().post("/api/chat", json={"message": "嗨"})
    assert r.status_code == 200
    assert r.get_json()["reply"] == "我是重機客服"


from de.data.catalog import load_catalog


def test_config_endpoint_shape_and_media_map(monkeypatch):
    monkeypatch.setattr(_cfg, "DEMO_MODE", False, raising=False)
    app = create_app(None, memory=_SS(), corpus_cache=object())
    r = app.test_client().get("/api/config")
    assert r.status_code == 200
    body = r.get_json()
    assert body["demo"] is False
    assert "models" in body and body["models"]["chat"] == _cfg.MODEL
    assert body["models"]["embed"] == _cfg.EMBED_MODEL
    media = body["media"]
    cat = load_catalog()
    # one entry per catalog title, mapping to its media_url
    assert len(media) == len({c["title"] for c in cat})
    sample = cat[0]
    assert media[sample["title"]] == sample["media_url"]


def test_config_demo_flag_true(monkeypatch):
    monkeypatch.setattr(_cfg, "DEMO_MODE", True, raising=False)
    app = create_app(None, memory=_SS(), corpus_cache=object())
    body = app.test_client().get("/api/config").get_json()
    assert body["demo"] is True


def test_config_contains_no_key(monkeypatch):
    monkeypatch.setattr(_cfg, "API_KEY", "sk-LEAKCANARYxxxxxxxxxxxxxx", raising=False)
    monkeypatch.setattr(_cfg, "DEMO_MODE", True, raising=False)
    app = create_app(None, memory=_SS(), corpus_cache=object())
    raw = app.test_client().get("/api/config").get_data(as_text=True)
    assert "sk-LEAKCANARY" not in raw
    assert "API_KEY" not in raw
