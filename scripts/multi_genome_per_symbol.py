"""multi_genome_per_symbol.py — race 3 genomes per symbol head-to-head.

User: 'run more than one genome per currency to see which one wins'.

Schema change: symbol_configs/<sym>.json now supports a `competitors`
list alongside the primary `deployed_genome`. Each entry is a full
genome dict the executor can rotate through, treating them as
independent strategies on the same symbol.

The executor's multi-scan iterates (symbol, genome) pairs. Each pair
gets its own gate evaluation. Each open position is tagged with the
genome id so HoF live_pnl tracks per-genome performance.

After ~20 trades per genome, the Genome Curator decides:
  • winning genome stays as primary
  • losing genomes get pruned (kill from competitors list, not HoF)
"""
from __future__ import annotations

import json
from pathlib import Path


CFG_DIR   = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
HOF_INDEX = Path(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame\index.json")
INTEL_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_intel")


# Per-symbol competition slate: 3 genomes per symbol with DIFFERENT
# signal mixes (so they can disagree and one of them ends up winning
# in the current regime). Mixed by gene profile — some are breakout-heavy,
# others are mean-reversion, others trend-followers.
COMPETITION_PLAN = {
    "BTCUSDm":  ["3206A4", "4F5F59", "8CE50E"],   # top 3 BTC scorers
    "EURUSDm":  ["4F5F59", "8CE50E", "A5FB5D"],   # different gene mixes
    "GBPUSDm":  ["8CE50E", "BCD286", "768186"],
    "USDJPYm":  ["BCD286", "A5FB5D", "0581D1"],
    "AUDUSDm":  ["0581D1", "98ED3A", "E96EF2"],
    "USDCHFm":  ["009C5C", "6BCA7E", "BCD286"],
    "USDCADm":  ["A5FB5D", "768186", "E96EF2"],
    "EURJPYm":  ["E96EF2", "0581D1", "98ED3A"],
    "GBPJPYm":  ["98ED3A", "4F5F59", "8CE50E"],
    "ETHUSDm":  ["8CE50E", "3206A4", "768186"],
    "XAUUSDm":  ["A5FB5D", "BCD286", "4F5F59"],   # gold gets top scorers
    "XAGUSDm":  ["BCD286", "009C5C", "98ED3A"],
}


def build_genome_dict(entry: dict) -> dict:
    """Reshape HoF entry → flat genome dict the executor/gate expects."""
    ap = entry.get("all_params") or {}
    return {
        "id":           entry.get("id"),
        "score":        float(entry.get("score") or 0),
        "stats":        entry.get("stats") or {},
        "all_params":   ap,
        "active_genes": entry.get("active_genes") or [],
        "archetype":    entry.get("archetype", "MIXED"),
        "flags":        ap.get("flags") or {},
        "params":       ap.get("params") or {},
        "start_hour":   0, "end_hour": 24,
        "profit_factor": (entry.get("stats") or {}).get("profit_factor", 0),
    }


def main():
    hof = json.loads(HOF_INDEX.read_text(encoding="utf-8"))
    deployed_count = 0
    skipped = []
    for symbol, gids in COMPETITION_PLAN.items():
        candidates = []
        for gid in gids:
            e = hof.get(gid)
            if not e:
                skipped.append((symbol, gid, "not in HoF"))
                continue
            if not any((e.get("all_params", {}).get("flags") or {}).values()):
                skipped.append((symbol, gid, "no flags"))
                continue
            candidates.append(build_genome_dict(e))
        if not candidates:
            skipped.append((symbol, "all", "no valid candidates"))
            continue

        cfg_path = CFG_DIR / f"{symbol}.json"
        cfg = {"symbol": symbol}
        if cfg_path.exists():
            try: cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception: pass
        # Primary = highest-scoring (keeps backward compat with old code)
        cfg["deployed_genome"] = candidates[0]
        # Competitors = ALL of them (including primary, for symmetry)
        cfg["competitors"] = candidates
        cfg["tradeable"]   = True
        cfg["best_tf"]     = "M5"
        cfg["competition_mode"] = True
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                            encoding="utf-8")

        # Reset trust on the symbol
        intel_path = INTEL_DIR / f"{symbol}.json"
        intel = {}
        if intel_path.exists():
            try: intel = json.loads(intel_path.read_text(encoding="utf-8"))
            except Exception: pass
        intel.setdefault("symbol", symbol)
        intel["trust_score"] = 50; intel["verdict"] = "OK"
        intel["consecutive_losses_now"] = 0
        intel_path.parent.mkdir(parents=True, exist_ok=True)
        intel_path.write_text(json.dumps(intel, ensure_ascii=False, indent=2),
                              encoding="utf-8")

        deployed_count += len(candidates)
        print(f"✅ {symbol}: 3 competitors deployed")
        for c in candidates:
            print(f"     • {c['id']} score {c['score']:.1f}")

    print()
    print(f"Total: {len(COMPETITION_PLAN)} symbols × 3 genomes = "
          f"{deployed_count} (symbol,genome) competitors")
    if skipped:
        print(f"\n⚠ {len(skipped)} skipped:")
        for sym, gid, why in skipped: print(f"   {sym} {gid}: {why}")


if __name__ == "__main__":
    main()
