"""Curated ETF peer groups and expense-ratio comparison math.

Purely descriptive utilities — peer lists group funds tracking similar
exposures so their costs and stats can be compared side by side. Nothing here
is a recommendation.

Public API:
  PEER_GROUPS: dict[group_key, list[ticker]]
  find_peers(ticker) -> list[str]   (its group minus itself; [] if unknown)
  expense_savings(er_current, er_alt, position=100_000.0)
      -> {"bps": float, "dollars_per_year": float}
"""
from __future__ import annotations

# Curated groups of ETFs with closely comparable exposures.
PEER_GROUPS: dict[str, list[str]] = {
    "sp500_core": ["SPY", "VOO", "IVV", "SPLG"],
    "nasdaq100": ["QQQ", "QQQM"],
    "total_market": ["VTI", "ITOT", "SCHB"],
    "dividend": ["SCHD", "VYM", "HDV", "DVY"],
    "small_cap": ["IWM", "VB", "IJR"],
    "intl_developed": ["VEA", "IEFA", "VXUS"],
    "bonds_core": ["AGG", "BND"],
    "gold": ["GLD", "IAU", "GLDM"],
    "semis": ["SMH", "SOXX"],
}


def find_peers(ticker: str) -> list[str]:
    """Tickers in the same curated group, excluding the ticker itself.

    Case-insensitive; returns [] when the ticker is not in any group.
    """
    if not ticker:
        return []
    tk = str(ticker).strip().upper()
    for members in PEER_GROUPS.values():
        if tk in members:
            return [m for m in members if m != tk]
    return []


def expense_savings(
    er_current: float,
    er_alt: float,
    position: float = 100_000.0,
) -> dict:
    """Cost difference between two expense ratios on a hypothetical position.

    Expense ratios are FRACTIONS (e.g. 0.0009 = 9 bps). Positive values mean
    the alternative costs less per year; negative means it costs more.
    Returns {"bps": float, "dollars_per_year": float}; zeros on bad input.
    """
    try:
        diff = float(er_current) - float(er_alt)
        pos = float(position)
    except (TypeError, ValueError):
        return {"bps": 0.0, "dollars_per_year": 0.0}
    return {"bps": diff * 10_000.0, "dollars_per_year": diff * pos}
