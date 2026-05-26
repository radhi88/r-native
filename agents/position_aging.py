"""agents/position_aging.py — close stagnant zombie positions 24/7.

Observed in cycle 7: 2 R-magic positions held open >2.5h with -$0.6
each, no clear trajectory. They tied up margin and slowly bled equity.
night_shift would close them — but only at -$1+ AND only during night
hours. So between London open and night, zombies accumulate.

This agent runs every 5 min and closes positions matching ANY of:

  1) MAX_AGE_HOURS (8h+, hard cap) — trade thesis stale regardless
  2) STAGNATION       — age ≥3h AND |profit| < $0.30
                        (no decisive movement, no clear direction)
  3) SLOW_BLEED       — age ≥4h AND profit < -$0.50 (under night's $1
                        floor but still draining; user's account is
                        small, so $0.50 = 0.4%)

Always preserves WINNERS:
  • profit > $1 → never closes (let trail-SL manage it)
  • profit > $0.50 AND age < MAX_AGE_HOURS → never closes

Always preserves recent trades:
  • age < MIN_AGE_HOURS (1h) → never closes (give it a chance)

Closes via market order with comment "aging_zombie_cut" so they're
distinguishable from night-shift cuts in the deal history.
"""
from __future__ import annotations

from datetime import datetime, timezone

from r_native.agents.base import Agent, emit_insight


R_MAGIC = 20260605


