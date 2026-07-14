"""shared/risk_sentinel.py — Central risk gate for all traders.

Born 2026-05-28 via /design-system Phase 4.

Replaces the duplicated `hard_guards()` function in every trader.
Single source of truth for "can this engine trade right now?"

CHECKS (in order):
  1. Equity floor       — equity < balance * 70% → BLOCK
  2. Daily loss limit   — realized PnL ≤ -15% of balance → BLOCK
  3. Cooldown           — last trade within 90s → BLOCK
  4. Consecutive SLs    — 2+ losses in a row → pause 30 min
  5. Max open per magic — too many positions → BLOCK
  6. Spread check       — spread > token threshold → BLOCK

USAGE:
    from runtime.shared.risk_sentinel import RiskSentinel
    risk = RiskSentinel(magic=99782, symbol="XAUUSDm")
    blocker = risk.check()           # None if clear, else reason
    if blocker: continue
    risk.mark_trade()                # call right after order_send succeeds
"""
from __future__ import annotations
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import MetaTrader5 as mt5

from runtime.shared.tokens import ACCOUNT_RISK, RISK, SYMBOLS, TIMING


class RiskSentinel:
    """Per-(magic, symbol) risk gate. One instance per trader."""

    def __init__(self, magic: int, symbol: str):
        self.magic = magic
        self.symbol = symbol
        self._last_trade_ts: float = 0.0
        self._pause_until: float = 0.0
        self._paused_on_exit_ts: float = 0.0   # newest exit that already triggered a pause
        # token-derived caps with safe fallbacks
        sym_risk = RISK.get(symbol, {})
        self.max_open = sym_risk.get("max_open", 2)
        self.cooldown_sec = TIMING.get("cooldown_default", 90.0)
        self.daily_loss_pct = ACCOUNT_RISK["daily_loss_pct"]
        self.equity_floor_pct = ACCOUNT_RISK["equity_floor_pct"]
        self.consec_sl_pause = ACCOUNT_RISK["consec_sl_pause"]
        self.pause_minutes = ACCOUNT_RISK["consec_pause_min"]
        spread_max = SYMBOLS.get(symbol, {}).get("spread_max")
        self.spread_max = spread_max

    # ──────────────────────────────────────────────────────────
    # public API
    # ──────────────────────────────────────────────────────────
    def check(self) -> Optional[str]:
        """Return None if clear to trade, else human-readable reason."""
        acc = mt5.account_info()
        if acc is None:
            return "mt5 account_info unavailable"

        # 1. paused after consec SLs
        if time.time() < self._pause_until:
            remaining = int(self._pause_until - time.time())
            return f"paused after {self.consec_sl_pause} consec SLs ({remaining}s left)"

        # 2. equity floor
        floor = acc.balance * self.equity_floor_pct / 100
        if acc.equity < floor:
            return f"equity ${acc.equity:.2f} < floor ${floor:.2f} ({self.equity_floor_pct}%)"

        # 3. daily realized loss
        realized = self._realized_today()
        daily_limit = -(acc.balance * self.daily_loss_pct / 100)
        if realized <= daily_limit:
            return f"realized ${realized:+.2f} ≤ daily limit ${daily_limit:.2f} ({self.daily_loss_pct}%)"

        # 4. cooldown
        since_last = time.time() - self._last_trade_ts
        if since_last < self.cooldown_sec:
            return f"cooldown {int(self.cooldown_sec - since_last)}s"

        # 5. max open
        positions = mt5.positions_get(symbol=self.symbol) or []
        my_pos = [p for p in positions if int(p.magic) == self.magic]
        if len(my_pos) >= self.max_open:
            return f"max {self.max_open} open positions"

        # 6. spread
        if self.spread_max is not None:
            tick = mt5.symbol_info_tick(self.symbol)
            if tick:
                spread = tick.ask - tick.bid
                if spread > self.spread_max:
                    return f"spread {spread:.4f} > max {self.spread_max:.4f}"

        # 7. consec SLs auto-pause — re-arm ONLY on a NEW losing streak, never on the same
        #    old SLs (otherwise it dead-locks: pause expires, same 2 SLs re-trigger, forever).
        cnt, latest_exit_ts = self._consec_sl_info()
        if cnt >= self.consec_sl_pause and latest_exit_ts > self._paused_on_exit_ts:
            self._pause_until = time.time() + self.pause_minutes * 60
            self._paused_on_exit_ts = latest_exit_ts
            return f"{self.consec_sl_pause} consec SLs → pausing {self.pause_minutes}min"

        return None

    def mark_trade(self) -> None:
        """Call this AFTER order_send returns DONE to start cooldown."""
        self._last_trade_ts = time.time()

    # ──────────────────────────────────────────────────────────
    # internals
    # ──────────────────────────────────────────────────────────
    def _realized_today(self) -> float:
        since = datetime.now(timezone.utc) - timedelta(hours=12)
        deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
        return sum(float(d.profit) for d in deals
                   if int(d.magic) == self.magic and int(d.entry) in (1, 2))

    def _consec_sl_count(self) -> int:
        return self._consec_sl_info()[0]

    def _consec_sl_info(self):
        """(consecutive losing exits in a row, timestamp of the most-recent exit) — last 12h."""
        since = datetime.now(timezone.utc) - timedelta(hours=12)
        deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
        exits = sorted(
            [d for d in deals if int(d.magic) == self.magic and int(d.entry) in (1, 2)],
            key=lambda d: d.time, reverse=True,
        )
        latest = float(exits[0].time) if exits else 0.0
        n = 0
        for d in exits:
            if float(d.profit) < 0:
                n += 1
            else:
                break
        return n, latest


__all__ = ["RiskSentinel"]
