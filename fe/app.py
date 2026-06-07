# fe/app.py
import config
from flask import Flask, request, jsonify, render_template
from fe.keyauth import extract_request_key, validate_key_format, build_request_orchestrator

_KEYLIKE_BODY_FIELDS = ("api_key", "apikey", "openai_key", "authorization", "x-ridebutler-key")


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
        orch = build_request_orchestrator(
            key, model=config.MODEL, embed_model=config.EMBED_MODEL,
            memory=memory_, corpus_cache=app.config["CORPUS_CACHE"])
        out = orch.process(sid, body["message"])
        return _no_store(jsonify({"session_id": sid, **out}))

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
