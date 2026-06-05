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

def test_proposed_tool_counts_toward_task_success():
    # a confirmation-gated tool that only appears as 'proposed' still satisfies expected_tools
    case = {"id":"txn","input":"i","expected_domain":"交易訂單","expected_tools":["book_viewing"],"ground_truth":{}}
    out = {"blocked": False, "reply": "要為您預約 L001，確認嗎？",
           "trace": {"router_label": "交易訂單",
                     "steps": [{"tool_name": "book_viewing", "proposed": True,
                                "tool_result": {"ok": None, "data": None, "error": None}}]}}
    s = score_case(case, out)
    assert s["tools_ok"] is True and s["grounded_ok"] is True

def test_groundedness_flags_unsupported_price():
    # reply quotes a price the tools never returned -> grounded_ok False
    case = {"id":"g","input":"i","expected_domain":"找車推薦","expected_tools":["recommend"],"ground_truth":{}}
    out = {"blocked": False, "reply": "這台只要 123456 元",
           "trace": {"router_label": "找車推薦",
                     "steps": [{"tool_name": "recommend",
                                "tool_result": {"ok": True, "data": [{"asking_price": 250000}], "error": None}}]}}
    assert score_case(case, out)["grounded_ok"] is False
