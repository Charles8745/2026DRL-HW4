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
