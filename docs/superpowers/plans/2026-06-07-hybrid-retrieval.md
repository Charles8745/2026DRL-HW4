# Hybrid Retrieval Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hybrid retrieval stage (BM25 + OpenAI dense/RAG + LLM listwise rerank, fused by RRF) to the「找車推薦」domain as a read-only `semantic_search` tool, so natural-language/lifestyle queries find bikes; plus an ablation eval (recall@k/MRR/nDCG) quantifying each stage.

**Architecture:** Catalog (33 models) is indexed at model level. `HybridRetriever.retrieve()` returns ranked model dicts (used by the ablation eval); the `semantic_search` tool expands top-k models to their 在售 listings (reusing `_enrich`) and returns a **flat listing list** so existing groundedness (`_facts_from_trace`) and ordinal reference (`set_viewed`) work with near-zero change. Embeddings + reranker sit behind `Embedder`/`Reranker` Protocols with deterministic `Fake*` implementations for offline tests, mirroring the existing `LLM`/`FakeLLM` pattern.

**Tech Stack:** Python 3.10 (project `.venv`), `rank_bm25`, `jieba`, `numpy`, OpenAI `text-embedding-3-small` + `gpt-4.1-mini`, pytest. All unit tests offline via `FakeEmbedder`/`FakeReranker`/`FakeLLM`.

**Spec:** `docs/superpowers/specs/2026-06-07-hybrid-retrieval-bm25-rag-rerank-design.md`

**Conventions:** Run everything inside the venv: `source .venv/bin/activate`. Commit identity: `git -c user.name="Charles" -c user.email="charles@j-tcg.com"`. Commit messages end with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Work on branch `feat/hybrid-retrieval`.

---

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `requirements.txt` | add rank_bm25 / jieba / numpy pins | Modify |
| `config.py` | add `EMBED_MODEL` | Modify |
| `.env.example` | document `OPENAI_EMBED_MODEL` | Modify |
| `harness/embedder.py` | `Embedder` Protocol, `OpenAIEmbedder`, `FakeEmbedder` | Create |
| `harness/reranker.py` | `Reranker` Protocol, `LLMReranker`, `FakeReranker` | Create |
| `harness/retrieval/__init__.py` | export `HybridRetriever` + constants | Create |
| `harness/retrieval/vectorstore.py` | `VectorStore` (numpy cosine) | Create |
| `harness/retrieval/bm25.py` | `BM25Index` (jieba + rank_bm25) | Create |
| `harness/retrieval/retriever.py` | `HybridRetriever` (RRF + ablation flags) | Create |
| `harness/tools.py` | `semantic_search` + registry | Modify |
| `harness/prompts.py` | `handler_sys` domain hint | Modify |
| `harness/orchestrator.py` | `set_viewed` tuple | Modify |
| `app.py`, `eval/run_eval.py`, `eval/run_full.py` | inject `store.retriever` | Modify |
| `eval/retrieval_testset.json` | gold labels (bookable models) | Create |
| `eval/retrieval_eval.py` | metrics + ablation runner | Create |
| `eval/sem_testset.json` | 4 end-to-end sem-* cases | Create |
| `tests/test_embedder.py` … `tests/test_retrieval_eval.py` | unit tests | Create |
| `tests/test_tool_registry.py` | update 2 assertions (3 tools in 找車推薦) | Modify |
| `report/report.md`, `log.md` | §7.4/§7.5 + build log | Modify |

---

## Task 1: Dependencies + config

**Files:**
- Modify: `requirements.txt`, `config.py`, `.env.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: Add deps and install**

Edit `requirements.txt` to append:
```
rank_bm25>=0.2,<1.0
jieba>=0.42,<1.0
numpy>=1.26,<3.0
```
Run: `source .venv/bin/activate && pip install -r requirements.txt`
Expected: rank_bm25, jieba installed (numpy already present).

- [ ] **Step 2: Write failing test for EMBED_MODEL**

Append to `tests/test_config.py`:
```python
def test_embed_model_default():
    import importlib, config
    importlib.reload(config)
    assert config.EMBED_MODEL  # non-empty
    assert "embedding" in config.EMBED_MODEL
```
Run: `pytest tests/test_config.py::test_embed_model_default -v` → FAIL (no attribute).

- [ ] **Step 3: Add EMBED_MODEL to config.py**

After the `MODEL = ...` line in `config.py`:
```python
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
```
Add to `.env.example`:
```
OPENAI_EMBED_MODEL=text-embedding-3-small
```

- [ ] **Step 4: Run test** → `pytest tests/test_config.py -v` PASS.

- [ ] **Step 5: Commit**
```bash
git add requirements.txt config.py .env.example tests/test_config.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: add retrieval deps (rank_bm25/jieba/numpy) + EMBED_MODEL config

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Embedder (Protocol + FakeEmbedder + OpenAIEmbedder)

**Files:**
- Create: `harness/embedder.py`, `tests/test_embedder.py`

- [ ] **Step 1: Write failing tests**

