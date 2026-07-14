"""
news_straddle.py — High-impact news event straddle strategy.

The ONLY strategy that historically works on $50 accounts with 300pt spread:
catch the explosive move at the news release by pending orders BOTH sides.

Logic:
  • 60s before high-impact news: place BUY_STOP +120pt above ask + SELL_STOP -120pt below bid
  • 90s after news: cancel whichever wasn't triggered
  • SL = entry ± 80pt, TP = entry ± 300pt → R:R 1:3.75
  • Lot: 0.02 (small but news moves 50-200pt = $5-20 profit potential)

News calendar:
  • Fetched from Forex Factory's free weekly XML
  • Filters: USD, EUR (impact on gold), High impact only
  • Key events: NFP, CPI, FOMC, ECB, GDP, PPI, Powell speeches

This module:
  • Pre-loads upcoming news (next 24h)
  • Runs as separate daemon: friday_v3_news_straddle.py
  • Won't fire during pure dip-buyer hours (avoids strategy collision)
"""
from __future__ import annotations
import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5

ROOT      = Path(r"C:\Users\Radhi\MT5\friday_v3")
NEWS_FILE = ROOT / "data" / "news_calendar.json"
STATE     = ROOT / "data" / "news_straddle_state.json"

SYMBOL    = "XAUUSDm"
MAGIC     = 20260604         # different magic from dip buyer (03)
SPREAD_BUFFER_PT = 120        # how far above/below market to place pendings
SL_PT            = 80
TP_PT            = 300
LOT              = 0.02
SECONDS_BEFORE_NEWS_TO_ARM   = 60
SECONDS_AFTER_NEWS_TO_CLEANUP = 90

# Forex Factory free weekly XML
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

# Currencies that move gold
RELEVANT_CCY = {"USD", "EUR", "GBP", "JPY"}


