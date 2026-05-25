"""
r_multi_symbol.py — Scan ALL tradeable symbols, rank by quality, auto blacklist losers.

Discovers symbols from MT5, filters to those:
  - currently market-open (session in active hours)
  - tradeable (symbol_info.trade_mode == 4)
  - sufficient ATR (real volatility)
  - reasonable spread/ATR ratio

Then for each candidate, computes a quality score using R's gate logic.

Blacklist / Whitelist (persisted across runs):
  - After N closed trades on a symbol:
      WR < 30% AND net_pl < $-3  →  BLACKLIST for 7 days
      WR > 60% AND net_pl > $+3  →  WHITELIST (priority)
  - Manual re-evaluation every 7 days (blacklist auto-expires)

File: friday_v3/data/r_symbol_book.json
"""
from __future__ import annotations
import json
import math
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import MetaTrader5 as mt5

SYMBOL_BOOK = Path(r"C:\Users\Radhi\MT5\friday_v3\data\r_symbol_book.json")

# Thresholds
MIN_TRADES_FOR_VERDICT  = 5
BLACKLIST_WR_BELOW      = 30
BLACKLIST_NET_BELOW_USD = -3.0
WHITELIST_WR_ABOVE      = 60
WHITELIST_NET_ABOVE_USD = 3.0
BLACKLIST_DAYS          = 7

# Filter: symbols we consider for trading at all
SYMBOL_FILTERS = {
    "max_spread_atr_ratio": 0.50,  # raised — many forex pairs have high spread/ATR on M5
    "min_atr_price":        0.0001, # very loose — let everything through, quality rank handles it
    "must_be_visible":      False, # scan ALL symbols, not just market-watch visible
    "must_be_tradeable":    True,
}


def _load_book() -> dict:
    if not SYMBOL_BOOK.exists(): return {}
    try: return json.loads(SYMBOL_BOOK.read_text(encoding="utf-8"))
    except Exception: return {}


def _save_book(book: dict):
    SYMBOL_BOOK.parent.mkdir(parents=True, exist_ok=True)
    SYMBOL_BOOK.write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")


def _quick_session_check(sym_info, max_age_min: int = 5) -> bool:
    """Best-effort: market open if last tick time within max_age_min minutes."""
    if not sym_info: return False
    try:
        tick = mt5.symbol_info_tick(sym_info.name)
        if not tick: return False
        age = datetime.now().timestamp() - tick.time
        return age < max_age_min * 60
    except Exception:
        return False


def _quick_atr(symbol: str, tf, n: int = 14) -> float:
    try:
        bars = mt5.copy_rates_from_pos(symbol, tf, 1, n + 1)
        if bars is None or len(bars) < 5: return 0.0
        tr = [max(float(bars["high"][i]) - float(bars["low"][i]),
                  abs(float(bars["high"][i]) - float(bars["close"][i-1])),
                  abs(float(bars["low"][i])  - float(bars["close"][i-1])))
              for i in range(1, len(bars))]
        return sum(tr) / len(tr)
    except Exception:
        return 0.0


def discover_symbols(category_filter: Optional[list] = None) -> list[dict]:
    """Return list of candidate symbols with metadata."""
    if not mt5.initialize(): return []
    all_syms = mt5.symbols_get() or []
    out = []
    for s in all_syms:
        if SYMBOL_FILTERS["must_be_visible"] and not s.visible:
            continue
        if SYMBOL_FILTERS["must_be_tradeable"] and s.trade_mode != 4:
            continue
        # Category filter (FOREX, METAL, etc.)
        if category_filter:
            path = (s.path or "").upper()
            if not any(c in path for c in category_filter):
                continue
        # Only major pairs + metals + indices + crypto by default
        out.append({
            "name":          s.name,
            "path":          s.path,
            "digits":        s.digits,
            "point":         s.point,
            "spread_pt":     getattr(s, "spread", 0),
            "contract_size": s.trade_contract_size,
            "min_lot":       s.volume_min,
            "currency_base": s.currency_base,
            "currency_profit": s.currency_profit,
        })
    return out


