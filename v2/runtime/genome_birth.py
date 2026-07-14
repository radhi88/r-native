"""runtime/genome_birth.py — Breed a CHILD genome from ALL engines' wins.

Born 2026-05-28 because: "ونحطم في جين ولدهم".
Every engine keeps its own decisions, but their COLLECTIVE winning
behavior gets distilled into a child genome that inherits the best
of all parents.

HOW IT WORKS:

  1. Query all winning trades + their entry context across every magic:
     - claude_simple, claude_genome, palace_council, R_Native, FRIDAY, MANUAL
     - Join trades.ts ≈ brain_snapshots.ts (closest within 60s)

  2. Compute the statistical "winning fingerprint":
     - Most common RSI band when wins happened
     - Pressure threshold above which wins clustered
     - MTF alignment that correlated with success
     - Best regime / session / bias combination

  3. Build the child genome with those exact params:
     - name: GEN-CHILD-{timestamp}
     - parents: list of every engine that contributed a winning sample
     - All standard genome params filled in from analysis

  4. Save to data/genomes_population.json (the GA pool).
     genome_promoter will eval its fitness next cycle.
     If fitness > current LIVE → it gets promoted automatically.

USAGE:
    python -m runtime.genome_birth                # breed once
    python -m runtime.genome_birth --dry          # show params without saving
    python -m runtime.genome_birth --min-wins 30  # require ≥30 wins per source
"""
from __future__ import annotations
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median, mean

from runtime.shared.db import db
from runtime.shared.tokens import PATHS, MAGICS, NAMES

POPULATION_FILE = PATHS["genomes_population"]


def _pull_winning_context(min_wins_per_source: int = 5) -> list[dict]:
    """Return rows: each winning trade joined with closest brain snapshot."""
    # First, get all winning trades from the trades table (real MT5 history)
    rows = db.query("""
        SELECT t.ts, t.magic, t.source, t.symbol, t.side, t.pnl, t.entry, t.ticket
        FROM trades t
        WHERE t.pnl > 0
        ORDER BY t.ts
    """)
    if not rows:
        return []
    snaps = db.query("SELECT * FROM brain_snapshots ORDER BY ts")
    if not snaps:
        return []

    enriched = []
    for r in rows:
        # Find latest snap <= trade ts (lookback-only)
        candidate = None
        for s in snaps:
            if s["ts"] <= r["ts"]:
                candidate = s
            else:
                break
        if candidate is None: continue
        enriched.append({
            "magic":    r["magic"],
            "source":   r["source"] or NAMES.get(r["magic"], str(r["magic"])),
            "side":     r["side"],
            "pnl":      r["pnl"],
            "regime":   candidate["regime"],
            "session":  candidate["session"],
            "rsi_m1":   candidate["rsi_m1"] or 50,
            "rsi_m5":   candidate["rsi_m5"] or 50,
            "atr_m1":   candidate["atr_m1"] or 0,
            "atr_h1":   candidate["atr_h1"] or 0,
            "pressure": candidate["pressure_10m1"] or 0,
            "bias_m5":  candidate["bias_m5"],
            "bias_m15": candidate["bias_m15"],
            "mtf_align": candidate["mtf_align"],
        })

    # Per-source minimum threshold
    by_source = Counter(r["source"] for r in enriched)
    keep_sources = {s for s, n in by_source.items() if n >= min_wins_per_source}
    return [r for r in enriched if r["source"] in keep_sources]