`tests/test_embedder.py`:
```python
from harness.embedder import FakeEmbedder

def test_fake_embedder_deterministic_and_normalized():
    e = FakeEmbedder(dim=64)
    a = e.embed(["通勤省油好停的速克達"])
    b = e.embed(["通勤省油好停的速克達"])
    assert a == b                                   # deterministic
    assert len(a[0]) == 64
    norm = sum(x * x for x in a[0]) ** 0.5
    assert abs(norm - 1.0) < 1e-9                   # L2-normalized

def test_fake_embedder_similar_texts_closer_than_dissimilar():
    e = FakeEmbedder(dim=64)
    import numpy as np
    v = e.embed(["速克達 通勤 省油", "速克達 通勤 都市", "大型 仿賽 賽道 馬力"])
    v = np.asarray(v)
    sim_close = float(v[0] @ v[1])
    sim_far = float(v[0] @ v[2])
    assert sim_close > sim_far

def test_fake_embedder_empty_text_is_zero_vector():
    e = FakeEmbedder(dim=8)
    assert e.embed([""])[0] == [0.0] * 8
```
Run: `pytest tests/test_embedder.py -v` → FAIL (module missing).

- [ ] **Step 2: Implement `harness/embedder.py`**
```python
import zlib
from typing import Protocol
import config


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """Deterministic offline embedder: char-bigram counts hashed (crc32, NOT
    salted hash()) into a fixed-dim vector, L2-normalized. Reproducible across
    processes so test fixtures are portable."""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for i in range(len(t) - 1):
                idx = zlib.crc32(t[i:i + 2].encode("utf-8")) % self.dim
                v[idx] += 1.0
            norm = sum(x * x for x in v) ** 0.5
            out.append([x / norm for x in v] if norm else v)
        return out


class OpenAIEmbedder:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key or config.API_KEY)
        self.model = model or config.EMBED_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]
```

- [ ] **Step 3: Run tests** → `pytest tests/test_embedder.py -v` PASS.

- [ ] **Step 4: Commit**
```bash
git add harness/embedder.py tests/test_embedder.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: Embedder Protocol + FakeEmbedder + OpenAIEmbedder

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: VectorStore

**Files:**
- Create: `harness/retrieval/__init__.py`, `harness/retrieval/vectorstore.py`, `tests/test_vectorstore.py`

- [ ] **Step 1: Write failing tests**

`tests/test_vectorstore.py`:
```python
from harness.retrieval.vectorstore import VectorStore

def test_query_ranks_by_cosine():
    vs = VectorStore(["a", "b", "c"], [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]])
    ranked = vs.query([1.0, 0.0], top_n=3)
    assert [d for d, _ in ranked] == ["a", "c", "b"]

def test_query_tie_break_by_doc_id():
    vs = VectorStore(["z", "a"], [[1.0, 0.0], [1.0, 0.0]])  # identical vectors
    ranked = vs.query([1.0, 0.0], top_n=2)
    assert [d for d, _ in ranked] == ["a", "z"]   # lexicographic tie-break

def test_query_top_n_truncates():
    vs = VectorStore(["a", "b", "c"], [[1, 0], [0, 1], [0.5, 0.5]])
    assert len(vs.query([1.0, 0.0], top_n=2)) == 2
```
Run → FAIL.

- [ ] **Step 2: Implement**

`harness/retrieval/__init__.py`:
```python
from harness.retrieval.retriever import (
    HybridRetriever, RRF_K, CANDIDATE_N, FINAL_K, SNIPPET_CHARS,
)

__all__ = ["HybridRetriever", "RRF_K", "CANDIDATE_N", "FINAL_K", "SNIPPET_CHARS"]
```
> NOTE: `__init__.py` imports `retriever`, created in Task 6. Until then, import `VectorStore`/`BM25Index` directly from their modules in tests (as the tests above do). If running Task 3 in isolation breaks collection, temporarily leave `__init__.py` empty and add the exports in Task 6.

Create `harness/retrieval/__init__.py` **empty** for now; the exports above are added in Task 6.

`harness/retrieval/vectorstore.py`:
```python
import numpy as np


class VectorStore:
    """In-memory cosine index. Vectors L2-normalized at construction;
    query returns ranked (doc_id, score) with lexicographic doc_id tie-break."""

    def __init__(self, doc_ids: list[str], vectors: list[list[float]]):
        self.doc_ids = list(doc_ids)
        mat = np.asarray(vectors, dtype=float)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.matrix = mat / norms

    def query(self, qvec: list[float], top_n: int) -> list[tuple[str, float]]:
        q = np.asarray(qvec, dtype=float)
        n = np.linalg.norm(q)
        if n:
            q = q / n
        sims = self.matrix @ q
        order = sorted(range(len(self.doc_ids)),
                       key=lambda i: (-sims[i], self.doc_ids[i]))
        return [(self.doc_ids[i], float(sims[i])) for i in order[:top_n]]
```

- [ ] **Step 3: Run tests** → PASS.

- [ ] **Step 4: Commit**
```bash
git add harness/retrieval/__init__.py harness/retrieval/vectorstore.py tests/test_vectorstore.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: VectorStore (numpy cosine, deterministic tie-break)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: BM25Index

**Files:**
- Create: `harness/retrieval/bm25.py`, `tests/test_bm25.py`

- [ ] **Step 1: Write failing tests**

`tests/test_bm25.py`:
```python
from harness.retrieval.bm25 import BM25Index, tokenize

def test_tokenize_chinese_drops_blanks():
    toks = tokenize("速克達 通勤 省油")
    assert "速克達" in toks
    assert "" not in toks and " " not in toks

def test_bm25_ranks_relevant_doc_first():
    idx = BM25Index(
        ["scooter", "sport"],
        ["速克達 都市通勤 省油 好停 輕巧", "仿賽 賽道 高馬力 戰鬥坐姿"],
    )
    ranked = idx.search("通勤省油的速克達")
    assert ranked[0][0] == "scooter"

def test_bm25_returns_all_docs():
    idx = BM25Index(["a", "b", "c"], ["x", "y", "z"])
    assert len(idx.search("x")) == 3
```
Run → FAIL.

