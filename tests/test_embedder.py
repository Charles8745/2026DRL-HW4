import numpy as np
from harness.embedder import FakeEmbedder


def test_fake_embedder_deterministic_and_normalized():
    e = FakeEmbedder(dim=64)
    a = e.embed(["通勤省油好停的速克達"])
    b = e.embed(["通勤省油好停的速克達"])
    assert a == b
    assert len(a[0]) == 64
    norm = sum(x * x for x in a[0]) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_fake_embedder_similar_texts_closer_than_dissimilar():
    e = FakeEmbedder(dim=64)
    v = np.asarray(e.embed(["速克達 通勤 省油", "速克達 通勤 都市", "大型 仿賽 賽道 馬力"]))
    sim_close = float(v[0] @ v[1])
    sim_far = float(v[0] @ v[2])
    assert sim_close > sim_far


def test_fake_embedder_empty_text_is_zero_vector():
    e = FakeEmbedder(dim=8)
    assert e.embed([""])[0] == [0.0] * 8
