from harness.llm import FakeLLM, LLMResponse
from data.store import DataStore
from harness.memory import SessionStore
from harness.orchestrator import Orchestrator
from app import create_app

def test_chat_endpoint_returns_reply_and_session():
    llm = FakeLLM([
        LLMResponse(text="閒聊", total_tokens=1),
        LLMResponse(text="閒聊範圍外", total_tokens=1),
        LLMResponse(text="我是重機客服", total_tokens=1),
    ])
    orch = Orchestrator(llm, DataStore(seed=42), SessionStore())
    app = create_app(orch)
    client = app.test_client()
    r = client.post("/api/chat", json={"message": "嗨"})
    body = r.get_json()
    assert r.status_code == 200
    assert body["reply"] == "我是重機客服"
    assert "session_id" in body and "trace" in body

def test_index_serves_html():
    orch = Orchestrator(FakeLLM([]), DataStore(seed=42), SessionStore())
    client = create_app(orch).test_client()
    assert client.get("/").status_code == 200
