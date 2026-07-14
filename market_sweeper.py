"""market_sweeper.py — market-wide pattern MEASUREMENT engine (NO prediction, NO orders).

Every 5 min: snapshot a compact state for each symbol x timeframe (trend/momentum/
volatility/structure/candle), log it, then honestly resolve past snapshots after a
12-bar forward horizon and accumulate pattern->outcome statistics with a trust gate
(COLLECTING < 30 samples; SIGNIFICANT only when |t| >= 2). Read-only w.r.t. MT5.
"""
import json, math, os, sys, time, traceback
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "r_native")
SWEEP_FILE = os.path.join(DATA, "market_sweep.jsonl")
KNOW_FILE = os.path.join(DATA, "market_knowledge.json")
MAP_FILE = os.path.join(DATA, "market_map.json")
STATUS_FILE = os.path.join(DATA, "market_sweeper_status.json")
CONFIG_FILE = os.path.join(DATA, "market_sweeper_config.json")
LOG_FILE = os.path.join(DATA, "market_sweeper.out.log")
UNIVERSE_FILE = os.path.join(ROOT, "symbol_universe.json")

FALLBACK_SYMBOLS = ["XAUUSDm", "BTCUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm",
                    "USDCADm", "USDCHFm", "EURJPYm", "GBPJPYm", "ETHUSDm", "US30m"]
HORIZON_BARS = 12
CYCLE_SEC = 300
BARS_FETCH = 520

import MetaTrader5 as mt5  # noqa: E402
import numpy as np  # noqa: E402

TFS = {"M5": (mt5.TIMEFRAME_M5, 5), "M15": (mt5.TIMEFRAME_M15, 15),
       "H1": (mt5.TIMEFRAME_H1, 60), "H4": (mt5.TIMEFRAME_H4, 240),
       "D1": (mt5.TIMEFRAME_D1, 1440)}


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, default=str)
    os.replace(tmp, path)


def get_symbols():
    uni = load_json(UNIVERSE_FILE, None)
    if isinstance(uni, dict) and isinstance(uni.get("symbols"), list):
        syms = [s.get("symbol") for s in uni["symbols"]
                if isinstance(s, dict) and s.get("enabled") and s.get("symbol")]
        if syms:
            return syms
    return list(FALLBACK_SYMBOLS)


def mt5_connect():
    for attempt in range(1, 6):
        try:
            if mt5.initialize(timeout=30000):
                ai = mt5.account_info()
                log(f"MT5 connected (attempt {attempt}) account={getattr(ai, 'login', '?')}")
                return True
            log(f"mt5.initialize failed attempt {attempt}: {mt5.last_error()}")
        except Exception as e:
            log(f"mt5.initialize exception attempt {attempt}: {e}")
        time.sleep(10 * attempt)
    return False


# ---------- indicators (numpy, no external TA deps) ----------
def ema(arr, period):
    out = np.empty_like(arr)
    k = 2.0 / (period + 1)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out


def rsi14(close):
    d = np.diff(close)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    n = 14
    if len(d) < n + 1:
        return 50.0
    au, ad = up[:n].mean(), dn[:n].mean()
    for i in range(n, len(d)):
        au = (au * (n - 1) + up[i]) / n
        ad = (ad * (n - 1) + dn[i]) / n
    if ad == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + au / ad)


def stoch_k(high, low, close, kp=14, sm=3):
    ks = []
    for i in range(len(close) - sm, len(close)):
        hh = high[i - kp + 1:i + 1].max()
        ll = low[i - kp + 1:i + 1].min()
        ks.append(50.0 if hh == ll else 100.0 * (close[i] - ll) / (hh - ll))
    return float(np.mean(ks))


def atr_series(high, low, close, period=14):
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
    out = np.empty(len(tr))
    out[period - 1] = tr[:period].mean()
    for i in range(period, len(tr)):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    out[:period - 1] = out[period - 1]
    return out  # aligned to close[1:]


def round_step(price):
    if price <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(price))
    for mult in (1.0, 0.5, 0.25, 0.1, 0.05, 0.025, 0.01):
        if mag * mult <= price * 0.012:
            return mag * mult
    return mag * 0.01


