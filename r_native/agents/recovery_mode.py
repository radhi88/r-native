"""agents/recovery_mode.py — micro-lot, winners-only recovery gate.

Background (cycle 39, 2026-05-27): account drew down 22% in 36h. Root-cause
audit found:
  1. trade_gate RSI-FLIP bug created wrong-side entries in trending markets
     (XAUUSDm SELLS lost -$43.7 in an uptrend where BUYS won 76% — fixed in
     trade_gate.py same commit).
  2. Genome routing put symbols B99880, 6EE942 onto exotic metal pairs
     (XAGAUD/GBP/EUR, XAUAUD/GBP) where they lost EVERY trade.
  3. Several genomes profitable on one side, ruinous on the other (e.g.
     ETHUSDm: SELLS +$1.8 / BUYS -$2.9, BTCUSDm: SELLS +$0.8 / BUYS -$3.8).

This agent enforces a "recovery whitelist" on every entry while the account
is rebuilding back to $105. It runs BEFORE r_executor's send_order and:
  • Blocks every symbol not on the whitelist.
  • Blocks the WRONG side per symbol based on actual 7-day per-side PnL.
  • Caps lot to 0.01 regardless of monster/regime/cert multipliers.
  • Caps concurrent open positions to 2.
  • Auto-disables itself once equity ≥ RECOVERY_TARGET_USD (default $105).

After target is hit, the whitelist relaxes (writes a flag) and normal gating
resumes — but with the RSI-flip bug fix permanent.

Whitelist derived from real 7d data (2026-05-20 → 05-27), magic 20260605:

  XAUUSDm        BUY   17t 76% +$5.5    ← buy-only
  US30_x10m      BUY   30t 90% +$3.4    ← buy-only (dow uptrend dominant)
  UKOILm         SELL   3t 100% +$2.4   ← sell-only
  USOILm         SELL   3t 100% +$0.9
  XAGUSDm        BUY    4t 100% +$12.7  ← buy-only
  GBPJPYm        BOTH   4t 75-100% +$1.0
  US30m          BUY    9t 67% +$0.2
  USTECm         BOTH   3t 100% +$0.1
  EURUSDm        BUY    1t (sparse but +)
  ETHUSDm        SELL  13t 54% +$1.8    ← sell-only (BUYs -$2.9)
  BTCUSDm        SELL  22t 55% +$0.8    ← sell-only (BUYs -$3.8)
  US500_x100m    BUY    1t (sparse but +)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


STATE_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\recovery_mode.json")
TARGET_USD = 105.0           # exit recovery once equity ≥ this
LOT_CAP    = 0.01            # never bigger than micro-lot in recovery
MAX_POS    = 2               # at most 2 concurrent in recovery

# (symbol, allowed_sides) — sides ∈ {"BUY","SELL","BOTH"}
WHITELIST: dict[str, str] = {
    "XAUUSDm":    "BUY",
    "US30_x10m":  "BUY",
    "XAGUSDm":    "BUY",
    "UKOILm":     "SELL",
    "USOILm":     "SELL",
    "GBPJPYm":    "BOTH",
    "US30m":      "BUY",
    "USTECm":     "BOTH",
    "EURUSDm":    "BUY",
    "ETHUSDm":    "SELL",
    "BTCUSDm":    "SELL",
    "US500_x100m": "BUY",
}


def _load_state() -> dict:
    if not STATE_PATH.exists(): return {}
    try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception: return {}


def _save_state(s: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_PATH)


def is_recovery_active() -> bool:
    """True while equity has not yet reached TARGET_USD. r_executor reads
    this before sizing/sending. Cheap call (one JSON read + one MT5 call)."""
    try:
        # 1) Honor explicit OFF flag if user disabled it
        st = _load_state()
        if st.get("force_off"): return False
        # 2) Otherwise auto-off once we hit target
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
        info = mt5.account_info()
        if not info: return True  # safe default
        return float(info.equity) < TARGET_USD
    except Exception:
        return True  # safer to assume ON


def filter_entry(symbol: str, side: str, requested_lot: float) -> tuple[bool, float, str]:
    """Decide if an entry should proceed under recovery rules.

    Returns (allowed, effective_lot, reason).
      • allowed=False → reject the entry entirely
      • allowed=True  → use the returned (possibly capped) lot
    """
    if not is_recovery_active():
        return True, requested_lot, "recovery off (target reached)"

    side_u = (side or "").upper()
    allowed_sides = WHITELIST.get(symbol)
    if not allowed_sides:
        return False, 0.0, f"{symbol} not on recovery whitelist"
    if allowed_sides != "BOTH" and side_u != allowed_sides:
        return False, 0.0, (f"{symbol} recovery side={allowed_sides} only "
                             f"(requested {side_u})")
    # Lot cap
    eff = min(requested_lot, LOT_CAP)
    if eff < requested_lot - 1e-9:
        reason = f"lot capped {requested_lot}→{eff}"
    else:
        reason = "ok"
    return True, eff, reason


def max_positions() -> int:
    return MAX_POS if is_recovery_active() else 999


class RecoveryMode(Agent):
    """Pure visibility agent. Recovery filter itself is enforced by
    r_executor (via filter_entry above). This agent's tick:
      • emits one-shot INFO when recovery starts (after kill_switch clear)
      • emits ACT when target reached → recovery disengages
      • writes status file so dashboard can show "RECOVERY: $98.20 → $105"
    """
    name = "recovery_mode"
    description = "Winners-only whitelist + 0.01 lot cap until equity ≥ $105"
    interval_seconds = 60
    default_enabled = True

    def tick(self):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
            info = mt5.account_info()
            if not info: return
            equity = float(info.equity)
        except Exception:
            return

        st = _load_state()
        active = equity < TARGET_USD and not st.get("force_off")
        progress_pct = round((equity / TARGET_USD) * 100, 1)

        st_new = {
            "active":        active,
            "target_usd":    TARGET_USD,
            "current_eq":    round(equity, 2),
            "progress_pct":  progress_pct,
            "lot_cap":       LOT_CAP,
            "max_positions": MAX_POS if active else 999,
            "whitelist":     WHITELIST,
            "force_off":     bool(st.get("force_off")),
            "updated_at":    datetime.now(timezone.utc).isoformat(),
        }
        _save_state(st_new)

        # One-shot transitions
        was_active = bool(st.get("active"))
        if active and not was_active:
            emit_insight(self.name, "INFO",
                f"🛟 RECOVERY MODE engaged — equity ${equity:.2f} → target "
                f"${TARGET_USD:.0f}. Whitelist {len(WHITELIST)} symbols, "
                f"lot cap {LOT_CAP}, max {MAX_POS} pos.")
        elif (not active) and was_active and not st.get("force_off"):
            emit_insight(self.name, "ACT",
                f"✅ RECOVERY TARGET REACHED — equity ${equity:.2f} ≥ "
                f"${TARGET_USD:.0f}. Whitelist disengaged, normal "
                f"gating resumes.",
                action="recovery_exit")
