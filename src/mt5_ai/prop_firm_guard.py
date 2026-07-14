"""
prop_firm_guard.py
------------------
Prop firm trading protection rules — replicated exactly from Algory's
prop_firm config in dashboard_settings.json.

Settings (Algory exact values):
    news_mode    : "FTMO"       — filter trades around news events
    news_mins    : 30           — minutes before/after news to block trading
    use_dd       : true         — enable daily drawdown limit
    dd_limit     : 4.0          — max daily drawdown % before hard stop
    use_friday   : true         — close all by Friday EOD
    friday_hour  : 19           — Friday close hour (server time)
    use_symbol_lock : true      — only one active direction per symbol
    use_max_agg_risk: false     — aggregate risk cap (disabled in this config)
    max_agg_risk_pct: 5.0       — aggregate risk cap % (dormant)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger("friday.prop_firm")

# ─────────────────────────────────────────────────────────────────────────────
#  Prop firm configuration — exact from Algory dashboard_settings.json
# ─────────────────────────────────────────────────────────────────────────────

PROP_CONFIG = {
    "news_mode":         "FTMO",    # FTMO | NONE
    "news_mins":         30,        # minutes buffer around news
    "use_dd":            True,
    "dd_limit":          4.0,       # % daily drawdown hard stop
    "use_friday":        True,
    "friday_hour":       19,        # 19:00 server time — close all trades
    "use_symbol_lock":   True,      # no opposing positions on same symbol
    "use_max_agg_risk":  False,     # aggregate risk cap disabled
    "max_agg_risk_pct":  5.0,       # % — dormant while use_max_agg_risk=False
}


# ─────────────────────────────────────────────────────────────────────────────
#  News event (injected externally via add_news_event)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NewsEvent:
    symbol:    str           # e.g. "EURUSD", "USD" (affects all USD pairs)
    time_utc:  datetime
    impact:    str = "HIGH"  # HIGH | MEDIUM | LOW


# ─────────────────────────────────────────────────────────────────────────────
#  PropFirmGuard
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PropFirmGuard:
    """
    Enforces Algory-style prop firm trading rules in FRIDAY.

    Instantiate once per session and share across agents.
    Call can_trade() before every order submission.
    """

    # Balance tracking for daily DD calculation
    session_open_balance:   float = 100_000.0
    current_balance:        float = 100_000.0
    peak_daily_balance:     float = 100_000.0

    # Symbol lock state: symbol → active direction ("BUY"|"SELL"|None)
    symbol_lock: dict[str, str | None] = field(default_factory=dict)

    # Scheduled news events
    news_events: list[NewsEvent] = field(default_factory=list)

    # Runtime flags
    _hard_stop_triggered: bool = False

    # ── Balance updates ───────────────────────────────────────────────────────

    def update_balance(self, new_balance: float) -> None:
        self.current_balance = new_balance
        if new_balance > self.peak_daily_balance:
            self.peak_daily_balance = new_balance

    def reset_daily(self) -> None:
        """Call at start of each trading day."""
        self.session_open_balance = self.current_balance
        self.peak_daily_balance   = self.current_balance
        self._hard_stop_triggered = False
        log.info("[PropFirm] Daily reset — balance=%.2f", self.current_balance)

    # ── News ──────────────────────────────────────────────────────────────────

    def add_news_event(self, symbol: str, time_utc: datetime, impact: str = "HIGH") -> None:
        self.news_events.append(NewsEvent(symbol=symbol, time_utc=time_utc, impact=impact))
        # Keep only future events
        now = datetime.now(timezone.utc)
        self.news_events = [e for e in self.news_events if e.time_utc > now - timedelta(hours=2)]

    def _is_news_window(self, symbol: str, now: datetime | None = None) -> bool:
        """Return True if now falls within ±news_mins of any high-impact event for symbol."""
        if PROP_CONFIG["news_mode"] == "NONE":
            return False
        now   = now or datetime.now(timezone.utc)
        buf   = timedelta(minutes=PROP_CONFIG["news_mins"])
        upper = now.upper() if hasattr(now, "upper") else symbol.upper()
        for event in self.news_events:
            if event.impact not in ("HIGH", "MEDIUM"):
                continue
            ev_sym = event.symbol.upper()
            # Match if event symbol is in the trading symbol, or is a currency code
            if ev_sym in symbol.upper() or symbol.upper() in ev_sym:
                if abs(now - event.time_utc) <= buf:
                    return True
        return False

    # ── Daily drawdown ────────────────────────────────────────────────────────

    def _daily_dd_breached(self) -> bool:
        if not PROP_CONFIG["use_dd"]:
            return False
        limit   = PROP_CONFIG["dd_limit"] / 100.0
        dd_from_peak = (self.peak_daily_balance - self.current_balance) / self.peak_daily_balance
        if dd_from_peak >= limit:
            if not self._hard_stop_triggered:
                self._hard_stop_triggered = True
                log.warning(
                    "[PropFirm] HARD STOP — daily DD %.2f%% ≥ limit %.2f%%",
                    dd_from_peak * 100, PROP_CONFIG["dd_limit"],
                )
            return True
        return False

    # ── Friday EOD ────────────────────────────────────────────────────────────

    def _is_friday_close(self, now: datetime | None = None) -> bool:
        if not PROP_CONFIG["use_friday"]:
            return False
        now  = now or datetime.now(timezone.utc)
        return now.weekday() == 4 and now.hour >= PROP_CONFIG["friday_hour"]  # 4 = Friday

    # ── Symbol lock ────────────────────────────────────────────────────────────

    def lock_symbol(self, symbol: str, direction: str) -> None:
        if PROP_CONFIG["use_symbol_lock"]:
            self.symbol_lock[symbol] = direction

    def unlock_symbol(self, symbol: str) -> None:
        self.symbol_lock.pop(symbol, None)

    def _symbol_conflicts(self, symbol: str, direction: str) -> bool:
        if not PROP_CONFIG["use_symbol_lock"]:
            return False
        active = self.symbol_lock.get(symbol)
        return active is not None and active != direction

    # ── Aggregate risk ─────────────────────────────────────────────────────────

    def _agg_risk_exceeded(self, new_risk_pct: float, current_agg_risk_pct: float) -> bool:
        if not PROP_CONFIG["use_max_agg_risk"]:
            return False
        return (current_agg_risk_pct + new_risk_pct) > PROP_CONFIG["max_agg_risk_pct"]

    # ── Main gate ─────────────────────────────────────────────────────────────

    def can_trade(
        self,
        symbol:              str,
        direction:           str,
        now:                 datetime | None = None,
        new_risk_pct:        float = 0.0,
        current_agg_risk_pct: float = 0.0,
    ) -> tuple[bool, str]:
        """
        Check all Algory prop firm rules.

        Returns:
            (True, "OK")            — trade is permitted
            (False, "<reason>")     — trade blocked, with explanation
        """
        now = now or datetime.now(timezone.utc)

        # 1. Daily drawdown hard stop
        if self._daily_dd_breached():
            return False, f"DD hard stop — daily loss ≥ {PROP_CONFIG['dd_limit']}%"

        # 2. Friday EOD close
        if self._is_friday_close(now):
            return False, f"Friday EOD — no new trades after {PROP_CONFIG['friday_hour']}:00"

        # 3. News window (FTMO rules)
        if self._is_news_window(symbol, now):
            return False, f"News blackout — ±{PROP_CONFIG['news_mins']}min around high-impact event"

        # 4. Symbol lock conflict
        if self._symbol_conflicts(symbol, direction):
            return False, f"Symbol lock — {symbol} already has {self.symbol_lock.get(symbol)} position"

        # 5. Aggregate risk (disabled in default Algory config but kept for completeness)
        if self._agg_risk_exceeded(new_risk_pct, current_agg_risk_pct):
            return False, f"Aggregate risk {current_agg_risk_pct + new_risk_pct:.1f}% > {PROP_CONFIG['max_agg_risk_pct']}%"

        return True, "OK"

    def should_close_all(self, now: datetime | None = None) -> tuple[bool, str]:
        """
        Returns (True, reason) if all open positions should be closed immediately.
        Called from position monitor / trailing SL logic.
        """
        now = now or datetime.now(timezone.utc)

        if self._daily_dd_breached():
            return True, "DD hard stop"

        if self._is_friday_close(now):
            return True, f"Friday EOD close at {PROP_CONFIG['friday_hour']}:00"

        return False, ""

    # ── Status summary ────────────────────────────────────────────────────────

    def status(self) -> dict:
        now    = datetime.now(timezone.utc)
        dd_pct = (
            (self.peak_daily_balance - self.current_balance) / self.peak_daily_balance * 100
            if self.peak_daily_balance > 0 else 0.0
        )
        return {
            "current_balance":    round(self.current_balance, 2),
            "peak_balance":       round(self.peak_daily_balance, 2),
            "daily_dd_pct":       round(dd_pct, 3),
            "dd_limit_pct":       PROP_CONFIG["dd_limit"],
            "hard_stop_active":   self._hard_stop_triggered,
            "friday_locked":      self._is_friday_close(now),
            "symbol_locks":       dict(self.symbol_lock),
            "pending_news":       len(self.news_events),
            "config":             PROP_CONFIG,
        }