- [ ] **Step 2: Implement `harness/retrieval/bm25.py`**
```python
import jieba
from rank_bm25 import BM25Okapi


def tokenize(text: str) -> list[str]:
    return [t for t in jieba.lcut(text) if t.strip()]


class BM25Index:
    """BM25 over jieba-tokenized docs. search() returns ALL docs ranked
    (no truncation), with lexicographic doc_id tie-break."""

    def __init__(self, doc_ids: list[str], texts: list[str]):
        self.doc_ids = list(doc_ids)
        self._bm25 = BM25Okapi([tokenize(t) for t in texts])

    def search(self, query: str) -> list[tuple[str, float]]:
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(self.doc_ids)),
                       key=lambda i: (-scores[i], self.doc_ids[i]))
        return [(self.doc_ids[i], float(scores[i])) for i in order]
```

- [ ] **Step 3: Run tests** → PASS (first run imports jieba dict, ~0.5s).

- [ ] **Step 4: Commit**
```bash
git add harness/retrieval/bm25.py tests/test_bm25.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: BM25Index (jieba tokenization, full-corpus ranking)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Reranker (Protocol + FakeReranker + LLMReranker)

**Files:**
- Create: `harness/reranker.py`, `tests/test_reranker.py`

- [ ] **Step 1: Write failing tests**

`tests/test_reranker.py`:
```python
import pytest
from harness.reranker import FakeReranker, LLMReranker
from harness.llm import FakeLLM, LLMResponse

CANDS = [
    {"doc_id": "scooter", "title": "scooter", "snippet": "速克達 通勤 省油"},
    {"doc_id": "sport", "title": "sport", "snippet": "仿賽 賽道 馬力"},
]

def test_fake_reranker_orders_by_query_overlap():
    out = FakeReranker().rerank("通勤省油", CANDS)
    assert out[0] == "scooter"

def test_fake_reranker_tie_break_preserves_input_order():
    cands = [{"doc_id": "b", "title": "b", "snippet": ""},
             {"doc_id": "a", "title": "a", "snippet": ""}]
    assert FakeReranker().rerank("zzz", cands) == ["b", "a"]  # no overlap → stable

def test_llm_reranker_parses_json_array():
    llm = FakeLLM([LLMResponse(text='["sport", "scooter"]', tool_calls=[], total_tokens=5)])
    assert LLMReranker(llm).rerank("q", CANDS) == ["sport", "scooter"]

def test_llm_reranker_raises_on_unknown_id():
    llm = FakeLLM([LLMResponse(text='["nope", "scooter"]', tool_calls=[], total_tokens=5)])
    with pytest.raises(ValueError):
        LLMReranker(llm).rerank("q", CANDS)

def test_llm_reranker_raises_on_count_mismatch():
    llm = FakeLLM([LLMResponse(text='["scooter"]', tool_calls=[], total_tokens=5)])
    with pytest.raises(ValueError):
        LLMReranker(llm).rerank("q", CANDS)

def test_llm_reranker_raises_on_malformed_json():
    llm = FakeLLM([LLMResponse(text="not json", tool_calls=[], total_tokens=5)])
    with pytest.raises(ValueError):
        LLMReranker(llm).rerank("q", CANDS)
```
> Verify `FakeLLM`/`LLMResponse` import paths and constructor in `harness/llm.py` before running; adjust the `LLMResponse(...)` kwargs to match (it has `text`, `tool_calls`, `total_tokens`).

Run → FAIL.

- [ ] **Step 2: Implement `harness/reranker.py`**
```python
import json
from typing import Protocol

RERANK_SYS = (
    "你是檢索重排器。根據查詢與候選車款，將候選由最相關到最不相關排序。"
    "只輸出一個 JSON 陣列，元素為候選的 doc_id 字串，不要任何其他文字。"
)


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[dict]) -> list[str]: ...


class FakeReranker:
    """Deterministic offline reranker: by char-overlap with query desc,
    stable tie-break preserving input (RRF) order."""

    def rerank(self, query: str, candidates: list[dict]) -> list[str]:
        qset = set(query)

        def overlap(c: dict) -> int:
            text = c.get("title", "") + c.get("snippet", "")
            return sum(1 for ch in qset if ch in text)

        order = sorted(range(len(candidates)), key=lambda i: (-overlap(candidates[i]), i))
        return [candidates[i]["doc_id"] for i in order]


class LLMReranker:
    """Listwise LLM reranker. Strict contract: returns a full reordering of the
    candidate doc_ids. Raises ValueError on malformed JSON or any id mismatch
    (caller keeps RRF order + marks rerank_skipped). No fuzzy matching."""

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
```

- [ ] **Step 3: Run tests** → PASS.

- [ ] **Step 4: Commit**
```bash
git add harness/reranker.py tests/test_reranker.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: Reranker Protocol + FakeReranker + LLMReranker (strict contract)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: HybridRetriever (RRF + ablation flags) + package exports

**Files:**
- Create: `harness/retrieval/retriever.py`, `tests/test_retriever.py`
- Modify: `harness/retrieval/__init__.py` (add exports)

