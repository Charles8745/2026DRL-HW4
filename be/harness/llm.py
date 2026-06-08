from dataclasses import dataclass, field
from typing import Protocol

@dataclass
class ToolCall:
    name: str
    args: dict

@dataclass
class LLMResponse:
    text: str | None = None
    tool_calls: list = field(default_factory=list)   # list[ToolCall]
    total_tokens: int = 0

class LLM(Protocol):
    def generate(self, system: str, messages: list[dict], tools: list[dict] | None = None,
                 on_token=None) -> LLMResponse: ...

class FakeLLM:
    """Returns scripted LLMResponses in order. Used by all unit tests."""
    def __init__(self, scripted: list):
        self.scripted, self.calls = scripted, 0
    def generate(self, system, messages, tools=None, on_token=None) -> LLMResponse:
        resp = self.scripted[self.calls]
        self.calls += 1
        if on_token is not None and resp.text:        # mimic token streaming deterministically
            for i in range(0, len(resp.text), 4):
                on_token(resp.text[i:i + 4])
        return resp
