import json, time, collections

THRESHOLDS = {"router_accuracy": 0.90, "task_success": 0.85}

def score_case(case: dict, out: dict) -> dict:
    if case["ground_truth"].get("blocked"):
        router_ok = bool(out.get("blocked"))
        return {"id": case["id"], "router_ok": router_ok, "tools_ok": router_ok, "tokens": 0}
    label = out.get("trace", {}).get("router_label")
    router_ok = (label == case["expected_domain"])
    steps = out.get("trace", {}).get("steps", []) or []
    used = {s["tool_name"] for s in steps}
    tools_ok = set(case["expected_tools"]).issubset(used) if case["expected_tools"] else (len(used) == 0)
    return {"id": case["id"], "router_ok": router_ok, "tools_ok": tools_ok,
            "tokens": out.get("trace", {}).get("tokens", 0)}

def run(orchestrator, cases: list[dict]) -> dict:
    rows = []
    for c in cases:
        sid = orchestrator.memory.new_session()
        t0 = time.time()
        out = orchestrator.process(sid, c["input"])
        rows.append({**score_case(c, out), "latency": time.time() - t0})
    n = len(rows)
    metrics = {
        "router_accuracy": sum(r["router_ok"] for r in rows) / n,
        "task_success": sum(r["tools_ok"] for r in rows) / n,
        "avg_latency": sum(r["latency"] for r in rows) / n,
        "avg_tokens": sum(r["tokens"] for r in rows) / n,
    }
    metrics["PASS"] = (metrics["router_accuracy"] >= THRESHOLDS["router_accuracy"]
                       and metrics["task_success"] >= THRESHOLDS["task_success"])
    return {"rows": rows, "metrics": metrics}

def main():
    from harness.gemini_client import GeminiClient
    from data.store import DataStore
    from harness.memory import SessionStore
    from harness.orchestrator import Orchestrator
    cases = json.load(open("eval/testset.json", encoding="utf-8"))
    orch = Orchestrator(GeminiClient(), DataStore(seed=42), SessionStore())
    report = run(orch, cases)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
