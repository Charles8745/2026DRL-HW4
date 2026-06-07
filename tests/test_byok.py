import importlib
import os


def _reload_config(monkeypatch, **env):
    for k in ("ALLOW_ENV_KEY", "DEMO_MODE", "ALLOW_ENV_KEY_PUBLIC", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config
    return importlib.reload(config)


def test_flags_default_off(monkeypatch):
    cfg = _reload_config(monkeypatch)
    assert cfg.ALLOW_ENV_KEY is False
    assert cfg.DEMO_MODE is False
    # existing names untouched
    assert hasattr(cfg, "API_KEY") and hasattr(cfg, "MODEL")
    assert hasattr(cfg, "EMBED_MODEL") and cfg.MAX_TOOL_CALLS_PER_TURN == 6


def test_flags_truthy_env(monkeypatch):
    cfg = _reload_config(monkeypatch, ALLOW_ENV_KEY="1", DEMO_MODE="true")
    assert cfg.ALLOW_ENV_KEY is True
    assert cfg.DEMO_MODE is True


def test_flags_falsey_strings(monkeypatch):
    cfg = _reload_config(monkeypatch, ALLOW_ENV_KEY="0", DEMO_MODE="false")
    assert cfg.ALLOW_ENV_KEY is False
    assert cfg.DEMO_MODE is False


from be.harness.retrieval.retriever import HybridRetriever
from be.harness.retrieval.vectorstore import VectorStore
from be.harness.embedder import FakeEmbedder
from be.harness.reranker import FakeReranker


_MINI_CATALOG = [
    {"title": "A", "brand": "X", "usage": "naked", "description": "通勤 街車"},
    {"title": "B", "brand": "Y", "usage": "sport", "description": "賽道 仿賽"},
]


class _SpyEmbedder(FakeEmbedder):
    def __init__(self, dim=64):
        super().__init__(dim)
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return super().embed(texts)


def test_vstore_kwarg_skips_build_embed():
    emb = _SpyEmbedder()
    pre = FakeEmbedder().embed(["A｜X｜naked｜通勤 街車", "B｜Y｜sport｜賽道 仿賽"])
    vs = VectorStore(["A", "B"], pre)
    r = HybridRetriever(_MINI_CATALOG, emb, FakeReranker(), vstore=vs)
    assert r.vstore is vs           # reused, not rebuilt
    assert emb.calls == 0           # no build-time embed


def test_no_vstore_kwarg_behaves_like_today():
    emb = _SpyEmbedder()
    r = HybridRetriever(_MINI_CATALOG, emb, FakeReranker())
    assert emb.calls == 1           # build-time embed happened (today's behavior)
    assert isinstance(r.vstore, VectorStore)
    out = r.retrieve("通勤", k=2)
    assert isinstance(out, list) and len(out) >= 1


from be.harness.retrieval.corpus_cache import CorpusEmbeddingCache


_DOC_IDS = ["A", "B"]
_TEXTS = ["A｜X｜naked｜通勤 街車", "B｜Y｜sport｜賽道 仿賽"]


def test_cache_embeds_once_and_returns_same_object():
    cache = CorpusEmbeddingCache()
    emb = _SpyEmbedder()
    v1 = cache.get_or_build("m", _DOC_IDS, _TEXTS, emb)
    v2 = cache.get_or_build("m", _DOC_IDS, _TEXTS, emb)
    assert isinstance(v1, VectorStore)
    assert v1 is v2          # cached object reused
    assert emb.calls == 1    # embedded exactly once across 2 calls


class _BoomEmbedder:
    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        raise RuntimeError("api down")


def test_cache_failure_is_not_poisoned():
    cache = CorpusEmbeddingCache()
    boom = _BoomEmbedder()
    miss = cache.get_or_build("m", _DOC_IDS, _TEXTS, boom)
    assert miss is None          # transient miss
    # a subsequent valid request must succeed (cache not poisoned)
    good = _SpyEmbedder()
    v = cache.get_or_build("m", _DOC_IDS, _TEXTS, good)
    assert isinstance(v, VectorStore)
    assert good.calls == 1
    assert boom.calls == 1


from fe import keyauth


def test_validate_key_format():
    assert keyauth.validate_key_format("sk-" + "a" * 20) is True
    assert keyauth.validate_key_format(None) is False
    assert keyauth.validate_key_format("") is False
    assert keyauth.validate_key_format("nope-" + "a" * 20) is False   # bad prefix
    assert keyauth.validate_key_format("sk-short") is False           # too short
    assert keyauth.validate_key_format("sk-" + "a" * 10 + " " + "b" * 12) is False  # whitespace


def test_redact_key_literal_and_generic():
    key = "sk-" + "A" * 25
    text = f"using {key} now"
    out = keyauth.redact_key(text, key)
    assert key not in out
    assert "sk-***REDACTED***" in out
    # generic pattern: a DIFFERENT sk- key (not the literal) still redacted
    other = "sk-" + "Z9_-" * 6
    out2 = keyauth.redact_key(f"leak {other}", None)
    assert other not in out2
    assert "sk-***REDACTED***" in out2


def test_redact_key_no_key_no_change():
    assert keyauth.redact_key("plain text", None) == "plain text"


import config as _config_mod


class _FakeReq:
    """Minimal stand-in for a Flask request: headers dict + remote_addr."""
    def __init__(self, headers=None, remote_addr="127.0.0.1"):
        self.headers = headers or {}
        self.remote_addr = remote_addr


def test_extract_header_key_takes_precedence():
    key = "sk-" + "h" * 20
    req = _FakeReq(headers={"X-RideButler-Key": key})
    assert keyauth.extract_request_key(req, allow_env=True) == key


def test_extract_no_header_no_env_returns_none():
    req = _FakeReq(headers={})
    assert keyauth.extract_request_key(req, allow_env=False) is None


def test_extract_env_fallback_on_localhost(monkeypatch):
    monkeypatch.setattr(_config_mod, "API_KEY", "sk-" + "e" * 20, raising=False)
    req = _FakeReq(headers={}, remote_addr="127.0.0.1")
    assert keyauth.extract_request_key(req, allow_env=True) == "sk-" + "e" * 20


def test_extract_env_fallback_blocked_on_public(monkeypatch):
    # R1 guard: ALLOW_ENV_KEY on but request is non-localhost -> no fallback
    monkeypatch.setattr(_config_mod, "API_KEY", "sk-" + "e" * 20, raising=False)
    req = _FakeReq(headers={}, remote_addr="203.0.113.7")
    assert keyauth.extract_request_key(req, allow_env=True) is None


def test_extract_env_fallback_requires_allow_env(monkeypatch):
    monkeypatch.setattr(_config_mod, "API_KEY", "sk-" + "e" * 20, raising=False)
    req = _FakeReq(headers={}, remote_addr="127.0.0.1")
    assert keyauth.extract_request_key(req, allow_env=False) is None


from be.harness.orchestrator import Orchestrator
from be.harness.memory import SessionStore


def _spy_factories():
    """Returns (llm_factory, embedder_factory, seen) where seen records the keys
    each factory was constructed with — to assert request-key (not config.API_KEY)."""
    seen = {"llm_keys": [], "embed_keys": []}

    class _SpyLLM:
        def __init__(self, key):
            seen["llm_keys"].append(key)
            self.key = key

        def generate(self, system, messages, tools=None):
            from be.harness.llm import LLMResponse
            return LLMResponse(text="ok", tool_calls=[], total_tokens=0)

    class _SpyEmb(FakeEmbedder):
        def __init__(self, key):
            super().__init__()
            seen["embed_keys"].append(key)
            self.key = key

    return _SpyLLM, _SpyEmb, seen


def test_build_uses_request_key_not_config(monkeypatch):
    monkeypatch.setattr(_config_mod, "API_KEY", "sk-" + "OWNER" * 4, raising=False)
    llm_f, emb_f, seen = _spy_factories()
    cache = CorpusEmbeddingCache()
    req_key = "sk-" + "REQ12345" * 3
    orch = keyauth.build_request_orchestrator(
        req_key, model="m", embed_model="em", memory=SessionStore(),
        corpus_cache=cache, llm_factory=llm_f, embedder_factory=emb_f)
    assert isinstance(orch, Orchestrator)
    assert seen["llm_keys"] == [req_key]
    assert seen["embed_keys"] == [req_key]
    assert _config_mod.API_KEY not in seen["llm_keys"]


def test_build_per_request_datastore_isolated(monkeypatch):
    llm_f, emb_f, _ = _spy_factories()
    cache = CorpusEmbeddingCache()
    mem = SessionStore()
    o1 = keyauth.build_request_orchestrator(
        "sk-" + "a" * 20, model="m", embed_model="em", memory=mem,
        corpus_cache=cache, llm_factory=llm_f, embedder_factory=emb_f)
    o2 = keyauth.build_request_orchestrator(
        "sk-" + "b" * 20, model="m", embed_model="em", memory=mem,
        corpus_cache=cache, llm_factory=llm_f, embedder_factory=emb_f)
    assert o1.store is not o2.store                 # separate DataStore objects
    assert o1.store.listings is not o2.store.listings
    assert o1.store.orders is not o2.store.orders
    assert o1.store.tickets is not o2.store.tickets
    assert o1.store.catalog is o2.store.catalog     # catalog shared read-only
    assert o1.memory is o2.memory is mem            # SessionStore shared
    # mutating one DataStore's tickets must not bleed into the other
    o1.store.add_ticket("客訴", "x")
    assert len(o1.store.tickets) == 1 and len(o2.store.tickets) == 0


def test_build_embeds_corpus_once_across_requests(monkeypatch):
    llm_f, emb_f, seen = _spy_factories()
    cache = CorpusEmbeddingCache()
    mem = SessionStore()
    o1 = keyauth.build_request_orchestrator(
        "sk-" + "a" * 20, model="m", embed_model="em", memory=mem,
        corpus_cache=cache, llm_factory=llm_f, embedder_factory=emb_f)
    o2 = keyauth.build_request_orchestrator(
        "sk-" + "b" * 20, model="m", embed_model="em", memory=mem,
        corpus_cache=cache, llm_factory=llm_f, embedder_factory=emb_f)
    # both retrievers share the same cached VectorStore (embedded once)
    assert o1.store.retriever.vstore is o2.store.retriever.vstore


def test_build_no_key_material_in_orchestrator_vars():
    llm_f, emb_f, _ = _spy_factories()
    cache = CorpusEmbeddingCache()
    secret = "sk-" + "CANARY12" * 3
    orch = keyauth.build_request_orchestrator(
        secret, model="m", embed_model="em", memory=SessionStore(),
        corpus_cache=cache, llm_factory=llm_f, embedder_factory=emb_f)
    # The key legitimately lives ENCAPSULATED inside the client/embedder (e.g.
    # orch.store.retriever.embedder.key) — that is by design. This sweep only proves
    # the key is not LOOSELY attached to the top-level Orchestrator / DataStore surface
    # (str(vars(...)) renders nested objects as <... object at 0x...> and does NOT
    # expand embedder.key, so this is a top-level-surface check, not a deep walk).
    assert secret not in (str(vars(orch)) + str(vars(orch.store)))
