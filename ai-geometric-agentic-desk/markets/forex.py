"""Forex strategy: SMC + Order Block + FVG at Square-of-9 90/180 levels."""
from markets.base import MarketStrategy

STRATEGY = MarketStrategy(
    name="forex",
    sq9_degrees=(90, 180, 360),
    r_multiple=1.5,
    emphasis=("smc", "ob", "fvg", "sq9_90_180"),
)
