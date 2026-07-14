"""live_quant.py — طبقة كمّية لحظية تتكيّف مع السوق (لا تزوّر، لا ضوضاء).

Each cycle it COMPUTES the current quant regime from price structure + recent
realized expectancy, then OUTPUTS:
  • chop veto   — skip entries when the market has no trend (efficiency ratio low)
  • risk_mult   — scale lot/conviction up in clean trends / when recently winning,
                  down in chop / high-vol / when recently losing  (bounded 0.4–1.6)

This is ADAPTIVE (reacts to measurable conditions) and ONLINE (leans into recent
edge) — NOT a per-tick parameter mutator (that overfits noise). Pure stdlib.
"""
from __future__ import annotations


def efficiency_ratio(c, i, n=20):
    """Kaufman ER: |net move| / total path. ~1 = clean trend, ~0 = chop."""
    if i < n: return 0.0
    net = abs(c[i] - c[i - n])
    path = sum(abs(c[k] - c[k - 1]) for k in range(i - n + 1, i + 1))
    return net / path if path > 1e-9 else 0.0


def vol_ratio(atr_now, atr_hist):
    """current ATR vs its recent median (1.0 = normal, >1.4 = hot, <0.7 = dead)."""
    if not atr_hist: return 1.0
    s = sorted(atr_hist); med = s[len(s) // 2]
    return atr_now / med if med > 1e-9 else 1.0


def quant(c, i, atr_now, atr_hist, recent_pnls):
    """Return (chop: bool, risk_mult: float, why: str)."""
    er = efficiency_ratio(c, i)
    vr = vol_ratio(atr_now, atr_hist)
    # base: trend quality drives aggression
    mult = 0.5 + er                      # ER 0→0.5x, 0.5→1.0x, 1.0→1.5x
    chop = er < 0.30                     # no real trend → stand aside
    notes = [f"ER {er:.2f}"]
    # volatility temper
    if vr > 1.5:  mult *= 0.7; notes.append(f"hot×{vr:.1f}")
    elif vr < 0.6: chop = True; notes.append(f"dead×{vr:.1f}")
    # online self-improve: lean into recent realized edge
    if recent_pnls:
        exp = sum(recent_pnls) / len(recent_pnls)
        if exp > 0:   mult *= 1.2; notes.append("edge+")
        elif exp < 0: mult *= 0.8; notes.append("edge-")
    mult = max(0.4, min(1.6, mult))
    return chop, round(mult, 2), " ".join(notes)