- [ ] **Step 1: Write failing tests**

`tests/test_retriever.py`:
```python
from harness.embedder import FakeEmbedder
from harness.reranker import FakeReranker
from harness.retrieval.retriever import HybridRetriever, _rrf, _snippet

CATALOG = [
    {"title": "Scoot", "brand": "Yamaha", "usage": "scooter",
     "description": "速克達 都市通勤 省油 輕巧 好停【規格】排氣量:155", "specs": {"displacement_cc": 155}},
    {"title": "Race", "brand": "Honda", "usage": "sport",
     "description": "仿賽 賽道 高馬力 戰鬥坐姿【規格】排氣量:1000", "specs": {"displacement_cc": 1000}},
    {"title": "Tour", "brand": "Kawasaki", "usage": "touring",
     "description": "長途 環島 舒適 風鏡 大旅行【規格】排氣量:1043", "specs": {"displacement_cc": 1043}},
]

def _retriever():
    return HybridRetriever(CATALOG, FakeEmbedder(dim=64), FakeReranker())

def test_rrf_fuses_two_lists():
    bm25 = [("a", 2.0), ("b", 1.0), ("c", 0.0)]
    dense = [("b", 0.9), ("a", 0.8), ("c", 0.1)]
    assert _rrf([(bm25, True), (dense, False)])[0] in ("a", "b")

def test_snippet_strips_spec_block_and_truncates():
    s = _snippet("行銷文字很長" * 50 + "【規格】排氣量:155")
    assert "【規格】" not in s
    assert len(s) <= 200

def test_retrieve_returns_models_with_rank():
    out = _retriever().retrieve("通勤省油好停的速克達", k=2)
    assert out[0]["title"] == "Scoot"
    assert out[0]["retrieval_rank"] == 0
    assert "snippet" in out[0] and "specs" in out[0]

def test_retrieve_ablation_flags_change_pipeline():
    r = _retriever()
    bm25_only = [m["title"] for m in r.retrieve("仿賽賽道", k=3, use_dense=False, use_rerank=False)]
    full = [m["title"] for m in r.retrieve("仿賽賽道", k=3, use_dense=True, use_rerank=True)]
    assert isinstance(bm25_only, list) and isinstance(full, list)
    assert bm25_only[0] == "Race"

def test_retrieve_degrades_when_embedder_raises():
    class Boom:
        def embed(self, texts):
            if len(texts) == 1:           # query-time embed
                raise RuntimeError("api down")
            return FakeEmbedder(64).embed(texts)  # construction-time ok
    r = HybridRetriever(CATALOG, Boom(), FakeReranker())
    out = r.retrieve("通勤速克達", k=2)        # must not raise
    assert r.last_trace["dense_skipped"] is True
    assert out  # still returns BM25 results

def test_retrieve_degrades_when_reranker_raises():
    class BoomRerank:
        def rerank(self, q, c):
            raise ValueError("bad")
    r = HybridRetriever(CATALOG, FakeEmbedder(64), BoomRerank())
    out = r.retrieve("通勤速克達", k=2)
    assert r.last_trace["rerank_skipped"] is True
    assert out
```
Run → FAIL.

- [ ] **Step 2: Implement `harness/retrieval/retriever.py`**
```python
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
    """ranked_lists: [(ranked[(doc_id,score)], is_bm25)]. Returns fused doc_ids
    desc by RRF; tie-break: higher BM25 score, then doc_id lexicographic."""
    scores: dict[str, float] = {}
    bm25_score: dict[str, float] = {}
    for ranked, is_bm25 in ranked_lists:
        for rank, (doc_id, s) in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            if is_bm25:
                bm25_score[doc_id] = s
    return sorted(scores, key=lambda d: (-scores[d], -bm25_score.get(d, 0.0), d))


class HybridRetriever:
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
                        "specs": c.get("specs", {}), "snippet": _snippet(c["description"]),
                        "retrieval_rank": rank})
        return out
```

- [ ] **Step 3: Add exports to `harness/retrieval/__init__.py`**
```python
from harness.retrieval.retriever import (
    HybridRetriever, RRF_K, CANDIDATE_N, FINAL_K, SNIPPET_CHARS,
)

__all__ = ["HybridRetriever", "RRF_K", "CANDIDATE_N", "FINAL_K", "SNIPPET_CHARS"]
```

- [ ] **Step 4: Run tests** → `pytest tests/test_retriever.py -v` PASS.

- [ ] **Step 5: Commit**
```bash
git add harness/retrieval/retriever.py harness/retrieval/__init__.py tests/test_retriever.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: HybridRetriever (BM25+dense RRF fusion, rerank, ablation flags, graceful degradation)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `semantic_search` tool + registry + registry-test update

**Files:**
- Modify: `harness/tools.py`, `tests/test_tool_registry.py`
- Create: `tests/test_tools_semantic.py`

- [ ] **Step 1: Write failing tests**

`tests/test_tools_semantic.py`:
```python
from data.store import DataStore
from harness.embedder import FakeEmbedder
from harness.reranker import FakeReranker
from harness.retrieval.retriever import HybridRetriever
from harness.tools import semantic_search

def _store():
    s = DataStore(seed=42)
    s.retriever = HybridRetriever(s.catalog, FakeEmbedder(dim=64), FakeReranker())
    return s

