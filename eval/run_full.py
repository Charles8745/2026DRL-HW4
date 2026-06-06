"""Full-run eval driver: optional throttle + retry + per-domain rollup.

Runs all 27 testset cases end-to-end against real OpenAI and writes per-case rows
incrementally (so a kill mid-run keeps progress), then prints aggregate + per-domain
metrics. A thin wrapper paces calls (default 0s — OpenAI paid tier doesn't need it) and
retries a transient 429/rate-limit so one blip doesn't turn a case into an `error` row.

Production code is untouched: `score_case`/`THRESHOLDS` are reused from run_eval, and the
client is a thin duck-typed wrapper over the real OpenAIClient (same LLM Protocol).

Usage:  python -m eval.run_full                       # all 27, model from config (gpt-4.1-mini)
        python -m eval.run_full --model gpt-4o-mini --min-interval 1
"""
import argparse, json, re, time

import config
from eval.run_eval import score_case, score_multiturn, THRESHOLDS
from harness.openai_client import OpenAIClient
from harness.llm import LLMResponse
from data.store import DataStore
from harness.memory import SessionStore
from harness.orchestrator import Orchestrator

DOMAINS = {  # testset id prefix -> human label (matches report's 5 router classes + eval buckets)
    "find": "找車推薦", "spec": "規格比較", "txn": "交易訂單", "after": "售後轉真人",
    "multi": "跨情境多輪", "oos": "範圍外", "inj": "injection",
}


class ThrottledRetryClient:
    """Duck-types the LLM Protocol: paces calls and retries 429s, wrapping the real OpenAIClient."""

    def __init__(self, model, min_interval=0.0, max_retries=8, max_sleep=65.0):
        self.inner = OpenAIClient(model=model)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.max_sleep = max_sleep
        self._last = 0.0
        self.calls = 0
        self.retries = 0

    def _throttle(self):
        dt = time.monotonic() - self._last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)

    def generate(self, system, messages, tools=None) -> LLMResponse:
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                self.calls += 1
                resp = self.inner.generate(system, messages, tools=tools)
                self._last = time.monotonic()
                return resp
            except Exception as e:
                self._last = time.monotonic()
                s = str(e)
                if ("429" not in s and "RESOURCE_EXHAUSTED" not in s) or attempt >= self.max_retries:
                    raise
                self.retries += 1
                m = re.search(r"retryDelay': '(\d+)s'", s) or re.search(r"retry in ([\d.]+)s", s)
                delay = float(m.group(1)) if m else 15.0
                time.sleep(min(delay + 2.0, self.max_sleep))


def aggregate(rows):
    n = len(rows)
    ra = sum(r["router_ok"] for r in rows) / n
    ts = sum(r["tools_ok"] for r in rows) / n
    gv = sum(not r["grounded_ok"] for r in rows) / n
    return {
        "n": n,
        "router_accuracy": ra,
        "task_success": ts,
        "groundedness_violation_rate": gv,
        "avg_latency": sum(r["latency"] for r in rows) / n,
        "avg_tokens": sum(r["tokens"] for r in rows) / n,
        "errors": sum(1 for r in rows if r.get("error")),
        "PASS": (ra >= THRESHOLDS["router_accuracy"]
                 and ts >= THRESHOLDS["task_success"]
                 and gv <= THRESHOLDS["groundedness_violation_rate"]),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=config.MODEL)
    ap.add_argument("--min-interval", type=float, default=0.0, help="min seconds between API calls")
    ap.add_argument("--offset", type=int, default=0, help="skip first N cases")
    ap.add_argument("--limit", type=int, default=None, help="run at most N cases (smoke test)")
    ap.add_argument("--out", default="eval/results.json")
    args = ap.parse_args()

    cases = json.load(open("eval/testset.json", encoding="utf-8"))
    cases = cases[args.offset:]
    if args.limit is not None:
        cases = cases[:args.limit]
    client = ThrottledRetryClient(args.model, min_interval=args.min_interval)
    orch = Orchestrator(client, DataStore(seed=42), SessionStore())

    rows = []
    for i, c in enumerate(cases):
        sid = orch.memory.new_session()
        t0 = time.time()
        try:
            out = orch.process(sid, c["input"])
            row = {**score_case(c, out), "latency": time.time() - t0, "error": None}
        except Exception as e:  # exhausted retries / non-429 failure -> honest error row
            row = {"id": c["id"], "router_ok": False, "tools_ok": False, "grounded_ok": False,
                   "tokens": 0, "latency": time.time() - t0, "error": str(e)[:200]}
        row["domain"] = DOMAINS.get(c["id"].split("-")[0], "?")
        # multi-* two-turn chain: drive the follow-up turn in the SAME session, score secondary tool
        if c.get("followup") and row.get("error") is None:
            try:
                out2 = orch.process(sid, c["followup"])
                row["chain"] = score_multiturn(c, out, out2)
            except Exception as e:
                row["chain"] = {"id": c["id"], "primary_ok": False, "secondary_ok": False,
                                "chain_ok": False, "error": str(e)[:160]}
        rows.append(row)
        flag = "ERR" if row.get("error") else ("ok " if row["router_ok"] and row["tools_ok"] else "x  ")
        chain = row.get("chain")
        chain_str = (f" | chain={'ok' if chain['chain_ok'] else 'x'}"
                     f"(2nd:{int(chain['secondary_ok'])} {c['ground_truth'].get('secondary_tool','')})") if chain else ""
        print(f"[{i + 1:2d}/{len(cases)}] {flag} {c['id']:9s} "
              f"router={int(row['router_ok'])} tools={int(row['tools_ok'])} "
              f"grounded={int(row['grounded_ok'])} tok={row['tokens']} lat={row['latency']:.1f}s"
              + chain_str + (f"  ({row['error']})" if row.get("error") else ""), flush=True)
        json.dump({"model": args.model, "rows": rows, "metrics": aggregate(rows)},
                  open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    metrics = aggregate(rows)
    by_dom = {}
    for r in rows:
        by_dom.setdefault(r["domain"], []).append(r)
    per_domain = {d: aggregate(rs) for d, rs in by_dom.items()}

    chain_rows = [r["chain"] for r in rows if r.get("chain")]
    multiturn = {"n": len(chain_rows),
                 "chain_success": (sum(c["chain_ok"] for c in chain_rows) / len(chain_rows)) if chain_rows else None,
                 "rows": chain_rows}

    json.dump({"model": args.model, "rows": rows, "metrics": metrics, "per_domain": per_domain,
               "multiturn": multiturn, "api_calls": client.calls, "api_retries": client.retries},
              open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("\n=== AGGREGATE ===")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"api_calls={client.calls} retries={client.retries}")
    print("\n=== PER DOMAIN (router / task / grounded-violation) ===")
    for d, m in per_domain.items():
        print(f"  {d:10s} n={m['n']} router={m['router_accuracy']:.2f} "
              f"task={m['task_success']:.2f} gviol={m['groundedness_violation_rate']:.2f}")
    if chain_rows:
        print(f"\n=== MULTI-TURN CHAIN (n={multiturn['n']}, success={multiturn['chain_success']:.2f}) ===")
        for c in chain_rows:
            print(f"  {'ok ' if c['chain_ok'] else 'x  '} {c['id']:9s} "
                  f"primary={int(c['primary_ok'])} secondary={int(c['secondary_ok'])}")


if __name__ == "__main__":
    main()