def candle_type(o, h, l, c, po, pc):
    rng = h - l
    if rng <= 0:
        return "doji"
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    if body / rng < 0.1:
        return "doji"
    if c > o and pc < po and c >= po and o <= pc:
        return "engulf-bull"
    if c < o and pc > po and c <= po and o >= pc:
        return "engulf-bear"
    if lower >= 2 * body and upper <= body:
        return "hammer"
    if upper >= 2 * body and lower <= body:
        return "star"
    return "plain-bull" if c > o else "plain-bear"


def bucket_rsi(v):
    if v < 30: return "rsi<30"
    if v < 45: return "rsi30-45"
    if v < 55: return "rsi45-55"
    if v <= 70: return "rsi55-70"
    return "rsi>70"


def compute_state(rates, prev_day_hl):
    """rates: numpy structured array incl. forming last bar. Uses last COMPLETED bar."""
    o = rates["open"].astype(float); h = rates["high"].astype(float)
    l = rates["low"].astype(float); c = rates["close"].astype(float)
    n = len(c) - 1  # index of forming bar; completed data = [:n+? ] -> use [:n]
    if n < 220:
        return None
    oc, hc, lc, cc = o[:n], h[:n], l[:n], c[:n]  # completed bars only
    close = float(cc[-1])
    e50 = ema(cc, 50); e200 = ema(cc, 200)
    if close > e50[-1] > e200[-1]:
        trend = "up"
    elif close < e50[-1] < e200[-1]:
        trend = "down"
    else:
        trend = "mixed"
    slope = "+" if e50[-1] > e50[-6] else "-"
    rsi = rsi14(cc[-120:])
    st = stoch_k(hc, lc, cc)
    st_b = "st<20" if st < 20 else ("st>80" if st > 80 else "st20-80")
    atrs = atr_series(hc, lc, cc)
    atr = float(atrs[-1])
    if atr <= 0:
        return None
    hist = atrs[-200:]
    pct = float((hist < atr).mean())
    vol = "low" if pct < 0.33 else ("high" if pct > 0.66 else "mid")
    # structure: round level + prev-day H/L distance in ATR
    step = round_step(close)
    d_round = abs(close - round(close / step) * step) / atr
    d_pd = None
    if prev_day_hl:
        d_pd = min(abs(close - prev_day_hl[0]), abs(close - prev_day_hl[1])) / atr
    near = d_round <= 0.5 or (d_pd is not None and d_pd <= 0.5)
    # breakout: close beyond 20-bar high/low within last 3 completed bars
    brk = "none"
    for i in range(1, 4):
        idx = n - i
        hh20 = hc[idx - 20:idx].max(); ll20 = lc[idx - 20:idx].min()
        if cc[idx] > hh20:
            brk = "breakout_up"; break
        if cc[idx] < ll20:
            brk = "breakout_dn"; break
    # liquidity sweep on last completed bar
    rng = hc[-1] - lc[-1]
    if rng > 0 and brk == "none":
        hh20 = hc[-21:-1].max(); ll20 = lc[-21:-1].min()
        up_wick = hc[-1] - max(oc[-1], cc[-1]); dn_wick = min(oc[-1], cc[-1]) - lc[-1]
        if hc[-1] > hh20 and cc[-1] < hh20 and up_wick / rng >= 0.30:
            brk = "sweep_up"
        elif lc[-1] < ll20 and cc[-1] > ll20 and dn_wick / rng >= 0.30:
            brk = "sweep_dn"
    cnd = candle_type(oc[-1], hc[-1], lc[-1], cc[-1], oc[-2], cc[-2])
    lev = "nearlevel" if near else "openfield"
    key = f"{trend}{slope}|{bucket_rsi(rsi)}|vol{vol}|{lev}|{brk}|{cnd}"
    state = {"trend": trend, "ema50_slope": slope, "rsi": round(rsi, 1), "stoch": round(st, 1),
             "stoch_bucket": st_b, "atr": atr, "atr_pct": round(pct, 2),
             "vol": vol, "dist_round_atr": round(d_round, 2),
             "dist_pdhl_atr": (round(d_pd, 2) if d_pd is not None else None),
             "near_level": near, "breakout": brk, "candle": cnd}
    return state, key, close, atr, int(rates["time"][n - 1])