def rank_symbols(max_symbols: int = 40) -> dict:
    """For each available symbol, compute a tradeability + quality score."""
    if not mt5.initialize(): return {"ok": False, "error": "mt5"}
    book = _load_book()
    now = datetime.now(timezone.utc)

    # Auto-expire blacklist entries
    for sym, rec in list(book.items()):
        if rec.get("status") == "BLACKLIST":
            try:
                until = datetime.fromisoformat(rec.get("blacklist_until","").replace("Z","+00:00"))
                if now > until:
                    rec["status"] = "NEUTRAL"
                    rec["blacklist_until"] = None
                    rec["status_changed_at"] = now.isoformat()
            except Exception: pass
    _save_book(book)

    candidates = discover_symbols()
    ranked = []
    for sym in candidates[:max_symbols * 3]:
        name = sym["name"]
        s_info = mt5.symbol_info(name)
        if not _quick_session_check(s_info): continue
        tick = mt5.symbol_info_tick(name)
        if not tick or tick.bid <= 0 or tick.ask <= 0: continue
        spread_pt = (tick.ask - tick.bid) / s_info.point if s_info.point > 0 else 999
        atr_m5  = _quick_atr(name, mt5.TIMEFRAME_M5)
        atr_h1  = _quick_atr(name, mt5.TIMEFRAME_H1)
        if atr_m5 <= 0: continue
        spread_atr_ratio = (spread_pt * s_info.point) / atr_m5 if atr_m5 > 0 else 99
        # Hard filters
        if atr_h1 < SYMBOL_FILTERS["min_atr_price"]: continue
        if spread_atr_ratio > SYMBOL_FILTERS["max_spread_atr_ratio"]: continue

        # Status from book
        rec = book.get(name, {})
        status = rec.get("status", "NEUTRAL")
        if status == "BLACKLIST": continue   # skip blacklisted

        # Quality score: lower spread_atr is better, higher H1 ATR is better, whitelist boost
        quality = (1.0 - min(1.0, spread_atr_ratio * 3)) * 50  # 0-50 from spread
        quality += min(50, atr_h1 / 0.5 * 10)                  # 0-50 from ATR
        if status == "WHITELIST": quality += 30                # priority boost
        wr = rec.get("win_rate", 0)
        if rec.get("trades", 0) >= 5:
            quality += (wr - 50) * 0.5    # bonus for proven winners

        ranked.append({
            "symbol":           name,
            "path":             sym["path"],
            "bid":              tick.bid,
            "ask":              tick.ask,
            "spread_pt":        round(spread_pt, 0),
            "atr_m5":           round(atr_m5, 3),
            "atr_h1":           round(atr_h1, 3),
            "spread_atr_ratio": round(spread_atr_ratio, 3),
            "status":           status,
            "trades":           rec.get("trades", 0),
            "wins":             rec.get("wins", 0),
            "win_rate":         round(rec.get("win_rate", 0), 1),
            "net_pl":           round(rec.get("net_pl", 0), 2),
            "quality":          round(quality, 1),
        })

    ranked.sort(key=lambda x: -x["quality"])
    return {
        "ok":          True,
        "ts":          now.isoformat(),
        "candidates":  ranked[:max_symbols],
        "total_examined": len(candidates),
        "total_tradeable": len(ranked),
        "blacklist":   [s for s,r in book.items() if r.get("status") == "BLACKLIST"],
        "whitelist":   [s for s,r in book.items() if r.get("status") == "WHITELIST"],
    }


def record_symbol_trade(symbol: str, profit: float):
    """After a closed trade, update the symbol book + maybe blacklist/whitelist."""
    book = _load_book()
    rec = book.setdefault(symbol, {
        "trades": 0, "wins": 0, "losses": 0,
        "net_pl": 0.0, "win_rate": 0.0,
        "status": "NEUTRAL", "first_seen": datetime.now(timezone.utc).isoformat(),
        "blacklist_until": None,
    })
    rec["trades"] += 1
    rec["net_pl"] = round(rec.get("net_pl", 0) + float(profit), 2)
    if profit > 0:
        rec["wins"] += 1
    else:
        rec["losses"] = rec.get("losses", 0) + 1
    rec["win_rate"] = round(rec["wins"] / rec["trades"] * 100, 1)
    rec["last_trade"] = datetime.now(timezone.utc).isoformat()

    # Decide status
    if rec["trades"] >= MIN_TRADES_FOR_VERDICT:
        if rec["win_rate"] < BLACKLIST_WR_BELOW and rec["net_pl"] < BLACKLIST_NET_BELOW_USD:
            new_status = "BLACKLIST"
            rec["blacklist_until"] = (datetime.now(timezone.utc) + timedelta(days=BLACKLIST_DAYS)).isoformat()
        elif rec["win_rate"] > WHITELIST_WR_ABOVE and rec["net_pl"] > WHITELIST_NET_ABOVE_USD:
            new_status = "WHITELIST"
        else:
            new_status = "NEUTRAL"
        if new_status != rec.get("status"):
            rec["status_changed_at"] = datetime.now(timezone.utc).isoformat()
        rec["status"] = new_status
    book[symbol] = rec
    _save_book(book)
    return rec


def get_book_summary() -> dict:
    book = _load_book()
    return {
        "total":     len(book),
        "blacklist": [{"symbol":s, **r} for s,r in book.items() if r.get("status") == "BLACKLIST"],
        "whitelist": [{"symbol":s, **r} for s,r in book.items() if r.get("status") == "WHITELIST"],
        "neutral":   [{"symbol":s, **r} for s,r in book.items() if r.get("status") == "NEUTRAL"],
    }


if __name__ == "__main__":
    r = rank_symbols(max_symbols=30)
    if r.get("ok"):
        print(f"Examined {r['total_examined']} symbols, {r['total_tradeable']} tradeable now\n")
        print(f"{'SYMBOL':12s} {'STATUS':10s} {'SPREAD':>7} {'ATR_H1':>8} {'TRADES':>6} {'WR':>5} {'NET':>7} {'QUALITY':>7}")
        for s in r["candidates"]:
            print(f"{s['symbol']:12s} {s['status']:10s} {s['spread_pt']:>7.0f} {s['atr_h1']:>8.3f} "
                  f"{s['trades']:>6} {s['win_rate']:>4.0f}% ${s['net_pl']:>+6.2f} {s['quality']:>7.1f}")
        print(f"\n🟢 Whitelist: {r['whitelist']}")
        print(f"🔴 Blacklist: {r['blacklist']}")
