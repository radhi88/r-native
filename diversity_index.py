"""diversity_index.py — J.24 — Measure genetic diversity in the vault.

Low diversity = early-stopping risk. The GA has converged on one or two
narrow strategy types and won't explore. We detect this and can trigger
forced gene injection or campaign restart.

Metrics:
- gene_entropy: Shannon entropy of gene usage across vault
- combo_uniqueness: ratio of unique combos to total genomes
- archetype_balance: how evenly spread across REVERSION/TREND/BREAKOUT/MIXED
- param_variance: coefficient of variation for key params (sl_atr, tp_atr, etc.)
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path


def gene_entropy(vault: list[dict]) -> float:
    """Shannon entropy of gene usage. Higher = more diverse."""
    if not vault: return 0.0
    gene_counts = Counter()
    total_appearances = 0
    for r in vault:
        genes = (r.get("genome", {}).get("active_genes") or
                 r.get("active_genes") or [])
        for g in genes:
            gene_counts[g] += 1
            total_appearances += 1
    if total_appearances == 0: return 0.0
    entropy = 0.0
    for c in gene_counts.values():
        p = c / total_appearances
        if p > 0: entropy -= p * math.log2(p)
    return round(entropy, 3)


def combo_uniqueness(vault: list[dict]) -> dict:
    """Ratio of unique gene combos to total genomes."""
    if not vault: return {"unique": 0, "total": 0, "ratio": 0}
    combos = set()
    for r in vault:
        genes = sorted((r.get("genome", {}).get("active_genes") or
                        r.get("active_genes") or []))
        combos.add("+".join(g for g in genes if not g.startswith("exec_")))
    return {
        "unique":  len(combos),
        "total":   len(vault),
        "ratio":   round(len(combos) / len(vault), 3) if vault else 0,
    }


def archetype_balance(vault: list[dict]) -> dict:
    """Distribution of derived archetypes. Returns Counter + 'balance score'."""
    REV   = {"use_sig_bb", "use_sig_rsi", "use_sig_stoch", "use_sig_williams",
             "use_sig_wick_rejection", "use_sig_pin_bar"}
    TREND = {"use_bias_ema", "use_bias_sma", "use_bias_chandelier",
             "use_bias_trailing", "use_sig_macd"}
    BRK   = {"use_sig_breakout", "use_sig_inside_break", "use_sig_mom_break",
             "use_sig_engulfing"}

    counts = Counter()
    for r in vault:
        ag = set(r.get("genome", {}).get("active_genes") or
                 r.get("active_genes") or [])
        rev_n, trend_n, brk_n = len(ag & REV), len(ag & TREND), len(ag & BRK)
        if max(rev_n, trend_n, brk_n) == 0:
            counts["MIXED"] += 1
        elif brk_n >= max(rev_n, trend_n):
            counts["BREAKOUT"] += 1
        elif rev_n > trend_n:
            counts["REVERSION"] += 1
        else:
            counts["TREND"] += 1

    # Balance score: 1.0 = perfectly even, 0 = all same archetype
    if not counts: return {"counts": {}, "balance_score": 0}
    total = sum(counts.values())
    expected = total / len(counts)
    chi_sq = sum((v - expected) ** 2 / expected for v in counts.values())
    balance = max(0, 1 - chi_sq / (total * (len(counts) - 1) or 1))
    return {
        "counts":        dict(counts),
        "balance_score": round(balance, 3),
        "dominant":      counts.most_common(1)[0][0],
    }


def param_variance(vault: list[dict], param_names: list[str] = None) -> dict:
    """Coefficient of variation for key params. Low CV = converged, high = diverse."""
    param_names = param_names or ["sl_atr_mult", "tp_atr_mult",
                                   "rsi_period", "ema_fast", "ema_slow"]
    out = {}
    for name in param_names:
        vals = []
        for r in vault:
            params = r.get("genome", {}).get("params") or {}
            v = params.get(name)
            if isinstance(v, (int, float)): vals.append(v)
        if len(vals) < 3:
            out[name] = {"n": len(vals), "cv": 0}; continue
        mean = sum(vals) / len(vals)
        if mean == 0:
            out[name] = {"n": len(vals), "cv": 0}; continue
        var  = sum((v - mean) ** 2 for v in vals) / len(vals)
        std  = math.sqrt(var)
        out[name] = {
            "n":     len(vals),
            "mean":  round(mean, 3),
            "std":   round(std, 3),
            "cv":    round(std / abs(mean), 3),   # coefficient of variation
        }
    return out


def diversity_report(vault: list[dict]) -> dict:
    """One-shot report ready for UI/logging."""
    entropy = gene_entropy(vault)
    uniqueness = combo_uniqueness(vault)
    arch = archetype_balance(vault)
    pv   = param_variance(vault)

    # Health score: combined 0-100
    score = 0
    # Entropy: 0-6 typical → scale to 0-30
    score += min(30, entropy * 5)
    # Uniqueness ratio: 0-1 → 0-30
    score += uniqueness["ratio"] * 30
    # Balance: 0-1 → 0-20
    score += arch["balance_score"] * 20
    # Param CV: average CV across tracked params → 0-20
    avg_cv = sum(p.get("cv", 0) for p in pv.values()) / max(1, len(pv))
    score += min(20, avg_cv * 30)

    if   score >= 75: verdict = "🌳 HEALTHY"
    elif score >= 50: verdict = "🟡 OK"
    elif score >= 25: verdict = "⚠️ CONVERGED — consider force-gene injection"
    else:             verdict = "🚨 STAGNANT — restart campaign with diverse seeds"

    return {
        "vault_size":      len(vault),
        "gene_entropy":    entropy,
        "combo_unique":    uniqueness,
        "archetype":       arch,
        "param_cv":        pv,
        "diversity_score": round(score, 1),
        "verdict":         verdict,
    }


def report_for_campaign(campaign_path: str | Path) -> dict:
    """Quick CLI helper."""
    p = Path(campaign_path) / "vault.json"
    if not p.exists(): return {"error": f"{p} not found"}
    vault = json.loads(p.read_text(encoding="utf-8"))
    return diversity_report(vault)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m r_native.diversity_index <campaign_path>")
        sys.exit(1)
    print(json.dumps(report_for_campaign(sys.argv[1]), indent=2,
                     ensure_ascii=False))
