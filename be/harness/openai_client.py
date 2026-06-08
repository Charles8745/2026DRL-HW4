import json
import logging
from openai import OpenAI
from be.harness.llm import LLMResponse, ToolCall
import config


def _to_openai_tools(decls):
    """Gemini function_declaration dicts -> OpenAI chat tools format."""
    return [{"type": "function",
             "function": {"name": d["name"], "description": d.get("description", ""),
                          "parameters": d.get("parameters", {"type": "object", "properties": {}})}}
            for d in decls]


def _to_openai_messages(system, messages):
    """Prepend the system prompt; map history roles (user stays user, everything else -> assistant)."""
    out = [{"role": "system", "content": system}]
    for m in messages:
        role = "user" if m["role"] == "user" else "assistant"
        out.append({"role": role, "content": m["content"]})
    return out


class OpenAIClient:
    """LLM Protocol impl over OpenAI chat completions (manual function calling)."""

    def __init__(self, api_key: str = None, model: str = None):
        self.model = model or config.MODEL
        # timeout < StreamRunner wall-clock; max_retries=0 so retries can't exceed it.
        self.client = OpenAI(api_key=api_key or config.API_KEY,
                             timeout=config.OPENAI_TIMEOUT, max_retries=0)

    def generate(self, system, messages, tools=None, on_token=None) -> LLMResponse:
        kwargs = {"model": self.model, "messages": _to_openai_messages(system, messages),
                  "temperature": 0}
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = False
        if on_token is None:
            resp = self.client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            calls = []
            for tc in (msg.tool_calls or []):
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                calls.append(ToolCall(tc.function.name, args))
            usage = getattr(resp, "usage", None)
            return LLMResponse(text=msg.content, tool_calls=calls,
                               total_tokens=getattr(usage, "total_tokens", 0) or 0)
        # streaming path: forward content deltas to on_token; reconstruct tool calls + usage
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        parts, frags, total = [], {}, 0
        for chunk in self.client.chat.completions.create(**kwargs):
            if getattr(chunk, "usage", None):
                total = chunk.usage.total_tokens or 0
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                parts.append(delta.content)
                try:
                    on_token(delta.content)
                except Exception:
                    logging.warning("on_token callback raised; continuing stream", exc_info=True)
            for tc in (getattr(delta, "tool_calls", None) or []):
                if tc.index is None:
                    continue
                slot = frags.setdefault(tc.index, {"name": None, "args": ""})
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments
        calls = []
        for idx in sorted(frags):
            f = frags[idx]
            if not f["name"]:
                continue
            try:
                args = json.loads(f["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(f["name"], args))
        return LLMResponse(text=("".join(parts) or None), tool_calls=calls, total_tokens=total)
