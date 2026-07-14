"""
QADER — Live Bayesian DNA Feedback Loop
=========================================
Reads live trade outcomes from journal, updates gene posterior probabilities,
and rewrites arbiter weights. Runs as a background daemon every N minutes.

Pipeline:
  live_performance_journal.jsonl
       ↓
  Bayesian update per gene (prior → posterior)
       ↓
  gene_store_backtest.json  (updated live_performance)
       ↓
  arbiter_gene_weights.json (rewritten with fresh weights)
       ↓
  SignalArbiter picks up new weights next cycle

Usage:
    .venv\\Scripts\\python.exe scripts\\dna_live_feedback.py
    .venv\\Scripts\\python.exe scripts\\dna_live_feedback.py --interval 300
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / "src"
for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QADER_ROOT", str(ROOT))

JOURNAL_PATH  = ROOT / "logs" / "live_performance_journal.jsonl"
DNA_PATH      = ROOT / "data" / "qader" / "dna" / "gene_store_backtest.json"
WEIGHTS_PATH  = ROOT / "data" / "qader" / "dna" / "arbiter_gene_weights.json"
FEEDBACK_LOG  = ROOT / "logs" / "dna_feedback.jsonl"


# ─── BAYESIAN UPDATE ─────────────────────────────────────────────────────────
def bayesian_update(prior: float, n_wins: int, n_total: int,
                    alpha_prior: int = 10) -> float:
    """
    Beta-Binomial Bayesian update.
    prior: historical win rate from backtest
    alpha_prior: strength of prior belief (equiv. sample size)
    Returns posterior win rate.
    """
    alpha = prior * alpha_prior
    beta  = (1 - prior) * alpha_prior
    posterior = (alpha + n_wins) / (alpha + beta + n_total)
    return round(posterior, 4)


def confidence_interval(posterior: float, n: int) -> tuple[float, float]:
    """95% Wilson confidence interval for win rate."""
    if n == 0:
        return 0.0, 1.0
    z = 1.96
    p = posterior
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)


# ─── JOURNAL READER ──────────────────────────────────────────────────────────
def load_live_trades() -> list[dict]:
    if not JOURNAL_PATH.exists():
        return []
    trades = []
    with JOURNAL_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("event") in ("demo_trade_exit", "demo_trade_entry"):
                    trades.append(rec)
            except Exception:
                continue
    return trades


# ─── GENE MATCHER ────────────────────────────────────────────────────────────
def match_gene(trade: dict, genes: list[dict]) -> str | None:
    """Find which gene best describes this trade's context."""
    symbol    = trade.get("symbol", "")
    timeframe = trade.get("timeframe", "")
    direction = trade.get("action") or trade.get("final_action") or trade.get("direction", "")
    session   = trade.get("session", "")
    atr_regime= trade.get("atr_regime", "")

    best_id    = None
    best_score = -1
    for gene in genes:
        grp = gene.get("group", {})
        score = 0
        if grp.get("symbol")    == symbol:    score += 3
        if grp.get("timeframe") == timeframe: score += 2
        if grp.get("direction") in (direction, direction.upper()): score += 2
        if grp.get("session")   == session:   score += 1
        if grp.get("atr_regime")== atr_regime:score += 1
        if score > best_score:
            best_score = score
            best_id    = gene["gene_id"]
    return best_id if best_score >= 5 else None


