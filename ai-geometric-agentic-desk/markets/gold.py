"""Gold strategy: SMC + OB/FVG anchored to the Square-of-9 360 degree.

Gold runs London + NY only with an ATR x2 stop and 2x lot scaling. The 360
rotation is the dominant Sq9 cycle for bullion per the spec.
"""
from markets.base import MarketStrategy

STRATEGY = MarketStrategy(
    name="gold",
    sq9_degrees=(180, 360, 720),
    r_multiple=1.5,
    emphasis=("smc", "ob", "fvg", "sq9_360"),
)
