"""shared/circuit_breaker.py — Catastrophe protection per engine.

Born 2026-05-28 after claude_auto's 28-loss cascade in 3 minutes (-$311).
This module is what would have stopped that cascade at trade #4.

THREE INDEPENDENT BREAKERS (any one trips → block):

  1. RATE LIMIT       — too many trades in too short a window
                        (default: max 3 trades / 60s per magic)

  2. LOSS CASCADE     — too many consecutive losses
                        (default: 3 losses in a row → freeze 30 min)

  3. DRAWDOWN VELOCITY — equity dropping too fast
                        (default: lose > 5% of balance in 5 min → freeze 60 min)

USAGE in any trader:
    from runtime.shared.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker(magic=99777, symbol="XAUUSDm")
    blocker = cb.check()
    if blocker:
        return  # don't fire entry
    # ...send order...
    cb.mark_trade(profit=None)  # mark intent
    # later, when trade closes:
    cb.mark_trade(profit=-8.0)  # mark realized PnL

State is persisted to data/circuit_breaker_state.json so freezes
survive process restarts. That's critical — without it, a crashed
bot would relaunch and immediately re-fire into the cascade.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import MetaTrader5 as mt5

from runtime.shared.tokens import PATHS

STATE_FILE = PATHS["brain_decisions"].parent / "circuit_breaker_state.json"


# ──────────────────────────────────────────────────────────
# Defaults (override per-engine via constructor)
# ──────────────────────────────────────────────────────────
DEFAULTS = {
    "max_trades_per_window":   3,
    "rate_window_sec":         60,
    "max_consec_losses":       3,
    "consec_freeze_min":       5,      # was 30 — user: لا تجمده مده طويله
    "max_dd_pct":              5.0,
    "dd_window_sec":           300,
    "dd_freeze_min":           10,     # was 60 — quick recovery
}


class CircuitBreaker:
    """Per-(magic, symbol) catastrophe guard."""

    def __init__(self, magic: int, symbol: str, **overrides):
        self.magic = magic
        self.symbol = symbol
        cfg = {**DEFAULTS, **overrides}
        self.max_trades_per_window = cfg["max_trades_per_window"]
        self.rate_window_sec        = cfg["rate_window_sec"]
        self.max_consec_losses      = cfg["max_consec_losses"]
        self.consec_freeze_min      = cfg["consec_freeze_min"]
        self.max_dd_pct             = cfg["max_dd_pct"]
        self.dd_window_sec          = cfg["dd_window_sec"]
        self.dd_freeze_min          = cfg["dd_freeze_min"]
        self._state = self._load_state()

    # ──────────────────────────────────────────────────────
    # Public — call BEFORE firing entry
    # ──────────────────────────────────────────────────────
    def check(self) -> Optional[str]:
        """None if engine cleared to trade, else reason string."""
        # Persistent freeze (survived restart)
        freeze_until = self._state.get("freeze_until_ts", 0)
        if time.time() < freeze_until:
            remaining = int(freeze_until - time.time())
            reason = self._state.get("freeze_reason", "?")
            return f"FROZEN {remaining}s remaining — {reason}"

        # 1. Rate limit
        recent = self._recent_trade_count(self.rate_window_sec)
        if recent >= self.max_trades_per_window:
            self._freeze(self.consec_freeze_min,
                         f"rate limit: {recent} trades in {self.rate_window_sec}s")
            return f"rate limit hit ({recent} ≥ {self.max_trades_per_window} per {self.rate_window_sec}s)"

        # 2. Loss cascade
        consec = self._consec_loss_count()
        if consec >= self.max_consec_losses:
            self._freeze(self.consec_freeze_min,
                         f"{consec} consec losses")
            return f"loss cascade: {consec} consec losses (max {self.max_consec_losses})"

        # 3. Drawdown velocity
        dd = self._drawdown_in_window(self.dd_window_sec)
        acc = mt5.account_info()
        if acc and acc.balance > 0:
            dd_pct = abs(dd) / acc.balance * 100 if dd < 0 else 0
            if dd_pct >= self.max_dd_pct:
                self._freeze(self.dd_freeze_min,
                             f"drawdown {dd_pct:.1f}% in {self.dd_window_sec}s")
                return f"drawdown velocity: lost {dd_pct:.1f}% in {self.dd_window_sec/60:.0f}min"

        return None

    def mark_trade(self, profit: Optional[float] = None) -> None:
        """Called after order_send DONE — keeps internal stats fresh.

        Pass profit=None for "trade just opened", or pass realized PnL
        when the trade closes.
        """
        # Refresh state from disk in case another process wrote
        self._state = self._load_state()
        self._state["last_trade_ts"] = time.time()
        self._save_state()

    def manual_freeze(self, minutes: int, reason: str) -> None:
        """Trip the breaker on demand (admin tool)."""
        self._freeze(minutes, reason)

    def reset(self) -> None:
        """Clear freeze state — use carefully."""
        all_state = self._load_all_state()
        all_state.pop(str(self.magic), None)
        self._save_all_state(all_state)

    def status(self) -> dict:
        """Snapshot for dashboards."""
        return {
            "magic": self.magic,
            "frozen_until": self._state.get("freeze_until_ts", 0),
            "freeze_reason": self._state.get("freeze_reason"),
            "consec_losses": self._consec_loss_count(),
            "recent_trades": self._recent_trade_count(self.rate_window_sec),
        }

    # ──────────────────────────────────────────────────────
    # Internals — MT5 history queries
    # ──────────────────────────────────────────────────────
    def _recent_trade_count(self, window_sec: int) -> int:
        # Fetch deals over a generous window to account for broker timezone offset
        since = datetime.now(timezone.utc) - timedelta(seconds=window_sec * 2 + 86400)
        deals = mt5.history_deals_get(since, datetime.now(timezone.utc) + timedelta(hours=24)) or []
        # Reference "now" in BROKER time (same clock as deal.time) — use the live
        # tick timestamp. Count entries within window_sec of NOW (not of the last
        # historical trade — that bug froze the engine permanently).
        tick = mt5.symbol_info_tick(self.symbol)
        now_broker = float(tick.time) if tick else 0.0
        if now_broker <= 0:
            # fallback: newest deal time across ALL magics ≈ broker now
            all_times = [d.time for d in deals]
            now_broker = float(max(all_times)) if all_times else 0.0
        if now_broker <= 0:
            return 0
        return sum(1 for d in deals
                   if int(d.magic) == self.magic and int(d.entry) == 0
                   and 0 <= (now_broker - d.time) < window_sec)

    def _consec_loss_count(self) -> int:
        since = datetime.now(timezone.utc) - timedelta(hours=6)
        deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
        exits = sorted([d for d in deals
                        if int(d.magic) == self.magic and int(d.entry) in (1, 2)],
                       key=lambda d: d.time, reverse=True)
        n = 0
        for d in exits:
            if float(d.profit) < 0:
                n += 1
            else:
                break
        return n

    def _drawdown_in_window(self, window_sec: int) -> float:
        since = datetime.now(timezone.utc) - timedelta(seconds=window_sec)
        deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
        exits = [d for d in deals
                 if int(d.magic) == self.magic and int(d.entry) in (1, 2)]
        return sum(float(d.profit) for d in exits)

    # ──────────────────────────────────────────────────────
    # State persistence — shared across all processes
    # ──────────────────────────────────────────────────────
    def _load_all_state(self) -> dict:
        if not STATE_FILE.exists():
            return {}
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_all_state(self, all_state: dict) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(all_state, indent=2, default=str), encoding="utf-8")
        tmp.replace(STATE_FILE)

    def _load_state(self) -> dict:
        return self._load_all_state().get(str(self.magic), {})

    def _save_state(self) -> None:
        all_state = self._load_all_state()
        all_state[str(self.magic)] = self._state
        self._save_all_state(all_state)

    def _freeze(self, minutes: int, reason: str) -> None:
        self._state["freeze_until_ts"] = time.time() + minutes * 60
        self._state["freeze_reason"] = reason
        self._state["frozen_at"] = datetime.now(timezone.utc).isoformat()
        self._save_state()


__all__ = ["CircuitBreaker", "DEFAULTS"]