def test_semantic_search_returns_flat_listing_list():
    s = _store()
    r = semantic_search(s, query="通勤省油好停的速克達")
    assert r["ok"] is True
    assert isinstance(r["data"], list)
    if r["data"]:
        row = r["data"][0]
        assert "listing_id" in row and "asking_price" in row
        assert "match_snippet" in row and "retrieval_rank" in row
        assert "model" in row

def test_semantic_search_only_in_sale():
    s = _store()
    for row in semantic_search(s, query="重機")["data"]:
        assert s.listing(row["listing_id"])["status"] == "在售"

def test_semantic_search_budget_filter():
    s = _store()
    rows = semantic_search(s, query="重機", budget=120000)["data"]
    assert all(row["asking_price"] <= 120000 for row in rows)

def test_semantic_search_empty_when_no_match_returns_ok_empty():
    s = _store()
    rows = semantic_search(s, query="重機", budget=1)["data"]   # nothing this cheap
    assert rows == []
```

Update `tests/test_tool_registry.py`:
```python
def test_four_groups_with_two_tools_each():
    assert set(TOOL_GROUPS) == {"找車推薦", "規格比較", "交易訂單", "售後轉真人"}
    # 找車推薦 has 3 tools (incl. read-only semantic_search); others have 2
    assert len(TOOL_GROUPS["找車推薦"]) == 3
    assert all(len(v) == 2 for k, v in TOOL_GROUPS.items() if k != "找車推薦")

def test_every_tool_has_callable_and_schema():
    for names in TOOL_GROUPS.values():
        for n in names:
            assert callable(TOOL_FUNCS[n])
    schemas = schemas_for("找車推薦")
    assert {s["name"] for s in schemas} == {"search_listings", "recommend", "semantic_search"}
    assert "parameters" in schemas[0]
```
Run → FAIL.

- [ ] **Step 2: Implement in `harness/tools.py`**

Add import at top:
```python
from harness.retrieval.retriever import FINAL_K
```
Add function (after `recommend`):
```python
def semantic_search(store, query, budget=None, usage=None):
    """Hybrid retrieval (BM25 + dense RAG + rerank) over catalog models, expanded
    to in-sale listings. Returns a FLAT list of enriched listing dicts (same shape
    as search_listings, plus match_snippet / retrieval_rank) so groundedness and
    ordinal reference work unchanged."""
    models = store.retriever.retrieve(query, k=FINAL_K)
    rows = []
    for m in models:
        if usage and m["usage"] != usage:
            continue
        for l in store.listings:
            if l["model"] != m["title"] or l["status"] != "在售":
                continue
            if budget and l["asking_price"] > int(budget):
                continue
            rows.append({**_enrich(store, l),
                         "match_snippet": m["snippet"],
                         "retrieval_rank": m["retrieval_rank"]})
    return _ok(rows)
```
Register: add to `TOOL_FUNCS`:
```python
    "semantic_search": semantic_search,
```
Append to `TOOL_GROUPS["找車推薦"]` so it reads:
```python
    "找車推薦": ["search_listings", "recommend", "semantic_search"],
```
Add schema to `TOOL_SCHEMAS`:
```python
    "semantic_search": {"name": "semantic_search",
        "description": "以自然語言語意檢索車款（用途/情境/模糊偏好，如『新手通勤省油好停』），回傳相關在售刈登。查詢若已含明確品牌/車種/價格條件，請改用 search_listings 或 recommend。",
        "parameters": _p({"query": {"type": "string"},
                          "budget": {"type": "integer"},
                          "usage": {"type": "string"}}, ["query"])},
```

- [ ] **Step 3: Run tests** → `pytest tests/test_tools_semantic.py tests/test_tool_registry.py -v` PASS.

- [ ] **Step 4: Commit**
```bash
git add harness/tools.py tests/test_tools_semantic.py tests/test_tool_registry.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: semantic_search tool (flat listing list) + register in 找車推薦; update registry test

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Orchestrator set_viewed + handler prompt hint

**Files:**
- Modify: `harness/orchestrator.py`, `harness/prompts.py`
- Test: `tests/test_orchestrator.py`, `tests/test_prompts.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_prompts.py`:
```python
def test_handler_sys_find_domain_has_tool_selection_hint():
    from harness.prompts import handler_sys
    s = handler_sys("找車推薦")
    assert "semantic_search" in s
    other = handler_sys("交易訂單")
    assert "semantic_search" not in other
```

Append to `tests/test_orchestrator.py` (a FakeLLM-driven two-turn test; mirror the existing scripted-LLM style already in that file — inspect it first for the exact `Orchestrator`/`FakeLLM`/`SessionStore` wiring and the `ToolCall`/`LLMResponse` constructors):
```python
def test_semantic_search_sets_viewed_for_ordinal_reference():
    from data.store import DataStore
    from harness.memory import SessionStore
    from harness.orchestrator import Orchestrator
    from harness.embedder import FakeEmbedder
    from harness.reranker import FakeReranker
    from harness.retrieval.retriever import HybridRetriever
    from harness.llm import FakeLLM, LLMResponse, ToolCall

    store = DataStore(seed=42)
    store.retriever = HybridRetriever(store.catalog, FakeEmbedder(64), FakeReranker())
    # Scripted: turn-1 rewriter, router->找車推薦, handler calls semantic_search then replies.
    llm = FakeLLM([
        LLMResponse(text="想找通勤省油好停的速克達", tool_calls=[], total_tokens=1),        # rewrite
        LLMResponse(text="找車推薦", tool_calls=[], total_tokens=1),                          # route
        LLMResponse(text="", tool_calls=[ToolCall("semantic_search", {"query": "通勤省油速克達"})], total_tokens=1),
        LLMResponse(text="幫你找到幾台速克達。", tool_calls=[], total_tokens=1),               # final reply
    ])
    orch = Orchestrator(llm, store, SessionStore())
    sid = orch.memory.new_session()
    out = orch.process(sid, "想找通勤省油好停的車")
    steps = out["trace"]["steps"]
    assert any(s["tool_name"] == "semantic_search" for s in steps)
    assert orch.memory.get(sid)["slots"]["viewed_listings"]   # set_viewed fired
```
> Adjust constructors (`LLMResponse`, `ToolCall`, `FakeLLM`) to the real signatures in `harness/llm.py`, and `SessionStore` slot key name (`viewed_listings`) to whatever `memory.py` uses (check `set_viewed`/`resolve_reference`).

