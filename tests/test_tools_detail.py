from data.store import DataStore
from harness.tools import get_listing_detail, compare_models

S = DataStore(seed=42)

def test_detail_includes_specs_and_condition():
    lid = S.listings[0]["listing_id"]
    r = get_listing_detail(S, lid)
    assert r["ok"] and "specs" in r["data"] and "condition" in r["data"]

def test_detail_unknown_id_errors():
    r = get_listing_detail(S, "L999")
    assert not r["ok"] and "找不到" in r["error"]

def test_compare_uses_sentinel_for_missing_hp():
    r = compare_models(S, "Ninja ZX-10R (ZX-1002L)", "YZF-R9")
    assert r["ok"]
    zx = r["data"]["Ninja ZX-10R (ZX-1002L)"]
    assert zx["horsepower"] == "資料未提供"          # missing hp -> sentinel, not fabricated

def test_compare_unknown_model_errors():
    r = compare_models(S, "NoSuchBike", "YZF-R9")
    assert not r["ok"]
