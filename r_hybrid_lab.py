"""r_hybrid_lab.py — strategy-hybridization lab for XAUUSDm (gold).

Five candidate models (behavioral-fingerprint hybrids), walk-forward weekly
evaluation, honest costs ($0.24 spread + $0.02 slippage per round trip),
no lookahead (signal on bar close, entry next bar open).
Pure python + numpy. No live orders. Results -> data/r_native/hybrid_lab_results.json
"""
import json, math, sys, time
from datetime import datetime, timezone, timedelta

import numpy as np

SYMBOL = "XAUUSDm"
DAYS = 60
COST = 0.26            # $ per round trip per 0.01 lot ($0.24 spread + $0.02 slip)
DOLLAR_PER_PRICE = 1.0 # per 0.01 lot: $1 price move = $1
ATR_MULT = 1.3
STOP_FRAC = 0.5        # stop = 0.5 * ATR14(M5)*1.3
BASE_TARGET_R = 1.2
COOLDOWN_BARS = 5
OUT = r"C:\Users\Radhi\MT5\data\r_native\hybrid_lab_results.json"


def fetch_rates():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print(f"FATAL: mt5.initialize() failed: {mt5.last_error()}")
        sys.exit(1)
    try:
        if mt5.symbol_info(SYMBOL) is None:
            print(f"FATAL: symbol {SYMBOL} not found"); sys.exit(1)
        mt5.symbol_select(SYMBOL, True)
        out = {}
        for name, tf, count in (("M5", mt5.TIMEFRAME_M5, 26000),
                                ("M15", mt5.TIMEFRAME_M15, 9000),
                                ("H1", mt5.TIMEFRAME_H1, 2500)):
            r = mt5.copy_rates_from_pos(SYMBOL, tf, 0, count)
            if r is None or len(r) == 0:
                print(f"FATAL: no {name} bars: {mt5.last_error()}"); sys.exit(1)
            out[name] = np.array(r)
        return out
    finally:
        mt5.shutdown()


def ema(x, n):
    a = 2.0 / (n + 1.0)
    out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def atr(high, low, close, n=14):
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    out = np.full(len(close), np.nan)
    if len(tr) < n: return out
    out[n] = tr[:n].mean()
    for i in range(n + 1, len(close)):
        out[i] = (out[i - 1] * (n - 1) + tr[i - 1]) / n
    return out


def stoch_k(high, low, close, n=14, smooth=3):
    k = np.full(len(close), np.nan)
    for i in range(n - 1, len(close)):
        hh = high[i - n + 1:i + 1].max(); ll = low[i - n + 1:i + 1].min()
        k[i] = 50.0 if hh == ll else 100.0 * (close[i] - ll) / (hh - ll)
    ks = np.full(len(close), np.nan)
    for i in range(n + smooth - 2, len(close)):
        ks[i] = np.nanmean(k[i - smooth + 1:i + 1])
    return ks


def map_htf(m5_time, htf_time, htf_secs):
    """Index of last COMPLETED htf bar as of each m5 bar CLOSE (m5_time+300)."""
    closes = htf_time + htf_secs           # htf bar close times
    idx = np.searchsorted(closes, m5_time + 300, side="right") - 1
    return np.clip(idx, 0, len(htf_time) - 1), idx >= 0


