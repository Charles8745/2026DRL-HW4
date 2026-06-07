import pytest
from eval.robustness_eval import CATEGORIES, CHECK_KEYS, evaluate_expect, aggregate

# --- 合成 out dict 工具：模擬 orchestrator.process 的回傳形狀 ---
def _out(reply="", router_label=None, steps=None, blocked=False,
         awaiting=False, confirmation=None):
    trace = {"router_label": router_label, "steps": steps or []}
    if confirmation is not None:
        trace["confirmation"] = confirmation
    return {"reply": reply, "blocked": blocked,
            "awaiting_confirmation": awaiting, "trace": trace}

def _step(name, data=None, ok=True, error=None):
    return {"tool_name": name, "tool_args": {},
            "tool_result": {"ok": ok, "data": data, "error": error}}

_CTX = {"user_input": "", "turn_delta": (0, 0), "errored": False}

def test_constants_present():
    assert CATEGORIES == {"usage", "edge", "exception", "security"}
    assert {"router_label", "tools", "no_domain_tool", "blocked",
            "awaiting_confirmation", "grounded", "honest_empty", "no_crash",
            "confirmed_executed", "confirmed_cancelled"} <= CHECK_KEYS

def test_router_label_and_tools():
    out = _out(router_label="找車推薦", steps=[_step("recommend", data=[{"asking_price": 100000}])])
    r = evaluate_expect({"router_label": "找車推薦", "tools": ["recommend"]}, out, _CTX)
    assert r == {"router_label": True, "tools": True}

def test_no_domain_tool_true_when_no_steps():
    assert evaluate_expect({"no_domain_tool": True}, _out(), _CTX) == {"no_domain_tool": True}

def test_no_domain_tool_false_when_tool_fired():
    out = _out(steps=[_step("check_order", data={"order_id": "O001"})])
    assert evaluate_expect({"no_domain_tool": True}, out, _CTX) == {"no_domain_tool": False}

def test_blocked():
    assert evaluate_expect({"blocked": True}, _out(blocked=True), _CTX) == {"blocked": True}
    assert evaluate_expect({"blocked": True}, _out(blocked=False), _CTX) == {"blocked": False}

def test_awaiting_confirmation_requires_zero_delta():
    out = _out(awaiting=True)
    assert evaluate_expect({"awaiting_confirmation": True}, out, _CTX)["awaiting_confirmation"]
    ctx = {**_CTX, "turn_delta": (1, 0)}  # 狀態已變更 -> 不算「閘住未執行」
    assert not evaluate_expect({"awaiting_confirmation": True}, out, ctx)["awaiting_confirmation"]

def test_grounded_flags_ungrounded_price():
    grounded = _out(reply="這台 100000 元", steps=[_step("recommend", data=[{"asking_price": 100000}])])
    assert evaluate_expect({"grounded": True}, grounded, _CTX) == {"grounded": True}
    halluc = _out(reply="這台 250000 元", steps=[_step("recommend", data=[{"asking_price": 100000}])])
    assert evaluate_expect({"grounded": True}, halluc, _CTX) == {"grounded": False}

def test_honest_empty():
    empty = _out(reply="查無符合的車輛", steps=[_step("recommend", data=[])])
    assert evaluate_expect({"honest_empty": True}, empty, _CTX) == {"honest_empty": True}
    # 工具有回資料 -> 非 empty
    nonempty = _out(reply="查無", steps=[_step("recommend", data=[{"asking_price": 1}])])
    assert evaluate_expect({"honest_empty": True}, nonempty, _CTX) == {"honest_empty": False}
    # 沒有誠實標記 -> 失敗
    nomark = _out(reply="好的", steps=[_step("recommend", data=[])])
    assert evaluate_expect({"honest_empty": True}, nomark, _CTX) == {"honest_empty": False}

def test_honest_empty_input_id_not_fabrication():
    # 回覆 echo 輸入裡查不到的 ID 不算捏造
    out = _out(reply="查無 L999", steps=[_step("get_listing_detail", ok=False, error="找不到")])
    ctx = {**_CTX, "user_input": "查 L999 的規格"}
    assert evaluate_expect({"honest_empty": True}, out, ctx) == {"honest_empty": True}
    # 回覆冒出輸入沒有的 ID -> 捏造
    out2 = _out(reply="查無，但您可看 L001", steps=[_step("get_listing_detail", ok=False, error="x")])
    assert evaluate_expect({"honest_empty": True}, out2, ctx) == {"honest_empty": False}

def test_no_crash():
    assert evaluate_expect({"no_crash": True}, _out(), _CTX) == {"no_crash": True}
    assert evaluate_expect({"no_crash": True}, _out(), {**_CTX, "errored": True}) == {"no_crash": False}

def test_confirmed_executed_and_cancelled():
    assert evaluate_expect({"confirmed_executed": True}, _out(confirmation="executed"), _CTX) == {"confirmed_executed": True}
    assert evaluate_expect({"confirmed_cancelled": True}, _out(confirmation="cancelled"), _CTX) == {"confirmed_cancelled": True}
    assert evaluate_expect({"confirmed_executed": True}, _out(), _CTX) == {"confirmed_executed": False}

def test_unknown_key_raises():
    with pytest.raises(ValueError):
        evaluate_expect({"bogus": True}, _out(), _CTX)

def test_aggregate():
    rows = [
        {"id": "usg-01", "category": "usage", "passed": True,
         "checks": {"grounded": True}, "checks2": None, "error": None},
        {"id": "usg-02", "category": "usage", "passed": False,
         "checks": {"grounded": False}, "checks2": None, "error": None},
        {"id": "sec-01", "category": "security", "passed": True,
         "checks": {"blocked": True}, "checks2": {"grounded": True}, "error": None},
    ]
    m = aggregate(rows)
    assert m["n"] == 3
    assert m["pass_rate"] == pytest.approx(2/3)
    assert m["by_category"]["usage"] == {"n": 2, "passed": 1, "pass_rate": 0.5}
    assert m["by_check"]["grounded"] == {"passed": 2, "total": 3}
    assert m["errors"] == 0
