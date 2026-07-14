"""agents/sl_safety_tightener.py — dynamically tighten too-wide SLs on open positions.

PROBLEM observed cycle 31: ETHUSDm BUY R-768186 hit SL at -\$3.18.
The 3% SL cap in r_executor rejects ENTRIES with wide SLs, but positions
opened when account was bigger keep their original SLs even after account
shrinks. As equity falls, a fixed-distance SL becomes a larger
percentage of equity → bigger relative loss.

This agent runs every 60s and, for each open R-magic position:
  • Computes max-loss-at-current-SL = SL_distance × per_point × lot
  • If max_loss > MAX_LOSS_PCT of current equity:
      Tighten SL closer so worst-case loss = MAX_LOSS_PCT
      (never widens, never moves past breakeven for winners)

Coexists with adaptive_trailing + breakeven_lock — those tighten
based on PROFIT progression; this tightens based on RISK exposure.
All three monotonically tighten; never widen.

Worst-case loss now capped by account size, not just entry-time
size. ETHUSDm at -\$3.18 would have been -\$2 max with this in place.
"""
from __future__ import annotations

from r_native.agents.base import Agent, emit_insight


R_MAGIC = 20260605


class SLSafetyTightener(Agent):
    name = "sl_safety_tightener"
    description = "Dynamically tightens SLs that exceed 3% account-equity loss exposure"
    interval_seconds = 60
    default_enabled = True

    MAX_LOSS_PCT = 3.0   # target max-loss as % of current equity

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
            if r and r.retcode == 10009:
                return True, "ok"
            return False, f"retcode {r.retcode if r else 'None'}"
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
            info = mt5.account_info()
            positions = mt5.positions_get() or []
        except Exception as e:
            emit_insight(self.name, "WARN", f"mt5 err: {e}")
            return

        if not info: return
        equity = float(info.equity)
        if equity <= 0: return
        max_loss_usd = equity * (self.MAX_LOSS_PCT / 100)

        r_positions = [p for p in positions if int(p.magic) == R_MAGIC]
        tightened = []
        for p in r_positions:
            if not p.sl: continue   # no SL set — skip (separate concern)
            si = mt5.symbol_info(p.symbol)
            if not si: continue

            entry  = float(p.price_open)
            cur_sl = float(p.sl)
            is_buy = int(p.type) == 0

            # Current max-loss at present SL
            sl_distance = abs(entry - cur_sl)
            per_point = float(si.trade_tick_value) / max(float(si.trade_tick_size), 1e-9)
            cur_max_loss = sl_distance * per_point * float(p.volume)
            if cur_max_loss <= max_loss_usd: continue   # already safe

            # Compute new SL that limits loss to max_loss_usd
            safe_distance = max_loss_usd / (per_point * float(p.volume))
            digits = int(si.digits)
            if is_buy:
                new_sl = round(entry - safe_distance, digits)
                # Never move SL past current price (would auto-trigger)
                tick = mt5.symbol_info_tick(p.symbol)
                if tick and new_sl >= float(tick.bid):
                    new_sl = round(float(tick.bid) - safe_distance * 0.1, digits)
                # Monotonic: only tighten (move CLOSER to entry, NOT past)
                if new_sl <= cur_sl: continue
            else:
                new_sl = round(entry + safe_distance, digits)
                tick = mt5.symbol_info_tick(p.symbol)
                if tick and new_sl <= float(tick.ask):
                    new_sl = round(float(tick.ask) + safe_distance * 0.1, digits)
                if new_sl >= cur_sl: continue

            ok, why = self._modify_sl(mt5, p, new_sl)
            if ok:
                tightened.append({
                    "ticket":  int(p.ticket),
                    "symbol":  p.symbol,
                    "old_sl":  round(cur_sl, digits),
                    "new_sl":  new_sl,
                    "old_max_loss": round(cur_max_loss, 2),
                    "new_max_loss": round(max_loss_usd, 2),
                })

        if tightened:
            emit_insight(self.name, "ACT",
                f"🛡 tightened SL on {len(tightened)} risky positions: "
                + ", ".join(f"{t['symbol']} ${t['old_max_loss']:.2f}→${t['new_max_loss']:.2f}"
                             for t in tightened[:3]),
                data={"tightened": tightened},
                action="sl_safety_tightened")
