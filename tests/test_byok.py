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
