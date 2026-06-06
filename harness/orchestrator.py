import config
from harness.governance import check_input, is_affirmative, TurnBudget
from harness.tools import TOOL_FUNCS
from harness.rewriter import rewrite
from harness.router import route
from harness.handlers import run_handler
from harness.prompts import FALLBACK_SYS

_BOOKING_CUES = ("約看車", "預約看車", "幫我約", "約看")

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

        # multi-intent: defer a secondary booking intent until a vehicle is chosen
        if label in ("找車推薦", "規格比較") and any(c in user_input for c in _BOOKING_CUES):
            slots["pending_intent"] = "約看車"

        # 3) fallback path (no tools)
        if label == "閒聊範圍外":
            resp = self.llm.generate(FALLBACK_SYS, [{"role": "user", "content": rw["rewritten_query"]}], tools=None)
            tokens += resp.total_tokens
            reply = resp.text or "我是二手重機客服，可協助找車、比規格、查訂單與售後。"
            self.memory.append_message(sid, "assistant", reply)
            return {"reply": reply, "blocked": False, "awaiting_confirmation": False,
                    "trace": {"raw_input": user_input, "rewritten_query": rw["rewritten_query"],
                              "router_label": label, "resolved_listing_id": rw["resolved_listing_id"],
                              "steps": [], "tokens": tokens}}

        # 4) domain handler — inject the deterministically-resolved listing id (ordinal reference)
        handler_query = rw["rewritten_query"]
        if rw["resolved_listing_id"]:
            handler_query += f"（指定 listing_id={rw['resolved_listing_id']}）"
        out = run_handler(self.llm, self.store, label, handler_query, TurnBudget(config.MAX_TOOL_CALLS_PER_TURN))
        tokens += out["tokens"]

        # remember viewed listings (ordinal resolution); auto-fill preference slots from tool args
        for step in out["trace"]:
            data = step["tool_result"].get("data")
            if step["tool_name"] in ("search_listings", "recommend", "semantic_search") and isinstance(data, list):
                self.memory.set_viewed(sid, data)
            args = step.get("tool_args", {})
            self.memory.update_slots(sid, budget=args.get("budget") or args.get("max_price"),
                                     brand_pref=args.get("brand_pref"), usage=args.get("usage"))

        # build trace steps; surface a proposed (not-yet-executed) state-changing tool so eval can see it
        steps = list(out["trace"])
        if out["pending_action"]:
            steps.append({"tool_name": out["pending_action"]["tool_name"],
                          "tool_args": out["pending_action"]["args"],
                          "tool_result": {"ok": None, "data": None, "error": None},
                          "proposed": True})
            slots["pending_action"] = out["pending_action"]
            awaiting = True
        else:
            awaiting = False

        reply = out["reply"]
        # multi-intent: proactively surface the deferred booking intent; clear once handled by 交易訂單
        if label == "交易訂單":
            slots["pending_intent"] = None
        elif slots.get("pending_intent") == "約看車":
            reply += "\n（選定車輛後，我可以再為您預約看車。）"

        self.memory.append_message(sid, "assistant", reply)
        return {"reply": reply, "blocked": False, "awaiting_confirmation": awaiting,
                "trace": {"raw_input": user_input, "rewritten_query": rw["rewritten_query"],
                          "router_label": label, "resolved_listing_id": rw["resolved_listing_id"],
                          "steps": steps, "tokens": tokens}}