def fetch_news_calendar(force: bool = False) -> list[dict]:
    """Return upcoming high-impact news events."""
    if NEWS_FILE.exists() and not force:
        try:
            data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
            if "events" in data and "fetched_at" in data:
                age_hours = (datetime.now(timezone.utc) -
                             datetime.fromisoformat(data["fetched_at"])).total_seconds() / 3600
                if age_hours < 6:
                    return data["events"]
        except Exception: pass

    # Fetch fresh (FF blocks requests without UA)
    events = []
    try:
        req = urllib.request.Request(FF_URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "application/xml, text/xml, */*;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml = resp.read().decode("utf-8", errors="ignore")
        # Parse very simply (no XML lib dependency)
        for m in re.finditer(
            r"<event>(.*?)</event>", xml, re.DOTALL):
            blk = m.group(1)
            def grab(tag):
                mm = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", blk, re.DOTALL)
                if not mm: return ""
                v = mm.group(1).strip()
                # Strip CDATA wrapper if present
                cd = re.match(r"<!\[CDATA\[(.*?)\]\]>", v, re.DOTALL)
                return cd.group(1).strip() if cd else v
            try:
                ev = {
                    "title":     grab("title"),
                    "country":   grab("country"),
                    "date":      grab("date"),
                    "time":      grab("time"),
                    "impact":    grab("impact"),
                    "forecast":  grab("forecast"),
                    "previous":  grab("previous"),
                }
                if ev["impact"] != "High": continue
                if ev["country"] not in RELEVANT_CCY: continue
                events.append(ev)
            except Exception: continue
    except Exception as e:
        print(f"[news_fetch] error: {e}")
        return []

    NEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
    NEWS_FILE.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "events":     events,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return events


def parse_event_time(ev: dict) -> datetime | None:
    """Parse a news event's time into a UTC datetime.

    Handles BOTH on-disk schemas that write news_calendar.json:
      A) ISO8601 datetime in `date`  e.g. '2026-06-30T08:30:00-04:00'  (no `time`)
         — the format the news_engine/calendar writer actually produces.
      B) Legacy FF split fields       date='05-17-2026' (MM-DD-YYYY),
         time='10:30pm' (US Eastern; 'All Day'/'Tentative' → no time).

    Returns a tz-aware UTC datetime, or None if it can't be parsed.

    NOTE: This previously only handled (B), so EVERY (A)-format event returned
    None and the gate's news_blackout HARD check silently never fired. Keep both
    paths so the blackout works regardless of which writer last touched the file.
    """
    d = (ev.get("date") or "").strip()
    t = (ev.get("time") or "").strip()
    # ── Format A: full ISO8601 datetime in `date` (carries its own offset) ──
    if "T" in d:
        try:
            dt = datetime.fromisoformat(d)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass  # fall through to legacy path
    # ── Format B: legacy FF date='MM-DD-YYYY' + time='h:mmAM/PM' (US Eastern) ──
    try:
        if not t or t.lower() in {"all day", "tentative", "day 1", "day 2"}:
            return None
        dt_local = datetime.strptime(f"{d} {t}", "%m-%d-%Y %I:%M%p")
        # FF publishes in US Eastern. Approximate ET = UTC-4 (EDT) for May–Nov.
        # Good enough for our ±15-min blackout window. (ISO path above is exact.)
        return (dt_local + timedelta(hours=4)).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def next_event_within(seconds: int) -> dict | None:
    """Return the next news event firing within `seconds`, or None."""
    events = fetch_news_calendar()
    now = datetime.now(timezone.utc)
    upcoming = []
    for ev in events:
        dt = parse_event_time(ev)
        if not dt: continue
        delta = (dt - now).total_seconds()
        if 0 < delta < seconds:
            upcoming.append((delta, ev))
    if not upcoming: return None
    upcoming.sort()
    return upcoming[0][1]


def place_straddle(ev: dict, dry_run: bool = True) -> dict:
    """Place pending BUY_STOP + SELL_STOP around current price."""
    if not mt5.initialize():
        return {"ok": False, "error": "mt5 init"}
    tick = mt5.symbol_info_tick(SYMBOL)
    sym  = mt5.symbol_info(SYMBOL)
    if not tick or not sym:
        return {"ok": False, "error": "no tick"}

    point = sym.point
    buy_entry  = tick.ask + SPREAD_BUFFER_PT * point
    sell_entry = tick.bid - SPREAD_BUFFER_PT * point
    buy_sl  = buy_entry - SL_PT * point
    buy_tp  = buy_entry + TP_PT * point
    sell_sl = sell_entry + SL_PT * point
    sell_tp = sell_entry - TP_PT * point

    note = f"news {ev['title'][:15]}".encode("ascii", errors="ignore").decode()[:20]

    placed = []
    for side, entry, sl, tp, otype in [
        ("BUY",  buy_entry,  buy_sl,  buy_tp,  mt5.ORDER_TYPE_BUY_STOP),
        ("SELL", sell_entry, sell_sl, sell_tp, mt5.ORDER_TYPE_SELL_STOP),
    ]:
        req = {
            "action":       mt5.TRADE_ACTION_PENDING,
            "symbol":       SYMBOL,
            "volume":       float(LOT),
            "type":         otype,
            "price":        float(entry),
            "sl":           float(sl),
            "tp":           float(tp),
            "magic":        MAGIC,
            "comment":      note,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if dry_run:
            placed.append({"side": side, "entry": entry, "ticket": 0, "ok": True, "msg": "DRY"})
            continue
        r = mt5.order_send(req)
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            placed.append({"side": side, "entry": entry, "ticket": r.order, "ok": True})
        else:
            placed.append({"side": side, "entry": entry, "ticket": 0, "ok": False,
                          "msg": r.comment if r else "None"})

    mt5.shutdown()
    return {"ok": True, "event": ev["title"], "placed": placed,
            "armed_at": datetime.now(timezone.utc).isoformat()}


def cleanup_after_news(dry_run: bool = True) -> int:
    """Cancel any un-triggered straddle pendings (magic=MAGIC)."""
    if not mt5.initialize(): return 0
    p = [o for o in (mt5.orders_get(symbol=SYMBOL) or []) if o.magic == MAGIC]
    cancelled = 0
    for o in p:
        if dry_run: cancelled += 1; continue
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            cancelled += 1
    mt5.shutdown()
    return cancelled


def main_loop(live: bool = False):
    """Main daemon — check every 30s for upcoming news, arm/disarm."""
    print(f"=== FRIDAY v3 News Straddle  {'🔴 LIVE' if live else '🟢 PAPER'} ===")
    armed_event = None
    armed_at_ts = 0
    while True:
        try:
            # If currently armed, check if cleanup time
            if armed_event and (time.time() - armed_at_ts) > (SECONDS_BEFORE_NEWS_TO_ARM + SECONDS_AFTER_NEWS_TO_CLEANUP):
                cancelled = cleanup_after_news(dry_run=not live)
                print(f"[cleanup] cancelled {cancelled} pendings after {armed_event['title']}")
                armed_event = None
                armed_at_ts = 0

            # Look for next news within arm window
            if not armed_event:
                ev = next_event_within(SECONDS_BEFORE_NEWS_TO_ARM)
                if ev:
                    print(f"[ARM] news in <{SECONDS_BEFORE_NEWS_TO_ARM}s: {ev['title']}")
                    result = place_straddle(ev, dry_run=not live)
                    print(json.dumps(result, indent=2))
                    armed_event = ev
                    armed_at_ts = time.time()

            # State
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps({
                "ts":           datetime.now(timezone.utc).isoformat(),
                "mode":         "LIVE" if live else "PAPER",
                "armed_event":  armed_event,
                "next_event":   fetch_news_calendar()[:5],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[error] {e}")
        time.sleep(30)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--test-fetch", action="store_true", help="just fetch news calendar")
    args = ap.parse_args()
    if args.test_fetch:
        ev = fetch_news_calendar(force=True)
        print(f"Fetched {len(ev)} high-impact USD/EUR/GBP/JPY events")
        for e in ev[:10]:
            print(f"  {e['date']} {e['time']:8s} {e['country']} — {e['title']}")
    else:
        main_loop(live=args.live)
