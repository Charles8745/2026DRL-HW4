import json
from typing import Protocol

RERANK_SYS = (
    "你是檢索重排器。根據查詢與候選車款，將候選由最相關到最不相關排序。"
    "只輸出一個 JSON 陣列，元素為候選的 doc_id 字串，不要任何其他文字。"
)


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[dict]) -> list[str]: ...


class FakeReranker:
    """Deterministic offline reranker: by char-overlap with the query, with a
    stable tie-break that preserves input (RRF) order on ties."""

    def rerank(self, query: str, candidates: list[dict]) -> list[str]:
        qset = set(query)

        def overlap(c: dict) -> int:
            text = c.get("title", "") + c.get("snippet", "")
            return sum(1 for ch in qset if ch in text)

        order = sorted(range(len(candidates)), key=lambda i: (-overlap(candidates[i]), i))
        return [candidates[i]["doc_id"] for i in order]


class LLMReranker:
    """Listwise LLM reranker. Strict contract: returns a full reordering of the
    candidate doc_ids, or raises ValueError on malformed JSON / any id mismatch
    (the caller then keeps RRF order and marks rerank_skipped). No fuzzy matching."""

    def __init__(self, llm):
        self.llm = llm

    def rerank(self, query: str, candidates: list[dict]) -> list[str]:
        ids = [c["doc_id"] for c in candidates]
        listing = "\n".join(
            f'- doc_id={c["doc_id"]!r}｜{c["title"]}｜{c.get("snippet", "")}'
            for c in candidates
        )
        prompt = f"查詢：{query}\n候選：\n{listing}"
        resp = self.llm.generate(RERANK_SYS, [{"role": "user", "content": prompt}], tools=None)
        try:
            arr = json.loads((resp.text or "").strip())
            returned = [str(x) for x in arr]
        except Exception as e:
            raise ValueError(f"rerank parse failed: {e}")
        if len(returned) != len(ids) or set(returned) != set(ids):
            raise ValueError("rerank id set mismatch")
        return returned