# ---------- knowledge ----------
def update_knowledge(know, key, tf, fwd_r):
    e = know.setdefault(key, {"n": 0, "sum": 0.0, "sumsq": 0.0, "up": 0, "down": 0, "per_tf": {}})
    e["n"] += 1; e["sum"] += fwd_r; e["sumsq"] += fwd_r * fwd_r
    if fwd_r > 0.3: e["up"] += 1
    if fwd_r < -0.3: e["down"] += 1
    t = e["per_tf"].setdefault(tf, {"n": 0, "sum": 0.0})
    t["n"] += 1; t["sum"] += fwd_r


def finalize_knowledge(know):
    for key, e in know.items():
        n = e["n"]
        mean = e["sum"] / n if n else 0.0
        e["mean_fwd_r"] = round(mean, 4)
        e["up_rate"] = round(e["up"] / n, 3) if n else 0.0
        e["down_rate"] = round(e["down"] / n, 3) if n else 0.0
        tstat = 0.0
        if n >= 2:
            var = max((e["sumsq"] - e["sum"] * e["sum"] / n) / (n - 1), 1e-12)
            tstat = mean / math.sqrt(var / n)
        e["t_stat"] = round(tstat, 2)
        if n < 30:
            e["trust"] = "COLLECTING"
        elif abs(tstat) >= 2:
            e["trust"] = "SIGNIFICANT"
        else:
            e["trust"] = "NOISE"
        for tf, d in e["per_tf"].items():
            d["mean_fwd_r"] = round(d["sum"] / d["n"], 4) if d["n"] else 0.0


