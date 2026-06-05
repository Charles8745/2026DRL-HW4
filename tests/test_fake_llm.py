from harness.llm import FakeLLM, ToolCall, LLMResponse

def test_fake_llm_returns_scripted_in_order():
    llm = FakeLLM([
        LLMResponse(text=None, tool_calls=[ToolCall("recommend", {"budget": 300000})], total_tokens=10),
        LLMResponse(text="這是推薦結果", tool_calls=[], total_tokens=8),
    ])
    a = llm.generate("sys", [{"role": "user", "content": "hi"}], tools=[])
    b = llm.generate("sys", [], tools=[])
    assert a.tool_calls[0].name == "recommend" and a.tool_calls[0].args["budget"] == 300000
    assert b.text == "這是推薦結果"
    assert llm.calls == 2
