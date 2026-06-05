from eval.run_eval import score_case, select_cases, run

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

def test_select_cases_offset_and_limit():
    cases = [{"id": i} for i in range(10)]
    assert [c["id"] for c in select_cases(cases, offset=3, limit=4)] == [3, 4, 5, 6]
    assert len(select_cases(cases)) == 10
    assert select_cases(cases, offset=8, limit=5) == [{"id": 8}, {"id": 9}]

def test_run_survives_a_failing_case():
    # a transient error on one case (e.g. 429) is recorded, not fatal; the batch completes
    class _Mem:
        def new_session(self): return "s"
    class _BoomOrch:
        memory = _Mem()
        def process(self, sid, text):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
    rep = run(_BoomOrch(), [{"id": "a", "input": "x"}, {"id": "b", "input": "y"}])
    assert rep["metrics"]["n"] == 2 and rep["metrics"]["errors"] == 2
    assert rep["rows"][0]["error"].startswith("429")
