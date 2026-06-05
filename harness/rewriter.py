from harness.prompts import REWRITER_SYS

def rewrite(llm, store, sid, raw_input: str) -> dict:
    history = store.get(sid)["history"]
    resp = llm.generate(REWRITER_SYS, history + [{"role": "user", "content": raw_input}], tools=None)
    return {
        "rewritten_query": (resp.text or raw_input).strip(),
        "resolved_listing_id": store.resolve_reference(sid, raw_input),
        "tokens": resp.total_tokens,
    }
