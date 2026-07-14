"""Crypto strategy: 24/7 Volume Profile + Fractal geometry (no session gate)."""
from markets.base import MarketStrategy

STRATEGY = MarketStrategy(
    name="crypto",
    sq9_degrees=(180, 360, 720),
    r_multiple=1.5,
    emphasis=("vp", "footprint", "fractal"),
)
