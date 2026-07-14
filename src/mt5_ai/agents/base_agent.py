"""Base class shared by all FRIDAY trading agents."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Signal:
    agent: str
    symbol: str
    side: str           # "BUY" | "SELL" | "HOLD"
    order_type: str     # "MARKET" | "LIMIT" | "STOP"
    probability: float
    confidence: float
    smc_score: int
    price: float
    sl: float | None = None
    tp: float | None = None
    limit_price: float | None = None   # for pending orders
    expiry_bars: int | None = None     # bars before pending order expires
    meta: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BaseAgent(ABC):
    name: str = "base"

    def __init__(self, executor, learning_engine, symbol: str):
        self.executor = executor
        self.learning = learning_engine
        self.symbol = symbol
        self.log = logging.getLogger(f"friday.agent.{self.name}")
        self._active_trade: dict | None = None

    @abstractmethod
    def evaluate(self, market_state: dict) -> Signal | None:
        """Analyse market_state and return a Signal or None."""

    def on_trade_closed(self, entry: float, exit_price: float, side: str):
        """Call after each closed trade so the agent can learn."""
        points = (exit_price - entry) if side == "BUY" else (entry - exit_price)
        self.learning.record(
            agent=self.name,
            symbol=self.symbol,
            side=side,
            entry=entry,
            exit_price=exit_price,
            points=points,
        )
        self.log.info(
            "trade closed | side=%s entry=%.5f exit=%.5f points=%.1f",
            side, entry, exit_price, points,
        )
        self._active_trade = None

    def has_open_trade(self) -> bool:
        return self._active_trade is not None

    def _set_active(self, side: str, entry: float, sl: float | None, tp: float | None):
        self._active_trade = {"side": side, "entry": entry, "sl": sl, "tp": tp}
