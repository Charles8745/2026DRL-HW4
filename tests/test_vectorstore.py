from harness.retrieval.vectorstore import VectorStore


def test_query_ranks_by_cosine():
    vs = VectorStore(["a", "b", "c"], [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]])
    ranked = vs.query([1.0, 0.0], top_n=3)
    assert [d for d, _ in ranked] == ["a", "c", "b"]


def test_query_tie_break_by_doc_id():
    vs = VectorStore(["z", "a"], [[1.0, 0.0], [1.0, 0.0]])
    ranked = vs.query([1.0, 0.0], top_n=2)
    assert [d for d, _ in ranked] == ["a", "z"]


def test_query_top_n_truncates():
    vs = VectorStore(["a", "b", "c"], [[1, 0], [0, 1], [0.5, 0.5]])
    assert len(vs.query([1.0, 0.0], top_n=2)) == 2
