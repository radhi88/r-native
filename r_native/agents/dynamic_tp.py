"""agents/dynamic_tp.py — compress fixed TPs when volatility dies.

The user explicitly asked for "profit-target dynamic adjustment".
adaptive_trailing already trails SL based on confidence + progress, but
TP stays where it was set at entry — often at +5..+8 × ATR_at_entry
to capture long runs. When markets stagnate (e.g. Sunday dead hours),
that distant TP becomes unreachable and the trade dies via aging or
SL drift even though it had a small profit available.

This agent runs every 3 min and, for each open R-magic position:

  Skip unless:
    • age >= COMPRESS_MIN_AGE_MIN (30 min — give it a fair shot)
    • profit > 0 (don't widen losers, just bring greedy winners closer)

  Compute current H1 ATR, then:
    • original-TP distance vs current_price (in profit direction)
    • if original_TP is more than TP_FAR_ATR_MULT × current_ATR away
      → market won't reach it; pull TP closer

  New TP = current_price + COMPRESS_TARGET_ATR_MULT × current_ATR
            (in profit direction)

  Safety:
    • new_tp MUST be farther than current price (still in profit)
    • new_tp MUST improve vs entry + buffer (always lock entry+)
    • never widen TP — only compress
    • only modify if new_tp is meaningfully closer (>= 0.3 × ATR shift)

Soft-fails — never raises. If MT5 modify fails (broker reject, stops
level, etc.), emit WARN and move on. Coexists with adaptive_trailing
(SL side) cleanly because they touch different fields.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


R_MAGIC = 20260605


class DynamicTP(Agent):
    name = "dynamic_tp"
    description = "Compresses unreachable TPs on stale-but-profitable positions"
    interval_seconds = 180        # every 3 min
    default_enabled = True

    COMPRESS_MIN_AGE_MIN   = 30       # don't touch fresh positions
    TP_FAR_ATR_MULT        = 6.0      # current TP more than 6×ATR away = "stranded"
    COMPRESS_TARGET_ATR_MULT = 2.0    # new TP at current ± 2×ATR
    MIN_SHIFT_ATR          = 0.3      # only modify if shift > 0.3×ATR
    BREAKEVEN_BUFFER       = 0.0001   # always at least entry+epsilon

    def _h1_atr(self, mt5, symbol: str, n: int = 20) -> float | None:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, n)
        if rates is None or len(rates) < 14: return None
        trs = [max(float(rates["high"][i]) - float(rates["low"][i]),
                    abs(float(rates["high"][i]) - float(rates["close"][i-1])),
                    abs(float(rates["low"][i])  - float(rates["close"][i-1])))
                for i in range(1, len(rates))]
        return sum(trs[-14:]) / 14

    def _modify_tp(self, mt5, position, new_tp: float) -> tuple[bool, str]:
        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": int(position.ticket),
            "symbol":   position.symbol,
            "sl":       float(position.sl),
            "tp":       float(new_tp),
            "magic":    R_MAGIC,
        }
        try:
            r = mt5.order_send(req)
            if r is None: return False, "order_send returned None"
            if r.retcode in (10009, 0):    # TRADE_RETCODE_DONE = 10009
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

        now_ts = datetime.now().timestamp()
        adjusted = []
        for p in r_positions:
            age_min = (now_ts - int(p.time)) / 60
            if age_min < self.COMPRESS_MIN_AGE_MIN: continue
            if float(p.profit) <= 0: continue   # only compress winners

            atr = self._h1_atr(mt5, p.symbol)
            if not atr or atr <= 0: continue

            tick = mt5.symbol_info_tick(p.symbol)
            if not tick: continue

            # For BUY: profit direction = up; for SELL: profit direction = down
            is_buy = int(p.type) == 0
            current = tick.bid if is_buy else tick.ask
            entry   = float(p.price_open)
            cur_tp  = float(p.tp) if p.tp else 0.0
            if cur_tp <= 0: continue   # no TP set, skip

            # Distance to current TP in profit direction (positive = ahead)
            if is_buy:
                tp_distance = cur_tp - current
            else:
                tp_distance = current - cur_tp

            if tp_distance <= 0: continue   # already past TP somehow

            # Only compress if TP is "too far" (more than TP_FAR_ATR_MULT × ATR)
            if tp_distance < atr * self.TP_FAR_ATR_MULT: continue

            # Compute new TP — closer to current, still profitable, never below entry
            target_offset = atr * self.COMPRESS_TARGET_ATR_MULT
            if is_buy:
                new_tp = current + target_offset
                # Never below entry+buffer (must remain profitable)
                new_tp = max(new_tp, entry + self.BREAKEVEN_BUFFER)
                # Never widen
                if new_tp >= cur_tp: continue
                shift = cur_tp - new_tp
            else:
                new_tp = current - target_offset
                new_tp = min(new_tp, entry - self.BREAKEVEN_BUFFER)
                if new_tp <= cur_tp: continue
                shift = new_tp - cur_tp

            if abs(shift) < atr * self.MIN_SHIFT_ATR: continue

            ok, reason = self._modify_tp(mt5, p, new_tp)
            if ok:
                adjusted.append({
                    "ticket":   int(p.ticket),
                    "symbol":   p.symbol,
                    "side":     "BUY" if is_buy else "SELL",
                    "age_min":  round(age_min, 0),
                    "profit":   round(float(p.profit), 2),
                    "old_tp":   round(cur_tp, 5),
                    "new_tp":   round(new_tp, 5),
                    "atr":      round(atr, 5),
                    "shift_atr": round(abs(shift) / atr, 2),
                })
            else:
                emit_insight(self.name, "WARN",
                    f"TP modify failed {p.symbol} #{p.ticket}: {reason}")

        if adjusted:
            emit_insight(self.name, "ACT",
                f"🎯 compressed TP on {len(adjusted)} stale winners: "
                + ", ".join(f"{a['symbol']} {a['side']} "
                             f"{a['old_tp']}→{a['new_tp']} (-{a['shift_atr']}×ATR)"
                             for a in adjusted[:4]),
                data={"adjusted": adjusted},
                action="tp_compressed")
