from be.harness.llm import FakeLLM, LLMResponse

def test_fake_llm_streams_text_via_on_token():
    fake = FakeLLM([LLMResponse(text="新手通勤推薦這幾台", tool_calls=[], total_tokens=5)])
    chunks = []
    resp = fake.generate("sys", [{"role": "user", "content": "x"}], on_token=chunks.append)
    assert "".join(chunks) == "新手通勤推薦這幾台"   # 串流片段拼回原文
    assert len(chunks) >= 2                          # 真的分多段
    assert resp.text == "新手通勤推薦這幾台"          # 回傳值不變

def test_fake_llm_without_on_token_is_unchanged():
    fake = FakeLLM([LLMResponse(text="hi", tool_calls=[], total_tokens=1)])
    resp = fake.generate("sys", [], )               # 無 on_token
    assert resp.text == "hi"
