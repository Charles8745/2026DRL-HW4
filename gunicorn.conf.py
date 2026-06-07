"""Gunicorn config for RideButler.

SSE-safe + single-instance HARD CLAMP. RideButler keeps real state in process
memory (SessionStore._sessions, CorpusEmbeddingCache, vector index, live SSE
connections) — multiple workers would each hold a divergent copy. We therefore
force workers=1 regardless of WEB_CONCURRENCY, and refuse to boot if a platform
still forces >1.

worker_class='gthread' (NOT sync: sync buffers the whole response and destroys
streaming; NOT gevent: it monkeypatches the openai SDK socket).
"""
import os
import sys

# --- bind / process model ---------------------------------------------------
bind = os.getenv("BIND", "0.0.0.0:" + os.getenv("PORT", "8000"))
worker_class = "gthread"

# HARD CLAMP: read WEB_CONCURRENCY (so the intent is visible in logs) but force 1.
_requested = int(os.getenv("WEB_CONCURRENCY", "1") or "1")
workers = 1

# Threads carry concurrency within the single worker (env-tunable).
threads = int(os.getenv("GUNICORN_THREADS", "8") or "8")

# --- SSE-safe timeouts ------------------------------------------------------
timeout = 120            # generous; per-turn wall-clock cap lives in StreamRunner
graceful_timeout = 30
keepalive = 5

# --- working dir + logging --------------------------------------------------
chdir = os.path.dirname(os.path.abspath(__file__))   # repo root
accesslog = "-"          # stdout
errorlog = "-"           # stderr
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
# Access-log format WITHOUT request body and WITHOUT any header that could
# carry a key (no %(headers)s, no X-RideButler-Key).
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms'


def on_starting(server):
    """Boot self-check: refuse to start if anything forced workers > 1 (R11)."""
    n = getattr(getattr(server, "cfg", None), "workers", 1)
    if n and int(n) > 1:
        sys.stderr.write(
            "FATAL: RideButler is single-instance only; workers=%s requested "
            "but >1 splits session/index/SSE state. Set WEB_CONCURRENCY=1.\n" % n
        )
        raise SystemExit(1)
    if _requested > 1:
        sys.stderr.write(
            "NOTE: WEB_CONCURRENCY=%s was requested but hard-clamped to 1.\n" % _requested
        )
