"""Retrieval ablation eval: recall@k / MRR / nDCG over eval/retrieval_testset.json
for three configs (BM25 only / +dense RRF / +rerank), using REAL OpenAI embeddings
+ LLM reranker (like run_full). The rerank stage is non-deterministic, so its config
is run multiple times and reported as mean ± spread. recall@10 = the RRF candidate-pool
ceiling the reranker reorders within.

Usage:  python -m be.eval.retrieval_eval
"""
import json
import math


def recall_at_k(relevant, ranked, k):
    rel = set(relevant)
    hit = sum(1 for d in ranked[:k] if d in rel)
    return hit / min(len(rel), k) if rel else 0.0


def mrr(relevant, ranked, k=10):
    rel = set(relevant)
    for i, d in enumerate(ranked[:k]):
        if d in rel:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(relevant, ranked, k=5):
    rel = set(relevant)
    dcg = sum((1.0 if d in rel else 0.0) / math.log2(i + 2) for i, d in enumerate(ranked[:k]))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(rel), k)))
    return dcg / idcg if idcg else 0.0


CONFIGS = {
    "bm25":       {"use_dense": False, "use_rerank": False, "repeats": 1},
    "bm25+dense": {"use_dense": True,  "use_rerank": False, "repeats": 1},
    "full":       {"use_dense": True,  "use_rerank": True,  "repeats": 3},
}


def _eval_once(retriever, cases, use_dense, use_rerank):
    acc = {"recall@1": 0.0, "recall@3": 0.0, "recall@5": 0.0,
           "recall@10": 0.0, "mrr@10": 0.0, "ndcg@5": 0.0}
    for c in cases:
        ranked = [m["title"] for m in retriever.retrieve(
            c["query"], k=10, use_dense=use_dense, use_rerank=use_rerank)]
        rel = c["relevant_models"]
        acc["recall@1"] += recall_at_k(rel, ranked, 1)
        acc["recall@3"] += recall_at_k(rel, ranked, 3)
        acc["recall@5"] += recall_at_k(rel, ranked, 5)
        acc["recall@10"] += recall_at_k(rel, ranked, 10)
        acc["mrr@10"] += mrr(rel, ranked, 10)
        acc["ndcg@5"] += ndcg_at_k(rel, ranked, 5)
    n = len(cases)
    return {k: v / n for k, v in acc.items()}


def run_ablation(retriever, cases):
    out = {}
    for name, cfg in CONFIGS.items():
        runs = [_eval_once(retriever, cases, cfg["use_dense"], cfg["use_rerank"])
                for _ in range(cfg["repeats"])]
        keys = runs[0].keys()
        out[name] = {
            "mean": {k: sum(r[k] for r in runs) / len(runs) for k in keys},
            "spread": {k: max(r[k] for r in runs) - min(r[k] for r in runs) for k in keys},
            "repeats": cfg["repeats"],
        }
    return out


def main():
    import config
    from de.data.store import DataStore
    from be.harness.openai_client import OpenAIClient
    from be.harness.embedder import OpenAIEmbedder
    from be.harness.reranker import LLMReranker
    from be.harness.retrieval.retriever import HybridRetriever

    cases = json.load(open("be/eval/retrieval_testset.json", encoding="utf-8"))
    store = DataStore(seed=42)
    llm = OpenAIClient()
    retriever = HybridRetriever(store.catalog, OpenAIEmbedder(), LLMReranker(llm))
    result = run_ablation(retriever, cases)
    print(f"# retrieval ablation  model={config.MODEL}  embed={config.EMBED_MODEL}  n={len(cases)}")
    print("# config       recall@1 recall@3 recall@5 mrr@10 ndcg@5  (recall@10 ceiling)")
    for name, r in result.items():
        m = r["mean"]
        print(f"  {name:11s}  {m['recall@1']:.3f}    {m['recall@3']:.3f}    {m['recall@5']:.3f}   "
              f"{m['mrr@10']:.3f}  {m['ndcg@5']:.3f}   ({m['recall@10']:.3f}, repeats={r['repeats']})")
    json.dump({"model": config.MODEL, "embed_model": config.EMBED_MODEL,
               "n": len(cases), "configs": result},
              open("be/eval/retrieval_results.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\nwrote be/eval/retrieval_results.json")


if __name__ == "__main__":
    main()
