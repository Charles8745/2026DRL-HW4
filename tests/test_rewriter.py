from harness.llm import FakeLLM, LLMResponse
from harness.memory import SessionStore
from harness.rewriter import rewrite

def test_rewrite_uses_llm_text_and_resolves_ordinal():
    store = SessionStore(); sid = store.new_session()
    store.set_viewed(sid, [{"listing_id": "L001"}])
    llm = FakeLLM([LLMResponse(text="第一台的規格", total_tokens=5)])
    r = rewrite(llm, store, sid, "第一台規格如何")
    assert r["resolved_listing_id"] == "L001"
    assert r["rewritten_query"] == "第一台的規格"
    assert r["tokens"] == 5
