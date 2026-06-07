import zlib
from typing import Protocol
import config


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """Deterministic offline embedder: char-bigram counts hashed (crc32, NOT the
    salted built-in hash()) into a fixed-dim vector, then L2-normalized.
    Reproducible across processes so test fixtures are portable."""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for i in range(len(t) - 1):
                idx = zlib.crc32(t[i:i + 2].encode("utf-8")) % self.dim
                v[idx] += 1.0
            norm = sum(x * x for x in v) ** 0.5
            out.append([x / norm for x in v] if norm else v)
        return out


class OpenAIEmbedder:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        from openai import OpenAI
        # timeout < StreamRunner wall-clock; max_retries=0 so retries can't exceed it.
        self._client = OpenAI(api_key=api_key or config.API_KEY,
                              timeout=config.OPENAI_TIMEOUT, max_retries=0)
        self.model = model or config.EMBED_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]
