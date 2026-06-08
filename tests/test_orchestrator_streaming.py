from de.data.store import DataStore
from be.harness.memory import SessionStore
from be.harness.llm import FakeLLM, LLMResponse
from be.harness.orchestrator import Orchestrator


def _orch(scripted):
    return Orchestrator(FakeLLM(scripted), DataStore(seed=42), SessionStore())


def test_emits_token_events_when_on_step_present():
    o = _orch([
        LLMResponse(text="新手通勤推薦", total_tokens=1),        # rewrite
        LLMResponse(text="找車推薦", total_tokens=1),            # route
        LLMResponse(text="這幾台都適合新手通勤", total_tokens=3),  # handler: 無 tool_call → 直接最終文字
    ])
    sid = o.memory.new_session()
    events = []
    o.process(sid, "推薦新手通勤車", on_step=lambda e, d: events.append((e, d)))
    toks = [d["text"] for (e, d) in events if e == "token"]
    assert "".join(toks) == "這幾台都適合新手通勤"   # FakeLLM 分段 on_token，拼回原文


def test_no_token_when_on_step_none():
    o = _orch([
        LLMResponse(text="新手通勤推薦", total_tokens=1),
        LLMResponse(text="找車推薦", total_tokens=1),
        LLMResponse(text="這幾台都適合新手通勤", total_tokens=3),
    ])
    sid = o.memory.new_session()
    out = o.process(sid, "推薦新手通勤車")   # on_step=None → 不串流、無 token
    assert out["reply"] == "這幾台都適合新手通勤"
