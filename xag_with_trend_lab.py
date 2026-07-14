"""xag_with_trend_lab.py — Does a WITH-TREND pullback-then-resume entry have a REAL
net-of-cost OOS edge on XAGUSDm (silver)?  [ruflo backtest-engineer role]

HYPOTHESIS (market-analyst proposal)
    Project prior: on volatile metals/indices/BTC, entering WITH the HTF trend beats
    counter-trend (counter-trend = falling-knife fat-tail risk). XAGUSDm led the
    truth-scoreboard (+0.3R lean, t<1.9, NOT significant at pooled n~1100). So the
    highest-prior candidate for a real with-trend edge = silver, with-trend pullback-
    resume.

SETUP TESTED (causal, no-lookahead)
    HTF trend (50-bar EMA50 slope, CLOSED bars only): at decision bar i, use last
        closed bar i-1. trend_up if EMA50[i-1] > EMA50[i-1-50] else trend_down.
        EMA50 recursive (k=2/51) on the SAME-TF close series.
    Entry (single-TF pullback-then-resume momentum, all indicators use bars <= i-1,
        entry at close[i]; conservative alt: open[i+1]):
        LONG  (trend_up):  RSI14(Wilder,causal)[i-1] < 50  AND  close[i] > close[i-1]
                           AND  close[i] > EMA20[i-1]
        SHORT (trend_down): mirror (RSI[i-1] > 50, close[i] < close[i-1], close[i] < EMA20[i-1])
    Risk R = 1.5 * ATR14[i-1] (causal). SL 1R against. Exits tested:
        fixed-R TP at R_MULT in {1.0, 1.5, 2.0}; ATR-chandelier trail (TRAIL_ATR*ATR, no TP).
        Horizon time-stop = 30 bars.
    NET-OF-SPREAD: round-trip XAG spread $0.03 charged in R (spread/R) per trade.

RIGOR (NON-NEGOTIABLE, copied from explosion_ride_lab causal machinery)
    causal ATR/EMA/RSI (bars <= i-1); intrabar SL-first pessimism; OOS walk-forward
    N-block with block0=burn-in discarded; bootstrap 2000x 95% CI; random-bar baseline
    in the SAME OOS region (matched direction-mix). EDGE only if OOS expectancy CI
    strictly > 0 AND pooled walk-forward OOS CI > 0 AND beats random-baseline CI AND
    n>=30. Else NO_EDGE. Compare with-trend vs against-trend vs all to confirm the
    direction of the hypothesis. Do NOT manufacture an edge.

DATA  data/lab_cache/XAGUSDm_{M15,M5}.npz + _meta.json
RUN   C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe xag_with_trend_lab.py
NOTE  read-only research; no MT5 connection. Writes xag_with_trend_lab_results.json.
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")
RESULTS = os.path.join(CACHE, "xag_with_trend_lab_results.json")

SYMBOL = "XAGUSDm"
TFS = ("M15", "M5")
ATR_PERIOD = 14
RSI_PERIOD = 14
EMA_FAST = 20
EMA_SLOW = 50
SLOPE_WIN = 50          # 50-bar EMA50 slope window for the trend label
SL_ATR = 1.5            # initial risk R = SL_ATR * ATR (per proposal)
R_MULT = (1.0, 1.5, 2.0)
TRAIL_ATR = 2.0
HORIZON = 30            # forward bars time-stop
SPREAD = 0.03           # round-trip XAG spread in price ($), charged in R
ENTRY_MODES = ("close_i", "open_i1")   # close[i] vs conservative open[i+1] fill
N_BLOCKS = 5            # walk-forward blocks; block0 = burn-in (discarded)
IS_FRACTION = 0.67      # 67/33 single OOS split
MIN_OOS = 30
BOOT = 2000
SEED = 17


def load_bars(tf):
    p = os.path.join(CACHE, f"{SYMBOL}_{tf}.npz")
    if not os.path.exists(p):
        return None
    d = np.load(p)
    return (d["t"].astype(np.int64), d["o"].astype(float), d["h"].astype(float),
            d["l"].astype(float), d["c"].astype(float), d["v"].astype(float))


def load_meta():
    p = os.path.join(CACHE, f"{SYMBOL}_meta.json")
    return json.load(open(p, encoding="utf-8-sig")) if os.path.exists(p) else {}


def money_per_unit(meta):
    tv, ts = meta.get("trade_tick_value"), meta.get("trade_tick_size") or meta.get("point")
    return float(tv) / float(ts) if (tv and ts and ts > 0) else 1.0


def atr(h, l, c, period=ATR_PERIOD):
    """Wilder/simple-mean ATR (matches reference). atr[i] uses bars 0..i (closed)."""
    n = h.size
    pc = np.empty(n); pc[0] = c[0]; pc[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(n, np.nan)
    if n >= period:
        cs = np.cumsum(tr)
        out[period - 1:] = (cs[period - 1:] - np.concatenate(([0.0], cs[:-period]))) / period
    return out


def ema(x, span):
    """Causal recursive EMA, k=2/(span+1). ema[i] depends only on x[0..i]."""
    n = x.size
    k = 2.0 / (span + 1.0)
    out = np.full(n, np.nan)
    out[0] = x[0]
    for i in range(1, n):
        out[i] = x[i] * k + out[i - 1] * (1.0 - k)
    return out


def rsi_wilder(c, period=RSI_PERIOD):
    """Causal Wilder RSI. rsi[i] uses closes 0..i only."""
    n = c.size
    out = np.full(n, np.nan)
    if n <= period:
        return out
    diff = np.diff(c)
    gain = np.where(diff > 0, diff, 0.0)
    loss = np.where(diff < 0, -diff, 0.0)
    ag = np.mean(gain[:period]); al = np.mean(loss[:period])
    rs = ag / al if al > 0 else np.inf
    out[period] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(period + 1, n):
        ag = (ag * (period - 1) + gain[i - 1]) / period
        al = (al * (period - 1) + loss[i - 1]) / period
        rs = ag / al if al > 0 else np.inf
        out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def trend_label(ema_slow):
    """Closed-bar 50-bar EMA50 slope sign. At decision bar i we read i-1:
    trend[i] = +1 if ema_slow[i-1] > ema_slow[i-1-SLOPE_WIN] else -1 (nan if not ready)."""
    n = ema_slow.size
    out = np.zeros(n, dtype=np.int8)
    for i in range(1, n):
        a = i - 1; b = i - 1 - SLOPE_WIN
        if b < 0 or not (np.isfinite(ema_slow[a]) and np.isfinite(ema_slow[b])):
            out[i] = 0
        else:
            out[i] = 1 if ema_slow[a] > ema_slow[b] else -1
    return out


def find_signals(o, h, l, c, a, ef, es, rsi, trend, mode):
    """Causal with-trend pullback-resume triggers. Returns list of entries with
    dir, side label (with/against), entry idx/price, sl. All conditions read bars
    <= i-1 except the close[i]>close[i-1] momentum & close[i] vs EMA20[i-1] (both
    use close[i], which is known at the decision bar i). Entry fill per `mode`."""
    n = c.size
    start = max(ATR_PERIOD + 1, RSI_PERIOD + 2, EMA_SLOW + SLOPE_WIN + 2)
    out = []
    for i in range(start, n - HORIZON - 2):
        tr = trend[i]
        if tr == 0:
            continue
        av = a[i - 1]
        r_i1 = rsi[i - 1]
        ef_i1 = ef[i - 1]
        if not (np.isfinite(av) and av > 0 and np.isfinite(r_i1) and np.isfinite(ef_i1)):
            continue
        mom_up = c[i] > c[i - 1]
        mom_dn = c[i] < c[i - 1]
        above = c[i] > ef_i1
        below = c[i] < ef_i1
        long_fire = (r_i1 < 50.0) and mom_up and above
        short_fire = (r_i1 > 50.0) and mom_dn and below
        d = 0
        if long_fire and not short_fire:
            d = 1
        elif short_fire and not long_fire:
            d = -1
        else:
            continue
        # with-trend if entry dir matches trend label; else against-trend
        side = "with" if d == tr else "against"
        # entry fill
        if mode == "close_i":
            ei = i
            entry = c[i]
        else:  # open_i1 conservative next-bar fill
            ei = i + 1
            if ei >= n - HORIZON - 1:
                continue
            entry = o[ei]
        R = SL_ATR * av
        sl = entry - R if d > 0 else entry + R
        out.append({"i": int(i), "ei": int(ei), "dir": int(d), "side": side,
                    "trend": int(tr), "entry": float(entry), "sl": float(sl),
                    "atr": float(av)})
    return out


def sim_fixed(h, l, c, entry_idx, d, entry, sl, tp_R, horizon):
    n = c.size
    R = abs(entry - sl)
    if R <= 0:
        return None
    tp = entry + tp_R * R if d > 0 else entry - tp_R * R
    last = min(entry_idx + horizon, n - 1)
    for j in range(entry_idx + 1, last + 1):
        hi, lo = h[j], l[j]
        hit_sl = (lo <= sl) if d > 0 else (hi >= sl)
        hit_tp = (hi >= tp) if d > 0 else (lo <= tp)
        if hit_sl:                       # SL-first pessimism (both -> SL)
            return -1.0
        if hit_tp:
            return float(tp_R)
    px = c[last]
    return float((px - entry) / R if d > 0 else (entry - px) / R)


def sim_trail(h, l, c, a, entry_idx, d, entry, sl0, horizon):
    n = c.size
    R = abs(entry - sl0)
    if R <= 0:
        return None
    last = min(entry_idx + horizon, n - 1)
    stop = sl0
    extreme = entry
    for j in range(entry_idx + 1, last + 1):
        hi, lo = h[j], l[j]
        hit = (lo <= stop) if d > 0 else (hi >= stop)   # check CURRENT stop intrabar first
        if hit:
            return float((stop - entry) / R if d > 0 else (entry - stop) / R)
        av = a[j] if (np.isfinite(a[j]) and a[j] > 0) else R   # update off now-closed bar
        if d > 0:
            extreme = max(extreme, hi)
            stop = max(stop, extreme - TRAIL_ATR * av)
        else:
            extreme = min(extreme, lo)
            stop = min(stop, extreme + TRAIL_ATR * av)
    px = c[last]
    return float((px - entry) / R if d > 0 else (entry - px) / R)


def run(h, l, c, a, sigs, exit_kind, tp_R, spread):
    netR = []
    for s in sigs:
        ei, d, entry, sl = s["ei"], s["dir"], s["entry"], s["sl"]
        R = abs(entry - sl)
        if R <= 0:
            continue
        if exit_kind == "fixed":
            rr = sim_fixed(h, l, c, ei, d, entry, sl, tp_R, HORIZON)
        else:
            rr = sim_trail(h, l, c, a, ei, d, entry, sl, HORIZON)
        if rr is None:
            continue
        netR.append(rr - spread / R)
    return np.asarray(netR)


def boot_ci(arr, rng):
    if arr.size == 0:
        return None
    m = np.empty(BOOT); n = arr.size
    for b in range(BOOT):
        m[b] = np.mean(arr[rng.integers(0, n, n)])
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def summ(arr, rng):
    if arr.size == 0:
        return {"n": 0, "expR": None, "wr": None, "ci95": None, "ci_pos": False,
                "t_stat": None}
    ci = boot_ci(arr, rng)
    sd = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    t = float(np.mean(arr) / (sd / np.sqrt(arr.size))) if sd > 0 else None
    return {"n": int(arr.size), "expR": float(np.mean(arr)),
            "wr": float(np.mean(arr > 0)), "ci95": ci,
            "ci_pos": bool(ci and ci[0] > 0), "t_stat": t}


def walk_forward(h, l, c, a, sigs, exit_kind, tp_R, spread, n, rng):
    """N-block walk-forward over bar index. block0 = burn-in (discarded). Pool
    blocks 1..N-1 OOS netR and bootstrap a pooled CI."""
    edges = [int(n * k / N_BLOCKS) for k in range(N_BLOCKS + 1)]
    per, pooled = [], []
    for b in range(N_BLOCKS):
        lo, hi = edges[b], edges[b + 1]
        blk = [s for s in sigs if lo <= s["i"] < hi]
        r = run(h, l, c, a, blk, exit_kind, tp_R, spread)
        s = summ(r, rng); s["block"] = b; s["burn_in"] = (b == 0)
        per.append(s)
        if b >= 1:
            pooled.append(r)
    pa = np.concatenate(pooled) if pooled else np.array([])
    return {"per_block": per, "pooled_oos": summ(pa, rng)}


def random_baseline(h, l, c, a, lo_i, hi_i, n_ent, dpf, exit_kind, tp_R, spread, rng):
    """Random-bar entries in the SAME OOS region, matched direction-mix (dpf =
    P(long)), same SL/exit logic. Returns mean + 95% CI of per-draw expectancy."""
    n = c.size
    valid = np.asarray([i for i in range(max(lo_i, ATR_PERIOD + 2), min(hi_i, n - HORIZON - 2))
                        if np.isfinite(a[i - 1]) and a[i - 1] > 0], dtype=np.int64)
    if valid.size < 5 or n_ent < 1:
        return None
    avgs = np.empty(BOOT)
    for b in range(BOOT):
        picks = rng.choice(valid, size=n_ent, replace=True)
        dd = np.where(rng.random(n_ent) < dpf, 1, -1)
        rs = []
        for i, d in zip(picks, dd):
            entry = c[i]; av = a[i - 1]
            R = SL_ATR * av
            sl = entry - R if d > 0 else entry + R
            if R <= 0:
                continue
            rr = (sim_fixed(h, l, c, int(i), int(d), float(entry), float(sl), tp_R, HORIZON)
                  if exit_kind == "fixed" else
                  sim_trail(h, l, c, a, int(i), int(d), float(entry), float(sl), HORIZON))
            if rr is not None:
                rs.append(rr - spread / R)
        avgs[b] = np.mean(rs) if rs else 0.0
    return {"mean": float(np.mean(avgs)), "ci_lo": float(np.percentile(avgs, 2.5)),
            "ci_hi": float(np.percentile(avgs, 97.5))}


def fmt(x):
    return "  n/a" if x is None else f"{x:+.3f}"


def analyze(tf, rng):
    bars = load_bars(tf)
    if bars is None:
        return {"error": f"no data {tf}"}
    t, o, h, l, c, v = bars
    n = c.size
    meta = load_meta(); mpu = money_per_unit(meta)
    a = atr(h, l, c)
    ef = ema(c, EMA_FAST); es = ema(c, EMA_SLOW)
    rsi = rsi_wilder(c)
    trend = trend_label(es)
    tr_up = float(np.mean(trend[trend != 0] == 1)) if np.any(trend != 0) else None

    res = {"symbol": SYMBOL, "tf": tf, "bars": int(n),
           "span_days": float((t[-1] - t[0]) / 86400), "mpu": mpu,
           "trend_up_frac": tr_up, "atr_median": float(np.nanmedian(a)),
           "sl_atr": SL_ATR, "r_mult": list(R_MULT), "trail_atr": TRAIL_ATR,
           "horizon": HORIZON, "spread": SPREAD, "n_blocks": N_BLOCKS,
           "is_fraction": IS_FRACTION, "boot": BOOT}

    cells = {}
    for mode in ENTRY_MODES:
        sigs_all = find_signals(o, h, l, c, a, ef, es, rsi, trend, mode)
        oos_i = int(n * IS_FRACTION)
        sigs_oos = [s for s in sigs_all if s["i"] >= oos_i]
        res[f"n_signals_{mode}"] = len(sigs_all)
        res[f"n_oos_{mode}"] = len(sigs_oos)

        def subset(lst, side):
            if side == "all":
                return lst
            return [s for s in lst if s["side"] == side]

        # exit grid x side, on OOS (single 67/33 split)
        for side in ("with", "against", "all"):
            ss = subset(sigs_oos, side)
            for label, (ek, tp) in {"fixed_1.0R": ("fixed", 1.0),
                                    "fixed_1.5R": ("fixed", 1.5),
                                    "fixed_2.0R": ("fixed", 2.0),
                                    "trail": ("trail", None)}.items():
                r = run(h, l, c, a, ss, ek, tp, SPREAD)
                cells[f"{mode}|{side}|{label}"] = summ(r, rng)

        # walk-forward for with-trend on each exit (the hypothesis side)
        wf = {}
        for label, (ek, tp) in {"fixed_1.0R": ("fixed", 1.0),
                                "fixed_1.5R": ("fixed", 1.5),
                                "fixed_2.0R": ("fixed", 2.0),
                                "trail": ("trail", None)}.items():
            wf[label] = walk_forward(h, l, c, a, subset(sigs_all, "with"),
                                     ek, tp, SPREAD, n, rng)
        res[f"walk_forward_with_{mode}"] = wf

        # random baseline (OOS) matched dir-mix, for fixed_1.0R and trail
        with_oos = subset(sigs_oos, "with")
        dpf = float(np.mean([1.0 if s["dir"] > 0 else 0.0 for s in with_oos])) if with_oos else 0.5
        res[f"random_baseline_{mode}_oos"] = {
            "fixed_1.0R": random_baseline(h, l, c, a, oos_i, n, len(with_oos), dpf, "fixed", 1.0, SPREAD, rng),
            "trail": random_baseline(h, l, c, a, oos_i, n, len(with_oos), dpf, "trail", None, SPREAD, rng),
        }
        # spread sensitivity (with-trend, fixed_1.0R, OOS): gross vs net
        res[f"spread_sensitivity_with_{mode}_fixed1R_oos"] = {
            f"spread_{sp}": summ(run(h, l, c, a, with_oos, "fixed", 1.0, sp), rng)
            for sp in (0.0, 0.03, 0.06)
        }

    res["cells_oos"] = cells
    return res


def best_cell(res):
    """Pick the best honest WITH-TREND OOS cell (close_i preferred for n) by expR
    among those with n>=MIN_OOS; return its full qualification check."""
    best = None
    for key, s in res["cells_oos"].items():
        mode, side, label = key.split("|")
        if side != "with" or s["n"] < MIN_OOS or s["expR"] is None:
            continue
        if best is None or s["expR"] > best[1]["expR"]:
            best = (key, s)
    return best


def verdict_for(res):
    """EDGE iff there exists a WITH-TREND OOS cell with: CI strictly>0 AND pooled
    walk-forward OOS CI>0 AND beats random baseline CI_hi AND n>=MIN_OOS."""
    for key, s in res["cells_oos"].items():
        mode, side, label = key.split("|")
        if side != "with" or s["n"] < MIN_OOS or not s["ci_pos"]:
            continue
        wf = res.get(f"walk_forward_with_{mode}", {}).get(label, {}).get("pooled_oos", {})
        if not wf.get("ci_pos"):
            continue
        rb_key = "fixed_1.0R" if label.startswith("fixed_1.0") else ("trail" if label == "trail" else None)
        rb = res.get(f"random_baseline_{mode}_oos", {}).get(rb_key) if rb_key else None
        if rb and s["expR"] is not None and s["expR"] <= rb["ci_hi"]:
            continue
        return "EDGE", key
    return "NO_EDGE", None


def main():
    rng = np.random.default_rng(SEED)
    print("=" * 96)
    print("xag_with_trend_lab — WITH-TREND pullback-resume on XAGUSDm: real net-of-cost OOS edge?")
    print(f"trend=EMA{EMA_SLOW} {SLOPE_WIN}-bar slope(closed) | entry: RSI{RSI_PERIOD}<>50 + momentum + EMA{EMA_FAST} cross")
    print(f"R={SL_ATR}xATR | exits fixed1/1.5/2R + ATR-trail({TRAIL_ATR}) | horizon={HORIZON} | spread=${SPREAD} net")
    print(f"OOS {int(IS_FRACTION*100)}/{int((1-IS_FRACTION)*100)} + walk-fwd{N_BLOCKS}(blk0 burn-in) | boot={BOOT} | with vs against vs all")
    print("PRIOR: scoreboard XAG +0.3R lean (t<1.9, NOT sig); almost nothing survives net-of-cost OOS.")
    print("=" * 96)
    out = {"ts": datetime.now(timezone.utc).isoformat(), "config": {
        "symbol": SYMBOL, "tfs": list(TFS), "sl_atr": SL_ATR, "r_mult": list(R_MULT),
        "trail_atr": TRAIL_ATR, "horizon": HORIZON, "spread": SPREAD, "ema_fast": EMA_FAST,
        "ema_slow": EMA_SLOW, "slope_win": SLOPE_WIN, "rsi_period": RSI_PERIOD,
        "n_blocks": N_BLOCKS, "is_fraction": IS_FRACTION, "boot": BOOT, "seed": SEED,
        "no_lookahead": "ATR/RSI/EMA causal (<=i-1 for trend & filters); momentum & EMA20 "
                        "cross use close[i] known at decision bar; entry close[i] or open[i+1]; "
                        "fwd sim bars>entry only; trail off closed bars; intrabar SL-first; "
                        "walk-fwd block0=burn-in discarded",
        "cost": "round-trip XAG spread $0.03 in R per trade"}, "results": {}}

    for tf in TFS:
        r = analyze(tf, rng); out["results"][tf] = r
        if "error" in r:
            print(f"\n{tf}: ERROR {r['error']}"); continue
        print(f"\n{'#'*96}\n{SYMBOL} {tf} bars={r['bars']} span={r['span_days']:.0f}d "
              f"trend_up={100*r['trend_up_frac']:.0f}% ATRmed=${r['atr_median']:.3f} $/unit/lot={r['mpu']:.0f}")
        for mode in ENTRY_MODES:
            print(f"  -- entry={mode}  signals={r[f'n_signals_{mode}']} (OOS={r[f'n_oos_{mode}']}) --")
            print(f"     {'cell':<14}{'with expR(n)':>20}{'against expR(n)':>22}{'all expR(n)':>20}")
            for label in ("fixed_1.0R", "fixed_1.5R", "fixed_2.0R", "trail"):
                row = []
                for side in ("with", "against", "all"):
                    s = r["cells_oos"][f"{mode}|{side}|{label}"]
                    row.append(f"{fmt(s['expR'])}(n{s['n']})")
                flag = "CI>0" if r["cells_oos"][f"{mode}|with|{label}"]["ci_pos"] else ""
                print(f"     {label:<14}{row[0]:>20}{row[1]:>22}{row[2]:>20}  {flag}")
            wf = r[f"walk_forward_with_{mode}"]
            for label in ("fixed_1.0R", "trail"):
                p = wf[label]["pooled_oos"]; ci = p["ci95"]
                print(f"     WF with {label:<10} pooled-OOS expR={fmt(p['expR'])} n={p['n']} "
                      f"CI={f'[{fmt(ci[0])},{fmt(ci[1])}]' if ci else 'n/a'} t={fmt(p['t_stat'])} {'CI>0' if p['ci_pos'] else ''}")
            rb = r[f"random_baseline_{mode}_oos"]
            for label in ("fixed_1.0R", "trail"):
                b = rb[label]
                if b:
                    print(f"     RAND with {label:<10} CI=[{fmt(b['ci_lo'])},{fmt(b['ci_hi'])}] mean {fmt(b['mean'])}")
            ss = r[f"spread_sensitivity_with_{mode}_fixed1R_oos"]
            sline = "  ".join(f"sp${sp}={fmt(ss[f'spread_{sp}']['expR'])}" for sp in (0.0, 0.03, 0.06))
            print(f"     SPREAD-SENS with fixed1R OOS (gross->net): {sline}")
        bc = best_cell(r); v, vkey = verdict_for(r)
        if bc:
            print(f"  BEST with-trend OOS cell: {bc[0]} expR={fmt(bc[1]['expR'])} n={bc[1]['n']} "
                  f"CI={bc[1]['ci95']} t={fmt(bc[1]['t_stat'])}")
        print(f"  VERDICT[{tf}]: {v}{(' @ '+vkey) if vkey else ''}")
        r["best_cell"] = {"key": bc[0], **bc[1]} if bc else None
        r["verdict"] = v; r["verdict_key"] = vkey

    os.makedirs(CACHE, exist_ok=True)
    json.dump(out, open(RESULTS, "w", encoding="utf-8"), indent=2)
    print(f"\nSaved -> {RESULTS}")
    return out


if __name__ == "__main__":
    main()
