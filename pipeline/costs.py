"""Summarise runs.jsonl per stage and provider: calls, latency, compute, list-price equivalent.

    python -m pipeline.costs            # markdown table to stdout
"""
from __future__ import annotations

import json
from collections import defaultdict

from .common import RUNS
from . import prices


def summarise() -> list[dict]:
    rows = [json.loads(l) for l in RUNS.read_text(encoding="utf-8").splitlines() if l.strip()]
    g: dict = defaultdict(lambda: {"calls": 0, "ok": 0, "errors": 0, "latency": [], "compute_s": 0.0, "gpu_s": 0.0, "list": 0.0})
    seen_imports = set()
    for r in rows:
        if r.get("imported"):  # a remote render can be imported more than once; count its GPU time once
            sig = (r.get("model"), r.get("item"), r.get("latency_s"))
            if sig in seen_imports:
                continue
            seen_imports.add(sig)
        # Experiment calls that went through production code are tagged "eNN:..." in `item`.
        if r["stage"] in ("smoke", "experiment") or str(r.get("item") or "").startswith(("e0", "e1", "smoke")):
            continue
        k = (r["stage"], r.get("provider"), r.get("model"))
        s = g[k]
        s["calls"] += 1
        s["ok" if r["status"] == "ok" else "errors"] += 1
        if r.get("latency_s") is not None and r["status"] == "ok":
            s["latency"].append(r["latency_s"])
        dev = str(r.get("device") or "")
        if "T4" in dev or "kaggle" in dev or "cuda" in dev:  # remote GPU work: not CPU time
            s["gpu_s"] += r.get("compute_s") or 0.0
        else:
            s["compute_s"] += r.get("compute_s") or 0.0
        s["list"] += r.get("list_price_usd") or 0.0
    out = []
    for (stage, prov, model), s in sorted(g.items(), key=lambda kv: str(kv[0])):
        lat = s["latency"]
        out.append({
            "stage": stage, "provider": prov, "model": model, "calls": s["calls"], "ok": s["ok"],
            "errors": s["errors"], "mean_latency_s": round(sum(lat) / len(lat), 2) if lat else None,
            "max_latency_s": round(max(lat), 2) if lat else None, "cpu_min": round(s["compute_s"] / 60, 2),
            "t4_min_equiv": round(s["compute_s"] / prices.RATES["cpu_to_t4_speedup"] / 60, 2),
            "t4_min_actual": round(s["gpu_s"] / 60, 2),
            "list_price_usd": round(s["list"], 4),
        })
    return out


def main() -> None:
    rows = summarise()
    cols = ["stage", "provider", "model", "calls", "ok", "errors", "mean_latency_s", "max_latency_s", "cpu_min",
            "t4_min_equiv", "t4_min_actual", "list_price_usd"]
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for r in rows:
        print("| " + " | ".join(str(r[c]) for c in cols) + " |")
    tot = sum(r["list_price_usd"] for r in rows)
    print(f"\nTotal list-price equivalent: ${tot:.4f}; actual spend: $0.00")


if __name__ == "__main__":
    main()
