"""market_data_collector.py — pull EVERY MT5 field, live, for every hot symbol.

The user wants the full market-watch column set (Last/High-Low/Volume/Spread/Time/Daily
Change/Tick Size/Tick Value/Face Value/margins/limits/Bid-Ask High-Low/Deals/Turnover/Open
Interest/Buy-Sell Orders & Volume/Open-Close/Avg Weighted/Volatility/Greeks ...) captured
live for ALL active symbols, so the system can compute on them. MT5's symbol_info exposes
all of these — we dump the full struct + tick + a few derived fields each cycle.

Read-only. Writes data/market_data_live.json (every symbol, every field) + a compact
data/market_data_hot.json (ranked active pairs). No order_send.
Run:  python market_data_collector.py --loop
"""
from __future__ import annotations
import argparse, json, time, sys
from pathlib import Path

_V2 = Path(__file__).resolve().parent
_MT5 = _V2.parent
for p in (str(_MT5), str(_V2)):
    if p not in sys.path:
        sys.path.insert(0, p)
DATA = _V2 / "data"
POLL = 5


def _asdict(obj):
    try:
        return obj._asdict()
    except Exception:
        return {k: getattr(obj, k) for k in dir(obj) if not k.startswith("_")}


def collect(mt5):
    syms = mt5.symbols_get() or []
    out = {}; hot = []
    now = time.time()
    for s in syms:
        try:
            name = s.name
            if getattr(s, "trade_mode", 0) == 0:
                continue
            mt5.symbol_select(name, True)
            info = mt5.symbol_info(name); tick = mt5.symbol_info_tick(name)
            if not info or not tick:
                continue
            d = _asdict(info)                      # ALL symbol_info fields (the full column set)
            t = _asdict(tick)
            # only keep symbols with a live-ish tick (hot/active)
            tick_age = now - float(t.get("time", 0))
            bid = float(t.get("bid", 0) or 0); ask = float(t.get("ask", 0) or 0)
            point = float(d.get("point", 0) or 0) or 1e-9
            # derived live fields
            d["bid"] = bid; d["ask"] = ask; d["last"] = float(t.get("last", 0) or 0)
            d["spread_pts"] = round((ask - bid) / point, 1)
            d["tick_age_s"] = round(tick_age, 1)
            so = float(d.get("session_open", 0) or 0)
            d["daily_change_pct"] = round((bid - so) / so * 100, 3) if so else 0.0
            d["volatility"] = float(d.get("price_volatility", 0) or 0)
            d["turnover"] = float(d.get("session_turnover", 0) or 0)
            d["open_interest"] = float(d.get("session_interest", 0) or 0)
            out[name] = d
            # hotness = recent tick + activity (volume/turnover)
            activity = float(d.get("volume", 0) or 0) + float(d.get("session_deals", 0) or 0)
            if tick_age < 120:
                hot.append((name, round(abs(d["daily_change_pct"]), 3), d["spread_pts"], activity))
        except Exception:
            continue
    hot.sort(key=lambda x: -x[1])                  # most-moving first
    return out, hot


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", action="store_true"); a = ap.parse_args(argv)
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    try:
        while True:
            t0 = time.time()
            full, hot = collect(mt5)
            DATA.mkdir(parents=True, exist_ok=True)
            (DATA / "market_data_live.json").write_text(
                json.dumps({"ts": time.time(), "count": len(full), "symbols": full}, ensure_ascii=False),
                encoding="utf-8")
            (DATA / "market_data_hot.json").write_text(
                json.dumps({"ts": time.time(), "hot": [
                    {"symbol": s, "daily_change_pct": c, "spread_pts": sp, "activity": ac}
                    for s, c, sp, ac in hot[:40]]}, ensure_ascii=False, indent=1), encoding="utf-8")
            n_fields = len(next(iter(full.values()))) if full else 0
            print(f"[MKT] {len(full)} symbols × {n_fields} fields in {time.time()-t0:.1f}s | "
                  f"hottest: {', '.join(f'{s}({c:+.2f}%)' for s,c,_,_ in hot[:6])}", flush=True)
            if not a.loop:
                break
            time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
