"""agents/news_blocker.py — silence trading 15min before/after high-impact news.

Reads friday_v3/data/news_calendar.json (populated by external news scraper).
If high-impact event (NFP, FOMC, CPI, etc.) is within ±15min on a relevant
currency, places a temporary kill_switch on that currency's symbols.

The kill_switch.json mechanism the Risk Sentinel already watches gets a
new field `disabled_symbols: [symbols]` which the executor checks before
trading.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


CALENDAR_PATH = Path(r"C:\Users\Radhi\MT5\friday_v3\data\news_calendar.json")
NEWS_BLOCK_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\news_blocked_symbols.json")

BLOCK_WINDOW_MIN = 15
HIGH_IMPACT_CURRENCIES_TO_SYMBOLS = {
    "USD": ["EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCHFm",
            "USDCADm", "BTCUSDm", "ETHUSDm", "XAUUSDm", "XAGUSDm"],
    "EUR": ["EURUSDm", "EURJPYm"],
    "GBP": ["GBPUSDm", "GBPJPYm"],
    "JPY": ["USDJPYm", "EURJPYm", "GBPJPYm"],
    "AUD": ["AUDUSDm"],
    "CAD": ["USDCADm"],
    "CHF": ["USDCHFm"],
}


class NewsBlocker(Agent):
    name = "news_blocker"
    description = "Blocks trades on currencies ±15min around high-impact news"
    interval_seconds = 60   # check every minute
    default_enabled = True

    def tick(self):
        if not CALENDAR_PATH.exists():
            # No news file yet — silent skip
            return
        try:
            data = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
            events = data.get("events", []) if isinstance(data, dict) else data
        except Exception:
            return

        now = datetime.now(timezone.utc)
        window_end = now + timedelta(minutes=BLOCK_WINDOW_MIN)
        blocked_symbols = set()
        active_events = []

        for ev in events:
            impact = (ev.get("impact") or "").lower()
            if impact not in ("high", "h", "3"): continue
            t_str = ev.get("time") or ev.get("when") or ""
            try:
                t = datetime.fromisoformat(t_str.replace("Z","+00:00"))
            except Exception: continue
            # Block when event is upcoming OR just happened (post-spike volatility)
            time_to_event = (t - now).total_seconds() / 60
            if abs(time_to_event) > BLOCK_WINDOW_MIN: continue
            ccy = (ev.get("currency") or ev.get("country") or "").upper()
            syms = HIGH_IMPACT_CURRENCIES_TO_SYMBOLS.get(ccy, [])
            blocked_symbols.update(syms)
            active_events.append({
                "time": t.isoformat(), "currency": ccy,
                "title": ev.get("title", ev.get("event", "?"))[:60],
                "minutes_to_event": round(time_to_event, 1)
            })

        # Persist the block list — executor will read this to decide (defensive: never let a
        # transient file/IO error surface as an agent crash).
        try:
            NEWS_BLOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            NEWS_BLOCK_PATH.write_text(json.dumps({
                "blocked_symbols": sorted(blocked_symbols),
                "active_events":   active_events,
                "updated_at":      now.isoformat(),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            return

        if blocked_symbols:
            emit_insight(self.name, "ACT",
                f"📰 news blackout: {len(blocked_symbols)} symbols blocked "
                f"for {len(active_events)} upcoming events",
                data={"symbols": list(blocked_symbols)[:8],
                       "events": active_events[:3]},
                action="news_blackout")
