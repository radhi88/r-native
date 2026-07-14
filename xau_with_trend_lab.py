"""xau_with_trend_lab.py — Does a WITH-TREND EMA20 pullback-resume entry, gated by
a CAUSAL M15 EMA50-slope trend, have a NET-of-spread OOS edge on XAUUSDm?
(ruflo backtest-engineer; FRIDAY's own verified causal machinery.)

HYPOTHESIS (market-analyst, falsifiable)
    Scoreboard leaned XAUUSDm +0.3R (NOT significant, t<1.9). Project prior: on
    volatile symbols (metals/indices/BTC) entering WITH the higher-TF trend beats
    counter-trend (counter-trend = fat-tail risk). Candidate edge = WITH-trend
    pullback-then-resume entries.

    HTF trend (CAUSAL): M15 EMA50, slope_k = EMA50_k - EMA50_{k-50}. UP if slope>0,
      DOWN if slope<0. Mapped to each entry bar i via the LAST FULLY-CLOSED M15 bar
      (m15_open_time + 900s <= entry_open_time[i]); that M15 trend value itself uses
      only closed M15 bars <= k. => no lookahead at all.
    Entry-TF: M5 (primary, ~209d) and M15 (variant, gated by its own M15 trend).
      Decision inputs use bars <= i-1; trigger confirmed at close[i].
      LONG (HTF==UP):   low[i-1] <= EMA20[i-1]  (pullback under fast mean)
                        AND close[i] > close[i-1] AND close[i] > open[i] (resume up).
      SHORT (HTF==DOWN): high[i-1] >= EMA20[i-1] AND close[i]<close[i-1] AND close[i]<open[i].
      Enter at close[i] (causal); SHIFT variant enters at open[i+1] (stricter).
    SL/TP: R = SL_ATR * ATR14(entry-TF at entry), SL_ATR=1.5, SL against trade.
      TP swept {1.0R,1.5R,2.0R} + ATR(2.5) chandelier trail. HORIZON=48 bars.
    Cost: round-trip XAU spread $0.30 -> spread/R per trade (NET reported). Swept.

RIGOR (non-negotiable)
    Causal only: EMA/ATR closed bars; HTF reads only fully-closed M15; fwd sim
      reads bars>entry; intrabar SL-FIRST pessimism. OOS only: headline = latest
      33% tail; walk-forward N-block (block0 burn-in discarded, pool 1..N-1).
      Bootstrap 2000x 95% CI. Random-bar baseline (same OOS region, same long/short
      mix, same exit/spread). EDGE requires on the BEST with-cell: OOS net CI>0 AND
      walk-fwd pooled CI>0 AND OOS expR beats random CI_hi AND n>=30. Else NO_EDGE.
    CONTROLS: with vs against (mirror) vs all (no gate) on the SAME trigger.

DATA  data/lab_cache/XAUUSDm_{M5,M15}.npz + _meta.json (tick_value/tick_size).
RUN   C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe xau_with_trend_lab.py
NOTE  read-only research. No MT5, no order_send. Writes
      data/lab_cache/xau_with_trend_lab_results.json
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")
RESULTS = os.path.join(CACHE, "xau_with_trend_lab_results.json")

SYMBOL = "XAUUSDm"
TF_SECONDS = {"M5": 300, "M15": 900, "H1": 3600}
# (exec_tf, htf_tf): M5 gated by M15 (true HTF/LTF); M15 gated by M15 (within-TF
# trend filter — the proposal's M15 variant).
SETUPS = [("M5", "M15"), ("M15", "M15")]

EMA_HTF = 50            # M15 trend EMA
SLOPE_LOOKBACK = 50     # EMA50_k - EMA50_{k-50}
ATR_PERIOD = 14
EMA_EXEC = 20           # execution-TF pullback fast mean
SL_ATR = 1.5
TP_RS = (1.0, 1.5, 2.0)
TRAIL_ATR = 2.5
HORIZON = 48            # forward bars time-stop
SPREAD_USD = 0.30       # round-trip XAU spread estimate ($, price units)
SPREAD_SWEEP = (0.15, 0.30, 0.50)
N_BLOCKS = 5            # block0 = burn-in
IS_FRACTION = 0.67      # headline OOS = latest 33%
MIN_OOS = 30
BOOT = 2000
SEED = 17


# --------------------------------------------------------------------------- #
def load_bars(tf):
    p = os.path.join(CACHE, f"{SYMBOL}_{tf}.npz")
    if not os.path.exists(p):
        return None
    d = np.load(p)
    return (d["t"].astype(np.int64), d["o"].astype(float), d["h"].astype(float),
            d["l"].astype(float), d["c"].astype(float), d["v"].astype(float))


def load_meta():
    p = os.path.join(CACHE, f"{SYMBOL}_meta.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8-sig"))
    return {}


def money_per_unit(meta):
    tv, ts = meta.get("trade_tick_value"), meta.get("trade_tick_size") or meta.get("point")
    return float(tv) / float(ts) if (tv and ts and ts > 0) else 1.0


# --------------------------------------------------------------------------- #
# Indicators (causal). value at bar k uses bars <= k; as a DECISION input at bar i
# we reference i-1 (last closed bar) for the pullback test.
def ema(c, period):
    n = c.size
    out = np.full(n, np.nan)
    if n < period:
        return out
    k = 2.0 / (period + 1.0)
    seed = float(np.mean(c[:period]))
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = c[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def atr(h, l, c, period=ATR_PERIOD):
    n = h.size
    pc = np.empty(n); pc[0] = c[0]; pc[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(n, np.nan)
    if n >= period:
        cs = np.cumsum(tr)
        out[period - 1:] = (cs[period - 1:] - np.concatenate(([0.0], cs[:-period]))) / period
    return out


def htf_trend_series(c_htf):
    """trend label per HTF bar k, known at CLOSE of k. +1/-1/0(insufficient hist).
    slope = EMA50_k - EMA50_{k-50}, sign only (matches proposal: UP slope>0)."""
    e = ema(c_htf, EMA_HTF)
    n = c_htf.size
    lab = np.zeros(n, dtype=np.int8)
    for k in range(n):
        if k < SLOPE_LOOKBACK or not np.isfinite(e[k]) or not np.isfinite(e[k - SLOPE_LOOKBACK]):
            continue
        slope = e[k] - e[k - SLOPE_LOOKBACK]
        lab[k] = 1 if slope > 0 else (-1 if slope < 0 else 0)
    return lab


def map_htf_to_exec(t_exec, t_htf, htf_sec):
    """For each exec bar i, the LAST FULLY-CLOSED HTF bar k with t_htf[k]+htf_sec
    <= t_exec[i] (entry bar's OPEN time). Returns idx array (-1 where none)."""
    close_htf = t_htf + htf_sec
    return np.searchsorted(close_htf, t_exec, side="right") - 1


# --------------------------------------------------------------------------- #
def find_triggers(o, h, l, c, ema_exec, htf_lab_at_exec):
    """Causal pullback-resume geometry. Returns triggers tagged with bull/bear
    geometry + HTF trend at i. Decision inputs use i-1 (EMA) and close[i]."""
    n = c.size
    out = []
    start = max(EMA_EXEC + 1, ATR_PERIOD + 1, 2)
    for i in range(start, n - HORIZON - 2):
        e_im1 = ema_exec[i - 1]
        if not np.isfinite(e_im1):
            continue
        bull = (l[i - 1] <= e_im1) and (c[i] > c[i - 1]) and (c[i] > o[i])
        bear = (h[i - 1] >= e_im1) and (c[i] < c[i - 1]) and (c[i] < o[i])
        if not (bull or bear):
            continue
        out.append({"i": int(i), "bull": bool(bull), "bear": bool(bear),
                    "trend": int(htf_lab_at_exec[i])})
    return out


def trade_dir(trig, gate):
    """with: trade in trend dir, trigger geometry must agree (LONG in UP w/ bull).
    against: same pullback-resume but counter to trend (LONG-bull while DOWN).
    all: trade the trigger's own geometric direction, no trend gate."""
    tr = trig["trend"]
    bull, bear = trig["bull"], trig["bear"]
    geo = 1 if (bull and not bear) else (-1 if (bear and not bull) else 0)
    if gate == "all":
        return geo
    if tr == 0 or geo == 0:
        return 0
    if gate == "with":
        return geo if geo == tr else 0
    if gate == "against":
        return geo if geo != tr else 0
    return 0


# --------------------------------------------------------------------------- #
def sim_fixed(h, l, c, ei, d, entry, sl, tp_R):
    n = c.size
    R = abs(entry - sl)
    if R <= 0:
        return None
    tp = entry + tp_R * R if d > 0 else entry - tp_R * R
    last = min(ei + HORIZON, n - 1)
    for j in range(ei + 1, last + 1):
        hi, loo = h[j], l[j]
        hit_sl = (loo <= sl) if d > 0 else (hi >= sl)
        hit_tp = (hi >= tp) if d > 0 else (loo <= tp)
        if hit_sl:                       # SL-first pessimism (covers both-touched)
            return -1.0
        if hit_tp:
            return float(tp_R)
    px = c[last]
    return float((px - entry) / R if d > 0 else (entry - px) / R)


def sim_trail(h, l, c, a, ei, d, entry, sl0):
    n = c.size
    R = abs(entry - sl0)
    if R <= 0:
        return None
    last = min(ei + HORIZON, n - 1)
    stop = sl0
    extreme = entry
    for j in range(ei + 1, last + 1):
        hi, loo = h[j], l[j]
        hit = (loo <= stop) if d > 0 else (hi >= stop)   # current stop, intrabar first
        if hit:
            return float((stop - entry) / R if d > 0 else (entry - stop) / R)
        av = a[j] if np.isfinite(a[j]) and a[j] > 0 else R
        if d > 0:
            extreme = max(extreme, hi)
            stop = max(stop, extreme - TRAIL_ATR * av)
        else:
            extreme = min(extreme, loo)
            stop = min(stop, extreme + TRAIL_ATR * av)
    px = c[last]
    return float((px - entry) / R if d > 0 else (entry - px) / R)


def run(o, h, l, c, a, trigs, gate, exit_kind, tp_R, spread, shift):
    netR = []
    n = c.size
    for trig in trigs:
        d = trade_dir(trig, gate)
        if d == 0:
            continue
        i = trig["i"]
        if shift:
            ei = i + 1
            if ei >= n - 1:
                continue
            entry = o[ei]
        else:
            ei = i
            entry = c[ei]
        av = a[ei] if (np.isfinite(a[ei]) and a[ei] > 0) else None
        if av is None:
            continue
        sl = entry - SL_ATR * av if d > 0 else entry + SL_ATR * av
        R = abs(entry - sl)
        if R <= 0:
            continue
        r = (sim_fixed(h, l, c, ei, d, float(entry), float(sl), tp_R) if exit_kind == "fixed"
             else sim_trail(h, l, c, a, ei, d, float(entry), float(sl)))
        if r is None:
            continue
        netR.append(r - spread / R)
    return np.asarray(netR)


# --------------------------------------------------------------------------- #
def boot_ci(arr, rng):
    if arr.size == 0:
        return None
    m = np.empty(BOOT); n = arr.size
    for b in range(BOOT):
        m[b] = np.mean(arr[rng.integers(0, n, n)])
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def summ(arr, rng):
    if arr.size == 0:
        return {"n": 0, "expR": None, "wr": None, "ci95": None, "ci_pos": False, "t_stat": None}
    ci = boot_ci(arr, rng)
    m = float(np.mean(arr))
    sd = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    t = (m * np.sqrt(arr.size) / sd) if sd > 0 else 0.0
    return {"n": int(arr.size), "expR": m, "wr": float(np.mean(arr > 0)), "ci95": ci,
            "ci_pos": bool(ci and ci[0] > 0), "t_stat": float(t)}


def walk_forward(o, h, l, c, a, trigs, gate, exit_kind, tp_R, spread, n_bars, rng):
    edges = [int(n_bars * k / N_BLOCKS) for k in range(N_BLOCKS + 1)]
    per, pooled = [], []
    for b in range(N_BLOCKS):
        lo, hi = edges[b], edges[b + 1]
        blk = [s for s in trigs if lo <= s["i"] < hi]
        r = run(o, h, l, c, a, blk, gate, exit_kind, tp_R, spread, shift=False)
        s = summ(r, rng); s["block"] = b; s["burn_in"] = (b == 0)
        per.append(s)
        if b >= 1:
            pooled.append(r)
    pa = np.concatenate(pooled) if pooled else np.array([])
    out = summ(pa, rng)
    out["per_block"] = per
    return out


def random_baseline(o, h, l, c, a, lo_i, hi_i, n_ent, dpf, exit_kind, tp_R, spread, rng):
    n = c.size
    valid = np.asarray([i for i in range(max(lo_i, ATR_PERIOD + 1), min(hi_i, n - HORIZON - 1))
                        if np.isfinite(a[i]) and a[i] > 0], dtype=np.int64)
    if valid.size < 5 or n_ent < 1:
        return None
    avgs = np.empty(BOOT)
    for b in range(BOOT):
        picks = rng.choice(valid, size=n_ent, replace=True)
        dd = np.where(rng.random(n_ent) < dpf, 1, -1)
        rs = []
        for ei, d in zip(picks, dd):
            entry = c[ei]; av = a[ei]
            sl = entry - SL_ATR * av if d > 0 else entry + SL_ATR * av
            R = abs(entry - sl)
            if R <= 0:
                continue
            r = (sim_fixed(h, l, c, int(ei), int(d), float(entry), float(sl), tp_R)
                 if exit_kind == "fixed" else
                 sim_trail(h, l, c, a, int(ei), int(d), float(entry), float(sl)))
            if r is not None:
                rs.append(r - spread / R)
        avgs[b] = np.mean(rs) if rs else 0.0
    return {"mean": float(np.mean(avgs)), "ci_lo": float(np.percentile(avgs, 2.5)),
            "ci_hi": float(np.percentile(avgs, 97.5))}


# --------------------------------------------------------------------------- #
EXIT_GRID = {"fixed_1.0R": ("fixed", 1.0), "fixed_1.5R": ("fixed", 1.5),
             "fixed_2.0R": ("fixed", 2.0), "trail": ("trail", None)}


def analyze(exec_tf, htf_tf, rng):
    eb = load_bars(exec_tf)
    tb = load_bars(htf_tf)
    if eb is None or tb is None:
        return {"error": f"no data {exec_tf}/{htf_tf}"}
    te, oe, he, le, ce, ve = eb
    th, oh, hh, lh, ch, vh = tb
    n = ce.size
    meta = load_meta(); mpu = money_per_unit(meta)

    a = atr(he, le, ce)
    ema_exec = ema(ce, EMA_EXEC)
    htf_lab = htf_trend_series(ch)
    idx = map_htf_to_exec(te, th, TF_SECONDS[htf_tf])
    htf_lab_at_exec = np.zeros(n, dtype=np.int8)
    valid = idx >= 0
    htf_lab_at_exec[valid] = htf_lab[idx[valid]]
    cover = float(np.mean(valid))

    trigs = find_triggers(oe, he, le, ce, ema_exec, htf_lab_at_exec)
    oos_i = int(n * IS_FRACTION)
    oos = [s for s in trigs if s["i"] >= oos_i]

    tr_arr = np.array([s["trend"] for s in trigs]) if trigs else np.array([])
    dist = {"up": float(np.mean(tr_arr > 0)) if tr_arr.size else None,
            "down": float(np.mean(tr_arr < 0)) if tr_arr.size else None,
            "flat": float(np.mean(tr_arr == 0)) if tr_arr.size else None}

    res = {"symbol": SYMBOL, "exec_tf": exec_tf, "htf_tf": htf_tf, "bars": int(n),
           "span_days": float((te[-1] - te[0]) / 86400), "mpu": mpu,
           "htf_coverage": cover, "n_triggers": len(trigs), "n_triggers_oos": len(oos),
           "trend_dist_at_triggers": dist, "sl_atr": SL_ATR, "horizon": HORIZON,
           "spread_usd": SPREAD_USD, "oos_fraction": round(1 - IS_FRACTION, 2),
           "small_sample_oos": bool(len(oos) < MIN_OOS)}

    # HEADLINE: with/against/all x exit grid, OOS, enter close[i]
    headline = {}
    for gate in ("with", "against", "all"):
        headline[gate] = {}
        for lbl, (ek, tp) in EXIT_GRID.items():
            headline[gate][lbl] = summ(run(oe, he, le, ce, a, oos, gate, ek, tp, SPREAD_USD, False), rng)
    res["headline_oos"] = headline

    # BEST with-cell by OOS expR (n>=MIN_OOS)
    best_label = None; best_exp = -1e9
    for lbl, (ek, tp) in EXIT_GRID.items():
        cell = headline["with"][lbl]
        if cell["n"] >= MIN_OOS and cell["expR"] is not None and cell["expR"] > best_exp:
            best_exp = cell["expR"]; best_label = lbl
    res["best_with_cell"] = best_label

    if best_label is not None:
        ek, tp = EXIT_GRID[best_label]
        res["walk_forward_with_best"] = walk_forward(oe, he, le, ce, a, trigs, "with", ek, tp, SPREAD_USD, n, rng)
        res["best_with_entry_shift_oos"] = summ(run(oe, he, le, ce, a, oos, "with", ek, tp, SPREAD_USD, True), rng)
        with_dirs = [d for d in (trade_dir(s, "with") for s in oos) if d != 0]
        n_with = len(with_dirs)
        dpf = float(np.mean([1 if d > 0 else 0 for d in with_dirs])) if n_with else 0.5
        res["random_baseline_with_best_oos"] = random_baseline(oe, he, le, ce, a, oos_i, n, n_with, dpf, ek, tp, SPREAD_USD, rng)
        sw = {}
        for sp in SPREAD_SWEEP:
            sw[f"spread_{sp}"] = summ(run(oe, he, le, ce, a, oos, "with", ek, tp, sp, False), rng)
        res["spread_sensitivity_with_best_oos"] = sw
        res["best_with_gross_oos"] = summ(run(oe, he, le, ce, a, oos, "with", ek, tp, 0.0, False), rng)
    return res


def verdict_tf(res):
    if "error" in res:
        return "INCONCLUSIVE"
    bl = res.get("best_with_cell")
    if not bl:
        return "NO_EDGE"
    if res["n_triggers_oos"] < MIN_OOS:
        return "NO_EDGE"
    cell = res["headline_oos"]["with"][bl]
    if cell["n"] < MIN_OOS or not cell.get("ci_pos"):
        return "NO_EDGE"
    wf = res.get("walk_forward_with_best", {})
    if not wf.get("ci_pos"):
        return "NO_EDGE"
    rb = res.get("random_baseline_with_best_oos")
    if rb and cell["expR"] is not None and cell["expR"] <= rb["ci_hi"]:
        return "NO_EDGE"
    return "EDGE"


def fmt(x):
    return "  n/a" if x is None else f"{x:+.3f}"


def main():
    rng = np.random.default_rng(SEED)
    print("=" * 94)
    print("xau_with_trend_lab — XAUUSDm WITH-TREND pullback-resume: net-of-cost OOS edge?")
    print(f"HTF=M15 EMA50 50-bar slope sign | entry EMA20 pullback+resume | SL={SL_ATR}xATR "
          f"| TP {TP_RS}+trail({TRAIL_ATR}) | H={HORIZON} | spread=${SPREAD_USD}")
    print(f"OOS latest {int((1-IS_FRACTION)*100)}% + walk-fwd{N_BLOCKS}(blk0 burn-in) | boot={BOOT} | SL-first")
    print("CONTROLS: with vs against vs all. PRIOR: most XAU setups NO_EDGE net-of-cost.")
    print("=" * 94)
    out = {"ts": datetime.now(timezone.utc).isoformat(),
           "config": {"symbol": SYMBOL, "setups": SETUPS, "ema_htf": EMA_HTF,
                      "slope_lookback": SLOPE_LOOKBACK, "atr_period": ATR_PERIOD,
                      "ema_exec": EMA_EXEC, "sl_atr": SL_ATR, "tp_rs": list(TP_RS),
                      "trail_atr": TRAIL_ATR, "horizon": HORIZON, "spread_usd": SPREAD_USD,
                      "spread_sweep": list(SPREAD_SWEEP), "n_blocks": N_BLOCKS,
                      "is_fraction": IS_FRACTION, "boot": BOOT, "seed": SEED,
                      "no_lookahead": "EMA/ATR closed bars; M15 trend=sign(EMA50_k-EMA50_{k-50}) "
                                      "mapped via last M15 with open+900s<=entry open; trigger uses "
                                      "bars<=i-1 + close[i]; entry close[i] (or open[i+1] shift); fwd "
                                      "sim bars>entry; intrabar SL-first; walk-fwd blk0 burn-in"},
           "results": {}, "verdicts": {}}
    for exec_tf, htf_tf in SETUPS:
        key = f"{exec_tf}_via_{htf_tf}"
        r = analyze(exec_tf, htf_tf, rng)
        out["results"][key] = r
        v = verdict_tf(r); out["verdicts"][key] = v
        if "error" in r:
            print(f"\n{key}: ERROR {r['error']}"); continue
        d = r["trend_dist_at_triggers"]
        print(f"\n{'#'*94}\n{SYMBOL} entry={exec_tf} (trend={htf_tf}) bars={r['bars']} "
              f"span={r['span_days']:.0f}d cover={100*r['htf_coverage']:.0f}% "
              f"triggers={r['n_triggers']} (OOS={r['n_triggers_oos']}) $/unit/lot={r['mpu']:.0f}")
        print(f"  trend@trigger: up={100*d['up']:.0f}% down={100*d['down']:.0f}% flat={100*d['flat']:.0f}%")
        print("  -- HEADLINE OOS (net-of-spread, expR / wr / t / CI) --")
        for gate in ("with", "against", "all"):
            print(f"    [{gate.upper()}]")
            for lbl, s in r["headline_oos"][gate].items():
                ci = s["ci95"]; cis = f"[{fmt(ci[0])},{fmt(ci[1])}]" if ci else "n/a"
                wr = "n/a" if s["wr"] is None else f"{100*s['wr']:.0f}%"
                t = "n/a" if s["t_stat"] is None else f"{s['t_stat']:+.2f}"
                flag = " <CI>0" if s["ci_pos"] else ""
                print(f"      {lbl:<10} n={s['n']:<5} expR={fmt(s['expR'])} wr={wr:<5} t={t:<6} CI={cis}{flag}")
        bl = r.get("best_with_cell")
        if bl:
            wf = r.get("walk_forward_with_best", {}); wci = wf.get("ci95")
            print(f"  -- BEST WITH cell = {bl} --")
            print(f"     walk-fwd pooled OOS: expR={fmt(wf.get('expR'))} n={wf.get('n')} "
                  f"t={'n/a' if wf.get('t_stat') is None else f'{wf['t_stat']:+.2f}'} "
                  f"CI={f'[{fmt(wci[0])},{fmt(wci[1])}]' if wci else 'n/a'} "
                  f"{'POOLED-CI>0' if wf.get('ci_pos') else ''}")
            blkstr = " ".join(f"b{p['block']}{'(burn)' if p['burn_in'] else ''}={fmt(p['expR'])}(n{p['n']})"
                              for p in wf.get("per_block", []))
            print(f"     per-block: {blkstr}")
            sh = r.get("best_with_entry_shift_oos", {})
            shci = sh.get("ci95")
            print(f"     entry-shift open[i+1] OOS: expR={fmt(sh.get('expR'))} n={sh.get('n')} "
                  f"CI={f'[{fmt(shci[0])},{fmt(shci[1])}]' if shci else 'n/a'}")
            rb = r.get("random_baseline_with_best_oos")
            if rb:
                print(f"     random baseline (same region/dir-mix): mean={fmt(rb['mean'])} "
                      f"CI=[{fmt(rb['ci_lo'])},{fmt(rb['ci_hi'])}]")
            g = r.get("best_with_gross_oos", {})
            print(f"     GROSS (spread=0) OOS: expR={fmt(g.get('expR'))}  (net headline above)")
            sw = r.get("spread_sensitivity_with_best_oos", {})
            print(f"     spread-sweep: " + "  ".join(f"${k.split('_')[1]}={fmt(v['expR'])}" for k, v in sw.items()))
        print(f"  VERDICT [{key}]: {v}")

    print("\n" + "=" * 94)
    print(f"OVERALL VERDICTS: {out['verdicts']}")
    print("=" * 94)
    os.makedirs(CACHE, exist_ok=True)
    json.dump(out, open(RESULTS, "w", encoding="utf-8"), indent=2)
    print(f"Saved -> {RESULTS}")
    return out


if __name__ == "__main__":
    main()
