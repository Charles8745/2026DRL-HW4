"""Production WSGI entrypoint (gunicorn target: `wsgi:app`).

BYOK-aware: boots with NO real OPENAI_API_KEY. Real keys arrive per-request
via the X-RideButler-Key header; this module only constructs the Flask app,
the shared SessionStore, and the process-level CorpusEmbeddingCache.
Never runs the dev server and never enables debug.
"""
import logging

import config
from fe.app import create_app
from fe.keyauth import install_log_redaction
from be.harness.memory import SessionStore
from be.harness.retrieval.corpus_cache import CorpusEmbeddingCache

logging.basicConfig(level=logging.INFO)
install_log_redaction()  # scrub any sk- shape from every log line, process-wide

# Process-level shared state (single instance only — see gunicorn.conf.py).
MEMORY = SessionStore()
CORPUS_CACHE = CorpusEmbeddingCache()

# Surface dangerous flag combos at boot (never logs the key itself).
for _w in config.boot_flag_warnings(__import__("os").getenv("BIND_HOST", "0.0.0.0")):
    logging.getLogger("rb.boot").warning(_w)

# BYOK-aware app: create_app boots without a real key; per-request
# orchestrators are built by fe.keyauth.build_request_orchestrator(...).
app = create_app(memory=MEMORY, corpus_cache=CORPUS_CACHE)

# Hard invariant: production must run BYOK mode — no preset orchestrator. A positional
# orchestrator would silently bypass R1/R4/R7 (key-gate + owner-token + per-sid lock).
assert app.config.get("ORCH") is None, "production must run BYOK mode (no preset orchestrator)"

# Hard invariant: production must never run with debug on (R6).
assert not app.debug, "wsgi.app.debug must be False in production"
