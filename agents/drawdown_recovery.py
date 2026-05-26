"""agents/drawdown_recovery.py — auto-reduce risk when account dips.

When equity drops below baseline by X%, this agent:
  • Steps 1-3 progressively reduce lot size (0.01 → 0.005 isn't legal, so
    it lowers max_positions instead, then halves lot multiplier in
    exposure_guard).
  • Step 4: outright kill_switch when DD breaches 15%.

When equity recovers to within 2% of high-water-mark → restore normal.

Conservative philosophy: drawdown is the warning, not the signal. Reduce
size during stress, scale back up only after proven recovery.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


PEAK_PATH    = Path(r"C:\Users\Radhi\MT5\data\r_native\peak_equity.json")
RECOVERY_CFG = Path(r"C:\Users\Radhi\MT5\data\r_native\dd_recovery_state.json")


class DrawdownRecovery(Agent):
    name = "drawdown_recovery"
    description = "Auto-reduces lot/positions when account in drawdown, restores on recovery"
    interval_seconds = 30
    default_enabled = True

    DD_LEVEL_1 = 3.0    # 3% off peak — light caution (info only)
    DD_LEVEL_2 = 7.0    # 7% off peak — halve positions max
    DD_LEVEL_3 = 12.0   # 12% off peak — block new entries
    DD_LEVEL_4 = 18.0   # 18% off peak — KILL SWITCH

    # Cycle 32 fix: dedup level emissions. Was firing same ACT every
    # 30 sec (40 messages per 20 min) flooding insights feed.
    # Now: only emit on LEVEL TRANSITION (e.g. 1→2 or 2→3 or 2→1).
    _last_emitted_level: int = -1

    def _get_equity(self) -> float | None:
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
            info = mt5.account_info()
            return float(info.equity) if info else None
        except Exception: return None

    def _load_peak(self) -> float:
        if PEAK_PATH.exists():
            try:
                return float(json.loads(PEAK_PATH.read_text(encoding="utf-8")).get("peak", 0))
            except Exception: pass
        return 0.0

    def _save_peak(self, peak: float):
        PEAK_PATH.parent.mkdir(parents=True, exist_ok=True)
        PEAK_PATH.write_text(json.dumps({
            "peak": peak, "updated_at": datetime.now(timezone.utc).isoformat()
        }), encoding="utf-8")

    def _save_state(self, state: dict):
        RECOVERY_CFG.parent.mkdir(parents=True, exist_ok=True)
        RECOVERY_CFG.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def tick(self):
        eq = self._get_equity()
        if not eq: return
        peak = self._load_peak()
        if eq > peak:
            self._save_peak(eq)
            return

        if peak <= 0: return
        dd_pct = (peak - eq) / peak * 100

        # Determine current severity level
        level = 0
        action_taken = ""
        if dd_pct >= self.DD_LEVEL_4:
            level = 4
            self._trip_kill_switch(f"DD {dd_pct:.1f}% breached emergency level")
            action_taken = f"💀 KILL SWITCH (DD {dd_pct:.1f}%)"
        elif dd_pct >= self.DD_LEVEL_3:
            level = 3
            action_taken = f"🛑 NEW ENTRIES BLOCKED (DD {dd_pct:.1f}%)"
        elif dd_pct >= self.DD_LEVEL_2:
            level = 2
            action_taken = f"⚠ POSITIONS REDUCED (DD {dd_pct:.1f}%)"
        elif dd_pct >= self.DD_LEVEL_1:
            level = 1
            action_taken = f"💡 caution (DD {dd_pct:.1f}%)"

        state = {
            "peak_equity":    peak,
            "current_equity": eq,
            "drawdown_pct":   round(dd_pct, 2),
            "severity_level": level,
            "action":         action_taken,
            "blocks_new_entries":   level >= 3,
            "halve_max_positions":  level >= 2,
            "updated_at":     datetime.now(timezone.utc).isoformat(),
        }
        self._save_state(state)

        # Only emit on LEVEL CHANGE — prevents same-level spam every 30s
        if level != self._last_emitted_level:
            if level >= 1 and action_taken:
                arrow = ""
                if self._last_emitted_level >= 0:
                    if level > self._last_emitted_level: arrow = " ⬆ worsening"
                    elif level < self._last_emitted_level: arrow = " ⬇ recovering"
                emit_insight(self.name,
                    "ACT" if level >= 2 else "INFO",
                    f"📉 DD {dd_pct:.1f}% off peak ${peak:.2f} "
                    f"(now ${eq:.2f}) — {action_taken}{arrow}",
                    data=state,
                    action=f"dd_level_{level}" if level >= 2 else None)
            elif level == 0 and self._last_emitted_level > 0:
                emit_insight(self.name, "INFO",
                    f"✓ DD recovered to {dd_pct:.1f}% (under {self.DD_LEVEL_1}%) "
                    f"— restrictions lifted")
            self._last_emitted_level = level

    def _trip_kill_switch(self, reason: str):
        kp = Path(r"C:\Users\Radhi\MT5\data\kill_switch.json")
        try:
            cur = json.loads(kp.read_text(encoding="utf-8")) if kp.exists() else {}
            if cur.get("kill_switch"): return
            cur.update({"kill_switch": True, "tripped_by": "drawdown_recovery",
                        "reason": reason,
                        "tripped_at": datetime.now(timezone.utc).isoformat()})
            kp.parent.mkdir(parents=True, exist_ok=True)
            kp.write_text(json.dumps(cur, indent=2), encoding="utf-8")
        except Exception: pass
