import pytest
from be.harness.reranker import FakeReranker, LLMReranker
from be.harness.llm import FakeLLM, LLMResponse

CANDS = [
    {"doc_id": "scooter", "title": "scooter", "snippet": "速克達 通勤 省油"},
    {"doc_id": "sport", "title": "sport", "snippet": "仿賽 賽道 馬力"},
]


def test_fake_reranker_orders_by_query_overlap():
    out = FakeReranker().rerank("通勤省油", CANDS)
    assert out[0] == "scooter"


def test_fake_reranker_tie_break_preserves_input_order():
    cands = [{"doc_id": "b", "title": "b", "snippet": ""},
             {"doc_id": "a", "title": "a", "snippet": ""}]
    assert FakeReranker().rerank("zzz", cands) == ["b", "a"]


def test_llm_reranker_parses_json_array():
    llm = FakeLLM([LLMResponse(text='["sport", "scooter"]', tool_calls=[], total_tokens=5)])
    assert LLMReranker(llm).rerank("q", CANDS) == ["sport", "scooter"]


def test_llm_reranker_raises_on_unknown_id():
    llm = FakeLLM([LLMResponse(text='["nope", "scooter"]', tool_calls=[], total_tokens=5)])
    with pytest.raises(ValueError):
        LLMReranker(llm).rerank("q", CANDS)


def test_llm_reranker_raises_on_count_mismatch():
    llm = FakeLLM([LLMResponse(text='["scooter"]', tool_calls=[], total_tokens=5)])
    with pytest.raises(ValueError):
        LLMReranker(llm).rerank("q", CANDS)


def test_llm_reranker_raises_on_malformed_json():
    llm = FakeLLM([LLMResponse(text="not json", tool_calls=[], total_tokens=5)])
    with pytest.raises(ValueError):
        LLMReranker(llm).rerank("q", CANDS)
