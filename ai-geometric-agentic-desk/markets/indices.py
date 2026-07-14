"""Indices strategy: BOS/CHoCH + VWAP confirmation along the Gann 1x1 angle."""
from markets.base import MarketStrategy

STRATEGY = MarketStrategy(
    name="indices",
    sq9_degrees=(90, 180, 360),
    r_multiple=2.0,
    emphasis=("bos", "choch", "vwap", "gann_1x1"),
)
