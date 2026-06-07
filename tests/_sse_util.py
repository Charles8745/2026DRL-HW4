# tests/_sse_util.py
"""Shared SSE frame parser for stream tests. Parses `event:`/`data:` blocks.
Single source — authored once in M2.1; reused by all later stream tests."""
import json


def parse_sse(raw: str):
    """Parse an SSE byte/str stream into a list of {event, data} dicts.
    Comment lines (starting ':') are ignored. data: lines are JSON-decoded
    when possible, else kept as the raw string. A frame with only data:
    (no event: line) defaults to event 'message' (SSE spec; matches sseparse.js)."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    frames = []
    for block in raw.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        event, data_lines = None, []
        is_comment = True
        for line in block.split("\n"):
            if line.startswith(":"):
                continue
            is_comment = False
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        if is_comment and event is None and not data_lines:
            continue
        if event is None and not data_lines:
            continue
        if event is None:                       # only data: present -> default per SSE spec
            event = "message"
        raw_data = "\n".join(data_lines)
        try:
            data = json.loads(raw_data)
        except Exception:
            data = raw_data
        frames.append({"event": event, "data": data})
    return frames


def event_types(frames):
    return [f["event"] for f in frames]


events_of = event_types   # alias (back-compat name)
