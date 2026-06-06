import json, collections
def test_quota_and_schema():
    data = json.load(open("eval/testset.json", encoding="utf-8"))
    by = collections.Counter(c["expected_domain"] for c in data)
    for d in ["找車推薦","規格比較","交易訂單","售後轉真人"]:
        assert by[d] >= 5, d
    assert sum(1 for c in data if c["id"].startswith("multi")) >= 4
    assert by["閒聊範圍外"] >= 3
    for c in data:
        assert {"id","input","expected_domain","expected_tools","ground_truth"} <= c.keys()

def test_main_testset_frozen_at_27():
    # The §7.1-7.3 honest numbers are computed on exactly these 27 cases; guard against drift.
    assert len(json.load(open("eval/testset.json", encoding="utf-8"))) == 27

def test_sem_testset_schema():
    cases = json.load(open("eval/sem_testset.json", encoding="utf-8"))
    assert 3 <= len(cases) <= 5
    for c in cases:
        assert c["expected_tools"] == ["semantic_search"]
        assert c["expected_domain"] == "找車推薦"
        assert c["input"]
