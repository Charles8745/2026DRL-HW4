import threading

from be.harness.retrieval.vectorstore import VectorStore


class CorpusEmbeddingCache:
    """Process-level cache of corpus VectorStores keyed by embed_model.

    Stores only numpy vectors + doc_ids (zero key material). Embeds once on miss
    under a per-key double-checked build lock; on embed failure returns None
    WITHOUT storing (transient miss -> the next valid request retries; never
    poison the cache)."""

    def __init__(self):
        self._lock = threading.Lock()          # guards _store / _build_locks
        self._store: dict[str, VectorStore] = {}
        self._build_locks: dict[str, threading.Lock] = {}

    def _lock_for(self, key: str) -> threading.Lock:
        with self._lock:
            lk = self._build_locks.get(key)
            if lk is None:
                lk = self._build_locks[key] = threading.Lock()
            return lk

    def get_or_build(self, embed_model: str, doc_ids: list[str],
                     texts: list[str], embedder) -> "VectorStore | None":
        # fast path: hit (no embed, no key needed)
        hit = self._store.get(embed_model)
        if hit is not None:
            return hit
        build_lock = self._lock_for(embed_model)
        with build_lock:
            # double-checked: another thread may have built it while we waited
            hit = self._store.get(embed_model)
            if hit is not None:
                return hit
            try:
                vectors = embedder.embed(texts)          # embed once
                vstore = VectorStore(list(doc_ids), vectors)
            except Exception:
                return None                              # transient miss -> do NOT store (no poison)
            with self._lock:
                self._store[embed_model] = vstore        # store only on success
            return vstore
