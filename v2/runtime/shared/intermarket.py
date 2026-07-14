"""shared/intermarket.py — Cross-market correlation features.

Born 2026-05-28 from the user's insight: "الذهب بيع والنفط شراء والعكس صحيح".

Gold (XAU) and crude oil (USOIL) often move in related ways through the
inflation/USD/risk channel. Sharp DIVERGENCE between them is a tradable
edge: when gold rallies while oil drops (or vice-versa), one of them is
usually mispriced relative to the macro backdrop.

This module computes a normalized divergence score that brain_v1 attaches
to every snapshot, and ml_clone learns from.

  gold_oil_divergence ∈ [-1, +1]:
    +1  → gold strongly UP while oil DOWN  (gold over-extended → fade gold / favour SELL gold)
    -1  → gold strongly DOWN while oil UP   (gold over-sold → favour BUY gold)
     0  → moving together (no divergence edge)

Cheap: pulls last ~30 M5 bars of each, computes % returns, caches 5s.
"""
from __future__ import annotations
import time

import MetaTrader5 as mt5

GOLD = "XAUUSDm"
OIL = "USOILm"
_LOOKBACK = 12          # M5 bars (~1h) return window
_CACHE: dict = {}
_CACHE_TS = 0.0
_CACHE_S = 5.0


_SELECTED: set[str] = set()


def _ensure(symbol: str) -> None:
    if symbol not in _SELECTED:
        try:
            mt5.symbol_select(symbol, True)
            _SELECTED.add(symbol)
        except Exception:
            pass


def _pct_return(symbol: str, bars: int) -> float | None:
    _ensure(symbol)
    r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, bars + 1)
    if r is None or len(r) < bars + 1:
        return None
    first = float(r[0]["close"]); last = float(r[-1]["close"])
    if first == 0:
        return None
    return (last - first) / first


def intermarket() -> dict:
    """Return {gold_oil_divergence, gold_ret, oil_ret, oil_bid}. Cached 5s."""
    global _CACHE, _CACHE_TS
    now = time.time()
    if now - _CACHE_TS < _CACHE_S and _CACHE:
        return _CACHE
    g = _pct_return(GOLD, _LOOKBACK)
    o = _pct_return(OIL, _LOOKBACK)
    out = {"gold_oil_divergence": 0.0, "gold_ret": 0.0, "oil_ret": 0.0, "oil_bid": None}
    if g is not None and o is not None:
        # Divergence = gold_ret - oil_ret, scaled. Both are small %; ×100 → ~pts.
        # Positive = gold outpacing oil to the upside (gold rich) → fade-gold bias.
        div = (g - o) * 100.0
        out["gold_oil_divergence"] = max(-1.0, min(1.0, div / 2.0))  # ±2% spread → ±1
        out["gold_ret"] = round(g * 100, 3)
        out["oil_ret"] = round(o * 100, 3)
    tick = mt5.symbol_info_tick(OIL)
    out["oil_bid"] = tick.bid if tick else None
    _CACHE = out; _CACHE_TS = now
    return out


def divergence_bias() -> str:
    """Human label: which side the divergence favours for GOLD."""
    d = intermarket()["gold_oil_divergence"]
    if d >= 0.4:  return "FADE_GOLD_UP"     # gold rich vs oil → lean SELL gold
    if d <= -0.4: return "FADE_GOLD_DOWN"   # gold cheap vs oil → lean BUY gold
    return "NEUTRAL"


__all__ = ["intermarket", "divergence_bias", "GOLD", "OIL"]
