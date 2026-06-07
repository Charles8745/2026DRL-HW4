import copy
import re
from typing import Callable

import config
from be.harness.governance import check_input, is_affirmative, TurnBudget
from be.harness.tools import TOOL_FUNCS
from be.harness.rewriter import rewrite
from be.harness.router import route
from be.harness.handlers import run_handler
from be.harness.prompts import FALLBACK_SYS

_BOOKING_CUES = ("約看車", "預約看車", "幫我約", "約看")

# strict "this message is ONLY a confirmation token" — distinct from the loose
# substring is_affirmative (which matches e.g. "好" inside "想找…好停的車"). Used to
# answer a stale/duplicate bare confirm (pending already consumed concurrently) with
# zero LLM calls instead of mis-routing it (R7 concurrent-confirm path).
_PURE_CONFIRM = ("好", "確認", "對", "是的", "ok", "yes", "沒問題", "可以")
_CONFIRM_PUNCT = re.compile(r"[\s,，。.!！？?、~～]")


def _is_pure_confirm(text: str) -> bool:
    return _CONFIRM_PUNCT.sub("", (text or "").strip().lower()) in _PURE_CONFIRM

OnStep = Callable[[str, dict], None]          # on_step(event_type, data) -> None

# api_key / Authorization-shaped keys are dropped; sk-... literals are masked.
_SECRET_KEYS = ("api_key", "apikey", "authorization", "openai_key", "openai_api_key", "x-ridebutler-key")
_SK_RE = re.compile(r"sk-[A-Za-z0-9_-]{20,}")


def _scrub(data):
    """Read-only deep-scrub: drop api_key/Authorization-shaped keys at any depth
    and mask sk-... literals in strings. Operates on an already-deepcopied value."""
    if isinstance(data, dict):
        return {k: _scrub(v) for k, v in data.items()
                if k.lower() not in _SECRET_KEYS}
    if isinstance(data, list):
        return [_scrub(v) for v in data]
    if isinstance(data, str):
        return _SK_RE.sub("sk-***REDACTED***", data)
    return data

