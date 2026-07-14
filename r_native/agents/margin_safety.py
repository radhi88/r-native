"""agents/margin_safety.py — preventive margin usage monitor for small accounts.

The user's account is small (~\$126). Each 0.01-lot position uses ~\$0.50-\$2
margin depending on symbol. With 3-4 open positions + pending orders also
reserving margin, the buffer can compress fast — especially when winner_booster
scales lot up 1.5x-2.5x or monster_genome boost triggers 2.5x.

Every 60s:
  • Read account: balance, equity, margin used, margin_free, margin_level
  • Write data/r_native/margin_usage.json
  • Emit WARN at margin_used > MARGIN_WARN_PCT of equity (default 40%)
  • Emit ACT-level insight at margin_used > MARGIN_CRITICAL_PCT (60%)
    so the user can react manually if needed

This is preventive only — does NOT auto-close positions. Risk_sentinel +
position_aging + drawdown_recovery handle reactive cuts. Margin_safety
gives early-warning so user wakes to find "you were close to margin call"
rather than "you got margin called".
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


OUT_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\margin_usage.json")


class MarginSafety(Agent):
    name = "margin_safety"
    description = "Margin-usage monitor with early-warning thresholds"
    interval_seconds = 60        # every minute
    default_enabled = True

    MARGIN_WARN_PCT      = 40.0    # margin used > 40% of equity → WARN
    MARGIN_CRITICAL_PCT  = 60.0    # > 60% → ACT (visible alert)
    MIN_MARGIN_LEVEL_PCT = 200.0   # MT5 margin level < 200% → WARN

    _last_warn_state: str = "OK"   # OK / WARN / CRITICAL

    def tick(self):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
        except Exception as e:
            emit_insight(self.name, "WARN", f"mt5 init err: {e}")
            return

        try:
            info = mt5.account_info()
        except Exception as e:
            emit_insight(self.name, "WARN", f"account_info err: {e}")
            return

        if not info: return

        balance      = float(info.balance)
        equity       = float(info.equity)
        margin       = float(info.margin)
        margin_free  = float(info.margin_free)
        margin_level = (float(equity) / margin * 100) if margin > 0 else 9999.0

        margin_pct = (margin / equity * 100) if equity > 0 else 0.0

        # Determine state
        if margin_pct >= self.MARGIN_CRITICAL_PCT or margin_level <= 150:
            state = "CRITICAL"
        elif margin_pct >= self.MARGIN_WARN_PCT or margin_level <= self.MIN_MARGIN_LEVEL_PCT:
            state = "WARN"
        else:
            state = "OK"

        # Count open positions for context
        try:
            positions = mt5.positions_get() or []
            r_positions = [p for p in positions if int(p.magic) == 20260605]
            pos_count = len(r_positions)
        except Exception:
            pos_count = 0

        # Write status snapshot
        out = {
            "balance":       round(balance, 2),
            "equity":        round(equity, 2),
            "margin_used":   round(margin, 2),
            "margin_free":   round(margin_free, 2),
            "margin_level":  round(margin_level, 1),
            "margin_pct":    round(margin_pct, 1),
            "positions":     pos_count,
            "state":         state,
            "updated_at":    datetime.now(timezone.utc).isoformat(),
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                             encoding="utf-8")

        # State-change insight only — don't re-fire same level
        if state == self._last_warn_state:
            return

        if state == "CRITICAL":
            emit_insight(self.name, "ACT",
                f"🚨 CRITICAL margin: {margin_pct:.0f}% used (${margin:.2f}/"
                f"${equity:.2f} equity, level {margin_level:.0f}%) — "
                f"{pos_count} positions open. Risk of margin call.",
                data=out, action="margin_critical")
        elif state == "WARN":
            emit_insight(self.name, "WARN",
                f"⚠ margin elevated: {margin_pct:.0f}% used "
                f"(${margin:.2f}/${equity:.2f}), level {margin_level:.0f}%, "
                f"{pos_count} positions")
        elif state == "OK" and self._last_warn_state != "OK":
            # Recovered to OK — emit INFO so user sees the all-clear
            emit_insight(self.name, "INFO",
                f"✓ margin OK: {margin_pct:.0f}% used (recovered from "
                f"{self._last_warn_state})")

        self._last_warn_state = state
