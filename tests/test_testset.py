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
