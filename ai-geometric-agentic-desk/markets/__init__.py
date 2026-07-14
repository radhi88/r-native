"""Market-specific strategy registry.

Each sub-module defines a :class:`~markets.base.MarketStrategy` describing how
that asset class is traded (Square-of-9 emphasis, reward multiple, indicator
focus). The registry resolves a market class to its strategy.
"""
from __future__ import annotations

from markets.base import MarketStrategy
from markets import gold, forex, indices, crypto, stocks

_REGISTRY: dict[str, MarketStrategy] = {
    "gold": gold.STRATEGY,
    "forex": forex.STRATEGY,
    "indices": indices.STRATEGY,
    "crypto": crypto.STRATEGY,
    "stocks": stocks.STRATEGY,
}


def get(market: str) -> MarketStrategy:
    """Return the :class:`MarketStrategy` for a market class (forex default)."""
    return _REGISTRY.get(market, forex.STRATEGY)
