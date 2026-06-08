import copy   # M0.5: deep-copy substep payloads before forwarding to on_step
import json
from be.harness.tools import TOOL_FUNCS, CONFIRM_REQUIRED, schemas_for
from be.harness.prompts import handler_sys

# spec §2.2: a tool_result whose data is a list of listing rows is projected to ONLY
# these keys (read-only subset copy, never an in-place alias of the trace row).
_SUMMARY_KEYS = ("listing_id", "model", "brand", "asking_price", "year", "condition",
                 "match_snippet", "retrieval_rank")


def _confirm_summary(name, args):
    return f"要為您執行「{name}」（參數：{json.dumps(args, ensure_ascii=False)}），確認嗎？"


def _result_summary(result):
    """Whitelisted, read-only projection of a tool_result for SSE. Listing-row lists
    become subset dicts (match_snippet/retrieval_rank kept only when present); other
    shapes are summarized as a small scalar/typed descriptor — never the raw data."""
    data = result.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict) and "listing_id" in data[0]:
        return [{k: row[k] for k in _SUMMARY_KEYS if k in row} for row in data]
    if isinstance(data, list):
        return {"type": "list", "count": len(data)}
    if isinstance(data, dict):
        return {"type": "dict", "keys": sorted(data.keys())}
    return {"type": type(data).__name__}


def _emit(on_step, etype, data):
    if on_step is None:
        return
    try:
        on_step(etype, data)
    except Exception:
        pass


def run_handler(llm, store, domain, query, budget, on_step=None, on_token=None) -> dict:
    schemas = schemas_for(domain)
    messages = [{"role": "user", "content": query}]
    trace, tokens = [], 0
    while True:
        resp = llm.generate(handler_sys(domain), messages, tools=schemas, on_token=on_token)
        tokens += resp.total_tokens
        if not resp.tool_calls:
            return {"reply": resp.text or "", "trace": trace,
                    "pending_action": None, "budget_exceeded": False, "tokens": tokens}
        call = resp.tool_calls[0]
        index = len(trace)
        if call.name in CONFIRM_REQUIRED:
            _emit(on_step, "tool_call", {"name": call.name, "args": call.args, "index": index})
            _emit(on_step, "tool_result", {"name": call.name, "index": index, "ok": None,
                                           "error": None, "proposed": True, "result_summary": None})
            return {"reply": _confirm_summary(call.name, call.args), "trace": trace,
                    "pending_action": {"tool_name": call.name, "args": call.args},
                    "budget_exceeded": False, "tokens": tokens}
        if not budget.allow():
            return {"reply": "（已達單輪工具呼叫上限）", "trace": trace,
                    "pending_action": None, "budget_exceeded": True, "tokens": tokens}
        _emit(on_step, "tool_call", {"name": call.name, "args": call.args, "index": index})
        # nest hybrid-retrieval substeps under THIS semantic_search tool_call (parentId=index)
        sub = None
        if on_step is not None and call.name == "semantic_search":
            def sub(et, d, _idx=index):
                # deep-copy before forwarding so a misbehaving observer cannot reach
                # back into the live retrieval payload (scrub invariant kept symmetric)
                on_step(et, {**copy.deepcopy(d), "parentId": _idx})
        try:
            if call.name == "semantic_search":
                result = TOOL_FUNCS[call.name](store, on_substep=sub, **call.args)
            else:
                result = TOOL_FUNCS[call.name](store, **call.args)
        except Exception as e:  # malformed tool call (e.g. missing required arg) -> feed error back, don't crash
            result = {"ok": False, "data": None, "error": f"工具執行失敗：{e}"}
        _emit(on_step, "tool_result", {"name": call.name, "index": index, "ok": result["ok"],
                                       "error": result["error"], "result_summary": _result_summary(result)})
        trace.append({"tool_name": call.name, "tool_args": call.args, "tool_result": result})
        messages.append({"role": "user", "content": f"工具 {call.name} 回傳：{json.dumps(result, ensure_ascii=False)}"})
