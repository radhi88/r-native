"""sentiment_feed.py — retail-sentiment context via ApeWisdom (free, no key).

ApeWisdom scrapes WallStreetBets, r/CryptoCurrency, StockTwits etc. and
exposes a 24h leaderboard of the most-mentioned tickers + sentiment %.

Endpoint:  https://apewisdom.io/api/v1.0/filter/{filter}/page/1
Filters we use:
  - "all-stocks"   — broad equity sentiment (S&P proxy)
  - "all-crypto"   — crypto sentiment (BTC / ETH alignment)
  - "wallstreetbets" — risk appetite gauge

What we extract per symbol of interest (BTC, ETH, SPY, GLD, ...):
  - mentions     : 24h mention count
  - mentions_24h_change : delta vs 24h ago  (positive → growing chatter)
  - sentiment    : 0..100 bullish %         (>60 bullish, <40 bearish)
  - upvotes      : raw upvote total

Cached 30 min on disk; in-memory cache shared with macro snapshot pattern.

Public API:
  get_sentiment_snapshot(force=False) → dict
  sentiment_signal_align(snap)        → (vote, reason)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import urllib.request as _ur
import urllib.error as _ue

CACHE_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\sentiment_snapshot.json")
CACHE_TTL_SEC = 1800  # 30 min

_AW_URL  = "https://apewisdom.io/api/v1.0/filter/{flt}/page/1"
_FILTERS = ("all-stocks", "all-crypto", "wallstreetbets")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Map our trading symbols → tickers the sentiment feeds use
_SYM_MAP = {
    "BTCUSD":  ["BTC", "BTC.X", "BITCOIN", "BTC-USD"],
    "ETHUSD":  ["ETH", "ETH.X", "ETHEREUM", "ETH-USD"],
    "XAUUSD":  ["GLD", "GOLD"],
    "USTEC":   ["QQQ", "NASDAQ", "NDX"],
    "US500":   ["SPY", "SPX"],
    "US30":    ["DIA", "DJI"],
}

_IN_MEMORY: dict = {}


def _fetch_filter(flt: str) -> Optional[list]:
    try:
        req = _ur.Request(_AW_URL.format(flt=flt),
                          headers={"User-Agent": _UA, "Accept": "application/json"})
        with _ur.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
        return data.get("results") or []
    except (_ue.URLError, _ue.HTTPError, OSError, ValueError):
        return None


def get_sentiment_snapshot(force: bool = False) -> dict:
    """Pull sentiment leaderboards, build a per-ticker lookup."""
    global _IN_MEMORY
    now = time.time()
    if not force and _IN_MEMORY and (now - _IN_MEMORY.get("_ts", 0) < CACHE_TTL_SEC):
        return _IN_MEMORY
    if not force and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if now - cached.get("_ts", 0) < CACHE_TTL_SEC:
                _IN_MEMORY = cached
                return cached
        except Exception: pass

    out = {"_ts": now, "issued_at": datetime.now(timezone.utc).isoformat(),
           "tickers": {}, "filters": {}}

    for flt in _FILTERS:
        rows = _fetch_filter(flt)
        if not rows: continue
        # Filter-level meta
        out["filters"][flt] = {"row_count": len(rows)}
        for r in rows[:50]:  # top 50 per filter is plenty
            tick = (r.get("ticker") or "").upper()
            if not tick: continue
            try:
                mentions   = int(r.get("mentions") or 0)
                upvotes    = int(r.get("upvotes") or 0)
                changed    = int(r.get("mentions_24h_ago") or 0)
                delta      = mentions - changed
            except (TypeError, ValueError):
                continue

            sent_str = r.get("sentiment")
            try:
                sent = float(sent_str) if sent_str is not None else None
            except (TypeError, ValueError):
                sent = None

            # Keep highest-mention entry across filters
            prev = out["tickers"].get(tick)
            if prev and prev.get("mentions", 0) >= mentions: continue
            out["tickers"][tick] = {
                "mentions":  mentions,
                "delta_24h": delta,
                "sentiment": sent,
                "upvotes":   upvotes,
                "filter":    flt,
            }

    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception: pass

    _IN_MEMORY = out
    return out


def _lookup_symbol_sentiment(symbol: str, snap: dict) -> Optional[dict]:
    """Find the sentiment row for our trading symbol (best of mapped tickers).

    Tries exact base (BTCUSDM), then progressively truncated prefixes
    (BTCUSD, BTCUS, BTCU, BTC, …) against `_SYM_MAP`. This handles broker
    suffixes like 'm', '.a', '_x100m' without per-symbol whitelisting.
    """
    if not symbol: return None
    base = ""
    for c in symbol.upper():
        if c.isalpha() or c.isdigit(): base += c
        else: break

    candidates: list = []
    # Progressive prefix match against the map (longest first)
    for n in range(len(base), 2, -1):
        prefix = base[:n]
        mapped = _SYM_MAP.get(prefix)
        if mapped:
            candidates.extend(mapped)
            break
    # Also try the raw base + any prefix as a literal ticker
    candidates.extend([base, base[:6], base[:5], base[:4], base[:3]])

    tickers = snap.get("tickers", {})
    best = None
    seen = set()
    for c in candidates:
        c = c.upper()
        if not c or c in seen: continue
        seen.add(c)
        row = tickers.get(c)
        if row and (not best or row.get("mentions", 0) > best.get("mentions", 0)):
            best = row
    return best


# ───────────────────────────────────────────────────────────────────────
# Signal helper
# ───────────────────────────────────────────────────────────────────────

def sentiment_signal_align(snap: dict) -> tuple:
    """Vote in the direction retail chatter leans, IF chatter is fresh.

    Rules:
      sentiment >= 65 and delta_24h > 0     → +1 (bullish wave)
      sentiment <= 35 and delta_24h > 0     → -1 (bearish wave)
      mentions < 10                         →  0 (too quiet to matter)
      otherwise                             →  0 (mixed)

    For symbols not in our retail-watched list (most FX pairs except crypto
    and indices), this returns 0 silently.
    """
    sentsnap = get_sentiment_snapshot()
    sym = (snap.get("symbol") or "").upper()
    row = _lookup_symbol_sentiment(sym, sentsnap)
    if not row: return 0, f"no retail chatter for {sym}"

    mentions = row.get("mentions", 0)
    sent     = row.get("sentiment")
    delta    = row.get("delta_24h", 0)
    if mentions < 10: return 0, f"only {mentions} mentions (too quiet)"

    # Sentiment % path (when ApeWisdom returns it)
    if sent is not None:
        if sent >= 65 and delta > 0:
            return +1, f"retail bullish ({sent:.0f}%, +{delta} new mentions)"
        if sent <= 35 and delta > 0:
            return -1, f"retail bearish ({sent:.0f}%, +{delta} new mentions)"
        return 0, f"retail mixed ({sent:.0f}%, Δ {delta})"

    # Mention-delta fallback: rising chatter on quiet market = trend onset,
    # collapsing chatter = squeeze ending. Threshold: |delta| >= 30% of base.
    base_men = max(1, mentions - delta)
    rel = delta / base_men
    if rel >= 0.30 and mentions >= 20:
        return +1, f"retail mentions surging (+{delta}, {rel:+.0%})"
    if rel <= -0.30 and mentions >= 20:
        return -1, f"retail mentions collapsing ({delta}, {rel:+.0%})"
    return 0, f"chatter flat ({mentions} mentions, Δ {delta})"


# ───────────────────────────────────────────────────────────────────────
# CLI
# ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="r_native.sentiment_feed")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--top", type=int, default=10, help="show top-N tickers")
    ap.add_argument("--test-signal", metavar="SYMBOL")
    args = ap.parse_args()

    snap = get_sentiment_snapshot(force=args.refresh)
    tickers = snap.get("tickers", {})
    print(f"issued_at={snap.get('issued_at')}  tickers={len(tickers)}")
    sorted_t = sorted(tickers.items(), key=lambda kv: -kv[1].get("mentions", 0))
    for t, row in sorted_t[:args.top]:
        print(f"  {t:10s}  m={row['mentions']:>5}  Δ={row['delta_24h']:>+4}  "
              f"sent={row.get('sentiment')}  ({row.get('filter')})")

    if args.test_signal:
        v, r = sentiment_signal_align({"symbol": args.test_signal})
        print(f"\nsentiment_signal_align({args.test_signal}) → vote={v} {r}")
