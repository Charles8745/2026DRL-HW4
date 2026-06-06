import json
from types import SimpleNamespace

from harness.openai_client import OpenAIClient, _to_openai_tools, _to_openai_messages
from harness.llm import LLMResponse


# --- pure converters -------------------------------------------------------

def test_to_openai_tools_wraps_gemini_declarations():
    decls = [{"name": "search_listings", "description": "找車",
              "parameters": {"type": "object", "properties": {"max_price": {"type": "integer"}},
                             "required": []}}]
    out = _to_openai_tools(decls)
    assert out == [{
        "type": "function",
        "function": {"name": "search_listings", "description": "找車",
                     "parameters": {"type": "object",
                                    "properties": {"max_price": {"type": "integer"}}, "required": []}},
    }]


def test_to_openai_messages_prepends_system_and_maps_roles():
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": "你好"},
            {"role": "user", "content": "推薦"}]
    out = _to_openai_messages("SYS", msgs)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert [m["role"] for m in out] == ["system", "user", "assistant", "user"]
    assert out[2] == {"role": "assistant", "content": "你好"}


# --- generate(): fake OpenAI SDK client ------------------------------------

def _fake_response(content=None, tool_calls=None, total_tokens=0):
    tcs = None
    if tool_calls is not None:
        tcs = [SimpleNamespace(function=SimpleNamespace(name=n, arguments=a)) for n, a in tool_calls]
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tcs))],
        usage=SimpleNamespace(total_tokens=total_tokens),
    )


class _FakeCreate:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _client_with(response):
    c = OpenAIClient(api_key="sk-test", model="gpt-4.1-mini")
    fake_create = _FakeCreate(response)
    c.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    return c, fake_create


def test_generate_returns_text_when_no_tool_calls():
    c, _ = _client_with(_fake_response(content="這是回覆", tool_calls=None, total_tokens=42))
    resp = c.generate("SYS", [{"role": "user", "content": "hi"}])
    assert isinstance(resp, LLMResponse)
    assert resp.text == "這是回覆"
    assert resp.tool_calls == []
    assert resp.total_tokens == 42


def test_generate_parses_tool_call_arguments_json():
    c, _ = _client_with(_fake_response(
        tool_calls=[("recommend", json.dumps({"budget": 300000, "usage": "naked"}))], total_tokens=7))
    resp = c.generate("SYS", [{"role": "user", "content": "推薦"}], tools=[
        {"name": "recommend", "description": "d", "parameters": {"type": "object", "properties": {}}}])
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "recommend"
    assert resp.tool_calls[0].args == {"budget": 300000, "usage": "naked"}
    assert resp.total_tokens == 7


def test_generate_handles_malformed_tool_arguments():
    c, _ = _client_with(_fake_response(tool_calls=[("book_viewing", "not-json")]))
    resp = c.generate("SYS", [{"role": "user", "content": "約看"}])
    assert resp.tool_calls[0].name == "book_viewing"
    assert resp.tool_calls[0].args == {}


def test_generate_handles_multiple_tool_calls():
    c, _ = _client_with(_fake_response(
        tool_calls=[("a", "{}"), ("b", json.dumps({"x": 1}))]))
    resp = c.generate("SYS", [{"role": "user", "content": "x"}])
    assert [t.name for t in resp.tool_calls] == ["a", "b"]
    assert resp.tool_calls[1].args == {"x": 1}


def test_generate_passes_converted_tools_and_system_message_to_api():
    c, fake = _client_with(_fake_response(content="ok"))
    c.generate("SYSPROMPT", [{"role": "user", "content": "hi"}], tools=[
        {"name": "recommend", "description": "d", "parameters": {"type": "object", "properties": {}}}])
    sent = fake.kwargs
    assert sent["model"] == "gpt-4.1-mini"
    assert sent["messages"][0] == {"role": "system", "content": "SYSPROMPT"}
    assert sent["tools"][0]["type"] == "function"
    assert sent["tools"][0]["function"]["name"] == "recommend"
    assert sent["tool_choice"] == "auto"
    assert sent["temperature"] == 0


def test_generate_omits_tools_when_none():
    c, fake = _client_with(_fake_response(content="ok"))
    c.generate("SYS", [{"role": "user", "content": "hi"}], tools=None)
    assert "tools" not in fake.kwargs
