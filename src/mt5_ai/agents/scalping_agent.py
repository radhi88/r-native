"""
ScalpingAgent — M1/M5 fast entries with tight stops.

Strategy:
- Market orders only
- Horizon: 20 bars (M1 default)
- Learns from every closed trade via LearningEngine
- Requires high probability + SMC confluence
"""

from .base_agent import BaseAgent, Signal
from ..strategy_profiles import get_profile


class ScalpingAgent(BaseAgent):
    name = "scalping"

    def __init__(self, executor, learning_engine, symbol: str, atr_sl_mult: float = 1.0, max_spread: float | None = None):
        super().__init__(executor, learning_engine, symbol)
        self._atr_sl_mult = atr_sl_mult
        self._max_spread  = max_spread

    def evaluate(self, market_state: dict) -> Signal | None:
        """
        market_state keys expected:
          probability, smc_buy_score, smc_sell_score, bias,
          spread_points, atr, price, regime (dict)
        """
        t = self.learning.thresholds(self.name)
        buy_thr  = t["buy_threshold"]
        sell_thr = t["sell_threshold"]
        min_smc  = t["min_smc_score"]

        prob     = float(market_state.get("probability", 0.5))
        smc_buy  = int(market_state.get("smc_buy_score", 0))
        smc_sell = int(market_state.get("smc_sell_score", 0))
        bias     = int(market_state.get("bias", 0))
        spread   = float(market_state.get("spread_points", 999))
        atr      = float(market_state.get("atr", 0))
        price    = float(market_state.get("price", 0))

        profile = get_profile(self.name)

        if self._max_spread is not None and spread > self._max_spread:
            return None

        ob_buy  = bool(market_state.get("in_bullish_ob", 0))
        ob_sell = bool(market_state.get("in_bearish_ob", 0))

        # Normal context: SMC alignment + any positive bias or OB confluence
        buy_context  = smc_buy  >= min_smc and (bias >= 0 or ob_buy)
        sell_context = smc_sell >= min_smc and (bias <= 0 or ob_sell)

        # Probability-neutral SMC override
        probability_neutral = sell_thr < prob < buy_thr
        buy_override  = probability_neutral and smc_buy  >= 3 and bias >= 2
        sell_override = probability_neutral and smc_sell >= 3 and bias <= -2

        # High-confidence override: model very sure, any SMC agreement
        high_conf_buy  = prob >= 0.76 and smc_buy  >= 1
        high_conf_sell = prob <= 0.24 and smc_sell >= 1

        if (prob >= buy_thr and buy_context) or buy_override or high_conf_buy:
            sl = price - atr * self._atr_sl_mult if atr else None
            tp = price + atr * self._atr_sl_mult * 2.0 if atr else None  # 1:2 R:R
            confidence = (prob - 0.5) * 2
            sig = Signal(
                agent=self.name, symbol=self.symbol,
                side="BUY", order_type="MARKET",
                probability=prob, confidence=confidence,
                smc_score=smc_buy, price=price, sl=sl, tp=tp,
            )
            self._set_active("BUY", price, sl, tp)
            return sig

        if (prob <= sell_thr and sell_context) or sell_override or high_conf_sell:
            sl = price + atr * self._atr_sl_mult if atr else None
            tp = price - atr * self._atr_sl_mult * 2.0 if atr else None  # 1:2 R:R
            confidence = abs(prob - 0.5) * 2
            sig = Signal(
                agent=self.name, symbol=self.symbol,
                side="SELL", order_type="MARKET",
                probability=prob, confidence=confidence,
                smc_score=smc_sell, price=price, sl=sl, tp=tp,
            )
            self._set_active("SELL", price, sl, tp)
            return sig

        return None