Run → FAIL.

- [ ] **Step 2: Implement**

`harness/orchestrator.py` line ~71 — add `"semantic_search"` to the tuple:
```python
            if step["tool_name"] in ("search_listings", "recommend", "semantic_search") and isinstance(data, list):
```

`harness/prompts.py` — add domain hint:
```python
_DOMAIN_HINTS = {
    "找車推薦": "（工具選擇：查詢點名車種/品牌或含任何價格、年份條件時，用 search_listings 或 recommend；"
              "僅在完全沒有結構化條件、純生活情境或模糊偏好時，才用 semantic_search。）",
}
def handler_sys(domain: str) -> str:
    return _HANDLER_BASE.format(domain=domain) + _DOMAIN_HINTS.get(domain, "")
```

- [ ] **Step 3: Run tests** → `pytest tests/test_prompts.py tests/test_orchestrator.py -v` PASS.

- [ ] **Step 4: Commit**
```bash
git add harness/orchestrator.py harness/prompts.py tests/test_prompts.py tests/test_orchestrator.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: wire semantic_search into orchestrator set_viewed + handler tool-selection hint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Inject `store.retriever` at construction points

**Files:**
- Modify: `app.py`, `eval/run_eval.py`, `eval/run_full.py`
- Test: `tests/test_app.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_app.py` (inspect existing app-factory test first for the helper that builds the app/store):
```python
def test_app_store_has_retriever():
    # The app factory must attach a HybridRetriever to the store so semantic_search works.
    import app as app_module
    # If create_app builds its own store/orchestrator, assert the orchestrator's store has .retriever
    # Adjust to the real factory signature.
    application = app_module.create_app()
    assert hasattr(application.config["ORCH"].store, "retriever")
```
> This test is illustrative — read `app.py` (currently `app factory: GET /, POST /api/chat`) and adapt to how the store/orchestrator are exposed. If the factory doesn't expose them, assert via a direct construction helper instead. The REAL acceptance for this task is Step 3 (full offline suite green) + Task 12 end-to-end run.

- [ ] **Step 2: Implement injection**

In `app.py`, `eval/run_eval.py:main`, `eval/run_full.py` — wherever `DataStore(...)` + `OpenAIClient()` + `Orchestrator(...)` are built, add after building `store` and `llm`:
```python
from harness.embedder import OpenAIEmbedder
from harness.reranker import LLMReranker
from harness.retrieval.retriever import HybridRetriever
store.retriever = HybridRetriever(store.catalog, OpenAIEmbedder(), LLMReranker(llm))
```
(Place BEFORE the orchestrator processes anything. `llm` is the same `OpenAIClient` used by the orchestrator.)

- [ ] **Step 3: Run FULL offline suite** → `pytest -q`
Expected: all tests pass (original 81 + new, minus the 2 updated registry assertions which now reflect 3 tools). Record the new count.

- [ ] **Step 4: Commit**
```bash
git add app.py eval/run_eval.py eval/run_full.py tests/test_app.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: inject HybridRetriever (OpenAI embedder + LLM reranker) at app/eval construction

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Retrieval ablation testset + schema test

**Files:**
- Create: `eval/retrieval_testset.json`, `tests/test_retrieval_testset.py`

- [ ] **Step 1: Author `eval/retrieval_testset.json`** (15–20 queries; gold = bookable model titles only; relevance by description/spec evidence; gold sets 1–3; balance usage classes; exclude `XMAX`, `AFRICA TWIN ES`)

First list candidate titles + usage to label against:
Run: `source .venv/bin/activate && python -c "from data.store import DataStore; s=DataStore(); insale={l['model'] for l in s.listings if l['status']=='在售'}; [print(c['usage'], c['title']) for c in s.catalog if c['title'] in insale]"`

Then write JSON, e.g.:
```json
[
  {"id": "rt-01", "query": "新手第一台、市區通勤、好停又省油", "relevant_models": ["MT-15", "CB300R"]},
  {"id": "rt-02", "query": "想環島跑長途、坐姿舒服防風的大車", "relevant_models": ["Ninja H2SX SE (ZX1002-R)", "CB1000GT"]},
  {"id": "rt-03", "query": "預算內最有仿賽戰鬥感的車", "relevant_models": ["YZF-R3", "CBR500R"]}
]
```
> Author 15–20 entries spanning scooter/naked/sport/adventure/touring/cruiser; keep each `relevant_models` 1–3 and grounded in the model's `description`. Under-sampled classes (cruiser=1, touring=2) noted in the report.

