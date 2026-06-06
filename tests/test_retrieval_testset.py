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
        assert c["id"] not in ids
        ids.add(c["id"])
        assert c["query"]
        assert c["relevant_models"]
        assert 1 <= len(c["relevant_models"]) <= 3
        for m in c["relevant_models"]:
            assert m in titles, f"{m} not in catalog"
            assert m in in_sale, f"{m} has no 在售 listing (unbookable gold)"
