from eval.run_eval import score_case

def test_router_accuracy_metric():
    case = {"id":"x","input":"i","expected_domain":"找車推薦","expected_tools":["recommend"],"ground_truth":{}}
    out = {"trace": {"router_label": "找車推薦", "steps": [{"tool_name": "recommend"}]}, "blocked": False}
    s = score_case(case, out)
    assert s["router_ok"] is True and s["tools_ok"] is True

def test_injection_case_scored_by_blocked():
    case = {"id":"inj","input":"i","expected_domain":"閒聊範圍外","expected_tools":[],"ground_truth":{"blocked":True}}
    out = {"blocked": True, "trace": {}}
    assert score_case(case, out)["router_ok"] is True
