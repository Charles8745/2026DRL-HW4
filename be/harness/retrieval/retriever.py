import re

from be.harness.retrieval.bm25 import BM25Index
from be.harness.retrieval.vectorstore import VectorStore

RRF_K = 60
CANDIDATE_N = 10
FINAL_K = 5
SNIPPET_CHARS = 200

# 5+ digit runs (e.g. marketing "76,000輛" sales-volume) — stripped from the snippet so
# the LLM can't quote a non-price big number that the price-only groundedness check would flag.
_BIGNUM = re.compile(r"\d[\d,]{4,}")


def _doc_text(c: dict) -> str:
    return f'{c["title"]}｜{c["brand"]}｜{c["usage"]}｜{c["description"]}'


def _snippet(description: str) -> str:
    head = description.split("【規格】")[0].strip()[:SNIPPET_CHARS]
    return _BIGNUM.sub("", head)


def _rrf(ranked_lists: list[tuple[list[tuple[str, float]], bool]], k: int = RRF_K) -> list[str]:
    """ranked_lists: [(ranked[(doc_id, score)], is_bm25)]. Returns fused doc_ids
    descending by RRF score; tie-break = higher BM25 score, then doc_id."""
    scores: dict[str, float] = {}
    bm25_score: dict[str, float] = {}
    for ranked, is_bm25 in ranked_lists:
        for rank, (doc_id, s) in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            if is_bm25:
                bm25_score[doc_id] = s
    return sorted(scores, key=lambda d: (-scores[d], -bm25_score.get(d, 0.0), d))


class HybridRetriever:
    """Hybrid retrieval over catalog models: BM25 (sparse) + dense (RAG) fused by
    RRF, then optional LLM listwise rerank. retrieve() returns ranked model dicts;
    listing expansion lives in the semantic_search tool."""

    def __init__(self, catalog: list[dict], embedder, reranker, *, vstore=None):
        self.catalog = catalog
        self._by_title = {c["title"]: c for c in catalog}
        self.embedder = embedder
        self.reranker = reranker
        doc_ids = [c["title"] for c in catalog]
        texts = [_doc_text(c) for c in catalog]
        self.bm25 = BM25Index(doc_ids, texts)
        if vstore is not None:
            self.vstore = vstore   # reuse cached VectorStore -> SKIP build-time embed
        else:
            try:
                self.vstore = VectorStore(doc_ids, embedder.embed(texts))  # build-time embed
            except Exception:
                self.vstore = None   # dense unavailable (API down) -> retrieve() degrades to BM25-only
        self.last_trace: dict = {"dense_skipped": False, "rerank_skipped": False}

    def retrieve(self, query: str, k: int = FINAL_K,
                 use_dense: bool = True, use_rerank: bool = True,
                 on_substep=None) -> list[dict]:
        trace = {"dense_skipped": False, "rerank_skipped": False}
        bm25_ranked = self.bm25.search(query)
        lists = [(bm25_ranked, True)]
        self._sub(on_substep, "bm25", False, bm25_ranked, k)   # snapshot already-computed bm25
        dense_ranked = []
        if use_dense:
            if self.vstore is None:
                trace["dense_skipped"] = True
            else:
                try:
                    qvec = self.embedder.embed([query])[0]
                    dense_ranked = self.vstore.query(qvec, top_n=len(self.catalog))
                    lists.append((dense_ranked, False))
                except Exception:
                    trace["dense_skipped"] = True
                    dense_ranked = []
        self._sub(on_substep, "vector", trace["dense_skipped"], dense_ranked, k)
        candidates = _rrf(lists)[:CANDIDATE_N]
        self._sub(on_substep, "rrf", False, [(t, None) for t in candidates], k)  # rrf doc_ids (no score)
        rerank_skipped = not (use_rerank and len(candidates) > 1)
        if use_rerank and len(candidates) > 1:
            cand_objs = [{"doc_id": t, "title": t,
                          "snippet": _snippet(self._by_title[t]["description"])}
                         for t in candidates]
            try:
                candidates = self.reranker.rerank(query, cand_objs)
            except Exception:
                trace["rerank_skipped"] = True
                rerank_skipped = True
        self._sub(on_substep, "rerank", rerank_skipped, [(t, None) for t in candidates], k)
        self.last_trace = trace
        out = []
        for rank, t in enumerate(candidates[:k]):
            c = self._by_title[t]
            out.append({"title": t, "brand": c["brand"], "usage": c["usage"],
                        "specs": c.get("specs", {}),
                        "snippet": _snippet(c["description"]),
                        "retrieval_rank": rank})
        return out

    def _sub(self, on_substep, phase: str, skipped: bool, ranked, k: int) -> None:
        """Read-only `retrieval` substep snapshot of an ALREADY-computed ranked list.
        `ranked` = [(doc_id, score|None)]. Never recompute / re-rank / re-slice the
        pipeline; only a bounded `top` projection for display. Observer is isolated."""
        if on_substep is None:
            return
        top = [{"title": t, "score": s, "rank": i}
               for i, (t, s) in enumerate(ranked[:k])]
        try:
            on_substep("retrieval", {"phase": phase, "skipped": skipped, "top": top, "k": k})
        except Exception:
            pass
