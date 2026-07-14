from dataclasses import asdict, dataclass

import numpy as np

from .learning_journal import LearningJournal
from .market_structure import latest_smc_snapshot
from .strategy_profiles import get_profile


@dataclass
class TradeDecision:
    action: str
    strategy: str
    probability: float
    confidence: float
    smc_buy_score: float
    smc_sell_score: float
    smc_bias: float
    reason: str
    context_score: int = 0   # how many independent SMC conditions fired
    risk_allowed: bool = True

    def to_dict(self):
        return asdict(self)


class TradingBrain:
    def __init__(self, model=None, profile_name="ict", journal=None):
        self.model = model
        self.profile = get_profile(profile_name)
        self.journal = journal or LearningJournal()

    def predict_probability(self, sequence):
        if self.model is None:
            return 0.5
        arr = np.asarray(sequence, dtype=float)
        if arr.ndim == 2:
            arr = arr.reshape(1, arr.shape[0], arr.shape[1])
        return float(np.asarray(self.model.predict(arr, verbose=0)).squeeze())

    def decide(self, df, sequence=None, probability=None, spread=None, ignore_spread=False):
        snapshot = latest_smc_snapshot(df)
        profile = self.profile
        shift = self.journal.suggest_threshold_shift(profile.name)
        buy_threshold = min(profile.buy_threshold + shift, 0.90)
        sell_threshold = max(profile.sell_threshold - shift, 0.10)

        if probability is None:
            probability = self.predict_probability(sequence)

        confidence = abs(float(probability) - 0.5) * 2

        # Spread check (hard block — not part of SMC scoring)
        spread_value = spread
        if not ignore_spread and spread_value is None and "spread" in df.columns:
            spread_value = float(df["spread"].iloc[-1])
        if not ignore_spread and profile.max_spread is not None and spread_value is not None:
            if spread_value > profile.max_spread:
                return TradeDecision(
                    action="NO_TRADE",
                    strategy=profile.name,
                    probability=probability,
                    confidence=confidence,
                    smc_buy_score=snapshot["smc_buy_score"],
                    smc_sell_score=snapshot["smc_sell_score"],
                    smc_bias=snapshot["smc_bias"],
                    reason=f"spread_too_high:{spread_value:.0f}",
                    context_score=0,
                )

        # Score each direction independently
        buy_score, buy_tags = self._context_score_buy(snapshot)
        sell_score, sell_tags = self._context_score_sell(snapshot)

        if probability >= buy_threshold and buy_score >= profile.min_context_score:
            return TradeDecision(
                action="BUY",
                strategy=profile.name,
                probability=probability,
                confidence=confidence,
                smc_buy_score=snapshot["smc_buy_score"],
                smc_sell_score=snapshot["smc_sell_score"],
                smc_bias=snapshot["smc_bias"],
                reason=f"buy:{'+'.join(buy_tags)}",
                context_score=buy_score,
            )

        if probability <= sell_threshold and sell_score >= profile.min_context_score:
            return TradeDecision(
                action="SELL",
                strategy=profile.name,
                probability=probability,
                confidence=confidence,
                smc_buy_score=snapshot["smc_buy_score"],
                smc_sell_score=snapshot["smc_sell_score"],
                smc_bias=snapshot["smc_bias"],
                reason=f"sell:{'+'.join(sell_tags)}",
                context_score=sell_score,
            )

        # If the model is poorly calibrated high/low, avoid making the system
        # one-sided. A strong directional SMC imbalance can trade inside the
        # probability-neutral zone, but never against a strong model signal.
        structure_floor = max(profile.min_context_score, 2)
        probability_neutral = sell_threshold < probability < buy_threshold
        if (
            probability_neutral
            and buy_score >= structure_floor
            and buy_score > sell_score
            and snapshot["smc_bias"] >= 0
        ):
            return TradeDecision(
                action="BUY",
                strategy=profile.name,
                probability=probability,
                confidence=confidence,
                smc_buy_score=snapshot["smc_buy_score"],
                smc_sell_score=snapshot["smc_sell_score"],
                smc_bias=snapshot["smc_bias"],
                reason=f"buy:structure_override+{'+'.join(buy_tags)}",
                context_score=buy_score,
            )

        if (
            probability_neutral
            and sell_score >= structure_floor
            and sell_score > buy_score
            and snapshot["smc_bias"] <= 0
        ):
            return TradeDecision(
                action="SELL",
                strategy=profile.name,
                probability=probability,
                confidence=confidence,
                smc_buy_score=snapshot["smc_buy_score"],
                smc_sell_score=snapshot["smc_sell_score"],
                smc_bias=snapshot["smc_bias"],
                reason=f"sell:structure_override+{'+'.join(sell_tags)}",
                context_score=sell_score,
            )

        # Build a human-readable reason for NO_TRADE
        if probability >= buy_threshold:
            reason = f"no_buy_context(score={buy_score}<{profile.min_context_score})"
        elif probability <= sell_threshold:
            reason = f"no_sell_context(score={sell_score}<{profile.min_context_score})"
        else:
            reason = f"prob_neutral(buy>{buy_threshold:.2f}_sell<{sell_threshold:.2f})"

        return TradeDecision(
            action="NO_TRADE",
            strategy=profile.name,
            probability=probability,
            confidence=confidence,
            smc_buy_score=snapshot["smc_buy_score"],
            smc_sell_score=snapshot["smc_sell_score"],
            smc_bias=snapshot["smc_bias"],
            reason=reason,
            context_score=0,
        )

    # ── Independent per-condition scoring ─────────────────────────────────────

    def _context_score_buy(self, snapshot) -> tuple[int, list[str]]:
        """
        Each SMC condition is evaluated independently.
        Returns (score, list_of_fired_tags).
        Any individual condition is sufficient when min_context_score=1.
        """
        profile = self.profile
        score = 0
        tags = []

        if snapshot["smc_buy_score"] >= profile.min_smc_score:
            score += 1
            tags.append(f"smc{int(snapshot['smc_buy_score'])}")

        if snapshot["smc_bias"] >= profile.min_bias:
            score += 1
            tags.append(f"bias{int(snapshot['smc_bias'])}")

        if snapshot["bos_up"] >= 1:
            score += 1
            tags.append("bos")

        if snapshot["choch_up"] >= 1:
            score += 1
            tags.append("choch")

        if snapshot["sell_side_liquidity_sweep"] >= 1:
            score += 1
            tags.append("liq_sweep")

        if snapshot["bullish_fvg"] >= 1 or snapshot["ifvg_bull"] >= 1:
            score += 1
            tags.append("fvg")

        if snapshot["in_bullish_ob"] >= 1:
            score += 1
            tags.append("ob")

        if snapshot["demand_zone"] >= 1:
            score += 1
            tags.append("demand")

        return score, tags

    def _context_score_sell(self, snapshot) -> tuple[int, list[str]]:
        profile = self.profile
        score = 0
        tags = []

        if snapshot["smc_sell_score"] >= profile.min_smc_score:
            score += 1
            tags.append(f"smc{int(snapshot['smc_sell_score'])}")

        if snapshot["smc_bias"] <= -profile.min_bias:
            score += 1
            tags.append(f"bias{int(snapshot['smc_bias'])}")

        if snapshot["bos_down"] >= 1:
            score += 1
            tags.append("bos")

        if snapshot["choch_down"] >= 1:
            score += 1
            tags.append("choch")

        if snapshot["buy_side_liquidity_sweep"] >= 1:
            score += 1
            tags.append("liq_sweep")

        if snapshot["bearish_fvg"] >= 1 or snapshot["ifvg_bear"] >= 1:
            score += 1
            tags.append("fvg")

        if snapshot["in_bearish_ob"] >= 1:
            score += 1
            tags.append("ob")

        if snapshot["supply_zone"] >= 1:
            score += 1
            tags.append("supply")

        return score, tags
