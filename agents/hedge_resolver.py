"""agents/hedge_resolver.py — close redundant BUY+SELL hedge pairs.

PROBLEM observed (cycle 29): volatility_hunter's 4-order grid
(breakout stops + reversion limits) sometimes fires BOTH legs when
price moves through them both. Result: same symbol, opposite sides,
guaranteed to cancel net pnl while paying spread×2 plus swap.

Example caught at cycle 29:
  GBPJPYm SELL +\$0.16 (vol_s — breakout SELL_STOP triggered)
  GBPJPYm BUY  -\$0.30 (vol_r — reversion BUY_LIMIT triggered)

Anti-hedge in executor only catches direct entries (try_enter_trade
checks). Broker-filled pending orders bypass it.

This agent runs every 60s and:
  • Groups R-magic positions by symbol
  • For each symbol with both BUY and SELL open:
      net_pl = sum of all positions on that symbol
      if both sides are losing OR net_pl < -$0.30:
        close BOTH sides — eliminates the wasteful hedge
      if one side is profitable AND total net > +$0.30:
        keep the profitable side, close the loser
        (lets winner run, kills the dead weight)

Safety: only acts on R-magic. Soft-fails. Won't touch positions
< 10 min old (give them a chance to diverge).
"""
from __future__ import annotations

from datetime import datetime
from collections import defaultdict

from r_native.agents.base import Agent, emit_insight


R_MAGIC = 20260605


class HedgeResolver(Agent):
    name = "hedge_resolver"
    description = "Detects opposite-side same-symbol hedges and closes them"
    interval_seconds = 60       # check every minute
    default_enabled = True

    MIN_AGE_MIN          = 10.0   # give 10 min for legs to diverge
    NET_LOSS_TRIGGER     = -0.30   # net pnl ≤ -$0.30 = close both
    KEEP_WINNER_NET_FLOOR = 0.30  # net pnl ≥ +$0.30 = keep winner, kill loser

    def _close_position(self, mt5, p, reason: str = "hedge_resolved") -> bool:
        tick = mt5.symbol_info_tick(p.symbol)
        if not tick: return False
        req = {
            "action":   mt5.TRADE_ACTION_DEAL,
            "position": int(p.ticket),
            "symbol":   p.symbol,
            "volume":   p.volume,
            "type":     mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
            "price":    tick.bid if p.type == 0 else tick.ask,
            "deviation": 50,
            "magic":    R_MAGIC,
            "comment":  reason[:31],
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        try:
            r = mt5.order_send(req)
            return bool(r and r.retcode == 10009)
        except Exception:
            return False

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
        if len(r_positions) < 2: return

        # Group by symbol
        by_sym = defaultdict(list)
        now_ts = datetime.now().timestamp()
        for p in r_positions:
            age_min = (now_ts - int(p.time)) / 60
            by_sym[p.symbol].append({
                "pos": p,
                "side": "BUY" if int(p.type) == 0 else "SELL",
                "pl": float(p.profit),
                "age_min": age_min,
            })

        actions = []
        for sym, items in by_sym.items():
            sides = {x["side"] for x in items}
            if "BUY" not in sides or "SELL" not in sides:
                continue   # no hedge — single direction
            # Both sides exist — this is a hedge
            # Check ages: skip if any leg is too fresh (might diverge)
            min_age = min(x["age_min"] for x in items)
            if min_age < self.MIN_AGE_MIN: continue
            net_pl = sum(x["pl"] for x in items)
            buy_pl  = sum(x["pl"] for x in items if x["side"] == "BUY")
            sell_pl = sum(x["pl"] for x in items if x["side"] == "SELL")

            if net_pl >= self.KEEP_WINNER_NET_FLOOR:
                # We're net-positive — close the losing side, keep the winner
                losing_side = "BUY" if buy_pl < sell_pl else "SELL"
                killed_n = 0
                for x in items:
                    if x["side"] != losing_side: continue
                    if self._close_position(mt5, x["pos"], "hedge_kill_loser"):
                        killed_n += 1
                if killed_n:
                    actions.append(f"{sym}: kept {('SELL' if losing_side=='BUY' else 'BUY')} "
                                    f"(net ${net_pl:+.2f}), closed {killed_n} {losing_side}")
            elif net_pl <= self.NET_LOSS_TRIGGER:
                # Both sides bleeding — close all of them
                killed_n = 0
                for x in items:
                    if self._close_position(mt5, x["pos"], "hedge_full_close"):
                        killed_n += 1
                if killed_n:
                    actions.append(f"{sym}: closed both ({killed_n} positions, net ${net_pl:+.2f})")
            # else: roughly flat, let them ride

        if actions:
            emit_insight(self.name, "ACT",
                f"🪢 resolved {len(actions)} hedge(s): " + " | ".join(actions),
                data={"resolved": actions}, action="hedges_resolved")
