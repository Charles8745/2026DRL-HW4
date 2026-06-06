import jieba
from rank_bm25 import BM25Okapi


def tokenize(text: str) -> list[str]:
    return [t for t in jieba.lcut(text) if t.strip()]


class BM25Index:
    """BM25 over jieba-tokenized docs. search() returns ALL docs ranked (no
    truncation), with lexicographic doc_id tie-break for determinism."""

    def __init__(self, doc_ids: list[str], texts: list[str]):
        self.doc_ids = list(doc_ids)
        self._bm25 = BM25Okapi([tokenize(t) for t in texts])

    def search(self, query: str) -> list[tuple[str, float]]:
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(self.doc_ids)),
                       key=lambda i: (-scores[i], self.doc_ids[i]))
        return [(self.doc_ids[i], float(scores[i])) for i in order]
