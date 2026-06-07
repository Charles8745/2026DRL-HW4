import json
from collections import Counter
from be.eval.robustness_eval import CATEGORIES, CHECK_KEYS
from be.harness.router import LABELS

CASES = json.load(open("be/eval/robustness_testset.json", encoding="utf-8"))

def test_count_frozen():
    assert len(CASES) == 40

def test_unique_ids():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))

def test_required_fields_and_category():
    for c in CASES:
        assert {"id", "category", "input", "expect"} <= c.keys(), c["id"]
        assert c["category"] in CATEGORIES, c["id"]
        assert isinstance(c["expect"], dict) and c["expect"], c["id"]

def test_expect_keys_valid():
    for c in CASES:
        for blk in ("expect", "expect_turn2"):
            if c.get(blk):
                assert set(c[blk]) <= CHECK_KEYS, (c["id"], blk, set(c[blk]) - CHECK_KEYS)

def test_expect_turn2_requires_followup():
    for c in CASES:
        if c.get("expect_turn2"):
            assert c.get("followup"), c["id"]

def test_each_category_min_eight():
    counts = Counter(c["category"] for c in CASES)
    for cat in CATEGORIES:
        assert counts[cat] >= 8, (cat, counts[cat])

def test_check_values_well_formed():
    # router_label carries a non-empty str; tools a non-empty list; every other
    # (boolean) check must be literally True (use no_domain_tool to assert zero tools).
    for c in CASES:
        for blk in ("expect", "expect_turn2"):
            for k, v in (c.get(blk) or {}).items():
                if k == "router_label":
                    assert isinstance(v, str) and v in LABELS, (c["id"], blk, k, v)
                elif k == "tools":
                    assert isinstance(v, list) and v, (c["id"], blk, k)
                else:
                    assert v is True, (c["id"], blk, k)