- [ ] **Step 2: Write schema test `tests/test_retrieval_testset.py`**
```python
import json
from data.store import DataStore

def test_retrieval_testset_valid():
    s = DataStore(seed=42)
    titles = {c["title"] for c in s.catalog}
    in_sale = {l["model"] for l in s.listings if l["status"] == "在售"}
    cases = json.load(open("eval/retrieval_testset.json", encoding="utf-8"))
    assert 10 <= len(cases) <= 25
    ids = set()
    for c in cases:
        assert c["id"] not in ids; ids.add(c["id"])
        assert c["query"] and c["relevant_models"]
        for m in c["relevant_models"]:
            assert m in titles, f"{m} not in catalog"
            assert m in in_sale, f"{m} has no 在售 listing"
```

- [ ] **Step 3: Run** → `pytest tests/test_retrieval_testset.py -v` PASS.

- [ ] **Step 4: Commit**
```bash
git add eval/retrieval_testset.json tests/test_retrieval_testset.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: retrieval ablation testset (gold = bookable models) + schema test

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Metrics + ablation runner

**Files:**
- Create: `eval/retrieval_eval.py`, `tests/test_retrieval_eval.py`

- [ ] **Step 1: Write failing metric tests**

`tests/test_retrieval_eval.py`:
```python
from eval.retrieval_eval import recall_at_k, mrr, ndcg_at_k

def test_recall_capped_by_min_rel_k():
    assert recall_at_k(["a"], ["a", "b", "c"], 3) == 1.0          # |rel|=1 -> min(1,3)=1
    assert recall_at_k(["a", "b", "c", "d"], ["a", "x", "y"], 3) == 1 / 3  # 1 hit / min(4,3)

def test_mrr_first_hit():
    assert mrr(["b"], ["a", "b", "c"], k=10) == 0.5
    assert mrr(["z"], ["a", "b", "c"], k=10) == 0.0

def test_ndcg_perfect_is_one():
    assert abs(ndcg_at_k(["a", "b"], ["a", "b", "c"], 5) - 1.0) < 1e-9

def test_ndcg_zero_when_no_hit():
    assert ndcg_at_k(["z"], ["a", "b"], 5) == 0.0
```
Run → FAIL.

- [ ] **Step 2: Implement `eval/retrieval_eval.py`**
```python
import json
import math


def recall_at_k(relevant, ranked, k):
    rel = set(relevant)
    hit = sum(1 for d in ranked[:k] if d in rel)
    return hit / min(len(rel), k) if rel else 0.0


def mrr(relevant, ranked, k=10):
    rel = set(relevant)
    for i, d in enumerate(ranked[:k]):
        if d in rel:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(relevant, ranked, k=5):
    rel = set(relevant)
    dcg = sum((1.0 if d in rel else 0.0) / math.log2(i + 2) for i, d in enumerate(ranked[:k]))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(rel), k)))
    return dcg / idcg if idcg else 0.0


CONFIGS = {
    "bm25":        {"use_dense": False, "use_rerank": False, "repeats": 1},
    "bm25+dense":  {"use_dense": True,  "use_rerank": False, "repeats": 1},
    "full":        {"use_dense": True,  "use_rerank": True,  "repeats": 3},
}


def _eval_once(retriever, cases, use_dense, use_rerank):
    r1 = r3 = r5 = mr = nd = 0.0
    for c in cases:
        ranked = [m["title"] for m in retriever.retrieve(
            c["query"], k=10, use_dense=use_dense, use_rerank=use_rerank)]
        rel = c["relevant_models"]
        r1 += recall_at_k(rel, ranked, 1); r3 += recall_at_k(rel, ranked, 3)
        r5 += recall_at_k(rel, ranked, 5); mr += mrr(rel, ranked, 10)
        nd += ndcg_at_k(rel, ranked, 5)
    n = len(cases)
    return {"recall@1": r1 / n, "recall@3": r3 / n, "recall@5": r5 / n,
            "mrr@10": mr / n, "ndcg@5": nd / n}


def run_ablation(retriever, cases):
    out = {}
    for name, cfg in CONFIGS.items():
        runs = [_eval_once(retriever, cases, cfg["use_dense"], cfg["use_rerank"])
                for _ in range(cfg["repeats"])]
        keys = runs[0].keys()
        mean = {k: sum(r[k] for r in runs) / len(runs) for k in keys}
        spread = {k: (max(r[k] for r in runs) - min(r[k] for r in runs)) for k in keys}
        out[name] = {"mean": mean, "spread": spread, "repeats": cfg["repeats"]}
    # candidate-pool recall ceiling rerank operates under (RRF top-10)
    return out