# ─── MAIN UPDATE CYCLE ───────────────────────────────────────────────────────
def run_update(verbose: bool = True) -> dict:
    if not DNA_PATH.exists():
        return {"error": "gene_store_backtest.json not found — run massive_backtest_engine.py first"}

    store = json.loads(DNA_PATH.read_text(encoding="utf-8"))
    genes = store.get("genes", [])
    if not genes:
        return {"error": "no genes in store"}

    live_trades = load_live_trades()
    if not live_trades:
        return {"status": "no_live_trades_yet", "genes": len(genes)}

    updates = {}
    for trade in live_trades:
        gene_id = match_gene(trade, genes)
        if not gene_id:
            continue
        if gene_id not in updates:
            updates[gene_id] = {"wins": 0, "total": 0}
        outcome = trade.get("outcome", "") or trade.get("execution_status", "")
        if trade.get("event") == "demo_trade_exit":
            won = bool(trade.get("won", False)) or float(trade.get("profit", 0) or 0) > 0
        else:
            won = outcome == "tp" or bool(trade.get("win", False))
        updates[gene_id]["total"] += 1
        if won:
            updates[gene_id]["wins"] += 1

    genes_updated = 0
    for gene in genes:
        gid = gene["gene_id"]
        if gid not in updates:
            continue
        prior  = float(gene["stats"].get("win_rate", 0.55))
        n_wins = updates[gid]["wins"]
        n_total= updates[gid]["total"]
        posterior = bayesian_update(prior, n_wins, n_total)
        ci_lo, ci_hi = confidence_interval(posterior, n_total)
        gene["live_performance"]["trades"]           = n_total
        gene["live_performance"]["wins"]             = n_wins
        gene["live_performance"]["win_rate"]         = round(n_wins / max(n_total, 1), 4)
        gene["live_performance"]["bayesian_posterior"]= posterior
        gene["live_performance"]["ci_95"]            = [ci_lo, ci_hi]
        gene["live_performance"]["last_updated"]     = datetime.now(timezone.utc).isoformat()
        # Deactivate if posterior drops far below min_confidence
        if n_total >= 20 and posterior < gene["thresholds"]["min_confidence"] - 0.15:
            gene["active"] = False
            if verbose:
                print(f"  [DEACTIVATE] {gid}: posterior={posterior:.3f} below threshold")
        elif not gene["active"] and posterior >= gene["thresholds"]["min_confidence"]:
            gene["active"] = True
            if verbose:
                print(f"  [REACTIVATE] {gid}: posterior={posterior:.3f} recovered")
        # Adjust lot_scale based on live performance vs backtest
        if n_total >= 10:
            ratio = posterior / max(prior, 0.01)
            gene["thresholds"]["lot_scale"] = round(
                float(gene["thresholds"].get("lot_scale", 1.0)) * min(1.5, max(0.5, ratio)), 2
            )
        genes_updated += 1

    # Rewrite gene store
    store["genes"] = genes
    store["last_feedback_update"] = datetime.now(timezone.utc).isoformat()
    DNA_PATH.write_text(json.dumps(store, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    # Rewrite arbiter weights
    weights = {}
    for gene in genes:
        if not gene.get("active", True):
            continue
        posterior = gene["live_performance"].get("bayesian_posterior") or gene["stats"]["win_rate"]
        weights[gene["gene_id"]] = {
            "min_confidence": gene["thresholds"]["min_confidence"],
            "lot_scale":      gene["thresholds"]["lot_scale"],
            "sl_atr_mult":    gene["thresholds"]["sl_atr_mult"],
            "tp_atr_mult":    gene["thresholds"]["tp_atr_mult"],
            "sharpe":         gene["stats"]["sharpe"],
            "win_rate_backtest": gene["stats"]["win_rate"],
            "win_rate_live":  gene["live_performance"].get("win_rate"),
            "bayesian_posterior": posterior,
            "active":         gene["active"],
        }
    WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEIGHTS_PATH.write_text(json.dumps(weights, indent=2), encoding="utf-8")

    result = {
        "status":        "updated",
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "live_trades":   len(live_trades),
        "genes_total":   len(genes),
        "genes_updated": genes_updated,
        "genes_active":  sum(1 for g in genes if g.get("active", True)),
        "gene_updates":  updates,
    }

    FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(result, default=str) + "\n")

    if verbose:
        print(f"  [BAYES] {genes_updated} genes updated | "
              f"active={result['genes_active']}/{result['genes_total']} | "
              f"live_trades={len(live_trades)}")

    return result


# ─── DAEMON MODE ─────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=60, help="Update interval in seconds")
    parser.add_argument("--once",     action="store_true", help="Run once and exit")
    args = parser.parse_args()

    print(f"[DNA FEEDBACK] Starting Bayesian live feedback daemon (interval={args.interval}s)")
    print(f"  Journal : {JOURNAL_PATH}")
    print(f"  DNA     : {DNA_PATH}")
    print(f"  Weights : {WEIGHTS_PATH}\n")

    if args.once:
        result = run_update(verbose=True)
        print(json.dumps(result, indent=2, default=str))
        return

    while True:
        try:
            result = run_update(verbose=True)
            if result.get("error"):
                print(f"  [WARN] {result['error']}")
        except Exception as exc:
            print(f"  [ERROR] Feedback loop error: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
