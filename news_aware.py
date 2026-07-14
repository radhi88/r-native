"""news_aware.py — J.10 — Realistic backtest by skipping news-blackout bars.

Generic backtest pretends all bars are tradeable. Reality: prop firms block trading
±30min around high-impact news. So a backtest that opens 30 trades during NFP
inflates the win rate vs what you'd actually trade.

Used by ga_simulator and trade_gate to mark "skip this bar" minutes.

Loads news calendar from data/news_calendar.json (FF format).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

NEWS_PATH = Path(r"C:\Users\Radhi\MT5\friday_v3\data\news_calendar.json")


def _load_events() -> list[dict]:
    if not NEWS_PATH.exists(): return []
    try:
        d = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
        return d.get("events") if isinstance(d, dict) else (d or [])
    except Exception:
        return []


def _parse_ts(ts_raw) -> datetime | None:
    try:
        if isinstance(ts_raw, (int, float)):
            return datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
        if isinstance(ts_raw, str):
            d = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
            return d
    except Exception:
        return None


def relevant_events(symbol: str, impact: str = "high") -> list[dict]:
    """Return events that would affect `symbol` at requested `impact`."""
    s = symbol.upper().rstrip("M")
    cur_in_symbol = set()
    known_currs = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"]
    for k in known_currs:
        if k in s: cur_in_symbol.add(k)
    # XAU, BTC affected by USD news
    if any(x in s for x in ("XAU", "XAG", "BTC", "OIL", "US30", "USTEC", "US500")):
        cur_in_symbol.add("USD")
    out = []
    for ev in _load_events():
        imp = (ev.get("impact") or "").lower()
        if impact == "high" and imp not in ("high", "red", "3"): continue
        ev_cur = (ev.get("currency") or ev.get("country") or "").upper()
        if cur_in_symbol and ev_cur and ev_cur not in cur_in_symbol: continue
        ts = _parse_ts(ev.get("ts") or ev.get("time") or ev.get("date"))
        if ts is None: continue
        out.append({"ts": ts, "title": ev.get("title", "?"),
                    "currency": ev_cur, "impact": imp})
    return out


def is_blackout_bar(bar_ts: int, blackout_intervals: list[tuple],
                   minutes: int = 30) -> bool:
    """Check if a bar timestamp falls within any blackout window."""
    return any(start <= bar_ts <= end for (start, end) in blackout_intervals)


def build_blackout_intervals(symbol: str, minutes: int = 30) -> list[tuple]:
    """Pre-compute blackout intervals (in epoch seconds) for fast `is_blackout_bar`."""
    half = timedelta(minutes=minutes)
    intervals = []
    for ev in relevant_events(symbol):
        start = int((ev["ts"] - half).timestamp())
        end   = int((ev["ts"] + half).timestamp())
        intervals.append((start, end))
    return sorted(intervals)


def filter_bars(bars, symbol: str, minutes: int = 30):
    """Return a filtered bars array with news-blackout bars masked.
    Compatible with numpy structured array from mt5.copy_rates_*."""
    if bars is None or len(bars) == 0:
        return bars
    blackouts = build_blackout_intervals(symbol, minutes)
    if not blackouts:
        return bars
    # bars has dtype 'time' field — keep bars NOT in blackout
    mask = []
    bi = 0
    for b in bars:
        bt = int(b["time"])
        # advance blackout pointer
        while bi < len(blackouts) and blackouts[bi][1] < bt:
            bi += 1
        in_blackout = bi < len(blackouts) and \
                      blackouts[bi][0] <= bt <= blackouts[bi][1]
        mask.append(not in_blackout)
    import numpy as np
    return bars[np.array(mask, dtype=bool)]
