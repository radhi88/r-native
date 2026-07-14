from dataclasses import dataclass

from .config import MAX_DAILY_LOSS_USD


MAX_RISK = 0.01


def position_size(balance, atr, risk=MAX_RISK):
    if atr <= 0:
        return 0.01

    risk_amount = balance * risk
    size = risk_amount / (atr * 10)
    return max(0.01, round(size, 2))


def kill_switch(daily_pnl, max_daily_loss=MAX_DAILY_LOSS_USD):
    return daily_pnl < -max_daily_loss


@dataclass
class RiskManager:
    daily_pnl: float = 0.0
    max_daily_loss: float = MAX_DAILY_LOSS_USD

    def can_trade(self):
        return not kill_switch(self.daily_pnl, self.max_daily_loss)
