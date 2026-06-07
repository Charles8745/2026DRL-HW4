from de.data.catalog import load_catalog
from de.data.listings import synth_listings

def test_deterministic_with_seed():
    cat = load_catalog()
    a = synth_listings(cat, seed=42)
    b = synth_listings(cat, seed=42)
    assert [x["listing_id"] for x in a] == [x["listing_id"] for x in b]
    assert a[0]["asking_price"] == b[0]["asking_price"]

def test_every_listing_joins_catalog_exactly():
    cat = load_catalog()
    titles = {c["title"] for c in cat}
    for l in synth_listings(cat, seed=42):
        assert l["model"] in titles            # exact-string join, no fuzzy match

def test_price_within_floor_and_msrp():
    cat = {c["title"]: c for c in load_catalog()}
    for l in synth_listings(list(cat.values()), seed=42):
        msrp = cat[l["model"]]["price"]
        assert 30000 <= l["asking_price"] <= msrp     # floored, never above MSRP

def test_condition_and_status_valid():
    for l in synth_listings(load_catalog(), seed=42):
        assert l["condition"] in {"A","B","C"}
        assert l["status"] in {"在售","已售出","保留中"}
