"""agents/session_pl_tracker.py — per-trading-session P/L breakdown.

Most genome systems perform unevenly across sessions: a genome trained
on London-session breakouts may bleed money during dead Asia hours.
Without per-session tracking the user can't see *when* the system
makes/loses money — just the cumulative result.

This agent walks the trailing 7 days of R-magic closes and groups
each trade's P/L by the session it CLOSED in:

  • Asia    — 00:00–08:00 UTC
  • London  — 08:00–16:00 UTC
  • NY      — 16:00–24:00 UTC

For each session, writes:
  - trade count, win count, win-rate
  - net P/L, best trade, worst trade
  - top + bottom symbol within that session

Output → data/r_native/session_pl.json (UI can render a 3-column card)

Emits a daily INFO summary at session rollover (00 UTC = NY close)
listing all three sessions side-by-side so the user sees on wake
which session is the cash cow vs the loser.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


OUT_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\session_pl.json")
R_MAGIC  = 20260605


class SessionPLTracker(Agent):
    name = "session_pl_tracker"
    description = "Per-session (Asia/London/NY) P/L breakdown over trailing 7 days"
    interval_seconds = 1800        # 30 min — sessions change slowly
    default_enabled = True

    LOOKBACK_DAYS = 7
    SESSION_BOUNDARIES = {
        "ASIA":   (0, 8),     # [start, end) in UTC hours
        "LONDON": (8, 16),
        "NY":     (16, 24),
    }
    DAILY_SUMMARY_HOUR_UTC = 0    # emit once when this hour ticks

    _last_summary_date: str = ""    # YYYY-MM-DD of last daily summary

    def _session_of(self, ts_utc: int) -> str:
        hr = datetime.fromtimestamp(ts_utc, tz=timezone.utc).hour
        for name, (lo, hi) in self.SESSION_BOUNDARIES.items():
            if lo <= hr < hi:
                return name
        return "ASIA"   # safety

    def tick(self):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): mt5.initialize()
        except Exception as e:
            emit_insight(self.name, "WARN", f"mt5 init err: {e}")
            return

        since = datetime.now() - timedelta(days=self.LOOKBACK_DAYS)
        try:
            deals = mt5.history_deals_get(since, datetime.now()) or []
        except Exception as e:
            emit_insight(self.name, "WARN", f"history_deals_get err: {e}")
            return

        # Only CLOSE deals with R magic — that's where the realized P/L is
        closes = [d for d in deals
                   if int(getattr(d, "magic", 0)) == R_MAGIC
                   and int(getattr(d, "entry", -1)) == 1]
        if not closes:
            return

        # Group by session
        by_sess = defaultdict(lambda: {
            "trades": 0, "wins": 0,
            "net_pl": 0.0, "best": 0.0, "worst": 0.0,
            "by_symbol": defaultdict(lambda: {"n": 0, "pl": 0.0}),
        })
        for d in closes:
            net = float(d.profit) + float(d.swap) + float(d.commission)
            sess = self._session_of(int(d.time))
            s = by_sess[sess]
            s["trades"] += 1
            if net > 0: s["wins"] += 1
            s["net_pl"] += net
            if net > s["best"]:  s["best"]  = net
            if net < s["worst"]: s["worst"] = net
            s["by_symbol"][d.symbol]["n"]  += 1
            s["by_symbol"][d.symbol]["pl"] += net

        # Finalize numbers + top/bottom symbol per session
        finalized = {}
        for sess, s in by_sess.items():
            wr = round(s["wins"] / max(1, s["trades"]) * 100, 1)
            sym_ranked = sorted(s["by_symbol"].items(),
                                 key=lambda kv: -kv[1]["pl"])
            top = ({"symbol": sym_ranked[0][0],
                    "pl":     round(sym_ranked[0][1]["pl"], 2),
                    "n":      sym_ranked[0][1]["n"]}
                   if sym_ranked else None)
            bot = ({"symbol": sym_ranked[-1][0],
                    "pl":     round(sym_ranked[-1][1]["pl"], 2),
                    "n":      sym_ranked[-1][1]["n"]}
                   if sym_ranked and len(sym_ranked) > 1 else None)
            finalized[sess] = {
                "trades":   s["trades"],
                "wins":     s["wins"],
                "win_rate": wr,
                "net_pl":   round(s["net_pl"], 2),
                "avg_pl":   round(s["net_pl"] / max(1, s["trades"]), 3),
                "best":     round(s["best"], 2),
                "worst":    round(s["worst"], 2),
                "top_symbol":    top,
                "bottom_symbol": bot,
            }

        out = {
            "lookback_days": self.LOOKBACK_DAYS,
            "sessions":      finalized,
            "updated_at":    datetime.now(timezone.utc).isoformat(),
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                             encoding="utf-8")

        # Daily summary at NY-close (00 UTC) — fire once per day
        now_utc = datetime.now(timezone.utc)
        today_str = now_utc.strftime("%Y-%m-%d")
        if (now_utc.hour == self.DAILY_SUMMARY_HOUR_UTC
                and today_str != self._last_summary_date):
            parts = []
            for sess in ("ASIA", "LONDON", "NY"):
                if sess not in finalized: continue
                f = finalized[sess]
                parts.append(f"{sess}: ${f['net_pl']:+.2f} ({f['trades']}t WR{f['win_rate']:.0f}%)")
            best_sess = max(finalized.items(), key=lambda kv: kv[1]["net_pl"],
                             default=(None, None))
            worst_sess = min(finalized.items(), key=lambda kv: kv[1]["net_pl"],
                              default=(None, None))
            tail = ""
            if best_sess[0] and worst_sess[0] and best_sess[0] != worst_sess[0]:
                tail = (f" · 🏆 best: {best_sess[0]} (${best_sess[1]['net_pl']:+.2f})"
                        f" · 🪦 worst: {worst_sess[0]} (${worst_sess[1]['net_pl']:+.2f})")
            emit_insight(self.name, "INFO",
                f"🕘 daily session summary ({self.LOOKBACK_DAYS}d): "
                + " | ".join(parts) + tail,
                data={"summary": finalized})
            self._last_summary_date = today_str
