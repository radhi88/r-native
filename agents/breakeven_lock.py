"""agents/breakeven_lock.py — snap SL to break-even on small wins.

Observed pattern across many cycles: positions reach \$0.30-\$1.00
profit briefly, then reverse and either hit SL (losing \$1-2) or get
position_aging-cut at break-even or worse. The unrealized profit
disappears.

adaptive_trailing.py handles this gradually — it locks 50-90% of
gain based on live confidence. That's the right behavior for trades
with strong directional conviction. But for the many small-conviction
trades that ARE briefly profitable, a faster aggressive lock pays:

Every 30 seconds, scan R-magic positions:
  • If position profit >= TRIGGER_PL (default \$0.30)
  • AND SL is not yet at break-even (still at original loss-side level)
  • Move SL to entry +/- BUFFER_POINTS (small +1 pip)

Effect: any trade that briefly touches +\$0.30 can no longer turn into
a loss. Worst case = exit at break-even instead of -\$1+. This trades
"some upside captured by trail" for "no losses on briefly-good trades".

Cooperates cleanly with adaptive_trailing — both never widen SL
(monotonically tightening). breakeven_lock fires the SNAP first; trail
then refines based on confidence later.

This is what the user has been asking for repeatedly: "احفظ الأرباح
الصغيرة" (lock in small gains).
"""
from __future__ import annotations

from datetime import datetime

from r_native.agents.base import Agent, emit_insight


R_MAGIC = 20260605


class BreakevenLock(Agent):
    name = "breakeven_lock"
    description = "Snaps SL to break-even on PROVEN winners (3 min old + ≥ $0.80 profit)"
    interval_seconds = 30      # half-minute scan
    default_enabled = True

    # CYCLE-39 FIX (user feedback "وقف الخسارة قريبه"): the old
    # 30-second / $0.30 trigger was killing winners. On 2026-05-27 the
    # BUY_LIMIT @ 4499.50 went +$0.63 in 30 seconds, BE-lock fired,
    # micro-reversal touched the new BE-SL, then price ran +$11 to 4511.
    # Lost $5+ of free PnL because BE snapped too fast.
    #
    # NEW policy: need PROVEN winner before locking.
    #   • Position must be ≥ 3 minutes old (price has had time to confirm)
    #   • Profit must be ≥ $0.80 (3× the noise floor of $0.30 wicks)
    #   • SL moves to entry + 2pt (small protection, not flush BE)
    TRIGGER_PL_USD     = 0.80   # was $0.30 — too tight, caught noise
    MIN_AGE_SECONDS    = 180    # was 0 — fire after 3 min minimum
    BUFFER_POINTS      = 2.0    # was 1.0 — slightly bigger BE buffer

    def _is_sl_locked(self, position, entry: float) -> bool:
        """Has SL already been moved to break-even or better?"""
        if not position.sl: return False
        is_buy = int(position.type) == 0
        if is_buy:
            return float(position.sl) >= entry
        else:
            return float(position.sl) <= entry

    def _modify_sl(self, mt5, position, new_sl: float) -> tuple[bool, str]:
        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": int(position.ticket),
            "symbol":   position.symbol,
            "sl":       float(new_sl),
            "tp":       float(position.tp),
            "magic":    R_MAGIC,
        }
        try:
            r = mt5.order_send(req)
            if r is None: return False, "order_send returned None"
            if r.retcode == 10009:    # TRADE_RETCODE_DONE
                return True, "ok"
            return False, f"retcode {r.retcode} {getattr(r, 'comment', '?')}"
        except Exception as e:
            return False, str(e)

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
        if not r_positions: return

        locked = []
        from datetime import datetime as _dt
        now_ts = _dt.now().timestamp()
        for p in r_positions:
            if float(p.profit) < self.TRIGGER_PL_USD: continue

            # CYCLE-39: age gate — don't lock fresh trades.
            age_sec = now_ts - int(p.time)
            if age_sec < self.MIN_AGE_SECONDS:
                continue

            entry = float(p.price_open)
            if self._is_sl_locked(p, entry):
                continue   # already at BE or better

            # Compute new SL = entry +/- buffer * point_size
            info = mt5.symbol_info(p.symbol)
            if not info: continue
            point_size = float(info.point)
            buffer = self.BUFFER_POINTS * point_size

            is_buy = int(p.type) == 0
            new_sl = entry + buffer if is_buy else entry - buffer
            # Round to symbol digits
            digits = int(info.digits)
            new_sl = round(new_sl, digits)

            ok, reason = self._modify_sl(mt5, p, new_sl)
            if ok:
                locked.append({
                    "ticket": int(p.ticket),
                    "symbol": p.symbol,
                    "side":   "BUY" if is_buy else "SELL",
                    "profit": round(float(p.profit), 2),
                    "old_sl": round(float(p.sl), digits),
                    "new_sl": new_sl,
                    "entry":  round(entry, digits),
                })
            else:
                # WARN once per failure (dedup at base.py prevents spam)
                emit_insight(self.name, "WARN",
                    f"BE lock failed {p.symbol} #{p.ticket}: {reason}")

        if locked:
            emit_insight(self.name, "ACT",
                f"🔒 BE-locked {len(locked)} positions: "
                + ", ".join(f"{l['symbol']} {l['side']} +${l['profit']:.2f}"
                             for l in locked[:4]),
                data={"locked": locked},
                action="breakeven_locked")
