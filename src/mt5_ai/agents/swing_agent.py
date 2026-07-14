"""
SwingAgent — H1/H4/D1 position trades with wider R:R.

Strategy:
- Market orders on strong SMC confluence
- Horizon: 80 bars
- Requires higher context_score (multiple SMC conditions aligned)
- Learns from each closed trade via LearningEngine
"""

from .base_agent import BaseAgent, Signal
from ..strategy_profiles import get_profile


class SwingAgent(BaseAgent):
    name = "swing"

    def __init__(self, executor, learning_engine, symbol: str, atr_sl_mult: float = 1.0, max_spread: float = 500):
        super().__init__(executor, learning_engine, symbol)
        self._atr_sl_mult = atr_sl_mult
        self._max_spread  = max_spread

    def evaluate(self, market_state: dict) -> Signal | None:
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
        context  = int(market_state.get("context_score", 0))

        profile = get_profile(self.name)

        if spread > self._max_spread:
            return None

        # Swing requires higher context alignment
        if context < profile.min_context_score:
            return None

        buy_context = smc_buy >= min_smc and bias >= 1
        sell_context = smc_sell >= min_smc and bias <= -1
        probability_neutral = sell_thr < prob < buy_thr
        buy_override = probability_neutral and buy_context and smc_buy > smc_sell
        sell_override = probability_neutral and sell_context and smc_sell > smc_buy

        if (prob >= buy_thr and buy_context) or buy_override:
            sl = price - atr * self._atr_sl_mult if atr else None
            tp = price + atr * self._atr_sl_mult * 1.65 if atr else None
            confidence = (prob - 0.5) * 2
            sig = Signal(
                agent=self.name, symbol=self.symbol,
                side="BUY", order_type="MARKET",
                probability=prob, confidence=confidence,
                smc_score=smc_buy, price=price, sl=sl, tp=tp,
                meta={"context_score": context},
            )
            self._set_active("BUY", price, sl, tp)
            return sig

        if (prob <= sell_thr and sell_context) or sell_override:
            sl = price + atr * self._atr_sl_mult if atr else None
            tp = price - atr * self._atr_sl_mult * 1.65 if atr else None
            confidence = abs(prob - 0.5) * 2
            sig = Signal(
                agent=self.name, symbol=self.symbol,
                side="SELL", order_type="MARKET",
                probability=prob, confidence=confidence,
                smc_score=smc_sell, price=price, sl=sl, tp=tp,
                meta={"context_score": context},
            )
            self._set_active("SELL", price, sl, tp)
            return sig

        return None
