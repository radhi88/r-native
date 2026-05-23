"""asset_classes.py — Per-asset-class slippage / spread / leverage settings.

Algory's edge: different fee structures per asset class. Generic settings
under-price crypto/index trades and over-price forex.

Used by:
- ga_simulator (realistic backtest fees)
- trade_gate (spread-vs-ATR sanity check)
- prop_firm (per-class risk caps)
"""
from __future__ import annotations

# Asset class detection
_INDICES = {"US30", "USTEC", "US500", "DE30", "FRA40", "UK100", "JPN225"}
_METALS  = {"XAU", "XAG", "XPT", "XPD"}
_CRYPTO  = {"BTC", "ETH", "XRP", "LTC", "BCH"}
_OIL     = {"USOIL", "UKOIL", "OIL", "BRENT"}
_MAJORS  = {"EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCAD", "USDCHF", "NZDUSD"}

# Per-class defaults (matching Algory's dashboard_settings.json)
CLASS_FEES = {
    "major":   {"slip_pts": 10,  "spread_pips": 3.0,   "leverage": 100},
    "cross":   {"slip_pts": 25,  "spread_pips": 10.0,  "leverage": 100},
    "metal":   {"slip_pts": 30,  "spread_pips": 16.0,  "leverage": 30},
    "index":   {"slip_pts": 300, "spread_pips": 60.0,  "leverage": 50},
    "crypto":  {"slip_pts": 600, "spread_pips": 100.0, "leverage": 5},
    "oil":     {"slip_pts": 50,  "spread_pips": 25.0,  "leverage": 20},
}


def classify(symbol: str) -> str:
    """Return one of: major / cross / metal / index / crypto / oil."""
    s = symbol.upper().rstrip("M").rstrip("_")
    # Strip trailing m for broker-suffixed names (BTCUSDm → BTCUSD)
    if s.endswith("M"): s = s[:-1]
    # Indices first (some contain currency-like prefixes)
    for k in _INDICES:
        if k in s: return "index"
    for k in _OIL:
        if k in s: return "oil"
    for k in _METALS:
        if s.startswith(k): return "metal"
    for k in _CRYPTO:
        if s.startswith(k): return "crypto"
    if s in _MAJORS:                return "major"
    if len(s) == 6 and s.isalpha(): return "cross"
    return "major"   # safe fallback


def fees_for(symbol: str) -> dict:
    """Return {slip_pts, spread_pips, leverage, class} for a symbol."""
    cls = classify(symbol)
    f = CLASS_FEES.get(cls, CLASS_FEES["major"]).copy()
    f["class"] = cls
    return f


def quality_for(symbol: str) -> str:
    """Quick quality classifier based on asset class:
    - EXCELLENT: forex majors (tight spread, deep liquidity)
    - GOOD: metals, crosses
    - MARGINAL: indices, oil
    - SPECULATIVE: crypto
    """
    cls = classify(symbol)
    return {
        "major": "EXCELLENT", "cross": "GOOD",
        "metal": "GOOD",      "oil":   "MARGINAL",
        "index": "MARGINAL",  "crypto":"SPECULATIVE",
    }.get(cls, "GOOD")


def all_supported() -> list[str]:
    """Return the full 18-asset list (broker-suffixed)."""
    return [
        # Majors
        "EURUSDm", "GBPUSDm", "AUDUSDm", "USDJPYm", "USDCADm", "USDCHFm",
        # Crosses
        "EURGBPm", "GBPJPYm", "EURJPYm", "GBPAUDm",
        # Crypto
        "BTCUSDm", "ETHUSDm",
        # Metals
        "XAUUSDm", "XAGUSDm",
        # Indices
        "US30m", "USTECm", "US500m", "DE30m",
        # Oil
        "USOILm",
    ]
