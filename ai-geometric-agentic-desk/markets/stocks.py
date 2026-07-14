"""Stocks strategy: cash-session Order Blocks + daily FVG (09:30-16:00 ET)."""
from markets.base import MarketStrategy

STRATEGY = MarketStrategy(
    name="stocks",
    sq9_degrees=(90, 180, 360),
    r_multiple=1.5,
    emphasis=("ob", "daily_fvg"),
)
