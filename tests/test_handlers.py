from data.store import DataStore
from harness.llm import FakeLLM, LLMResponse, ToolCall
from harness.governance import TurnBudget
from harness.handlers import run_handler

def test_handler_executes_tool_then_replies():
    S = DataStore(seed=42)
    llm = FakeLLM([
        LLMResponse(tool_calls=[ToolCall("recommend", {"budget": 300000, "usage": "sport"})], total_tokens=10),
        LLMResponse(text="為您推薦這幾台", total_tokens=7),
    ])
    out = run_handler(llm, S, "找車推薦", "推薦30萬sport", TurnBudget(6))
    assert out["reply"] == "為您推薦這幾台"
    assert out["trace"][0]["tool_name"] == "recommend"
    assert out["pending_action"] is None
    assert out["tokens"] == 17

def test_handler_returns_pending_action_for_state_change():
    S = DataStore(seed=42)
    lid = S.listings[0]["listing_id"]
    llm = FakeLLM([
        LLMResponse(tool_calls=[ToolCall("book_viewing",
                   {"listing_id": lid, "datetime": "2026-06-13", "contact": "0912"})], total_tokens=9),
    ])
    out = run_handler(llm, S, "交易訂單", "約看車", TurnBudget(6))
    assert out["pending_action"]["tool_name"] == "book_viewing"
    assert out["reply"].startswith("要為您")          # confirmation summary
    assert out["pending_action"]["args"]["listing_id"] == lid

def test_handler_stops_at_turn_budget():
    S = DataStore(seed=42)
    llm = FakeLLM([LLMResponse(tool_calls=[ToolCall("recommend", {"budget": 1})], total_tokens=1)] * 10)
    out = run_handler(llm, S, "找車推薦", "x", TurnBudget(2))
    assert out["budget_exceeded"] is True