def _derive_genome(rows: list[dict]) -> dict:
    """Compute genome params from the winning sample population."""
    if not rows:
        return {}

    # RSI: use 75th percentile so genome ALLOWS the looser end of wins
    rsi_values = sorted([r["rsi_m1"] for r in rows if r["rsi_m1"]])
    rsi_max = int(rsi_values[int(0.75 * len(rsi_values))]) if rsi_values else 60

    # Pressure: median absolute value (winning trades had this much pressure)
    pressures_abs = [abs(r["pressure"]) for r in rows]
    min_pressure_abs = int(median(pressures_abs)) if pressures_abs else 2

    # MTF agreement: how often wins had 3+/4 align?
    mtf_counts = Counter(r["mtf_align"] for r in rows)
    # If majority of wins came from MTF "UP" or "DOWN" (i.e. 3+ aligned) → require it
    aligned_wins = mtf_counts.get("UP", 0) + mtf_counts.get("DOWN", 0)
    mixed_wins = mtf_counts.get("MIXED", 0)
    min_mtf_agreement = 3 if aligned_wins > mixed_wins else 2

    # Regime filter: which regimes hosted most wins?
    regime_counts = Counter(r["regime"] for r in rows if r["regime"] not in (None, "?"))
    top_regime = regime_counts.most_common(1)[0][0] if regime_counts else None
    regime_share = regime_counts[top_regime] / sum(regime_counts.values()) if regime_counts else 0
    regime_filter = [top_regime] if regime_share > 0.5 else list(regime_counts.keys())

    # Session filter: same logic
    session_counts = Counter(r["session"] for r in rows if r["session"])
    sessions_sorted = [s for s, _ in session_counts.most_common(3)]

    # Side bias: BUY-heavy or SELL-heavy winners?
    side_counts = Counter(r["side"] for r in rows)
    total = sum(side_counts.values())
    side_bias = None
    if side_counts.get("BUY", 0) / total > 0.7:    side_bias = "BUY_ONLY"
    elif side_counts.get("SELL", 0) / total > 0.7: side_bias = "SELL_ONLY"

    # Lot — use median lot across wins, clamp to safe range
    # (we don't have lot in trades query but can approximate)
    lot = 0.02  # safe default for current account size

    # ATR-based SL/TP (median of winning trades' atr_m1)
    atrs_m1 = [r["atr_m1"] for r in rows if r["atr_m1"]]
    sl_pts = round(median(atrs_m1) * 1.5, 2) if atrs_m1 else 3.0
    sl_pts = max(2.0, min(6.0, sl_pts))   # clamp 2-6pt
    tp_pts = round(sl_pts * 2.5, 2)        # R:R 2.5:1

    # Parents — every source that contributed
    parents = sorted(set(r["source"] for r in rows))

    name = f"GEN-CHILD-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    return {
        "name": name,
        "rsi_max": rsi_max,
        "min_imb_count": 2,           # default — footprint dependent
        "use_footprint": True,
        "min_pressure_abs": min_pressure_abs,
        "min_mtf_agreement": min_mtf_agreement,
        "lot": lot,
        "sl_pts": sl_pts,
        "tp_pts": tp_pts,
        "regime_filter": regime_filter,
        "session_filter": sessions_sorted,
        "side_bias": side_bias,
        "parents": parents,
        "born": datetime.now(timezone.utc).isoformat(),
        "born_from": "decision_log_distillation",
        "n_winning_samples": len(rows),
    }


def _summarize_samples(rows: list[dict]) -> None:
    """Print what we learned from the wins."""
    if not rows:
        print("  (no winning samples)")
        return
    by_source = Counter(r["source"] for r in rows)
    by_side = Counter(r["side"] for r in rows)
    by_regime = Counter(r["regime"] for r in rows if r["regime"])
    by_session = Counter(r["session"] for r in rows if r["session"])
    avg_pnl = mean(r["pnl"] for r in rows)
    print(f"  Total winning samples:  {len(rows)}")
    print(f"  Avg win:                ${avg_pnl:+.2f}")
    print(f"  Sources contributing:   {dict(by_source)}")
    print(f"  Sides:                  {dict(by_side)}")
    print(f"  Top regimes:            {dict(by_regime.most_common(5))}")
    print(f"  Top sessions:           {dict(by_session.most_common(5))}")


def _save_child(genome: dict) -> None:
    """Append the child to the population JSON file."""
    pop = {"genomes": []}
    if POPULATION_FILE.exists():
        try:
            pop = json.loads(POPULATION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    pop.setdefault("genomes", []).append(genome)
    POPULATION_FILE.write_text(
        json.dumps(pop, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def main():
    ap = argparse.ArgumentParser(description="Breed a child genome from all engines' wins")
    ap.add_argument("--dry", action="store_true", help="Show params, don't save")
    ap.add_argument("--min-wins", type=int, default=5,
                     help="Min wins per source to include (default 5)")
    args = ap.parse_args()

    print(f"═══ GENOME BIRTH — child of all engines ═══\n")
    print(f"[1] Pulling winning decisions across engines (min {args.min_wins} per source)...")
    rows = _pull_winning_context(min_wins_per_source=args.min_wins)
    _summarize_samples(rows)
    print()

    if not rows:
        print("  ✗ Not enough data to breed yet. Let traders run longer.")
        return

    print("[2] Distilling winning fingerprint into genome params...")
    child = _derive_genome(rows)

    print(f"\n  Child genome: {child['name']}")
    print(f"  ┌── parents: {', '.join(child['parents'])}")
    print(f"  ├── rsi_max:           {child['rsi_max']}")
    print(f"  ├── min_pressure_abs:  {child['min_pressure_abs']}")
    print(f"  ├── min_mtf_agreement: {child['min_mtf_agreement']}")
    print(f"  ├── sl_pts / tp_pts:   {child['sl_pts']} / {child['tp_pts']} (R:R {child['tp_pts']/child['sl_pts']:.1f}:1)")
    print(f"  ├── regime_filter:     {child['regime_filter']}")
    print(f"  ├── session_filter:    {child['session_filter']}")
    print(f"  ├── side_bias:         {child['side_bias'] or 'BOTH'}")
    print(f"  └── n_samples:         {child['n_winning_samples']}")

    if args.dry:
        print(f"\n  (--dry — not saving)")
        return

    print(f"\n[3] Saving to {POPULATION_FILE}")
    _save_child(child)
    print(f"  ✓ Added to population")
    print(f"\n  Next: genome_evolver evaluates fitness.")
    print(f"        genome_promoter promotes it to LIVE if it beats current.")


if __name__ == "__main__":
    main()
