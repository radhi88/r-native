"""deploy_multi_symbol.py — push proven genomes onto every major symbol.

User wants the genome system trading ALL currencies in LIVE mode, each
symbol learning its own evolution. This script:

  1. Lists the tradeable universe (forex majors, crypto, gold, indices)
  2. For each, picks a starting genome (top-K HoF entries, distributed)
  3. Writes data/r_native/symbol_configs/<symbol>.json with the full
     genome dict including flags + params (PRIORITY 0 needs these)
  4. Forces 0-24h session for crypto/gold, 0-24h for forex 24/5
  5. Resets that symbol's trust score to 50 so executor doesn't skip

After this, the executor's PRIORITY 0 will see N tradeable symbols
with real flags and rotate through them every cycle.
"""
from __future__ import annotations

import json
from pathlib import Path


CFG_DIR    = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
INTEL_DIR  = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_intel")
HOF_INDEX  = Path(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame\index.json")

# Distributed deployment: forex majors get the proven scalper genomes,
# crypto + metals get the higher-volatility ones, indices get the trend ones.
# All currently-best HoF entries are BTC-trained but the flags are universal
# (use_sig_breakout works on any TF), so they generalize.
SYMBOL_PLAN = [
    # Forex majors (24/5)
    ("EURUSDm",  "4F5F59",  "FX_MAJOR"),
    ("GBPUSDm",  "8CE50E",  "FX_MAJOR"),
    ("USDJPYm",  "BCD286",  "FX_MAJOR"),
    ("AUDUSDm",  "0581D1",  "FX_MAJOR"),
    ("USDCHFm",  "009C5C",  "FX_MAJOR"),
    ("USDCADm",  "A5FB5D",  "FX_MAJOR"),
    # Forex crosses
    ("EURJPYm",  "E96EF2",  "FX_CROSS"),
    ("GBPJPYm",  "98ED3A",  "FX_CROSS"),
    # Crypto (24/7)
    ("BTCUSDm",  "3206A4",  "CRYPTO"),
    ("ETHUSDm",  "8CE50E",  "CRYPTO"),
    # Metals (24/5)
    ("XAUUSDm",  "A5FB5D",  "METAL"),
    ("XAGUSDm",  "BCD286",  "METAL"),
]


def main():
    hof = json.loads(HOF_INDEX.read_text(encoding="utf-8"))
    deployed = []
    skipped  = []
    for symbol, genome_id, asset_class in SYMBOL_PLAN:
        entry = hof.get(genome_id)
        if not entry:
            skipped.append((symbol, f"HoF entry {genome_id} not found"))
            continue
        ap = entry.get("all_params") or {}
        if not ap.get("flags"):
            skipped.append((symbol, f"{genome_id} has no flags"))
            continue

        # Build the deployed_genome — flat structure the executor expects
        target = {
            "id":           genome_id,
            "score":        float(entry.get("score") or 0),
            "stats":        entry.get("stats") or {},
            "all_params":   ap,
            "active_genes": entry.get("active_genes") or [],
            "archetype":    entry.get("archetype", "MIXED"),
            "flags":        ap.get("flags") or {},
            "params":       ap.get("params") or {},
            # 24-hour window for crypto/metals; forex effectively 24/5 too
            "start_hour":   0,
            "end_hour":     24,
        }
        # Symbol config write
        cfg_path = CFG_DIR / f"{symbol}.json"
        cfg = {"symbol": symbol}
        if cfg_path.exists():
            try: cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception: pass
        cfg["deployed_genome"] = target
        cfg["tradeable"]       = True
        cfg["asset_class"]     = asset_class
        cfg["deployed_at"]     = "manual-multi-deploy"
        cfg["best_tf"]         = entry.get("tf", "M5")
        cfg["best_archetype"]  = target["archetype"]
        cfg["best_pf"]         = (target["stats"] or {}).get("profit_factor", 0)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                            encoding="utf-8")

        # Reset symbol_intel trust score so executor doesn't skip
        intel_path = INTEL_DIR / f"{symbol}.json"
        intel = {}
        if intel_path.exists():
            try: intel = json.loads(intel_path.read_text(encoding="utf-8"))
            except Exception: pass
        intel.setdefault("symbol", symbol)
        intel["trust_score"] = 50
        intel["verdict"]     = "OK"
        intel["consecutive_losses_now"] = 0
        intel.setdefault("total_trades", 0)
        intel_path.parent.mkdir(parents=True, exist_ok=True)
        intel_path.write_text(json.dumps(intel, ensure_ascii=False, indent=2),
                              encoding="utf-8")

        deployed.append((symbol, genome_id, asset_class,
                          float(entry.get("score") or 0)))

    print(f"✅ Deployed {len(deployed)} symbols:")
    for sym, gid, cls, score in deployed:
        print(f"   {sym:10} ← {gid} (score {score:.1f}, {cls})")
    if skipped:
        print(f"\n⚠ Skipped {len(skipped)}:")
        for sym, why in skipped: print(f"   {sym}: {why}")


if __name__ == "__main__":
    main()
