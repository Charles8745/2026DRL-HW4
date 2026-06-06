from harness.retrieval.bm25 import BM25Index
from harness.retrieval.vectorstore import VectorStore

RRF_K = 60
CANDIDATE_N = 10
FINAL_K = 5
SNIPPET_CHARS = 200


def _doc_text(c: dict) -> str:
    return f'{c["title"]}｜{c["brand"]}｜{c["usage"]}｜{c["description"]}'


def _snippet(description: str) -> str:
    return description.split("【規格】")[0].strip()[:SNIPPET_CHARS]


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

    def __init__(self, catalog: list[dict], embedder, reranker):
        self.catalog = catalog
        self._by_title = {c["title"]: c for c in catalog}
        self.embedder = embedder
        self.reranker = reranker
        doc_ids = [c["title"] for c in catalog]
        texts = [_doc_text(c) for c in catalog]
        self.bm25 = BM25Index(doc_ids, texts)
        self.vstore = VectorStore(doc_ids, embedder.embed(texts))  # build-time embed
        self.last_trace: dict = {"dense_skipped": False, "rerank_skipped": False}

    def retrieve(self, query: str, k: int = FINAL_K,
                 use_dense: bool = True, use_rerank: bool = True) -> list[dict]:
        trace = {"dense_skipped": False, "rerank_skipped": False}
        lists = [(self.bm25.search(query), True)]
        if use_dense:
            try:
                qvec = self.embedder.embed([query])[0]
                lists.append((self.vstore.query(qvec, top_n=len(self.catalog)), False))
            except Exception:
                trace["dense_skipped"] = True
        candidates = _rrf(lists)[:CANDIDATE_N]
        if use_rerank and len(candidates) > 1:
            cand_objs = [{"doc_id": t, "title": t,
                          "snippet": _snippet(self._by_title[t]["description"])}
                         for t in candidates]
            try:
                candidates = self.reranker.rerank(query, cand_objs)
            except Exception:
                trace["rerank_skipped"] = True
        self.last_trace = trace
        out = []
        for rank, t in enumerate(candidates[:k]):
            c = self._by_title[t]
            out.append({"title": t, "brand": c["brand"], "usage": c["usage"],
                        "specs": c.get("specs", {}),
                        "snippet": _snippet(c["description"]),
                        "retrieval_rank": rank})
        return out