class Orchestrator:
    def __init__(self, llm, store, memory):
        self.llm, self.store, self.memory = llm, store, memory

    def _emit(self, on_step, etype: str, data: dict) -> None:
        if on_step is None:
            return                                  # hard no-op == today's bits
        payload = _scrub(copy.deepcopy(data))       # read-only deepcopy + key scrub
        try:
            on_step(etype, payload)                 # observer isolation: swallow all
        except Exception:
            pass

    def process(self, sid: str, user_input: str, on_step: "OnStep | None" = None) -> dict:
        # 0) input guard
        guard = check_input(user_input)
        if guard["blocked"]:
            reply = "您的訊息疑似異常指令，已忽略。請描述您的購車或訂單需求。"
            self.memory.append_message(sid, "assistant", reply)
            ret = {"reply": reply, "blocked": True, "awaiting_confirmation": False, "trace": {}}
            self._emit(on_step, "guard", {"blocked": True, "reason": guard["reason"]})
            self._emit(on_step, "final", {"reply": reply, "blocked": True, "awaiting_confirmation": False,
                                          "router_label": None, "resolved_listing_id": None,
                                          "tokens": 0, "trace": ret["trace"]})
            return ret
        self._emit(on_step, "guard", {"blocked": False, "reason": None})

        # 1) pending confirmation? (no LLM needed)
        slots = self.memory.get(sid)["slots"]
        pending = slots.get("pending_action")
        if pending:
            slots["pending_action"] = None
            if is_affirmative(user_input):
                result = TOOL_FUNCS[pending["tool_name"]](self.store, **pending["args"])
                reply = ("已為您完成預約。" if result["ok"] else f"執行失敗：{result['error']}")
                self.memory.append_message(sid, "assistant", reply)
                ret = {"reply": reply, "blocked": False, "awaiting_confirmation": False,
                       "trace": {"confirmation": "executed", "tool_result": result}}
                self._emit(on_step, "confirm_gate",
                           {"tool_name": pending["tool_name"], "args": pending["args"],
                            "stage": "executed", "tool_result": {"ok": result["ok"], "error": result["error"]}})
                self._emit(on_step, "final", {"reply": reply, "blocked": False, "awaiting_confirmation": False,
                                              "router_label": None, "resolved_listing_id": None,
                                              "tokens": 0, "trace": ret["trace"]})
                return ret
            self.memory.append_message(sid, "assistant", "好的，已取消該操作。")
            ret = {"reply": "好的，已取消該操作。", "blocked": False,
                   "awaiting_confirmation": False, "trace": {"confirmation": "cancelled"}}
            self._emit(on_step, "confirm_gate",
                       {"tool_name": pending["tool_name"], "args": pending["args"], "stage": "cancelled"})
            self._emit(on_step, "final", {"reply": ret["reply"], "blocked": False, "awaiting_confirmation": False,
                                          "router_label": None, "resolved_listing_id": None,
                                          "tokens": 0, "trace": ret["trace"]})
            return ret

        # 1b) bare-confirm with NO pending action (e.g. a duplicate "確認" whose pending
        # was already consumed by a concurrent request): reply gracefully, no LLM call.
        # Strict pure-confirm only — a substantive query containing "好" still routes.
        if _is_pure_confirm(user_input):
            reply = "目前沒有待確認的操作，請告訴我您的需求。"
            self.memory.append_message(sid, "assistant", reply)
            ret = {"reply": reply, "blocked": False, "awaiting_confirmation": False,
                   "trace": {"confirmation": "noop"}}
            self._emit(on_step, "final", {"reply": reply, "blocked": False, "awaiting_confirmation": False,
                                          "router_label": None, "resolved_listing_id": None,
                                          "tokens": 0, "trace": ret["trace"]})
            return ret

        self.memory.append_message(sid, "user", user_input)

        # 2) rewrite -> route
        rw = rewrite(self.llm, self.memory, sid, user_input)
        self._emit(on_step, "rewrite", {"rewritten_query": rw["rewritten_query"],
                                        "resolved_listing_id": rw["resolved_listing_id"],
                                        "tokens": rw["tokens"]})
        rt = route(self.llm, rw["rewritten_query"])
        tokens = rw["tokens"] + rt["tokens"]
        label = rt["label"]
        self._emit(on_step, "route", {"label": label, "tokens": rt["tokens"]})

        # multi-intent: defer a secondary booking intent until a vehicle is chosen
        if label in ("找車推薦", "規格比較") and any(c in user_input for c in _BOOKING_CUES):
            slots["pending_intent"] = "約看車"

        # 3) fallback path (no tools)
        if label == "閒聊範圍外":
            resp = self.llm.generate(FALLBACK_SYS, [{"role": "user", "content": rw["rewritten_query"]}], tools=None)
            tokens += resp.total_tokens
            reply = resp.text or "我是二手重機客服，可協助找車、比規格、查訂單與售後。"
            self.memory.append_message(sid, "assistant", reply)
            ret = {"reply": reply, "blocked": False, "awaiting_confirmation": False,
                   "trace": _scrub({"raw_input": user_input, "rewritten_query": rw["rewritten_query"],
                                    "router_label": label, "resolved_listing_id": rw["resolved_listing_id"],
                                    "steps": [], "tokens": tokens})}
            self._emit(on_step, "fallback", {"reply_preview": reply[:80]})
            self._emit(on_step, "memory", {"viewed_count": len(slots.get("viewed_listings") or []),
                                           "slots": {"budget": slots.get("budget"),
                                                     "brand_pref": slots.get("brand_pref"),
                                                     "usage": slots.get("usage"),
                                                     "pending_intent": slots.get("pending_intent")}})
            self._emit(on_step, "final", {"reply": reply, "blocked": False, "awaiting_confirmation": False,
                                          "router_label": label, "resolved_listing_id": rw["resolved_listing_id"],
                                          "tokens": tokens, "trace": ret["trace"]})
            return ret

        # 4) domain handler — inject the deterministically-resolved listing id (ordinal reference)
        handler_query = rw["rewritten_query"]
        if rw["resolved_listing_id"]:
            handler_query += f"（指定 listing_id={rw['resolved_listing_id']}）"
        out = run_handler(self.llm, self.store, label, handler_query,
                          TurnBudget(config.MAX_TOOL_CALLS_PER_TURN), on_step=on_step)
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
            self._emit(on_step, "confirm_gate",
                       {"tool_name": out["pending_action"]["tool_name"],
                        "args": out["pending_action"]["args"], "stage": "proposed"})
        else:
            awaiting = False

        reply = out["reply"]
        # multi-intent: proactively surface the deferred booking intent; clear once handled by 交易訂單
        if label == "交易訂單":
            slots["pending_intent"] = None
        elif slots.get("pending_intent") == "約看車":
            reply += "\n（選定車輛後，我可以再為您預約看車。）"

        self.memory.append_message(sid, "assistant", reply)
        ret = {"reply": reply, "blocked": False, "awaiting_confirmation": awaiting,
               "trace": _scrub({"raw_input": user_input, "rewritten_query": rw["rewritten_query"],
                                "router_label": label, "resolved_listing_id": rw["resolved_listing_id"],
                                "steps": steps, "tokens": tokens})}
        self._emit(on_step, "memory", {"viewed_count": len(slots.get("viewed_listings") or []),
                                       "slots": {"budget": slots.get("budget"),
                                                 "brand_pref": slots.get("brand_pref"),
                                                 "usage": slots.get("usage"),
                                                 "pending_intent": slots.get("pending_intent")}})
        self._emit(on_step, "final", {"reply": reply, "blocked": False, "awaiting_confirmation": awaiting,
                                      "router_label": label, "resolved_listing_id": rw["resolved_listing_id"],
                                      "tokens": tokens, "trace": ret["trace"]})
        return ret
