import re

import os

import config

# Generic OpenAI-shaped key matcher used for redaction (sk- + >=20 url-safe chars).
_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
_REDACTED = "sk-***REDACTED***"


def validate_key_format(key: "str | None") -> bool:
    """UX precheck ONLY (not a security control): ^sk- prefix, len >= 20, no whitespace."""
    if not key:
        return False
    if any(ch.isspace() for ch in key):
        return False
    return key.startswith("sk-") and len(key) >= 20


def redact_key(text: str, key: "str | None") -> str:
    """Replace the literal key (if given) AND any generic sk-[A-Za-z0-9_-]{20,}
    run with 'sk-***REDACTED***'. Idempotent and safe on non-string-free text."""
    if not isinstance(text, str):
        text = str(text)
    if key:
        text = text.replace(key, _REDACTED)
    return _KEY_RE.sub(_REDACTED, text)


_LOCALHOST = {"127.0.0.1", "::1", "localhost"}


def _is_localhost(req) -> bool:
    addr = getattr(req, "remote_addr", None) or ""
    return addr in _LOCALHOST


def extract_request_key(req, *, allow_env: bool) -> "str | None":
    """Header 'X-RideButler-Key' ONLY. If allow_env, fall back to config.API_KEY,
    but the .env fallback is honored only on localhost (or with an explicit
    ALLOW_ENV_KEY_PUBLIC=1 public override). Never read a body field."""
    header_key = req.headers.get("X-RideButler-Key")
    if header_key:
        return header_key
    if not allow_env:
        return None
    public_ok = os.getenv("ALLOW_ENV_KEY_PUBLIC", "0").strip().lower() in ("1", "true", "yes", "on")
    if not (public_ok or _is_localhost(req)):
        return None              # R1: do NOT leak owner key on a public host
    return config.API_KEY or None


import copy

from be.harness.retrieval.retriever import HybridRetriever, _doc_text
from be.harness.orchestrator import Orchestrator
from de.data.store import DataStore


def _per_request_store() -> DataStore:
    """Per-request DataStore: catalog shared read-only; listings/orders/tickets are
    independent deep copies so concurrent requests never bleed mutable state."""
    store = DataStore.__new__(DataStore)
    base = _CATALOG_BASE()
    store.catalog = base.catalog                       # shared read-only
    store.listings = copy.deepcopy(base.listings)      # independent copy
    store.orders = copy.deepcopy(base.orders)          # independent copy
    store.tickets = []                                 # fresh per request
    store._catalog_by_title = base._catalog_by_title   # shared (read-only index)
    store._listings_by_id = {l["listing_id"]: l for l in store.listings}
    return store


_BASE_STORE = None


def _CATALOG_BASE() -> DataStore:
    """Process-level template DataStore (seeded once) whose catalog + synthesized
    listings/orders we copy per request. Built lazily, no key needed."""
    global _BASE_STORE
    if _BASE_STORE is None:
        _BASE_STORE = DataStore(seed=42)
    return _BASE_STORE


def build_request_orchestrator(key: str, *, model: str, embed_model: str,
                               memory, corpus_cache,
                               llm_factory=None, embedder_factory=None) -> "Orchestrator":
    """Construct an isolated per-request Orchestrator from the request key.

    - llm/embedder/reranker are built from `key` (never config.API_KEY).
    - DataStore is per-request (catalog shared read-only; listings/orders/tickets copies).
    - retriever reuses the process-level corpus VectorStore (embed-once), so the
      per-request embedder is only used for the live query, not corpus build.
    llm_factory/embedder_factory are injection points for tests (Fake/spy); in
    production they default to the real OpenAI clients."""
    from be.harness.reranker import LLMReranker
    if llm_factory is None:
        from be.harness.openai_client import OpenAIClient
        llm_factory = lambda k: OpenAIClient(api_key=k, model=model)
    if embedder_factory is None:
        from be.harness.embedder import OpenAIEmbedder
        embedder_factory = lambda k: OpenAIEmbedder(api_key=k, model=embed_model)

    llm = llm_factory(key)
    embedder = embedder_factory(key)
    reranker = LLMReranker(llm)

    store = _per_request_store()
    doc_ids = [c["title"] for c in store.catalog]
    texts = [_doc_text(c) for c in store.catalog]
    vstore = corpus_cache.get_or_build(embed_model, doc_ids, texts, embedder)
    store.retriever = HybridRetriever(store.catalog, embedder, reranker, vstore=vstore)
    return Orchestrator(llm, store, memory)
