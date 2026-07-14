from dataclasses import dataclass
import logging

_log = logging.getLogger("friday.profiles")


@dataclass(frozen=True)
class StrategyProfile:
    name: str
    horizon: int
    buy_threshold: float
    sell_threshold: float
    min_smc_score: int
    min_bias: int
    max_spread: float | None
    min_context_score: int = 1


PROFILES = {
    "scalping": StrategyProfile(
        name="scalping",
        horizon=20,
        buy_threshold=0.74,
        sell_threshold=0.26,
        min_smc_score=2,
        min_bias=1,
        max_spread=None,
        min_context_score=2,
    ),
    "swing": StrategyProfile(
        name="swing",
        horizon=80,
        buy_threshold=0.68,
        sell_threshold=0.32,
        min_smc_score=2,
        min_bias=1,
        max_spread=500,
        min_context_score=2,
    ),
    "ict": StrategyProfile(
        name="ict",
        horizon=30,
        buy_threshold=0.72,
        sell_threshold=0.28,
        min_smc_score=3,
        min_bias=2,
        max_spread=500,
        min_context_score=3,
    ),
    "sb": StrategyProfile(
        name="sb",
        horizon=20,
        buy_threshold=0.70,
        sell_threshold=0.30,
        min_smc_score=2,
        min_bias=1,
        max_spread=500,
        min_context_score=2,
    ),
    "sk": StrategyProfile(
        name="sk",
        horizon=50,
        buy_threshold=0.68,
        sell_threshold=0.32,
        min_smc_score=1,
        min_bias=1,
        max_spread=500,
        min_context_score=1,
    ),
    # Gold: sensitive, fast (min_context_score=1) -- permissive for testing
    "gold": StrategyProfile(
        name="gold",
        horizon=20,
        buy_threshold=0.62,
        sell_threshold=0.38,
        min_smc_score=1,
        min_bias=1,
        max_spread=None,
        min_context_score=1,
    ),
    # Gold Precision: fewer but higher-quality entries (ICT video style)
    # Requires 3 confirmed SMC conditions -- mimics clean swing-structure entries
    "gold_precision": StrategyProfile(
        name="gold_precision",
        horizon=30,
        buy_threshold=0.65,
        sell_threshold=0.35,
        min_smc_score=2,
        min_bias=1,
        max_spread=None,
        min_context_score=3,
    ),
}


def get_profile(name: str) -> StrategyProfile:
    if name not in PROFILES:
        _log.warning("Unknown profile '%s' -- falling back to 'sk'", name)
        return PROFILES["sk"]
    return PROFILES[name]
