import json
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
        self.client = OpenAI(api_key=api_key or config.API_KEY)

    def generate(self, system, messages, tools=None) -> LLMResponse:
        kwargs = {"model": self.model, "messages": _to_openai_messages(system, messages),
                  "temperature": 0}
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = False
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
