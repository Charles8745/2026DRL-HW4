import json, time
from harness.governance import groundedness_violations

THRESHOLDS = {"router_accuracy": 0.90, "task_success": 0.85, "groundedness_violation_rate": 0.0}

def _facts_from_trace(out: dict) -> dict:
    """Collect every price the tools actually returned, so the reply can be checked against them."""
    prices = []
    for s in out.get("trace", {}).get("steps", []) or []:
        data = (s.get("tool_result") or {}).get("data")
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict):
                for k in ("asking_price", "price"):
                    if isinstance(it.get(k), int):
                        prices.append(it[k])
    return {"prices": prices}

def score_case(case: dict, out: dict) -> dict:
    if case["ground_truth"].get("blocked"):
        router_ok = bool(out.get("blocked"))
        return {"id": case["id"], "router_ok": router_ok, "tools_ok": router_ok,
                "grounded_ok": True, "tokens": 0}
    label = out.get("trace", {}).get("router_label")
    router_ok = (label == case["expected_domain"])
    steps = out.get("trace", {}).get("steps", []) or []
    used = {s["tool_name"] for s in steps}     # includes proposed (confirmation-gated) tools
    tools_ok = set(case["expected_tools"]).issubset(used) if case["expected_tools"] else (len(used) == 0)
    grounded_ok = len(groundedness_violations(out.get("reply", ""), _facts_from_trace(out))) == 0
    return {"id": case["id"], "router_ok": router_ok, "tools_ok": tools_ok,
            "grounded_ok": grounded_ok, "tokens": out.get("trace", {}).get("tokens", 0)}

def select_cases(cases: list[dict], offset: int = 0, limit: int | None = None) -> list[dict]:
    """Pick a batch of cases (for running the testset in chunks under a rate-limited key)."""
    sliced = cases[offset:]
    return sliced[:limit] if limit is not None else sliced

def run(orchestrator, cases: list[dict], sleep_s: float = 0.0) -> dict:
    rows = []
    for i, c in enumerate(cases):
        if sleep_s and i:
            time.sleep(sleep_s)
        sid = orchestrator.memory.new_session()
        t0 = time.time()
        try:
            out = orchestrator.process(sid, c["input"])
            row = {**score_case(c, out), "latency": time.time() - t0, "error": None}
        except Exception as e:                       # one 429/transient error shouldn't abort the batch
            row = {"id": c["id"], "router_ok": False, "tools_ok": False, "grounded_ok": False,
                   "tokens": 0, "latency": time.time() - t0, "error": str(e)[:200]}
        rows.append(row)
    n = len(rows)
    metrics = {
        "n": n,
        "router_accuracy": sum(r["router_ok"] for r in rows) / n,
        "task_success": sum(r["tools_ok"] for r in rows) / n,
        "groundedness_violation_rate": sum(not r["grounded_ok"] for r in rows) / n,
        "avg_latency": sum(r["latency"] for r in rows) / n,
        "avg_tokens": sum(r["tokens"] for r in rows) / n,
        "errors": sum(1 for r in rows if r.get("error")),
    }
    metrics["PASS"] = (metrics["router_accuracy"] >= THRESHOLDS["router_accuracy"]
                       and metrics["task_success"] >= THRESHOLDS["task_success"]
                       and metrics["groundedness_violation_rate"] <= THRESHOLDS["groundedness_violation_rate"])
    return {"rows": rows, "metrics": metrics}

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Run the RideButler evaluation testset against real OpenAI.")
    ap.add_argument("--limit", type=int, default=None, help="max cases to run (batch size)")
    ap.add_argument("--offset", type=int, default=0, help="skip the first N cases (for batching)")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds to wait between cases (avoid 429)")
    args = ap.parse_args()

    from harness.openai_client import OpenAIClient
    from data.store import DataStore
    from harness.memory import SessionStore
    from harness.orchestrator import Orchestrator
    cases = json.load(open("eval/testset.json", encoding="utf-8"))
    batch = select_cases(cases, args.offset, args.limit)
    orch = Orchestrator(OpenAIClient(), DataStore(seed=42), SessionStore())
    report = run(orch, batch, sleep_s=args.sleep)
    print(f"# batch: offset={args.offset} limit={args.limit} -> {len(batch)} cases "
          f"({batch[0]['id']}..{batch[-1]['id']})" if batch else "# batch: empty")
    for r in report["rows"]:
        flag = "ERR" if r.get("error") else ("ok " if r["router_ok"] and r["tools_ok"] else "x  ")
        print(f"  {flag} {r['id']}" + (f"  ({r['error']})" if r.get("error") else ""))
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
