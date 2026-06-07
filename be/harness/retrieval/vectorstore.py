import numpy as np


class VectorStore:
    """In-memory cosine index. Vectors are L2-normalized at construction; query
    returns ranked (doc_id, score) with lexicographic doc_id tie-break."""

    def __init__(self, doc_ids: list[str], vectors: list[list[float]]):
        self.doc_ids = list(doc_ids)
        mat = np.asarray(vectors, dtype=float)
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0] = 1.0          # zero vectors stay zero (no similarity)
            self.matrix = mat / norms

    def query(self, qvec: list[float], top_n: int) -> list[tuple[str, float]]:
        q = np.asarray(qvec, dtype=float)
        # Guard against degenerate (zero) vectors and any leaked global FP state;
        # the matmul of finite unit vectors is itself safe.
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            n = np.linalg.norm(q)
            if n:
                q = q / n
            sims = self.matrix @ q
        order = sorted(range(len(self.doc_ids)),
                       key=lambda i: (-sims[i], self.doc_ids[i]))
        return [(self.doc_ids[i], float(sims[i])) for i in order[:top_n]]
