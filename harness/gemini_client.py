from google import genai
from google.genai import types
from harness.llm import LLMResponse, ToolCall
import config

class GeminiClient:
    def __init__(self, api_key: str = None, model: str = None):
        self.model = model or config.MODEL
        self.client = genai.Client(api_key=api_key or config.API_KEY)

    def generate(self, system, messages, tools=None) -> LLMResponse:
        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
        cfg = types.GenerateContentConfig(system_instruction=system)
        if tools:
            cfg.tools = [types.Tool(function_declarations=tools)]
            cfg.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        resp = self.client.models.generate_content(model=self.model, contents=contents, config=cfg)
        calls, text = [], None
        cand = resp.candidates[0]
        for part in cand.content.parts:
            if getattr(part, "function_call", None):
                calls.append(ToolCall(part.function_call.name, dict(part.function_call.args or {})))
            elif getattr(part, "text", None):
                text = (text or "") + part.text
        tokens = getattr(resp, "usage_metadata", None)
        return LLMResponse(text=text, tool_calls=calls,
                           total_tokens=getattr(tokens, "total_token_count", 0) or 0)
