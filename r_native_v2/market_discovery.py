"""market_discovery.py — F2-b slice 1: discover EVERY tradable MT5 symbol and rank it.

The user's vision: "R Native enters any market it sees, breeds genes, tests every market."
This is the safe first step — DISCOVERY + SCORING only. It NEVER enables trading. It scans
all MT5 symbols, scores each by tradeability (spread tightness · range/volatility activity ·
liquidity), and writes a ranked candidates file. Promotion to live trading stays behind the
OOS efficiency gate + explicit approval (later slices).

Read-only · no order_send · no symbol_universe mutation (writes its own candidates file).
Run:  python market_discovery.py            (one scan)
      python market_discovery.py --loop     (rescan every INTERVAL s)
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

_V2 = Path(__file__).resolve().parent
_MT5 = _V2.parent
for p in (str(_MT5), str(_V2)):
    if p not in sys.path:
        sys.path.insert(0, p)

DATA = _V2 / "data"
OUT = DATA / "market_candidates.json"
INTERVAL = 300


def _atr_pct(rows, n=14):
    """ATR as a fraction of price (normalized range) — comparable across symbols."""
    if rows is None or len(rows) < n + 2:
        return 0.0
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = float(rows[i]["high"]), float(rows[i]["low"]), float(rows[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[-n:]) / n
    price = float(rows[-1]["close"]) or 1.0
    return atr / price


def _score(sym_info, spread_pts, atr_pct, avg_vol, vol_state):
    """Composite tradeability score 0..100. Higher = better candidate.
    Rewards tight spread, healthy (not dead, not insane) range, real liquidity."""
    # spread relative to ATR: a spread that eats the range is untradeable
    atr_pts = atr_pct * (sym_info.get("price", 1.0)) / (sym_info.get("point", 1e-5) or 1e-5)
    spread_ratio = spread_pts / atr_pts if atr_pts > 0 else 9.9
    spread_score = max(0.0, 1.0 - spread_ratio / 0.10)          # spread <10% of ATR = good
    # range: want movement but not chaos. Sweet spot ~0.3%–3% ATR/price.
    if atr_pct <= 0:
        range_score = 0.0
    elif atr_pct < 0.0008:
        range_score = atr_pct / 0.0008 * 0.4                    # too dead
    elif atr_pct <= 0.03:
        range_score = 1.0                                       # healthy
    else:
        range_score = max(0.2, 0.03 / atr_pct)                  # too wild
    liq_score = min(1.0, avg_vol / 500.0)                       # tick-volume proxy
    regime_bonus = {"expansion": 1.0, "normal": 0.9, "contraction": 0.5}.get(vol_state, 0.6)
    return round(100 * (0.35 * spread_score + 0.35 * range_score + 0.20 * liq_score + 0.10 * regime_bonus), 1)


def discover(mt5):
    import vol_regime as vr
    syms = mt5.symbols_get() or []
    out = []
    for s in syms:
        try:
            name = s.name
            # must be fully tradable (not disabled / close-only)
            if getattr(s, "trade_mode", 0) == 0:
                continue
            mt5.symbol_select(name, True)
            info = mt5.symbol_info(name)
            tick = mt5.symbol_info_tick(name)
            if not info or not tick or not info.point:
                continue
            spread_pts = (tick.ask - tick.bid) / info.point if info.point else 0.0
            r = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_M15, 0, 150)
            if r is None or len(r) < 40:
                continue
            rows = [{"high": x["high"], "low": x["low"], "close": x["close"]} for x in r]
            atr_pct = _atr_pct(rows)
            avg_vol = sum(float(x["tick_volume"]) for x in r[-30:]) / 30.0
            reg = vr.classify(rows)
            sym_info = {"price": float(tick.bid), "point": info.point}
            sc = _score(sym_info, spread_pts, atr_pct, avg_vol, reg.get("state"))
            out.append({
                "symbol": name, "score": sc, "spread_pts": round(spread_pts, 1),
                "atr_pct": round(atr_pct * 100, 3), "avg_vol": round(avg_vol, 0),
                "vol_state": reg.get("state"), "target_mult": reg.get("target_mult"),
                "path": getattr(s, "path", ""),
            })
        except Exception:
            continue
    out.sort(key=lambda d: -d["score"])
    return out


def write(candidates):
    DATA.mkdir(parents=True, exist_ok=True)
    # current live/signal symbols (so we never re-discover what's already managed)
    live = []
    try:
        from symbol_universe import get_symbols
        live = list(get_symbols()) if callable(get_symbols) else []
    except Exception:
        pass
    payload = {
        "ts": time.time(), "scanned": len(candidates),
        "already_live": live,
        "top": candidates[:25],            # ranked shortlist
        "note": "DISCOVERY ONLY — none enabled. Promotion needs OOS efficiency gate + approval.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    a = ap.parse_args(argv)
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    try:
        while True:
            t = time.time()
            cands = discover(mt5)
            p = write(cands)
            top = p["top"][:8]
            print(f"[DISCOVER] scanned {p['scanned']} symbols in {time.time()-t:.1f}s — top:", flush=True)
            for c in top:
                print(f"   {c['score']:5.1f}  {c['symbol']:10s} spread {c['spread_pts']}p · range {c['atr_pct']}% · {c['vol_state']}", flush=True)
            if not a.loop:
                break
            time.sleep(INTERVAL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
