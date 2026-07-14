"""Reset and reactivate all DNA genes — fix corrupted live_performance and lot_scale."""
import json
from pathlib import Path

GENE_STORE = Path("data/qader/dna/gene_store_backtest.json")
ARBITER    = Path("data/qader/dna/arbiter_gene_weights.json")

d = json.loads(GENE_STORE.read_bytes())

for gene in d["genes"]:
    gid = gene["gene_id"]
    t   = gene["thresholds"]
    s   = gene["stats"]

    # Reactivate
    gene["active"] = True

    # Fix corrupted lot_scale (must be 0.5–2.0 range, not 0.01)
    pf = s.get("profit_factor", 1.0)
    if t.get("lot_scale", 1.0) < 0.1:
        t["lot_scale"] = round(min(2.0, max(0.5, pf / 2.0)), 2)
        print(f"  Fixed lot_scale -> {t['lot_scale']} for {gid}")

    # Reset live performance counters (corrupted from stale logs)
    gene["live_performance"] = {
        "trades":             0,
        "wins":               0,
        "win_rate":           None,
        "bayesian_prior":     s["win_rate"],
        "bayesian_posterior": s["win_rate"],
    }
    print(f"  Reactivated: {gid} | conf>={t['min_confidence']} | lot={t['lot_scale']}x")

GENE_STORE.write_text(
    json.dumps(d, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
)

# Rebuild arbiter weights with all 3 genes
weights = {}
for gene in d["genes"]:
    t = gene["thresholds"]
    weights[gene["gene_id"]] = {
        "min_confidence": t["min_confidence"],
        "lot_scale":      t["lot_scale"],
        "sl_atr_mult":    t["sl_atr_mult"],
        "tp_atr_mult":    t["tp_atr_mult"],
        "sharpe":         gene["stats"]["sharpe"],
        "win_rate":       gene["stats"]["win_rate"],
        "active":         True,
        "group":          gene.get("group", {}),
    }

ARBITER.write_text(json.dumps(weights, indent=2), encoding="utf-8")
print(f"\nArbiter weights: {len(weights)} genes written -> {ARBITER}")
print("Done. The live loop will reload weights on next cycle-100 tick.")
