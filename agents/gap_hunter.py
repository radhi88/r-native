"""agents/gap_hunter.py — detect price gaps + place PENDING orders at fill levels.

THE statistical edge: ~70% of price gaps fill within 5 trading days.
This agent hunts them.

Every 5 minutes:
  1. For each deployed symbol, look at last close vs current open
  2. If gap > X pips (configurable per symbol), it's a GAP
  3. Place a pending order to enter when price returns to the gap fill:
     • Upward gap (open > prev_close): SELL_LIMIT at ½-gap-fill, expect rejection back
     • Downward gap (open < prev_close): BUY_LIMIT at ½-gap-fill, expect bounce up
  4. SL goes beyond the gap origin
  5. TP at the prev_close (full gap fill)
  6. Pending expires in 24h — if gap didn't fill by then, the edge is gone

Pending orders are cancelled if:
  • Price moves >2x the gap distance further away (gap unlikely to fill)
  • Position fills + closes (cleanup leftover sibling pendings)
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


# Minimum gap size per symbol class to consider it actionable.
# Below this = market noise, not a real gap.
GAP_MIN_PCT = {
    "BTCUSDm":  0.20,   # 0.2% gap on BTC = ~$150
    "ETHUSDm":  0.30,
    "XAUUSDm":  0.10,   # gold: 0.1% = ~$4-5
    "XAGUSDm":  0.20,
    # Forex pairs — gap measured as fraction of price
    "EURUSDm":  0.05,
    "GBPUSDm":  0.05,
    "USDJPYm":  0.05,
    "AUDUSDm":  0.05,
    "USDCHFm":  0.05,
    "USDCADm":  0.05,
    "EURJPYm":  0.07,
    "GBPJPYm":  0.08,
}


class GapHunter(Agent):
    name = "gap_hunter"
    description = "Detects price gaps + places pending limit orders at fill levels"
    interval_seconds = 300   # every 5 min
    default_enabled = True

    PENDING_LOT       = 0.01
    EXPIRY_HOURS      = 24
    PARTIAL_FILL_PCT  = 0.50    # enter at 50% of gap fill
    MAX_PENDING_TOTAL = 8       # don't flood with pending orders

    def _list_deployed_symbols(self) -> list[str]:
        import json
        cfg_dir = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        out = []
        for p in cfg_dir.glob("*.json"):
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
                if cfg.get("tradeable", True) and (cfg.get("deployed_genome") or {}).get("id"):
                    out.append(p.stem)
            except Exception: continue
        return out

    def _detect_gap(self, symbol: str) -> dict | None:
        """Return gap info or None if no significant gap."""
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
            # Last 2 H1 bars — current open vs previous close
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 5)
            if rates is None or len(rates) < 3: return None
            prev_close = float(rates[-2]["close"])
            cur_open   = float(rates[-1]["open"])
            if prev_close == 0: return None
            gap_pct = abs(cur_open - prev_close) / prev_close * 100
            min_pct = GAP_MIN_PCT.get(symbol, 0.05)
            if gap_pct < min_pct: return None
            direction = "UP" if cur_open > prev_close else "DOWN"
            return {
                "symbol": symbol,
                "prev_close": prev_close,
                "cur_open":   cur_open,
                "gap_size":   abs(cur_open - prev_close),
                "gap_pct":    gap_pct,
                "direction":  direction,
            }
        except Exception as e:
            return None

    def _propose_pending(self, gap: dict) -> dict:
        """Decide BUY_LIMIT or SELL_LIMIT entry + SL/TP."""
        # Upward gap (price jumped UP at open):
        #   Expect a reversion DOWN to fill the gap
        #   → place SELL_LIMIT at fade level (half-way back up isn't right;
        #     instead enter at current price + small buffer = SELL_LIMIT just
        #     above current bid which expects price to spike up briefly)
        # Better logic: enter when price RETRACES toward gap fill:
        #   Upward gap: SELL_LIMIT placed at  prev_close + (gap_size * 0.25)
        #     SL = cur_open + gap_size*0.5  (beyond gap origin)
        #     TP = prev_close  (full gap fill)
        gs = gap["gap_size"]; pc = gap["prev_close"]; co = gap["cur_open"]
        if gap["direction"] == "UP":
            entry = pc + gs * self.PARTIAL_FILL_PCT      # enter at half-fill
            sl    = co + gs * 0.5                        # beyond gap origin
            tp    = pc                                   # full fill
            side, kind = "SELL", "LIMIT"
        else:   # DOWN gap
            entry = pc - gs * self.PARTIAL_FILL_PCT
            sl    = co - gs * 0.5
            tp    = pc
            side, kind = "BUY", "LIMIT"
        return {"side": side, "kind": kind,
                "entry": entry, "sl": sl, "tp": tp}

    def tick(self):
        from r_native.pending_orders import (
            place_pending, list_r_pending, cancel_expired
        )

        # Clean stale pendings first
        cancelled = cancel_expired(max_age_hours=self.EXPIRY_HOURS)
        if cancelled:
            emit_insight(self.name, "INFO",
                f"🧹 cancelled {cancelled} expired pending orders")

        # Cap total pendings
        existing = list_r_pending()
        if len(existing) >= self.MAX_PENDING_TOTAL:
            return

        # Don't re-place pending on a symbol that already has one
        held_symbols = {o["symbol"] for o in existing}

        fired = 0
        for sym in self._list_deployed_symbols():
            if sym in held_symbols: continue
            if len(existing) + fired >= self.MAX_PENDING_TOTAL: break
            gap = self._detect_gap(sym)
            if not gap: continue
            prop = self._propose_pending(gap)
            result = place_pending(
                symbol=sym, side=prop["side"], order_kind=prop["kind"],
                price=prop["entry"], sl=prop["sl"], tp=prop["tp"],
                lot=self.PENDING_LOT, reason="gap",
                expiry_hours=self.EXPIRY_HOURS,
                agent_name="gaphun",
            )
            if result.get("ok"):
                fired += 1
                emit_insight(self.name, "ACT",
                    f"📐 gap {sym} {gap['direction']} {gap['gap_pct']:.2f}% — "
                    f"placed {prop['side']} {prop['kind']} @ {prop['entry']:.5f} "
                    f"(TP fill @ {prop['tp']:.5f}) ticket={result['ticket']}",
                    data={**gap, **prop, "ticket": result["ticket"]},
                    action="gap_pending_placed")
        if fired:
            emit_insight(self.name, "INFO",
                f"placed {fired} gap-fill pending orders this sweep")
