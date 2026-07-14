"""footprint_feeder.py — HEADLESS order-flow (footprint) feed, no chart needed.

The CLAUDE_FOOTPRINT_v5 MQL5 indicator was heavy and FROZE the chart, so the user
removed it. This reproduces its footprint export in pure Python straight from MT5
tick data — NO chart, NO indicator, no lag on the user's terminal. It writes
footprint_<SYMBOL>.json in the SAME schema footprint_features._load() and
chart_signal_writer.py already consume, so the order-flow pillars
(flow / cvd / tape / imb / accel) stay ALIVE and fresh.

Per minute bar it computes, from inferred tick aggressors (TICK_FLAG_BUY/SELL,
else mid up/down-tick):
  • per-price-level bid/ask volume  → POC, diagonal imbalance counts
  • bar delta = ask_vol - bid_vol   → cum_delta (rolling over the window)
  • signal_value = recent delta bias (-100..+100)

Run:  python -m runtime.footprint_feeder --loop
"""
from __future__ import annotations
import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

COMMON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
# F2-a.3: symbols from the single source of truth (signal_symbols = analysis/display set),
# a superset of this legacy list. Fail-safe to the literal if the loader is unavailable.
_LEGACY_SYMBOLS = ["XAUUSDm", "XAGUSDm", "BTCUSDm", "EURUSDm", "GBPUSDm", "USDJPYm"]
try:
    from runtime.shared.symbol_universe import signal_symbols as _signal_symbols
    SYMBOLS = _signal_symbols() or _LEGACY_SYMBOLS
except Exception:  # noqa: BLE001 — analysis feed must never crash on universe import
    SYMBOLS = _LEGACY_SYMBOLS
WINDOW_BARS = 15            # how many M1 bars of footprint to keep
PERIOD = 60                 # M1
POLL = 3.0                  # rebuild cadence (seconds)
IMB_RATIO = 2.0             # diagonal imbalance ratio (buyers vs sellers)
IMB_MIN = 8                 # min volume on a level to count an imbalance


def _log(m):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}Z] [FP-FEEDER] {m}", flush=True)


def _bucket(mt5, symbol):
    info = mt5.symbol_info(symbol)
    if not info:
        return 0.01
    step = info.trade_tick_size or (info.point * 10 if info.point else 0.0)
    if step <= 0:
        step = 0.01
    return step * 10.0          # matches the MQL5 InpPricePrecision=10


def _build_from_rates(mt5, symbol):
    """Fallback when tick data is unavailable: approximate per-bar delta from M1
    candles (tick_volume split by candle direction). Coarser than real footprint
    but keeps footprint_<SYM>.json FRESH so the flow pillars never die."""
    try:
        info = mt5.symbol_info(symbol)
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, WINDOW_BARS + 1)
        if r is None or len(r) < 3:
            return None
        digits = (info.digits if info else 5) or 5
        out_bars = []; cum = 0.0
        for b in r:
            o, c = float(b["open"]), float(b["close"])
            vol = float(b["tick_volume"]) or 1.0
            # body-fraction of the range estimates aggressor balance
            rng = float(b["high"]) - float(b["low"]) or 1e-9
            frac = max(-1.0, min(1.0, (c - o) / rng))
            delta = vol * frac
            cum += delta
            out_bars.append({
                "ts": int(b["time"]), "o": round(o, digits), "h": round(float(b["high"]), digits),
                "l": round(float(b["low"]), digits), "c": round(c, digits),
                "vol": int(vol), "delta": int(round(delta)), "cum_delta": round(cum, 1),
                "poc": round((float(b["high"]) + float(b["low"])) / 2.0, digits),
                "imb_buy": 0, "imb_sell": 0, "finalized": True,
            })
        recent = sum(b["delta"] for b in out_bars[-3:])
        avgabs = (sum(abs(b["delta"]) for b in out_bars) / max(len(out_bars), 1)) or 1.0
        sv = max(-100.0, min(100.0, 100.0 * math.tanh(recent / (3.0 * avgabs))))
        return {
            "schema_version": 2, "source": "footprint_feeder_py_rates", "symbol": symbol,
            "ts": int(time.time()), "period_sec": PERIOD,
            "cum_delta": round(out_bars[-1]["cum_delta"], 1),
            "svp_poc": out_bars[-1]["poc"], "svp_vah": 0, "svp_val": 0,
            "signal_value": round(sv, 1), "sd_zones": [], "bars": out_bars[-WINDOW_BARS:],
        }
    except Exception:
        return None


