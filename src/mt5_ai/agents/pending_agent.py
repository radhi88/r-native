"""
PendingOrderAgent — places LIMIT and STOP orders at Order Block / FVG levels.

Strategy:
- Places pending orders when price is away from a key level
- Manages an internal queue of pending orders with expiry
- Learns from fill rate and final outcome (profit/loss after fill)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .base_agent import BaseAgent, Signal
from ..strategy_profiles import get_profile


@dataclass
class PendingOrder:
    side: str
    order_type: str         # "LIMIT" | "STOP"
    limit_price: float
    sl: float | None
    tp: float | None
    bars_remaining: int
    placed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    filled: bool = False


class PendingOrderAgent(BaseAgent):
    name = "pending"

    def __init__(
        self,
        executor,
        learning_engine,
        symbol: str,
        max_pending: int = 3,
        default_expiry_bars: int = 20,
        atr_sl_mult: float = 1.0,
        max_spread: float = 500,
    ):
        super().__init__(executor, learning_engine, symbol)
        self._max_pending = max_pending
        self._default_expiry = default_expiry_bars
        self._atr_sl_mult = atr_sl_mult
        self._max_spread  = max_spread
        self._queue: list[PendingOrder] = []

    # ── main evaluation ────────────────────────────────────────────────────────

    def evaluate(self, market_state: dict) -> Signal | None:
        """Returns a Signal with order_type LIMIT or STOP when a key level is found."""
        self._tick_expiry()

        if len(self._queue) >= self._max_pending:
            return None

        t = self.learning.thresholds(self.name)
        buy_thr  = t["buy_threshold"]
        sell_thr = t["sell_threshold"]
        min_smc  = t["min_smc_score"]

        prob      = float(market_state.get("probability", 0.5))
        smc_buy   = int(market_state.get("smc_buy_score", 0))
        smc_sell  = int(market_state.get("smc_sell_score", 0))
        bias      = int(market_state.get("bias", 0))
        spread    = float(market_state.get("spread_points", 999))
        atr       = float(market_state.get("atr", 0))
        price     = float(market_state.get("price", 0))
        ob_buy    = float(market_state.get("ob_buy_level", 0))   # Order Block demand level
        ob_sell   = float(market_state.get("ob_sell_level", 0))  # Order Block supply level
        fvg_low   = float(market_state.get("fvg_low", 0))
        fvg_high  = float(market_state.get("fvg_high", 0))

        profile = get_profile("swing")  # pending orders use swing thresholds

        if spread > self._max_spread:
            return None

        buy_context = smc_buy >= min_smc and bias >= 1
        sell_context = smc_sell >= min_smc and bias <= -1
        probability_neutral = sell_thr < prob < buy_thr
        buy_override = probability_neutral and buy_context and smc_buy > smc_sell
        sell_override = probability_neutral and sell_context and smc_sell > smc_buy

        # BUY LIMIT at demand OB below current price
        if ((prob >= buy_thr and buy_context) or buy_override) and ob_buy > 0 and ob_buy < price - atr * 0.5:
            entry  = ob_buy
            sl     = entry - atr * self._atr_sl_mult if atr else None
            tp     = entry + atr * self._atr_sl_mult * 1.5 if atr else None
            pending = PendingOrder(
                side="BUY", order_type="LIMIT",
                limit_price=entry, sl=sl, tp=tp,
                bars_remaining=self._default_expiry,
            )
            self._queue.append(pending)
            return Signal(
                agent=self.name, symbol=self.symbol,
                side="BUY", order_type="LIMIT",
                probability=prob, confidence=(prob - 0.5) * 2,
                smc_score=smc_buy, price=price,
                limit_price=entry, sl=sl, tp=tp,
                expiry_bars=self._default_expiry,
                meta={"ob_level": ob_buy},
            )

        # SELL LIMIT at supply OB above current price
        if ((prob <= sell_thr and sell_context) or sell_override) and ob_sell > 0 and ob_sell > price + atr * 0.5:
            entry  = ob_sell
            sl     = entry + atr * self._atr_sl_mult if atr else None
            tp     = entry - atr * self._atr_sl_mult * 1.5 if atr else None
            pending = PendingOrder(
                side="SELL", order_type="LIMIT",
                limit_price=entry, sl=sl, tp=tp,
                bars_remaining=self._default_expiry,
            )
            self._queue.append(pending)
            return Signal(
                agent=self.name, symbol=self.symbol,
                side="SELL", order_type="LIMIT",
                probability=prob, confidence=(0.5 - prob) * 2,
                smc_score=smc_sell, price=price,
                limit_price=entry, sl=sl, tp=tp,
                expiry_bars=self._default_expiry,
                meta={"ob_level": ob_sell},
            )

        # BUY STOP above FVG (breakout entry)
        if ((prob >= buy_thr and buy_context) or buy_override) and fvg_high > 0 and fvg_high > price:
            entry  = fvg_high
            sl     = price - atr * self._atr_sl_mult if atr else None
            tp     = entry + atr * self._atr_sl_mult * 1.5 if atr else None
            pending = PendingOrder(
                side="BUY", order_type="STOP",
                limit_price=entry, sl=sl, tp=tp,
                bars_remaining=self._default_expiry,
            )
            self._queue.append(pending)
            return Signal(
                agent=self.name, symbol=self.symbol,
                side="BUY", order_type="STOP",
                probability=prob, confidence=(prob - 0.5) * 2,
                smc_score=smc_buy, price=price,
                limit_price=entry, sl=sl, tp=tp,
                expiry_bars=self._default_expiry,
                meta={"fvg_high": fvg_high},
            )

        return None

    # ── queue management ────────────────────────────────────────────────────────

    def _tick_expiry(self):
        """Decrement bar counter; remove expired orders."""
        still_active = []
        for o in self._queue:
            if not o.filled:
                o.bars_remaining -= 1
                if o.bars_remaining > 0:
                    still_active.append(o)
                else:
                    self.log.info("pending order expired | side=%s level=%.5f", o.side, o.limit_price)
            else:
                still_active.append(o)
        self._queue = still_active

    def mark_filled(self, limit_price: float, side: str):
        for o in self._queue:
            if o.side == side and abs(o.limit_price - limit_price) < 0.01:
                o.filled = True
                self._set_active(side, limit_price, o.sl, o.tp)
                self.log.info("pending order filled | side=%s @ %.5f", side, limit_price)
                break

    def pending_count(self) -> int:
        return sum(1 for o in self._queue if not o.filled)
