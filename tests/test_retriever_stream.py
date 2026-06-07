"""M0 golden-ranking guard: retrieve() must return a bit-identical ranking
before/after on_substep instrumentation, across all 3 ablation combos. Plus
read-only snapshot-shape assertions. All Fake*, zero real network."""
from de.data.store import DataStore
from be.harness.embedder import FakeEmbedder
from be.harness.reranker import FakeReranker
from be.harness.retrieval.retriever import HybridRetriever

_ABLATIONS = [
    {"use_dense": True, "use_rerank": True},
    {"use_dense": True, "use_rerank": False},
    {"use_dense": False, "use_rerank": False},
]
_QUERY = "通勤省油速克達"


def _fresh():
    store = DataStore(seed=42)
    return HybridRetriever(store.catalog, FakeEmbedder(64), FakeReranker())


def test_ranking_bit_identical_with_and_without_on_substep():
    for ab in _ABLATIONS:
        r = _fresh()
        golden = r.retrieve(_QUERY, k=10, **ab)                       # no observer
        r2 = _fresh()
        observed = r2.retrieve(_QUERY, k=10, on_substep=lambda *a: None, **ab)  # with observer
        assert observed == golden, f"ranking diverged under {ab}"


def test_observer_exception_does_not_change_ranking():
    def boom(*a, **k):
        raise RuntimeError("observer blew up")
    for ab in _ABLATIONS:
        r = _fresh()
        golden = r.retrieve(_QUERY, k=10, **ab)
        r2 = _fresh()
        observed = r2.retrieve(_QUERY, k=10, on_substep=boom, **ab)
        assert observed == golden, f"raising observer mutated ranking under {ab}"


def test_substep_phase_order_and_skipped_flags_full_pipeline():
    r = _fresh()
    subs = []
    r.retrieve(_QUERY, k=5, use_dense=True, use_rerank=True,
               on_substep=lambda et, d: subs.append((et, d)))
    phases = [d["phase"] for _, d in subs]
    assert phases == ["bm25", "vector", "rrf", "rerank"]
    assert all(et == "retrieval" for et, _ in subs)
    by_phase = {d["phase"]: d for _, d in subs}
    assert by_phase["vector"]["skipped"] is False
    assert by_phase["rerank"]["skipped"] is False
    # each snapshot carries a read-only `top` list of {title, score|null, rank} + k
    for _, d in subs:
        assert set(d) >= {"phase", "skipped", "top", "k"}
        for item in d["top"]:
            assert set(item) == {"title", "score", "rank"}


def test_substep_dense_skipped_when_no_vstore():
    r = _fresh()
    r.vstore = None                      # simulate dense unavailable (API down)
    subs = []
    r.retrieve(_QUERY, k=5, use_dense=True, use_rerank=False,
               on_substep=lambda et, d: subs.append((et, d)))
    by_phase = {d["phase"]: d for _, d in subs}
    assert by_phase["vector"]["skipped"] is True
    assert by_phase["vector"]["top"] == []


def test_substep_rerank_skipped_flag_when_disabled():
    r = _fresh()
    subs = []
    r.retrieve(_QUERY, k=5, use_dense=True, use_rerank=False,
               on_substep=lambda et, d: subs.append((et, d)))
    by_phase = {d["phase"]: d for _, d in subs}
    assert by_phase["rerank"]["skipped"] is True
