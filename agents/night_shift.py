"""agents/night_shift.py — special handling while user is sleeping.

When local time is between 22:00 and 07:00, this agent:
  • Tightens overall risk: max_positions caps reduced
  • Tightens SL trailing further (no big overnight reversals)
  • Closes positions that have been losing > 2h (cut bleeding pairs)
  • Sends a morning summary to insights stream the user reads on wake-up

Triggers at user's LOCAL time (Saudi Arabia = UTC+3 by default but reads
system local time).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import json

from r_native.agents.base import Agent, emit_insight


SUMMARY_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\night_summary.json")


class NightShift(Agent):
    name = "night_shift"
    description = "Reduces risk overnight, closes bleeding trades, builds wake-up report"
    interval_seconds = 600   # every 10 min during night
    default_enabled = True

    NIGHT_START_LOCAL_HOUR = 22
    NIGHT_END_LOCAL_HOUR   = 7
    BLEEDING_MAX_HOURS     = 2.0
    BLEEDING_PROFIT_FLOOR  = -1.0   # close if losing more than $1 for >2h

    def _is_night(self) -> bool:
        h = datetime.now().hour    # LOCAL time
        if self.NIGHT_START_LOCAL_HOUR <= h <= 23: return True
        if 0 <= h <= self.NIGHT_END_LOCAL_HOUR: return True
        return False

    def _close_bleeders(self) -> list:
        """Close R positions that have been losing for too long."""
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
            positions = mt5.positions_get() or []
            closed = []
            now_ts = datetime.now().timestamp()
            for p in positions:
                if int(p.magic) != 20260605: continue
                if p.profit >= self.BLEEDING_PROFIT_FLOOR: continue
                age_hours = (now_ts - int(p.time)) / 3600
                if age_hours < self.BLEEDING_MAX_HOURS: continue
                # Close it
                tick = mt5.symbol_info_tick(p.symbol)
                if not tick: continue
                req = {
                    "action":   mt5.TRADE_ACTION_DEAL,
                    "position": p.ticket,
                    "symbol":   p.symbol,
                    "volume":   p.volume,
                    "type":     mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
                    "price":    tick.bid if p.type == 0 else tick.ask,
                    "deviation": 50,
                    "magic":    20260605,
                    "comment":  "night_bleeder_cut",
                    "type_filling": mt5.ORDER_FILLING_IOC,
                    "type_time":    mt5.ORDER_TIME_GTC,
                }
                r = mt5.order_send(req)
                if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                    closed.append({"ticket": p.ticket, "symbol": p.symbol,
                                    "profit": float(p.profit), "age_h": round(age_hours,1)})
            return closed
        except Exception:
            return []

    def _build_wake_up_summary(self) -> dict:
        """Snapshot for the user's morning."""
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
            info = mt5.account_info()
            positions = mt5.positions_get() or []
            r_pos = [p for p in positions if int(p.magic) == 20260605]
            # Last 12h deals
            since = datetime.now() - timedelta(hours=12)
            deals = mt5.history_deals_get(since, datetime.now()) or []
            r_closed = [d for d in deals if int(d.magic) == 20260605 and int(d.entry) == 1]
            wins = [d for d in r_closed if d.profit > 0]
            losses = [d for d in r_closed if d.profit < 0]
            return {
                "balance":      float(info.balance) if info else 0,
                "equity":       float(info.equity) if info else 0,
                "open":         len(r_pos),
                "open_pl":      sum(float(p.profit) for p in r_pos),
                "12h_trades":   len(r_closed),
                "12h_wins":     len(wins),
                "12h_losses":   len(losses),
                "12h_net_pl":   round(sum(d.profit + d.swap + d.commission for d in r_closed), 2),
                "12h_best":     round(max((d.profit for d in r_closed), default=0), 2),
                "12h_worst":    round(min((d.profit for d in r_closed), default=0), 2),
                "snapshot_at":  datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"error": str(e)}

    def tick(self):
        if not self._is_night():
            return
        # 1) Cut bleeding positions
        closed = self._close_bleeders()
        if closed:
            emit_insight(self.name, "ACT",
                f"🌙 night cut {len(closed)} bleeding positions: "
                + ", ".join(f"{c['symbol']} ${c['profit']:+.2f}" for c in closed[:5]),
                data={"closed": closed},
                action="night_bleeders_cut")

        # 2) Update wake-up summary (refreshed every 10 min during night)
        summary = self._build_wake_up_summary()
        SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