def main():
    import config
    from data.store import DataStore
    from harness.openai_client import OpenAIClient
    from harness.embedder import OpenAIEmbedder
    from harness.reranker import LLMReranker
    from harness.retrieval.retriever import HybridRetriever

    cases = json.load(open("eval/retrieval_testset.json", encoding="utf-8"))
    store = DataStore(seed=42)
    llm = OpenAIClient()
    retriever = HybridRetriever(store.catalog, OpenAIEmbedder(), LLMReranker(llm))
    result = run_ablation(retriever, cases)
    print(f"# retrieval ablation  model={config.MODEL} embed={config.EMBED_MODEL}  n={len(cases)}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    json.dump(result, open("eval/retrieval_results.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run metric tests** → `pytest tests/test_retrieval_eval.py -v` PASS.

- [ ] **Step 4: Commit**
```bash
git add eval/retrieval_eval.py tests/test_retrieval_eval.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: retrieval metrics (recall@k/MRR/nDCG) + 3-config ablation runner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: sem-* end-to-end testset + frozen-testset guard

**Files:**
- Create: `eval/sem_testset.json`
- Test: `tests/test_testset.py` (append) or `tests/test_run_eval.py`

- [ ] **Step 1: Author `eval/sem_testset.json`** (3–5 cases, semantic queries that should fire `semantic_search`)
```json
[
  {"id": "sem-01", "input": "新手想找好上手、市區通勤又省油的車", "expected_tools": ["semantic_search"], "expected_domain": "找車推薦"},
  {"id": "sem-02", "input": "想要能跑長途環島、坐起來舒服的車", "expected_tools": ["semantic_search"], "expected_domain": "找車推薦"},
  {"id": "sem-03", "input": "喜歡有戰鬥感、騎起來熱血的車", "expected_tools": ["semantic_search"], "expected_domain": "找車推薦"}
]
```

- [ ] **Step 2: Write frozen-testset guard test**

Append to `tests/test_testset.py`:
```python
import json

def test_main_testset_frozen_at_27():
    cases = json.load(open("eval/testset.json", encoding="utf-8"))
    assert len(cases) == 27

def test_sem_testset_schema():
    cases = json.load(open("eval/sem_testset.json", encoding="utf-8"))
    assert 3 <= len(cases) <= 5
    for c in cases:
        assert c["expected_tools"] == ["semantic_search"]
        assert c["expected_domain"] == "找車推薦"
```

- [ ] **Step 3: Run** → `pytest tests/test_testset.py -v` PASS.

- [ ] **Step 4: Commit**
```bash
git add eval/sem_testset.json tests/test_testset.py
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "feat: sem-* end-to-end testset + frozen 27-case guard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Full offline verification

- [ ] **Step 1: Run entire suite** → `source .venv/bin/activate && pytest -q`
Expected: ALL green. Note the total count (≈ 81 + ~22 new). If any pre-existing test regressed, STOP and fix before proceeding.

- [ ] **Step 2: Sanity-run app** (manual, optional) → `python app.py`, ask「想找通勤省油好停的車」, confirm `semantic_search` fires in the trace sidebar and a grounded reply with real listings appears.

---

## Task 14: Real eval — ablation + no-regression + report

> These steps hit the real OpenAI API (cost ~ a few cents). Requires `OPENAI_API_KEY` in `.env`.

- [ ] **Step 1: Run retrieval ablation** → `python -m eval.retrieval_eval`
Capture `eval/retrieval_results.json` (three configs, full = mean of 3).

- [ ] **Step 2: No-regression on the 27-case main eval** → `python -m eval.run_full`
Compare `router_accuracy` / `task_success` / `groundedness_violation_rate` and `multiturn_chain_success` against the pre-change numbers in `report/report.md` §7.1–7.3. **find-01..05, multi-01/02 must keep their expected tools.** If find-02/find-05 regressed to `semantic_search`, tighten the `_DOMAIN_HINTS` wording (Task 8) and re-run — do NOT edit the frozen testset.

- [ ] **Step 3: Run sem-* end-to-end** (small loop reading `eval/sem_testset.json` through `orchestrator.process`, scoring `semantic_search ∈ used tools` + groundedness). Record fired/grounded.

- [ ] **Step 4: Fill report §7.4 (ablation table + RRF top-10 ceiling + rerank mean±spread + caveat) and §7.5 (sem-* results), with model id + date + non-determinism caveat. Update §2 architecture diagram. Append build log to `log.md`.**

- [ ] **Step 5: Commit**
```bash
git add report/report.md log.md eval/retrieval_results.json
git -c user.name="Charles" -c user.email="charles@j-tcg.com" commit -m "docs: report §7.4 retrieval ablation + §7.5 sem-* e2e; log build

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Notes (author)

- **Spec coverage:** every §4 module → a task (T2 embedder, T3 vectorstore, T4 bm25, T5 reranker, T6 retriever, T7 tool, T8 wiring, T9 injection, T10 testset, T11 eval, T12 sem/frozen). Error-handling (§7) covered by T6 degradation tests + T7 empty-result test. Metric defs (§8.2) → T11. Routing tie-break (§2.1) → T8 + T14 no-regression gate.
- **Risk gates:** T9 Step 3 and T13 enforce "no offline regression"; T14 Step 2 enforces "no 27-case eval regression" with an explicit find-02/find-05 fallback (tighten prompt, never edit frozen testset).
- **Cross-task type consistency:** `retrieve()` → list of model dicts (`title/brand/usage/specs/snippet/retrieval_rank`); `semantic_search` → `_ok(flat listing list)` each with `match_snippet/retrieval_rank`; reranker returns full doc_id reordering or raises; constants `FINAL_K/CANDIDATE_N/RRF_K/SNIPPET_CHARS` live in `retriever.py` and are imported where needed.
- **Adapt-on-read:** T5/T8/T9 tests reference `harness/llm.py` (`FakeLLM`/`LLMResponse`/`ToolCall`), `harness/memory.py` slot names, and `app.py` factory shape — read those files and adjust constructors/keys before running (flagged inline).
