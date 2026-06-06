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
    assert isinstance(r["data"], list) and r["data"]
    row = r["data"][0]
    assert "listing_id" in row and "asking_price" in row
    assert "match_snippet" in row and "retrieval_rank" in row
    assert "model" in row and "brand" in row


def test_semantic_search_only_in_sale():
    s = _store()
    for row in semantic_search(s, query="重機")["data"]:
        assert s.listing(row["listing_id"])["status"] == "在售"


def test_semantic_search_budget_filter():
    s = _store()
    rows = semantic_search(s, query="重機", budget=120000)["data"]
    assert all(row["asking_price"] <= 120000 for row in rows)


def test_semantic_search_usage_filter():
    s = _store()
    rows = semantic_search(s, query="重機", usage="scooter")["data"]
    assert all(row["usage"] == "scooter" for row in rows)


def test_semantic_search_empty_returns_ok_empty():
    s = _store()
    r = semantic_search(s, query="重機", budget=1)   # nothing this cheap
    assert r["ok"] is True and r["data"] == []
