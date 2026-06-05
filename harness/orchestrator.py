import config
from harness.governance import check_input, is_affirmative, TurnBudget
from harness.tools import TOOL_FUNCS
from harness.rewriter import rewrite
from harness.router import route
from harness.handlers import run_handler
from harness.prompts import FALLBACK_SYS

class Orchestrator:
    def __init__(self, llm, store, memory):
        self.llm, self.store, self.memory = llm, store, memory

    def process(self, sid: str, user_input: str) -> dict:
        # 0) input guard
        guard = check_input(user_input)
        if guard["blocked"]:
            reply = "您的訊息疑似異常指令，已忽略。請描述您的購車或訂單需求。"
            self.memory.append_message(sid, "assistant", reply)
            return {"reply": reply, "blocked": True, "awaiting_confirmation": False, "trace": {}}

        # 1) pending confirmation? (no LLM needed)
        slots = self.memory.get(sid)["slots"]
        pending = slots.get("pending_action")
        if pending:
            slots["pending_action"] = None
            if is_affirmative(user_input):
                result = TOOL_FUNCS[pending["tool_name"]](self.store, **pending["args"])
                reply = ("已為您完成預約。" if result["ok"] else f"執行失敗：{result['error']}")
                self.memory.append_message(sid, "assistant", reply)
                return {"reply": reply, "blocked": False, "awaiting_confirmation": False,
                        "trace": {"confirmation": "executed", "tool_result": result}}
            self.memory.append_message(sid, "assistant", "好的，已取消該操作。")
            return {"reply": "好的，已取消該操作。", "blocked": False,
                    "awaiting_confirmation": False, "trace": {"confirmation": "cancelled"}}

        self.memory.append_message(sid, "user", user_input)

        # 2) rewrite -> route
        rw = rewrite(self.llm, self.memory, sid, user_input)
        rt = route(self.llm, rw["rewritten_query"])
        tokens = rw["tokens"] + rt["tokens"]
        label = rt["label"]

        # 3) fallback path (no tools)
        if label == "閒聊範圍外":
            resp = self.llm.generate(FALLBACK_SYS, [{"role": "user", "content": rw["rewritten_query"]}], tools=None)
            tokens += resp.total_tokens
            reply = resp.text or "我是二手重機客服，可協助找車、比規格、查訂單與售後。"
            self.memory.append_message(sid, "assistant", reply)
            return {"reply": reply, "blocked": False, "awaiting_confirmation": False,
                    "trace": {"raw_input": user_input, "rewritten_query": rw["rewritten_query"],
                              "router_label": label, "tokens": tokens}}

        # 4) domain handler
        out = run_handler(self.llm, self.store, label, rw["rewritten_query"], TurnBudget(config.MAX_TOOL_CALLS_PER_TURN))
        tokens += out["tokens"]

        # remember viewed listings for ordinal resolution
        for step in out["trace"]:
            data = step["tool_result"].get("data")
            if step["tool_name"] in ("search_listings", "recommend") and isinstance(data, list):
                self.memory.set_viewed(sid, data)

        if out["pending_action"]:
            slots["pending_action"] = out["pending_action"]
            awaiting = True
        else:
            awaiting = False
        self.memory.append_message(sid, "assistant", out["reply"])
        return {"reply": out["reply"], "blocked": False, "awaiting_confirmation": awaiting,
                "trace": {"raw_input": user_input, "rewritten_query": rw["rewritten_query"],
                          "router_label": label, "steps": out["trace"], "tokens": tokens}}
