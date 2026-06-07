# fe/app.py
import logging
import secrets
import threading

import config
from flask import Flask, request, jsonify, render_template
from fe.keyauth import extract_request_key, validate_key_format, build_request_orchestrator, redact_key

_KEYLIKE_BODY_FIELDS = ("api_key", "apikey", "openai_key", "authorization", "x-ridebutler-key")


class _SessionGuard:
    """Per-sid owner token + per-sid lock. Owner token binds a client-chosen
    session_id to its creator (R7); the lock serializes pending_action read-modify-
    write so concurrent confirms can't double-execute."""
    def __init__(self):
        self._owners: dict[str, str] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def issue(self, sid: str) -> str:
        with self._guard:
            tok = self._owners.get(sid)
            if tok is None:
                tok = secrets.token_urlsafe(24)
                self._owners[sid] = tok
            return tok

    def authorize(self, sid: str, presented: "str | None") -> tuple[bool, str]:
        """Return (ok, owner_token). First use of a sid issues + binds the token.
        Subsequent use requires the matching token."""
        with self._guard:
            existing = self._owners.get(sid)
            if existing is None:
                tok = secrets.token_urlsafe(24)
                self._owners[sid] = tok
                return True, tok
            if presented and secrets.compare_digest(presented, existing):
                return True, existing
            return False, existing

    def lock_for(self, sid: str) -> threading.Lock:
        with self._guard:
            lk = self._locks.get(sid)
            if lk is None:
                lk = threading.Lock()
                self._locks[sid] = lk
            return lk


_SESSION_GUARD = _SessionGuard()


class _RedactFilter(logging.Filter):
    """Process-level filter: run generic redact_key over every LogRecord's rendered
    message so an accidental key in any log line becomes sk-***REDACTED*** (R6)."""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            red = redact_key(msg, None)   # generic sk-... branch
            if red != msg:
                record.msg = red
                record.args = ()
        except Exception:
            pass
        return True


def _install_redact_filter():
    """Install the redaction once (idempotent). A logging.Filter on the root logger
    is the install marker AND redacts records emitted directly on root; a LogRecord
    factory applies the same redaction to records from *any* logger (root-logger
    filters are not consulted when a child logger propagates a record), so R6 holds
    for every LogRecord regardless of which logger produced it."""
    root = logging.getLogger()
    if any(isinstance(f, _RedactFilter) for f in root.filters):
        return
    rf = _RedactFilter()
    root.addFilter(rf)
    inner = logging.getLogRecordFactory()

    def _redacting_factory(*args, **kwargs):
        record = inner(*args, **kwargs)
        rf.filter(record)
        return record

    logging.setLogRecordFactory(_redacting_factory)


def _strip_keylike(body: dict) -> dict:
    """Drop any api_key/authorization-shaped field from the request body BEFORE
    it reaches process() (header-only key channel; R4)."""
    return {k: v for k, v in body.items() if k.lower() not in _KEYLIKE_BODY_FIELDS}


def _no_store(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


def _resolve_key(req):
    """Return (key, error_code|None). error_code in {'missing_key','invalid_key'}."""
    allow_env = bool(getattr(config, "ALLOW_ENV_KEY", False))
    key = extract_request_key(req, allow_env=allow_env)
    if not key:
        return None, "missing_key"
    if not validate_key_format(key):
        return None, "invalid_key"
    return key, None


def create_app(orchestrator=None, *, memory=None, corpus_cache=None):
    app = Flask(__name__)
    _install_redact_filter()
    app.config["ORCH"] = orchestrator          # legacy single-orch mode (frozen test_app.py)
    app.config["MEMORY"] = memory              # BYOK shared SessionStore
    app.config["CORPUS_CACHE"] = corpus_cache  # BYOK process-level CorpusEmbeddingCache

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/api/chat")
    def chat():
        legacy = app.config["ORCH"]
        body = request.get_json(force=True)
        if legacy is not None:
            # legacy mode: behavior identical to today (no key gating)
            sid = body.get("session_id") or legacy.memory.new_session()
            out = legacy.process(sid, body["message"])
            return jsonify({"session_id": sid, **out})

        # BYOK mode
        key, err = _resolve_key(request)
        if err:
            return _no_store(jsonify({"error": err})), 401
        body = _strip_keylike(body)
        memory_ = app.config["MEMORY"]
        sid = body.get("session_id") or memory_.new_session()
        ok, owner = _SESSION_GUARD.authorize(sid, request.headers.get("X-RideButler-Owner"))
        if not ok:
            return _no_store(jsonify({"error": "session_forbidden"})), 403
        orch = build_request_orchestrator(
            key, model=config.MODEL, embed_model=config.EMBED_MODEL,
            memory=memory_, corpus_cache=app.config["CORPUS_CACHE"])
        with _SESSION_GUARD.lock_for(sid):
            out = orch.process(sid, body["message"])
        resp = _no_store(jsonify({"session_id": sid, **out}))
        resp.headers["X-RideButler-Owner"] = owner
        return resp

    @app.post("/api/chat/stream")
    def chat_stream():
        from flask import Response
        from fe.streaming import StreamRunner
        key, err = _resolve_key(request)
        if err:
            # zh error, JSON, NO stream
            msg = "請先設定您的 OpenAI 金鑰再開始對話。" if err == "missing_key" \
                else "金鑰格式不正確，請重新輸入。"
            return _no_store(jsonify({"error": err, "message": msg})), 401
        body = _strip_keylike(request.get_json(force=True))
        memory_ = app.config["MEMORY"]
        sid = body.get("session_id") or memory_.new_session()
        ok, owner = _SESSION_GUARD.authorize(sid, request.headers.get("X-RideButler-Owner"))
        if not ok:
            return _no_store(jsonify({"error": "session_forbidden"})), 403
        orch = build_request_orchestrator(
            key, model=config.MODEL, embed_model=config.EMBED_MODEL,
            memory=memory_, corpus_cache=app.config["CORPUS_CACHE"])
        lock = _SESSION_GUARD.lock_for(sid)

        def _locked_process(s, ui, on_step=None):
            with lock:
                return orch.process(s, ui, on_step=on_step)

        class _Locked:
            process = staticmethod(_locked_process)
        gen = StreamRunner().run(_Locked(), sid, body["message"], request_key=key)
        resp = Response(gen, mimetype="text/event-stream", headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "X-RideButler-Owner": owner,
        })
        return resp

    @app.get("/api/config")
    def api_config():
        from de.data.catalog import load_catalog
        media = {c["title"]: c["media_url"] for c in load_catalog()}
        return _no_store(jsonify({
            "demo": bool(getattr(config, "DEMO_MODE", False)),
            "models": {"chat": config.MODEL, "embed": config.EMBED_MODEL},
            "media": media,
        }))

    return app


def _build_default():
    from be.harness.memory import SessionStore
    from be.harness.retrieval.corpus_cache import CorpusEmbeddingCache
    return create_app(None, memory=SessionStore(), corpus_cache=CorpusEmbeddingCache())


if __name__ == "__main__":
    _build_default().run(debug=True, port=5000)
