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
            if len(texts) == 1:
                raise RuntimeError("api down")
            return FakeEmbedder(64).embed(texts)

    r = HybridRetriever(CATALOG, Boom(), FakeReranker())
    out = r.retrieve("通勤速克達", k=2)
    assert r.last_trace["dense_skipped"] is True
    assert out


def test_retrieve_degrades_when_reranker_raises():
    class BoomRerank:
        def rerank(self, q, c):
            raise ValueError("bad")

    r = HybridRetriever(CATALOG, FakeEmbedder(64), BoomRerank())
    out = r.retrieve("通勤速克達", k=2)
    assert r.last_trace["rerank_skipped"] is True
    assert out
