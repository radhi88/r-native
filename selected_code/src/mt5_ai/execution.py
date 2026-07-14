from dataclasses import dataclass
from datetime import datetime, timezone

from .config import DEFAULT_LOT
from .mt5_gateway import OrderPlan


@dataclass
class ExecutionResult:
    mode: str
    action: str
    symbol: str
    side: str
    lot: float
    price: float
    sent: bool
    reason: str
    timestamp: str

    def to_dict(self):
        return self.__dict__.copy()


class PaperExecutor:
    def execute(self, symbol, side, price, lot=DEFAULT_LOT, sl=None, tp=None):
        return ExecutionResult(
            mode="paper",
            action="OPEN",
            symbol=symbol,
            side=side,
            lot=float(lot),
            price=float(price),
            sent=True,
            reason="paper_trade_logged",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


class SafeMT5Executor:
    def __init__(self, gateway, allow_live=False):
        self.gateway = gateway
        self.allow_live = allow_live

    def execute(self, symbol, side, price, lot=DEFAULT_LOT, sl=None, tp=None):
        plan = OrderPlan(symbol=symbol, side=side, lot=lot, sl=sl, tp=tp)
        result = self.gateway.send_market_order(plan, allow_live=self.allow_live)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "live",
            "requested_price": float(price),
            **result,
        }


class DemoMT5Executor:
    def __init__(self, gateway):
        self.gateway = gateway

    def execute(self, symbol, side, price, lot=DEFAULT_LOT, sl=None, tp=None):
        plan = OrderPlan(
            symbol=symbol,
            side=side,
            lot=lot,
            sl=sl,
            tp=tp,
            comment="friday-demo-only",
        )
        result = self.gateway.send_demo_market_order(plan)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "demo_mt5",
            "requested_price": float(price),
            **result,
        }
