# fe/sse.py
"""SSE frame builders. Single source for the wire format used by /api/chat/stream.
Note ensure_ascii=False so zh-Hant payloads are sent as real UTF-8, not \\uXXXX."""
import json


def sse_frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_comment() -> str:
    return ": ping\n\n"
