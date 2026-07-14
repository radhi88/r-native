"""
pattern_miner.py — Extract WINNING patterns from backtest trades.

Reads backtest_trades.csv (3000+ trades with full context) and finds:
  "When ALL of {condition_X, condition_Y, condition_Z} are true,
   win rate jumps from 35% to 65%+"

This gives us the FILTERS to add to the gene pool — turning the failed
strategy into a profitable one by only trading the proven setups.

Output: friday_v3/data/miner_rules.json
"""
from __future__ import annotations
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Callable
from itertools import combinations

ROOT     = Path(r"C:\Users\Radhi\MT5\friday_v3")
TRADES   = ROOT / "data" / "backtest_trades.csv"
OUT      = ROOT / "data" / "miner_rules.json"

MIN_SAMPLE = 30        # need at least N trades for a rule to be valid
MIN_WIN_RATE = 55      # only keep rules with >= 55% WR


def load_trades() -> list[dict]:
    if not TRADES.exists():
        return []
    out = []
    with open(TRADES, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                row["pl"]           = float(row["pl"])
                row["lot"]          = float(row["lot"])
                row["dip_score"]    = int(row["dip_score"])
                row["dip_drop_atr"] = float(row["dip_drop_atr"])
                row["age_bars"]     = int(row["age_bars"])
                row["win"]          = int(row["win"])
                out.append(row)
            except Exception: continue
    return out


def compute_metrics(trades: list[dict]) -> dict:
    if not trades: return {}
    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    gain = sum(t["pl"] for t in wins)
    loss = abs(sum(t["pl"] for t in losses))
    return {
        "trades": len(trades),
        "wins":   len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins)/len(trades)*100, 1),
        "profit_factor": round(gain/loss, 2) if loss > 0 else 999,
        "net_pl": round(sum(t["pl"] for t in trades), 2),
        "avg_win": round(gain/max(1,len(wins)), 4),
        "avg_loss": round(-loss/max(1,len(losses)), 4),
    }


# Only PREDICTIVE filters (known AT ENTRY) — no outcome-based filters
FILTERS = [
    ("dip_score>=70",          lambda t: t["dip_score"] >= 70),
    ("dip_score>=80",          lambda t: t["dip_score"] >= 80),
    ("dip_score>=90",          lambda t: t["dip_score"] >= 90),
    ("drop_atr>=1.5",          lambda t: t["dip_drop_atr"] >= 1.5),
    ("drop_atr>=2.0",          lambda t: t["dip_drop_atr"] >= 2.0),
    ("drop_atr>=2.5",          lambda t: t["dip_drop_atr"] >= 2.5),
    ("drop_atr<3.5",           lambda t: t["dip_drop_atr"] < 3.5),
    ("lot<=0.01",              lambda t: t["lot"] <= 0.01),
    ("lot>=0.02",              lambda t: t["lot"] >= 0.02),
]


def evaluate_rule(trades: list[dict], filters: list[tuple]) -> dict:
    """Apply ALL filters (AND) and compute metrics on the subset."""
    subset = trades
    for _, pred in filters:
        subset = [t for t in subset if pred(t)]
    m = compute_metrics(subset)
    m["name"] = " + ".join(name for name, _ in filters)
    m["condition"] = m["name"]
    m["sample_size"] = m.get("trades", 0)
    return m


def mine(trades: list[dict]) -> list[dict]:
    """Find winning single-filter and two-filter combinations."""
    baseline = compute_metrics(trades)
    print(f"Baseline (all {baseline.get('trades',0)} trades):")
    print(f"  WR: {baseline.get('win_rate',0)}%   PF: {baseline.get('profit_factor',0)}   Net: ${baseline.get('net_pl',0)}")

    rules = []

    # Single filters
    for name, pred in FILTERS:
        m = evaluate_rule(trades, [(name, pred)])
        if m.get("trades", 0) >= MIN_SAMPLE and m.get("win_rate", 0) >= MIN_WIN_RATE:
            rules.append(m)

    # Two-filter combos (find synergies)
    for f1, f2 in combinations(FILTERS, 2):
        m = evaluate_rule(trades, [f1, f2])
        if m.get("trades", 0) >= MIN_SAMPLE and m.get("win_rate", 0) >= MIN_WIN_RATE:
            rules.append(m)

    # Sort by net P/L (best edges first)
    rules.sort(key=lambda r: -r.get("net_pl", -999))

    # Dedup by win_rate × sample_size (avoid near-duplicates)
    seen = set()
    final = []
    for r in rules:
        key = (round(r["win_rate"]), r["sample_size"] // 10)
        if key in seen: continue
        seen.add(key)
        final.append(r)
        if len(final) >= 15: break

    return final


def main():
    trades = load_trades()
    if not trades:
        print("No backtest trades — run python -m friday_v3.backtest.runner first.")
        return

    print(f"Loaded {len(trades)} backtest trades\n")
    rules = mine(trades)
    baseline = compute_metrics(trades)

    output = {
        "baseline":         baseline,
        "rules_found":      len(rules),
        "min_sample":       MIN_SAMPLE,
        "min_win_rate_pct": MIN_WIN_RATE,
        "rules":            rules,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== {len(rules)} WINNING RULES FOUND ===\n")
    for i, r in enumerate(rules[:10], 1):
        edge = r["win_rate"] - baseline.get("win_rate", 0)
        print(f"#{i}. {r['name']}")
        print(f"     WR {r['win_rate']}% (+{edge:.1f}pp)  PF {r['profit_factor']}  "
              f"n={r['sample_size']}  Net ${r['net_pl']}")
    print(f"\nWritten to: {OUT}")


if __name__ == "__main__":
    main()
