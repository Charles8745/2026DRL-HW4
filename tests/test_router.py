from harness.llm import FakeLLM, LLMResponse
from harness.router import route, LABELS

def test_route_returns_clean_label():
    llm = FakeLLM([LLMResponse(text="找車推薦\n", total_tokens=3)])
    r = route(llm, "30萬的Yamaha")
    assert r["label"] == "找車推薦" and r["tokens"] == 3

def test_unknown_label_falls_back_to_out_of_scope():
    llm = FakeLLM([LLMResponse(text="天氣如何", total_tokens=2)])
    assert route(llm, "今天天氣")["label"] == "閒聊範圍外"

def test_labels_are_the_five():
    assert LABELS == ["找車推薦","規格比較","交易訂單","售後轉真人","閒聊範圍外"]
