from harness.prompts import ROUTER_SYS

LABELS = ["找車推薦", "規格比較", "交易訂單", "售後轉真人", "閒聊範圍外"]

def route(llm, query: str) -> dict:
    resp = llm.generate(ROUTER_SYS, [{"role": "user", "content": query}], tools=None)
    raw = (resp.text or "").strip()
    label = next((l for l in LABELS if l in raw), "閒聊範圍外")
    return {"label": label, "tokens": resp.total_tokens}
