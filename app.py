from flask import Flask, request, jsonify, render_template

def create_app(orchestrator):
    app = Flask(__name__)
    app.config["ORCH"] = orchestrator

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/api/chat")
    def chat():
        orch = app.config["ORCH"]
        body = request.get_json(force=True)
        sid = body.get("session_id") or orch.memory.new_session()
        out = orch.process(sid, body["message"])
        return jsonify({"session_id": sid, **out})

    return app

def _build_default():
    from harness.openai_client import OpenAIClient
    from harness.embedder import OpenAIEmbedder
    from harness.reranker import LLMReranker
    from harness.retrieval.retriever import HybridRetriever
    from data.store import DataStore
    from harness.memory import SessionStore
    from harness.orchestrator import Orchestrator
    llm = OpenAIClient()
    store = DataStore(seed=42)
    store.retriever = HybridRetriever(store.catalog, OpenAIEmbedder(), LLMReranker(llm))
    return create_app(Orchestrator(llm, store, SessionStore()))

if __name__ == "__main__":
    _build_default().run(debug=True, port=5000)
