from data.store import DataStore
from harness.tools import search_listings, recommend

S = DataStore(seed=42)

def test_search_filters_by_brand_and_price():
    r = search_listings(S, brand_pref="Yamaha", max_price=300000)
    assert r["ok"]
    for x in r["data"]:
        assert x["brand"] == "Yamaha" and x["asking_price"] <= 300000

def test_search_filters_by_usage():
    r = search_listings(S, usage="sport")
    assert r["ok"] and all(x["usage"] == "sport" for x in r["data"])

def test_recommend_respects_budget_and_returns_sorted():
    r = recommend(S, budget=300000, usage="sport")
    assert r["ok"]
    prices = [x["asking_price"] for x in r["data"]]
    assert prices == sorted(prices) and all(p <= 300000 for p in prices)

def test_recommend_empty_is_ok_with_message():
    r = recommend(S, budget=1000, usage="sport")
    assert r["ok"] and r["data"] == []