def build(mt5, symbol):
    """Build the footprint JSON for one symbol from the last ~WINDOW_BARS minutes
    of ticks. Stateless (recomputed each cycle) — robust, no drift."""
    info = mt5.symbol_info(symbol)
    if not info:
        return None
    now = datetime.now(timezone.utc)
    frm = now - timedelta(seconds=PERIOD * (WINDOW_BARS + 1))
    ticks = mt5.copy_ticks_range(symbol, frm, now, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        return _build_from_rates(mt5, symbol)      # robustness: never go fully stale
    step = _bucket(mt5, symbol)
    digits = info.digits or 5
    FB = getattr(mt5, "TICK_FLAG_BUY", 0)
    FS = getattr(mt5, "TICK_FLAG_SELL", 0)

    bars = {}                  # bar_start -> {lv:{li:[bid,ask]}, o,h,l,c}
    prev_mid = None
    for t in ticks:
        bid = float(t['bid']); ask = float(t['ask']); last = float(t['last'])
        mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else (last or bid or ask)
        if mid <= 0:
            continue
        vr = float(t['volume_real']) if t['volume_real'] else float(t['volume'])
        vol = vr if vr > 0 else 1.0
        bstart = int(t['time'] // PERIOD * PERIOD)
        b = bars.get(bstart)
        if b is None:
            b = {"lv": {}, "o": mid, "h": mid, "l": mid, "c": mid}
            bars[bstart] = b
        b["c"] = mid
        if mid > b["h"]: b["h"] = mid
        if mid < b["l"]: b["l"] = mid
        # aggressor: prefer broker BUY/SELL flags, else mid up/down-tick
        fl = int(t['flags'])
        buy = None
        if FB and (fl & FB):   buy = True
        elif FS and (fl & FS): buy = False
        elif prev_mid is not None:
            if mid > prev_mid:   buy = True
            elif mid < prev_mid: buy = False
        prev_mid = mid
        if buy is None:
            continue
        li = int(round(mid / step))            # integer level index (exact keys)
        cell = b["lv"].get(li)
        if cell is None:
            cell = [0.0, 0.0]; b["lv"][li] = cell
        cell[1 if buy else 0] += vol           # [bid, ask]

    if not bars:
        return None

    out_bars = []
    cum = 0.0
    for bstart in sorted(bars.keys()):
        b = bars[bstart]
        ask_sum = sum(c[1] for c in b["lv"].values())
        bid_sum = sum(c[0] for c in b["lv"].values())
        delta = ask_sum - bid_sum
        cum += delta
        # POC = level with max total volume
        poc_li, mx = 0, -1.0
        for li, c in b["lv"].items():
            tot = c[0] + c[1]
            if tot > mx:
                mx = tot; poc_li = li
        # diagonal imbalance counts
        imb_b = imb_s = 0
        for li, c in b["lv"].items():
            bid_v, ask_v = c
            below = b["lv"].get(li - 1)
            above = b["lv"].get(li + 1)
            if below and below[0] > 0 and ask_v >= IMB_RATIO * below[0] and ask_v >= IMB_MIN:
                imb_b += 1
            if above and above[1] > 0 and bid_v >= IMB_RATIO * above[1] and bid_v >= IMB_MIN:
                imb_s += 1
        out_bars.append({
            "ts": bstart, "o": round(b["o"], digits), "h": round(b["h"], digits),
            "l": round(b["l"], digits), "c": round(b["c"], digits),
            "vol": int(ask_sum + bid_sum), "delta": int(round(delta)),
            "cum_delta": round(cum, 1), "poc": round(poc_li * step, digits),
            "imb_buy": imb_b, "imb_sell": imb_s, "finalized": True,
        })
    out_bars = out_bars[-WINDOW_BARS:]
    if not out_bars:
        return None

    # signal_value = recent (last 3 bars) delta bias, scaled by avg |delta|
    recent = sum(b["delta"] for b in out_bars[-3:])
    avgabs = (sum(abs(b["delta"]) for b in out_bars) / max(len(out_bars), 1)) or 1.0
    signal_value = max(-100.0, min(100.0, 100.0 * math.tanh(recent / (3.0 * avgabs))))

    return {
        "schema_version": 2, "source": "footprint_feeder_py", "symbol": symbol,
        "ts": int(time.time()), "period_sec": PERIOD,
        "cum_delta": round(out_bars[-1]["cum_delta"], 1),
        "svp_poc": out_bars[-1]["poc"], "svp_vah": 0, "svp_val": 0,
        "signal_value": round(signal_value, 1), "sd_zones": [],
        "bars": out_bars,
    }


def _write(symbol, payload):
    try:
        COMMON.mkdir(parents=True, exist_ok=True)
        (COMMON / f"footprint_{symbol}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        _log(f"write {symbol} err: {e}")
        return False


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--symbols", nargs="*", default=SYMBOLS)
    args = ap.parse_args(argv)
    if not mt5.initialize() and not mt5.initialize():
        _log("MT5 init failed"); return 1
    _log(f"start — headless footprint feed for {len(args.symbols)} symbols "
         f"(replaces the laggy chart indicator)")
    dry_cycles = 0           # SELF-HEAL: consecutive cycles where NOTHING was written
    try:
        while True:
            wrote = 0
            for s in args.symbols:
                try:
                    j = build(mt5, s)
                    if j and _write(s, j):
                        wrote += 1
                except Exception as e:
                    _log(f"{s} build err: {e}")
            # WATCHDOG: if a whole cycle produced no fresh footprint, the MT5 link
            # has likely gone stale (copy_ticks_range silently returning empty/
            # hanging under multi-process contention). Reconnect to recover —
            # this is what kept needing an external restart every ~hour.
            if wrote == 0:
                dry_cycles += 1
                if dry_cycles >= 2:
                    _log(f"watchdog: {dry_cycles} dry cycles — reinitializing MT5 link")
                    try:
                        mt5.shutdown()
                    except Exception:
                        pass
                    time.sleep(1.0)
                    mt5.initialize() or mt5.initialize()
                    dry_cycles = 0
            else:
                dry_cycles = 0
            if not (args.loop and not args.once):
                break
            time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