def build_levels(t, h, l, c):
    """Per-bar level sets: prev UTC-day high/low + $5 round grid (3 nearest)."""
    day = (t // 86400).astype(np.int64)
    dhl = {}
    for d in np.unique(day):
        m = day == d
        dhl[d] = (h[m].max(), l[m].min())
    levels = []
    for i in range(len(t)):
        ls = []
        pd = day[i] - 1
        for back in range(1, 4):                      # skip weekend gaps
            if day[i] - back in dhl: pd = day[i] - back; break
        if pd in dhl and pd != day[i]: ls += list(dhl[pd])
        base = round(c[i] / 5.0) * 5.0
        ls += [base - 5.0, base, base + 5.0]
        levels.append(ls)
    return levels


def simulate(kind, sig_dir, ind, model):
    """Generic event loop. sig_dir[i] in {0,+1,-1} on bar close i -> entry open i+1."""
    t, o, h, l, c, a = ind["t"], ind["o"], ind["h"], ind["l"], ind["c"], ind["atr"]
    n = len(t); trades = []; i = 0; next_ok = 0
    while i < n - 2:
        d = sig_dir[i]
        if d == 0 or i < next_ok or np.isnan(a[i]):
            i += 1; continue
        stop_d = STOP_FRAC * a[i] * ATR_MULT
        if stop_d <= 0: i += 1; continue
        ei = i + 1; entry = o[ei]
        sl = entry - d * stop_d
        tp = entry + d * BASE_TARGET_R * stop_d if model != "E" else None
        trail_atr = a[i] * ATR_MULT
        armed_be = False; trailing = False
        best = entry; exit_px = None; xi = ei
        for j in range(ei, n):
            hi, lo = h[j], l[j]
            # conservative: stop checked before target / before trail update
            if d > 0:
                if o[j] <= sl and j > ei: exit_px = o[j]; xi = j; break
                if lo <= sl: exit_px = sl; xi = j; break
                if tp is not None and hi >= tp: exit_px = tp; xi = j; break
                best = max(best, hi)
            else:
                if o[j] >= sl and j > ei: exit_px = o[j]; xi = j; break
                if hi >= sl: exit_px = sl; xi = j; break
                if tp is not None and lo <= tp: exit_px = tp; xi = j; break
                best = min(best, lo)
            if model == "E":                     # trailing management (after bar)
                fav = d * (best - entry) / stop_d
                if not armed_be and fav >= 0.8:
                    sl = entry + d * 0.2 * stop_d; armed_be = True
                if fav >= 1.2: trailing = True
                if trailing:
                    ns = best - d * 0.6 * trail_atr
                    sl = max(sl, ns) if d > 0 else min(sl, ns)
        if exit_px is None:                      # data end
            exit_px = c[n - 1]; xi = n - 1
        # per 0.01 lot: $1 price move = $1  ->  gross = d*(exit-entry)*1.0
        gross = d * (exit_px - entry) * DOLLAR_PER_PRICE
        net = gross - COST
        trades.append({"t_in": int(t[ei]), "t_out": int(t[xi]), "dir": int(d),
                       "entry": round(entry, 3), "exit": round(exit_px, 3),
                       "r": round(d * (exit_px - entry) / stop_d, 3),
                       "gross": round(gross, 4), "net": round(net, 4),
                       "hold_bars": int(xi - ei)})
        next_ok = xi + 1 + COOLDOWN_BARS
        i = xi + 1
    return trades


def signals(model, ind):
    t, o, h, l, c = ind["t"], ind["o"], ind["h"], ind["l"], ind["c"]
    hour = ((t // 3600) % 24).astype(int)
    n = len(t); sig = np.zeros(n, dtype=int)
    e20 = ind["ema20"]; st = ind["stoch"]; a = ind["atr"]
    m15_up, h1_up = ind["m15_up"], ind["h1_up"]
    levels = ind["levels"]
    bearish = c < o
    for i in range(20, n):
        hr = hour[i]
        if model == "A":
            if hr in (23, 0) and c[i] < e20[i] and bearish[i]: sig[i] = -1
        elif model == "B":
            if (hr in (23, 0) and c[i] < e20[i] and bearish[i]
                    and not h1_up[i] and not np.isnan(st[i]) and st[i] > 60):
                sig[i] = -1
        elif model in ("C", "E"):
            hours_ok = (8 <= hr <= 22) if model == "C" else hr in (23, 0)
            if not hours_ok: continue
            rng = h[i] - l[i]
            if rng <= 0: continue
            uw = h[i] - max(o[i], c[i]); lw = min(o[i], c[i]) - l[i]
            for L in levels[i]:
                if h[i] >= L > c[i] and uw >= 0.3 * rng:      # sell rejection
                    if model == "E" or (not m15_up[i] and not h1_up[i]):
                        sig[i] = -1; break
                if l[i] <= L < c[i] and lw >= 0.3 * rng and model == "C":
                    if m15_up[i] and h1_up[i]:                 # buy rejection
                        sig[i] = 1; break
        elif model == "D":
            if not (6 <= hr <= 17) or i < 2 or np.isnan(a[i]): continue
            tol = 0.15 * a[i]
            if l[i] > h[i - 2]:                                # bullish FVG
                mid = 0.5 * (l[i] + h[i - 2])
                if h1_up[i] and any(abs(mid - L) <= tol for L in levels[i]):
                    sig[i] = 1
            elif h[i] < l[i - 2]:                              # bearish FVG
                mid = 0.5 * (h[i] + l[i - 2])
                if (not h1_up[i]) and any(abs(mid - L) <= tol for L in levels[i]):
                    sig[i] = -1
    return sig


def stats(trades, t0, t1):
    nets = np.array([tr["net"] for tr in trades]) if trades else np.array([])
    def block(ns):
        if len(ns) == 0:
            return {"trades": 0, "wr": 0.0, "net": 0.0, "pf": 0.0, "avg_r": 0.0,
                    "max_dd": 0.0, "t_stat": 0.0}
        wins = ns[ns > 0]; losses = ns[ns <= 0]
        eq = np.cumsum(ns); dd = float(np.max(np.maximum.accumulate(eq) - eq)) if len(eq) else 0.0
        pf = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf")
        ts = float(ns.mean() / (ns.std(ddof=1) / math.sqrt(len(ns)))) if len(ns) > 1 and ns.std(ddof=1) > 0 else 0.0
        return {"trades": int(len(ns)), "wr": round(100.0 * len(wins) / len(ns), 1),
                "net": round(float(ns.sum()), 2), "pf": round(pf, 3) if pf != float("inf") else 999.0,
                "avg_r": 0.0, "max_dd": round(dd, 2), "t_stat": round(ts, 2)}
    full = block(nets)
    if trades:
        full["avg_r"] = round(float(np.mean([tr["r"] for tr in trades])), 3)
    mid = t0 + (t1 - t0) / 2
    h1 = block(np.array([tr["net"] for tr in trades if tr["t_in"] < mid]))
    h2 = block(np.array([tr["net"] for tr in trades if tr["t_in"] >= mid]))
    weeks = {}
    for tr in trades:
        wk = datetime.fromtimestamp(tr["t_in"], tz=timezone.utc).strftime("%G-W%V")
        weeks[wk] = round(weeks.get(wk, 0.0) + tr["net"], 2)
    return full, h1, h2, dict(sorted(weeks.items()))


def verdict(full, h1, h2):
    reasons = []
    if full["trades"] < 30: reasons.append(f"trades {full['trades']} < 30")
    if full["t_stat"] < 2.0: reasons.append(f"t-stat {full['t_stat']} < 2.0")
    if h1["net"] <= 0: reasons.append(f"first-half net {h1['net']} <= 0")
    if h2["net"] <= 0: reasons.append(f"second-half net {h2['net']} <= 0")
    return ("SURVIVOR", "") if not reasons else ("REJECTED", "; ".join(reasons))


def main():
    rates = fetch_rates()
    m5, m15, h1r = rates["M5"], rates["M15"], rates["H1"]
    cutoff = time.time() - DAYS * 86400
    m5 = m5[m5["time"] >= cutoff]
    m15 = m15[m15["time"] >= cutoff - 86400 * 3]
    h1r = h1r[h1r["time"] >= cutoff - 86400 * 5]
    t = m5["time"].astype(np.int64)
    span_d = (t[-1] - t[0]) / 86400.0
    print(f"Data: {len(t)} M5 bars, {datetime.fromtimestamp(t[0], tz=timezone.utc):%Y-%m-%d} -> "
          f"{datetime.fromtimestamp(t[-1], tz=timezone.utc):%Y-%m-%d} ({span_d:.1f} days), "
          f"{len(m15)} M15, {len(h1r)} H1 bars")
    o, h, l, c = (m5[k].astype(float) for k in ("open", "high", "low", "close"))
    ind = {"t": t, "o": o, "h": h, "l": l, "c": c,
           "atr": atr(h, l, c, 14), "ema20": ema(c, 20),
           "stoch": stoch_k(h, l, c, 14, 3)}
    # HTF trend context mapped without lookahead (last completed HTF bar)
    m15_e = ema(m15["close"].astype(float), 50)
    h1_e = ema(h1r["close"].astype(float), 50)
    i15, _ = map_htf(t, m15["time"].astype(np.int64), 900)
    i1, _ = map_htf(t, h1r["time"].astype(np.int64), 3600)
    ind["m15_up"] = m15["close"].astype(float)[i15] > m15_e[i15]
    ind["h1_up"] = h1r["close"].astype(float)[i1] > h1_e[i1]
    ind["levels"] = build_levels(t, h, l, c)

    names = {"A": "ASIA_SELL", "B": "ASIA_SELL_STRICT", "C": "LEVEL_REACT_MTF",
             "D": "FVG_AT_LEVEL", "E": "HYBRID_ASIA_LEVEL"}
    results = {"symbol": SYMBOL, "generated": datetime.now(timezone.utc).isoformat(),
               "span_days": round(span_d, 1), "m5_bars": int(len(t)),
               "cost_per_trade": COST, "models": {}}
    rows = []
    for m in "ABCDE":
        sig = signals(m, ind)
        trades = simulate(m, sig, ind, m)
        full, ha, hb, weeks = stats(trades, int(t[0]), int(t[-1]))
        v, why = verdict(full, ha, hb)
        results["models"][m] = {
            "name": names[m], "full": full, "first_half": ha, "second_half": hb,
            "weekly_net": weeks, "verdict": v, "reject_reason": why,
            "trades": trades}
        rows.append((m, names[m], full, ha, hb, v, why, weeks))

    import os
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(results, f, indent=1)
    print(f"Saved -> {OUT}\n")

    hdr = f"{'M':<2}{'Model':<19}{'N':>5}{'WR%':>7}{'Net$':>9}{'PF':>7}{'avgR':>7}{'DD$':>7}{'t':>7}{'H1$':>8}{'H2$':>8}  Verdict"
    print(hdr); print("-" * len(hdr))
    for m, nm, f_, a_, b_, v, why, _ in rows:
        print(f"{m:<2}{nm:<19}{f_['trades']:>5}{f_['wr']:>7}{f_['net']:>9}{f_['pf']:>7}"
              f"{f_['avg_r']:>7}{f_['max_dd']:>7}{f_['t_stat']:>7}{a_['net']:>8}{b_['net']:>8}  {v}"
              + (f" ({why})" if why else ""))
    print("\nPer-week net breakdown ($ per 0.01 lot):")
    for m, nm, *_rest, weeks in rows:
        print(f"  {m} {nm}: " + (", ".join(f"{k}:{v:+.2f}" for k, v in weeks.items()) or "no trades"))


if __name__ == "__main__":
    main()
