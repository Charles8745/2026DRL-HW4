import json
from be.harness.tools import TOOL_FUNCS, CONFIRM_REQUIRED, schemas_for
from be.harness.prompts import handler_sys

def _confirm_summary(name, args):
    return f"要為您執行「{name}」（參數：{json.dumps(args, ensure_ascii=False)}），確認嗎？"

def run_handler(llm, store, domain, query, budget, on_step=None) -> dict:
    schemas = schemas_for(domain)
    messages = [{"role": "user", "content": query}]
    trace, tokens = [], 0
    while True:
        resp = llm.generate(handler_sys(domain), messages, tools=schemas)
        tokens += resp.total_tokens
        if not resp.tool_calls:
            return {"reply": resp.text or "", "trace": trace,
                    "pending_action": None, "budget_exceeded": False, "tokens": tokens}
        call = resp.tool_calls[0]
        if call.name in CONFIRM_REQUIRED:
            return {"reply": _confirm_summary(call.name, call.args), "trace": trace,
                    "pending_action": {"tool_name": call.name, "args": call.args},
                    "budget_exceeded": False, "tokens": tokens}
        if not budget.allow():
            return {"reply": "（已達單輪工具呼叫上限）", "trace": trace,
                    "pending_action": None, "budget_exceeded": True, "tokens": tokens}
        try:
            result = TOOL_FUNCS[call.name](store, **call.args)
        except Exception as e:  # malformed tool call (e.g. missing required arg) -> feed error back, don't crash
            result = {"ok": False, "data": None, "error": f"工具執行失敗：{e}"}
        trace.append({"tool_name": call.name, "tool_args": call.args, "tool_result": result})
        messages.append({"role": "user", "content": f"工具 {call.name} 回傳：{json.dumps(result, ensure_ascii=False)}"})
