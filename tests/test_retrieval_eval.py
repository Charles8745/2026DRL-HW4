from eval.retrieval_eval import recall_at_k, mrr, ndcg_at_k


def test_recall_capped_by_min_rel_k():
    assert recall_at_k(["a"], ["a", "b", "c"], 3) == 1.0          # |rel|=1 -> min(1,3)=1
    assert recall_at_k(["a", "b", "c", "d"], ["a", "x", "y"], 3) == 1 / 3  # 1 hit / min(4,3)


def test_recall_zero_when_no_relevant():
    assert recall_at_k([], ["a", "b"], 3) == 0.0


def test_mrr_first_hit():
    assert mrr(["b"], ["a", "b", "c"], k=10) == 0.5
    assert mrr(["z"], ["a", "b", "c"], k=10) == 0.0


def test_ndcg_perfect_is_one():
    assert abs(ndcg_at_k(["a", "b"], ["a", "b", "c"], 5) - 1.0) < 1e-9


def test_ndcg_zero_when_no_hit():
    assert ndcg_at_k(["z"], ["a", "b"], 5) == 0.0


def test_ndcg_discounts_lower_ranks():
    # one hit at rank 1 should score higher than the same hit at rank 3
    assert ndcg_at_k(["a"], ["a", "x", "y"], 5) > ndcg_at_k(["a"], ["x", "y", "a"], 5)


def test_run_ablation_shape_offline():
    # ablation runner works with a fake retriever (no API); verifies config wiring
    from eval.retrieval_eval import run_ablation

    class StubRetriever:
        def retrieve(self, query, k=10, use_dense=True, use_rerank=True):
            order = ["A", "B", "C"] if use_rerank else ["B", "A", "C"]
            return [{"title": t} for t in order[:k]]

    cases = [{"id": "x", "query": "q", "relevant_models": ["A"]}]
    out = run_ablation(StubRetriever(), cases)
    assert set(out) == {"bm25", "bm25+dense", "full"}
    assert out["full"]["repeats"] == 3
    assert "recall@10" in out["bm25"]["mean"]
