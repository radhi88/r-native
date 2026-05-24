"""walkforward.py — J.2 — Robust strategy validation via walk-forward testing.

A single GA campaign can overfit. WF runs MULTIPLE campaigns on rolling
in-sample/out-of-sample windows and only "blesses" genomes that survive across
all (or most) windows.

Approach (Anchored Walk-Forward):
  Window 1: Jan IS → Feb OOS
  Window 2: Jan-Feb IS → Mar OOS
  Window 3: Jan-Mar IS → Apr OOS
  ...
  A genome is ROBUST if it appears in top-K AND keeps positive OOS PF across windows.

Use case: instead of deploying the top genome from one campaign blindly,
deploy a genome that proved itself across 4+ historical windows.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def run_walkforward(symbol: str, tf: str,
                    n_windows: int = 4,
                    window_size_days: int = 30,
                    pg_per_window: int = 200,
                    gens_per_window: int = 2,
                    top_k: int = 20,
                    progress_cb=None) -> dict:
    """Run N walkforward windows. Returns ranking by robustness.

    Args:
        symbol:           e.g. BTCUSDm
        tf:               e.g. M5
        n_windows:        how many WF windows to run
        window_size_days: OOS window length (IS grows anchored)
        pg_per_window:    Proving Grounds candidates per window
        gens_per_window:  generations per tribe per window
        top_k:            within each window, look at top K only
        progress_cb:      optional callback(window_i, total, genome_id)
    """
    from r_native.genetic_engine import GeneticEngine, CampaignConfig
    import multiprocessing as mp

    # Collect genome appearances across windows
    # genome_id → {windows: [w1, w2,...], pf_per_window: [...], oos_pf_per_window: [...]}
    robustness: dict[str, dict] = {}

    for wi in range(n_windows):
        if progress_cb: progress_cb(wi + 1, n_windows, None)

        # Each window uses anchored IS — earlier WF windows use less data
        # bars_per_day approx for M5 = 288
        bars_per_day = {"M5": 288, "M15": 96, "M30": 48, "H1": 24, "H4": 6}.get(tf, 100)
        is_days  = window_size_days * (wi + 1)   # anchored: grows each window
        oos_days = window_size_days
        bars_total = bars_per_day * (is_days + oos_days)
        train_split = is_days / (is_days + oos_days)

        cfg = CampaignConfig(
            symbol=symbol, timeframe=tf, bars=bars_total,
            pg_candidates=pg_per_window,
            tribe_a_gens=gens_per_window, tribe_b_gens=gens_per_window,
            war_gens=gens_per_window, revival_gens=1, retrain_gens=1,
            n_workers=max(2, mp.cpu_count() - 1),
            train_split=train_split,
        )

        engine  = GeneticEngine(cfg)
        summary = engine.run_full_campaign()

        # Take top K from this window
        top_genomes = summary.get("elite_genomes", []) or []
        for rank, gid in enumerate(top_genomes[:top_k]):
            if not gid: continue
            r = robustness.setdefault(gid, {
                "id": gid, "windows": [], "rank_per_window": [],
                "score_per_window": [],
            })
            r["windows"].append(wi)
            r["rank_per_window"].append(rank + 1)
            # Best score for top would be summary["top_score"] for rank 0
            if rank == 0:
                r["score_per_window"].append(summary.get("top_score", 0))

    # Score robustness: appearances count + average rank (lower = better)
    ranked = []
    for gid, r in robustness.items():
        n_appearances = len(r["windows"])
        avg_rank = sum(r["rank_per_window"]) / n_appearances if n_appearances else 99
        # Robustness score: bonus for appearances, penalty for high avg_rank
        robust_score = n_appearances * 10 - avg_rank
        ranked.append({
            "id":            gid,
            "appearances":   n_appearances,
            "appearances_pct": round(n_appearances / n_windows * 100, 1),
            "avg_rank":      round(avg_rank, 1),
            "best_rank":     min(r["rank_per_window"]),
            "windows":       r["windows"],
            "robust_score":  round(robust_score, 2),
        })
    ranked.sort(key=lambda x: -x["robust_score"])

    return {
        "symbol":    symbol,
        "tf":        tf,
        "n_windows": n_windows,
        "candidates_total": len(ranked),
        "robust_top":      ranked[:10],
        "completed_at":    datetime.now(timezone.utc).isoformat(),
    }


def is_robust(genome_id: str, wf_result: dict, min_appearances_pct: float = 50) -> bool:
    """Return True if genome appears in ≥X% of WF windows."""
    for r in wf_result.get("robust_top", []):
        if r["id"] == genome_id:
            return r["appearances_pct"] >= min_appearances_pct
    return False
