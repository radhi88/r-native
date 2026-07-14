"""Base type for per-market trading strategies."""
from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass(frozen=True)
class MarketStrategy:
    """Declarative description of how a market class is traded.

    Attributes:
        name: Market-class key (matches :data:`config.PROFILES`).
        sq9_degrees: Square-of-9 rotations to project for this market.
        r_multiple: Default reward-to-risk target.
        emphasis: Ordered confluence emphasis tags.
    """

    name: str
    sq9_degrees: tuple[float, ...]
    r_multiple: float
    emphasis: tuple[str, ...]

    @property
    def profile(self) -> config.MarketProfile:
        """The :class:`config.MarketProfile` backing this strategy."""
        return config.PROFILES[self.name]

    def describe(self) -> str:
        """One-line human summary for reports/dashboards."""
        return (f"{self.name}: Sq9{list(map(int, self.sq9_degrees))} "
                f"R={self.r_multiple} k={self.profile.atr_sl_mult} "
                f"emphasis={'+'.join(self.emphasis)}")