# ---------- main loop ----------
def load_pending():
    pend, resolved_tail = [], []
    if os.path.exists(SWEEP_FILE):
        with open(SWEEP_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                (resolved_tail if r.get("resolved") else pend).append(r)
    return pend, resolved_tail[-5000:]


def write_sweep(pend, resolved_tail):
    tmp = SWEEP_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in pend + resolved_tail[-5000:]:
            f.write(json.dumps(r) + "\n")
    os.replace(tmp, SWEEP_FILE)


def main():
    os.makedirs(DATA, exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save_json(CONFIG_FILE, {"enabled": True, "cycle_sec": CYCLE_SEC})
    if not mt5_connect():
        save_json(STATUS_FILE, {"ts": time.time(), "error": "MT5 connect failed", "cycles": 0})
        sys.exit(1)
    symbols = get_symbols()
    skipped = [s for s in symbols if mt5.symbol_info(s) is None]
    symbols = [s for s in symbols if s not in skipped]
    log(f"symbols={symbols} skipped={skipped}")
    know = load_json(KNOW_FILE, {})
    for e in know.values():  # ensure numeric fields exist
        e.setdefault("per_tf", {})
    pend, resolved_tail = load_pending()
    cycles = 0
    snapshots_total = sum(1 for _ in pend) + len(resolved_tail)
    while True:
        cfg = load_json(CONFIG_FILE, {"enabled": True})
        cycle_sec = int(cfg.get("cycle_sec", CYCLE_SEC))
        if not cfg.get("enabled", True):
            save_json(STATUS_FILE, {"ts": time.time(), "enabled": False, "cycles": cycles,
                                    "note": "disabled by config"})
            time.sleep(30)
            continue
        t0 = time.time()
        scanned = 0
        market_map = {}
        rates_cache = {}
        for sym in symbols:
            market_map[sym] = {}
            # prev-day H/L from D1
            pd_hl = None
            try:
                d1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 1, 2)
                if d1 is not None and len(d1) >= 1:
                    pd_hl = (float(d1[-1]["high"]), float(d1[-1]["low"]))
            except Exception:
                pass
            for tf_name, (tf_const, _) in TFS.items():
                try:
                    rates = mt5.copy_rates_from_pos(sym, tf_const, 0, BARS_FETCH)
                    if rates is None or len(rates) < 230:
                        continue
                    rates_cache[(sym, tf_name)] = rates
                    res = compute_state(rates, pd_hl)
                    if res is None:
                        continue
                    state, key, close, atr, bar_ts = res
                    snap = {"ts": time.time(), "bar_ts": bar_ts, "symbol": sym, "tf": tf_name,
                            "state": state, "state_key": key, "close": close, "atr": atr,
                            "resolved": False}
                    # dedupe: don't re-log same bar for same sym/tf
                    if not any(p["symbol"] == sym and p["tf"] == tf_name and p["bar_ts"] == bar_ts
                               for p in pend[-600:]):
                        pend.append(snap)
                        snapshots_total += 1
                    m = dict(state)
                    m.pop("atr", None)
                    m["close"] = close
                    m["state_key"] = key
                    market_map[sym][tf_name] = m
                    scanned += 1
                except Exception as e:
                    log(f"scan error {sym} {tf_name}: {e}")
        # resolve pending snapshots using cached rates (bar-count based, gap-safe)
        still = []
        n_resolved = 0
        for p in pend:
            rates = rates_cache.get((p["symbol"], p["tf"]))
            done = False
            if rates is not None:
                times = rates["time"].astype(np.int64)
                idxs = np.where(times == p["bar_ts"])[0]
                if len(idxs):
                    i = int(idxs[0])
                    j = i + HORIZON_BARS
                    if j <= len(rates) - 2:  # forward bar completed (last bar is forming)
                        fwd_r = (float(rates["close"][j]) - p["close"]) / p["atr"]
                        p["resolved"] = True
                        p["fwd_r"] = round(fwd_r, 4)
                        update_knowledge(know, p["state_key"], p["tf"], fwd_r)
                        resolved_tail.append(p)
                        n_resolved += 1
                        done = True
                elif len(times) and p["bar_ts"] < int(times[0]):
                    done = True  # fell off history window; drop silently
            if not done:
                # discard pathologically stale (>30 days) unresolved snapshots
                if time.time() - p["ts"] > 30 * 86400:
                    done = True
                else:
                    still.append(p)
        pend = still
        resolved_tail = resolved_tail[-5000:]
        finalize_knowledge(know)
        # top-10 significant states for the human map
        sig = [(k, e) for k, e in know.items() if e.get("trust") == "SIGNIFICANT"]
        sig.sort(key=lambda kv: -abs(kv[1]["t_stat"]))
        top10 = [{"state_key": k, "n": e["n"], "mean_fwd_r": e["mean_fwd_r"],
                  "t_stat": e["t_stat"], "up_rate": e["up_rate"], "down_rate": e["down_rate"]}
                 for k, e in sig[:10]]
        cycles += 1
        try:
            write_sweep(pend, resolved_tail)
            save_json(KNOW_FILE, know)
            save_json(MAP_FILE, {"ts": time.time(), "updated": datetime.now(timezone.utc).isoformat(),
                                 "symbols": market_map, "top_significant": top10,
                                 "doctrine": "measured stats only — trust requires n>=30 and |t|>=2"})
        except Exception as e:
            log(f"write error: {e}")
        save_json(STATUS_FILE, {"ts": time.time(), "enabled": True, "cycles": cycles,
                                "symbols_scanned": scanned, "symbols": symbols,
                                "skipped_symbols": skipped, "pending": len(pend),
                                "resolved_this_cycle": n_resolved,
                                "snapshots_total": snapshots_total,
                                "knowledge_keys": len(know),
                                "cycle_took_sec": round(time.time() - t0, 1)})
        log(f"cycle {cycles}: scanned={scanned} pend={len(pend)} resolved+={n_resolved} keys={len(know)}")
        # sleep in chunks, refreshing heartbeat ts so watchers see us alive
        slept = 0
        while slept < cycle_sec:
            time.sleep(30)
            slept += 30
            try:
                st = load_json(STATUS_FILE, {})
                st["ts"] = time.time()
                save_json(STATUS_FILE, st)
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        log("FATAL: " + traceback.format_exc())
        raise
