"""End-to-end sem-* eval: drive be/eval/sem_testset.json through the real orchestrator
and check that (a) the semantic query fires semantic_search and (b) the grounded
reply cites only prices/specs the tool returned. Reported separately in report §7.5;
the frozen 27-case main eval (run_full) is untouched.

Usage:  python -m be.eval.run_sem
"""
import json

from be.harness.governance import groundedness_violations


def _retrieved_numbers(out: dict) -> dict:
    """Collect every numeric fact the tools actually returned (price, mileage, year)
    so groundedness reflects reality. The shared run_eval._facts_from_trace harvests
    prices ONLY (frozen for the §7.1-7.3 eval); semantic replies legitimately cite
    mileage too, so a faithful sem-* check must whitelist those as well."""
    nums = []
    for s in out.get("trace", {}).get("steps", []) or []:
        data = (s.get("tool_result") or {}).get("data")
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict):
                for k in ("asking_price", "price", "mileage_km", "year"):
                    if isinstance(it.get(k), int):
                        nums.append(it[k])
    return {"prices": nums}
from be.harness.openai_client import OpenAIClient
from be.harness.embedder import OpenAIEmbedder
from be.harness.reranker import LLMReranker
from be.harness.retrieval.retriever import HybridRetriever
from de.data.store import DataStore
from be.harness.memory import SessionStore
from be.harness.orchestrator import Orchestrator


def main():
    import config
    cases = json.load(open("be/eval/sem_testset.json", encoding="utf-8"))
    llm = OpenAIClient()
    store = DataStore(seed=42)
    store.retriever = HybridRetriever(store.catalog, OpenAIEmbedder(), LLMReranker(llm))
    orch = Orchestrator(llm, store, SessionStore())

    rows = []
    for c in cases:
        sid = orch.memory.new_session()
        try:
            out = orch.process(sid, c["input"])
            used = {s["tool_name"] for s in out.get("trace", {}).get("steps", []) or []}
            fired = "semantic_search" in used
            grounded = len(groundedness_violations(out.get("reply", ""), _retrieved_numbers(out))) == 0
            router_ok = out.get("trace", {}).get("router_label") == c["expected_domain"]
            err = None
        except Exception as e:  # a bad tool call shouldn't abort the batch (cf. run_full)
            fired = grounded = router_ok = False
            err = str(e)[:160]
        rows.append({"id": c["id"], "router_ok": router_ok, "fired": fired,
                     "grounded": grounded, "error": err})
        print(f"  {'ok ' if fired and grounded else 'x  '} {c['id']}  "
              f"router={int(router_ok)} fired={int(fired)} grounded={int(grounded)}"
              + (f"  ERR:{err}" if err else ""), flush=True)

    n = len(rows)
    summary = {"n": n,
               "fired_rate": sum(r["fired"] for r in rows) / n,
               "grounded_rate": sum(r["grounded"] for r in rows) / n,
               "router_accuracy": sum(r["router_ok"] for r in rows) / n}
    print(f"\n# sem-* e2e  model={config.MODEL}  embed={config.EMBED_MODEL}  n={n}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    json.dump({"model": config.MODEL, "rows": rows, "summary": summary},
              open("be/eval/sem_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