class PositionAging(Agent):
    name = "position_aging"
    description = "Closes stagnant/zombie positions 24/7 (complements night_shift)"
    interval_seconds = 60          # every 60s — fast enough to catch emergency bleeds
    default_enabled = True

    # Thresholds — conservative, leave winners alone
    MAX_AGE_HOURS         = 8.0     # hard cap regardless of profit
    STAGNATION_AGE_HOURS  = 3.0     # zombie threshold
    STAGNATION_PL_BAND    = 0.30    # |pl| < $0.30 = stagnant
    SLOW_BLEED_AGE_HOURS  = 3.0     # was 4.0 — bleed for 3h is enough
    SLOW_BLEED_PL_FLOOR   = -0.50   # < -$0.50 after 3h = cut
    # Fast-bleed tier (cycle 15): catches volatility-hunter straddle fakeouts
    # that lose $1.50+ within an hour. Without this, USDCHFm BUY-type fast
    # losers grind down to SL (-$2.50+) before slow_bleed (3h) triggers.
    # Active 24/7 — unlike night_shift's -$1 floor that only runs at night.
    FAST_BLEED_AGE_HOURS  = 1.0
    FAST_BLEED_PL_FLOOR   = -1.50
    # EMERGENCY tier (cycle 24): catastrophic-fast losses (≥$3 in any time
    # frame, even brand new positions). On a $120 account that's 2.5% on a
    # single trade — at this magnitude we cut now, no MIN_AGE grace period.
    # Triggered by observation: XAUUSDm SELL and XAGUSDm SELL each hit
    # -$3+ within 2 minutes of opening. The genomes set SL too wide for
    # high-volatility metals (XAGUSDm SL was $10.30 max loss = 8% account).
    EMERGENCY_PL_FLOOR    = -3.00
    EMERGENCY_OVERRIDE_MIN_AGE = True   # bypasses MIN_AGE_HOURS=1.0

    # Protections
    WINNER_PROTECT_PL     = 1.00    # > $1 = always keep (let trail manage)
    EARLY_PROTECT_PL      = 0.50    # > $0.50 + young = keep
    MIN_AGE_HOURS         = 1.0     # < 1h = never touch (fresh entry)

    def _close_position(self, mt5, p) -> dict:
        tick = mt5.symbol_info_tick(p.symbol)
        if not tick: return {"ok": False, "reason": "no tick"}
        req = {
            "action":   mt5.TRADE_ACTION_DEAL,
            "position": p.ticket,
            "symbol":   p.symbol,
            "volume":   p.volume,
            "type":     mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
            "price":    tick.bid if p.type == 0 else tick.ask,
            "deviation": 50,
            "magic":    R_MAGIC,
            "comment":  "aging_zombie_cut",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        try:
            r = mt5.order_send(req)
            if r is None:
                return {"ok": False, "reason": "order_send returned None"}
            if r.retcode == mt5.TRADE_RETCODE_DONE:
                return {"ok": True, "deal": r.deal}
            return {"ok": False, "reason": f"retcode {r.retcode} {r.comment}"}
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    def _classify(self, age_h: float, profit: float) -> tuple[bool, str]:
        """Decide if a position should be closed. Returns (should_close, reason)."""
        # EMERGENCY first — bypass ALL grace periods on catastrophic loss
        if profit <= self.EMERGENCY_PL_FLOOR and self.EMERGENCY_OVERRIDE_MIN_AGE:
            return True, f"🚨 EMERGENCY {age_h:.2f}h, ${profit:+.2f} ≤ ${self.EMERGENCY_PL_FLOOR}"
        # Protections (skipped only by emergency)
        if age_h < self.MIN_AGE_HOURS:
            return False, "fresh entry"
        if profit >= self.WINNER_PROTECT_PL:
            return False, f"winner ${profit:+.2f}"
        if profit >= self.EARLY_PROTECT_PL and age_h < self.MAX_AGE_HOURS:
            return False, f"young winner ${profit:+.2f}"

        # Close triggers (in priority order — fast bleed first to catch
        # straddle-fakeout situations before they reach SL)
        if (age_h >= self.FAST_BLEED_AGE_HOURS
                and profit <= self.FAST_BLEED_PL_FLOOR):
            return True, f"fast bleed ({age_h:.1f}h, ${profit:+.2f})"
        if age_h >= self.MAX_AGE_HOURS:
            return True, f"max age {age_h:.1f}h ≥ {self.MAX_AGE_HOURS}h"
        if (age_h >= self.STAGNATION_AGE_HOURS
                and abs(profit) < self.STAGNATION_PL_BAND):
            return True, f"stagnant ({age_h:.1f}h, ${profit:+.2f})"
        if (age_h >= self.SLOW_BLEED_AGE_HOURS
                and profit <= self.SLOW_BLEED_PL_FLOOR):
            return True, f"slow bleed ({age_h:.1f}h, ${profit:+.2f})"

        return False, "active"

    def tick(self):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
        except Exception as e:
            emit_insight(self.name, "WARN", f"mt5 init err: {e}")
            return

        try:
            positions = mt5.positions_get() or []
        except Exception as e:
            emit_insight(self.name, "WARN", f"positions_get err: {e}")
            return

        r_positions = [p for p in positions if int(p.magic) == R_MAGIC]
        if not r_positions:
            return

        now_ts = datetime.now().timestamp()
        closed = []
        for p in r_positions:
            age_h = (now_ts - int(p.time)) / 3600
            should, reason = self._classify(age_h, float(p.profit))
            if not should:
                continue
            result = self._close_position(mt5, p)
            if result.get("ok"):
                # Attribute the close to the original opener-genome so
                # HoF live_pnl stays accurate. Soft-fail — never block
                # on bookkeeping.
                attributed_gid = None
                try:
                    from r_native.hall_of_fame import attribute_and_record
                    attributed_gid = attribute_and_record(int(p.ticket),
                                                          float(p.profit))
                except Exception: pass
                closed.append({
                    "ticket":   int(p.ticket),
                    "symbol":   p.symbol,
                    "side":     "BUY" if p.type == 0 else "SELL",
                    "profit":   round(float(p.profit), 2),
                    "age_h":    round(age_h, 1),
                    "reason":   reason,
                    "attributed_to": attributed_gid,
                })
            else:
                emit_insight(self.name, "WARN",
                    f"failed to close {p.symbol} #{p.ticket}: {result.get('reason')}")

        if closed:
            total_freed = sum(c["profit"] for c in closed)
            emit_insight(self.name, "ACT",
                f"⏱ aged-out {len(closed)} zombies (net ${total_freed:+.2f} realized): "
                + ", ".join(f"{c['symbol']} {c['side']} {c['reason']}" for c in closed[:4]),
                data={"closed": closed},
                action="zombies_cut")
