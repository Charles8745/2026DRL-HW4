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
