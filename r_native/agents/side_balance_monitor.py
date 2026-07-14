"""agents/side_balance_monitor.py — surface BUY/SELL imbalance.

Detected in cycle 5 audit: in the trailing 24h, 23 of 24 trades opened
were SELL — a 96% SELL rate. The signal evaluators are symmetric so
this comes from genuinely bearish markets, but it ALSO means we're
starving every BUY-side genome of evaluation data (Monster qualification
needs ≥3 BUY trades per genome, currently impossible).

This agent:
  • Every hour, counts R-magic OPEN deals by side over the last 24h
  • Computes BUY%, SELL%, and per-symbol breakdown
  • Writes data/r_native/side_balance.json
  • Emits WARN if BUY% < BUY_FLOOR_PCT for two consecutive ticks (~2h)
    — that's structural imbalance worth surfacing to the user
  • Emits INFO summary every 12h regardless (so the user always has
    a recent baseline number to look at)
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


OUT_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\side_balance.json")
R_MAGIC  = 20260605


class SideBalanceMonitor(Agent):
    name = "side_balance_monitor"
    description = "Tracks BUY/SELL ratio over 24h; flags structural imbalance"
    interval_seconds = 3600     # hourly
    default_enabled = True

    BUY_FLOOR_PCT = 15.0    # < 15% BUY for 2 ticks → WARN
    LOOKBACK_HOURS = 24

    _consecutive_low_buy_ticks: int = 0
    _last_summary_ts: float = 0.0
    SUMMARY_EVERY_SECONDS = 12 * 3600   # 12h INFO summary cadence

    def tick(self):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
        except Exception as e:
            emit_insight(self.name, "WARN", f"mt5 init failed: {e}")
            return

        since = datetime.now() - timedelta(hours=self.LOOKBACK_HOURS)
        try:
            deals = mt5.history_deals_get(since, datetime.now()) or []
        except Exception as e:
            emit_insight(self.name, "WARN", f"history_deals_get err: {e}")
            return

        opens = [d for d in deals
                 if int(getattr(d, "magic", 0)) == R_MAGIC
                 and int(getattr(d, "entry", -1)) == 0]
        total = len(opens)
        if total == 0:
            return     # no data, no insight (don't fire on empty)

        buys  = sum(1 for d in opens if int(d.type) == 0)
        sells = sum(1 for d in opens if int(d.type) == 1)
        buy_pct  = round(buys  / total * 100, 1)
        sell_pct = round(sells / total * 100, 1)

        # Per-symbol breakdown
        by_sym = Counter()
        for d in opens:
            side = "BUY" if int(d.type) == 0 else "SELL"
            by_sym[(d.symbol, side)] += 1
        symbol_breakdown = {}
        for (sym, side), n in sorted(by_sym.items()):
            symbol_breakdown.setdefault(sym, {"BUY": 0, "SELL": 0})[side] = n

        out = {
            "lookback_hours": self.LOOKBACK_HOURS,
            "total":          total,
            "buy_count":      buys,
            "sell_count":     sells,
            "buy_pct":        buy_pct,
            "sell_pct":       sell_pct,
            "by_symbol":      symbol_breakdown,
            "updated_at":     datetime.now(timezone.utc).isoformat(),
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                             encoding="utf-8")

        # ── WARN: persistent imbalance ──
        if buy_pct < self.BUY_FLOOR_PCT:
            self._consecutive_low_buy_ticks += 1
            if self._consecutive_low_buy_ticks >= 2:
                emit_insight(self.name, "WARN",
                    f"⚖ structural imbalance — only {buy_pct}% BUY across "
                    f"{total} trades / {self.LOOKBACK_HOURS}h. "
                    f"Monster qualification stalled (need ≥3 BUY per genome). "
                    f"Consider GA refresh with breeder.",
                    data=out)
                self._consecutive_low_buy_ticks = 0   # require 2 more ticks
        else:
            self._consecutive_low_buy_ticks = 0

        # ── INFO: 12h cadence summary ──
        import time as _t
        now_s = _t.time()
        if (now_s - self._last_summary_ts) >= self.SUMMARY_EVERY_SECONDS:
            top_syms = sorted(symbol_breakdown.items(),
                               key=lambda kv: -(kv[1]["BUY"] + kv[1]["SELL"]))[:5]
            sym_str = " · ".join(
                f"{s}({d['BUY']}B/{d['SELL']}S)" for s, d in top_syms)
            emit_insight(self.name, "INFO",
                f"📊 side balance 24h: {buy_pct}% BUY / {sell_pct}% SELL "
                f"({total} trades). Top: {sym_str}",
                data={"summary": out})
            self._last_summary_ts = now_s
