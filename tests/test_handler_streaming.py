from be.harness.llm import FakeLLM, LLMResponse
from be.harness.governance import TurnBudget
from be.harness.handlers import run_handler


def test_run_handler_streams_final_reply():
    fake = FakeLLM([LLMResponse(text="這是最終回覆", tool_calls=[], total_tokens=3)])
    chunks = []
    out = run_handler(fake, None, "找車推薦", "查詢", TurnBudget(5), on_token=chunks.append)
    assert out["reply"] == "這是最終回覆"
    assert "".join(chunks) == "這是最終回覆"
