"""explosion_ride_lab.py — Does RIDING an M1 price explosion pay, and HOW MUCH
does our ENTRY LATENCY cost? (XAUUSDm + US30m, M1, ~100 days)

WHY THIS EXISTS
    Live event 2026-06-19: gold exploded down ~$18 in the butter window and our
    system entered a 0.01 SELL at 4176 — about 8 M1 bars / ~$4 AFTER the move,
    near the exhaustion low. The user (rightly) asks: why is our response so
    slow, and can we enter WITH the explosion, fast, and size up when confident?

    Two prior facts we must respect:
      * FADE (against the spike) = significant LOSER (-0.18..-0.72R), confirmed.
      * RIDE (with the spike) = the "less bad" side but NO_EDGE at M5 entering at
        the spike-bar close; gold-ride looked +0.25R on one split but collapsed
        under walk-forward (window artifact).
    The NEW question is fair to the user's actual claim and tests the thing we
    can actually FIX — speed:
      (Q1) Is RIDE +EV if we enter FAST (on the explosive M1 bar) vs LATE?
      (Q2) How much expectancy do we lose per bar of latency (our real bug)?
      (Q3) Does a trailing exit (let the explosion run) beat a fixed 1R cap?
      (Q4) Is there a high-CONFIDENCE subset (big volume surge / big body /
           streak) that is genuinely +EV — i.e. earns the right to a bigger lot?

WHAT IT DOES (honest, falsifiable, NO-lookahead)
    Detection (causal, known at close of bar i):
        explosion if |c[i]-o[i]| >= K*ATR(14)[i-1]  (body explosion)
                 OR vol[i] >= VZ * median(vol[i-50:i])  (volume surge)
        direction d = sign(c[i]-o[i]).  RIDE = trade WITH d.
    Entry-latency sweep: enter at the CLOSE of bar i+lag, lag in {0,1,2,4,8}.
        (lag=0 = instant on the explosive bar; lag=8 ≈ the ~8-bar lateness we
        actually showed live). Causal: we only ever use bars <= entry bar.
    Exits (per trade, intrabar SL-first pessimism):
        - fixedR: TP at R_MULT*R, SL = entry -/+ R (R = SL_ATR*ATR at entry).
        - trail:  ATR chandelier trailing stop (TRAIL_ATR*ATR), no fixed TP —
                  the "ride the explosion" exit. Time-stop at HORIZON.
    Confidence score per trade = z of (body/ATR) + z of (vol/medvol) + streak.
        We bucket into LOW / MID / HIGH and report expectancy per bucket — a
        +EV HIGH bucket is the only thing that would justify a bigger lot.
    Costs: WIDE explosion-moment spread (gold $0.5/1.0/1.5; US30 3/5/8), charged
        round-trip in R per trade (spread/R). Reported expectancy is NET.
    OOS: walk-forward 4 blocks (block0 = burn-in/IS, discarded) + 67/33 latest.
        Bootstrap 2000x 95% CI. Random-bar baseline in the SAME OOS region. EDGE
        requires the OOS expectancy CI strictly > 0 AND beating the random CI.
    Big-lot ruin: worst-R trade and worst-$ trade (each paired with its OWN
        counterpart, NOT multiplied across trades) on a 1.0 lot; continuation/
        adverse-excursion tail.

DATA  data/lab_cache/{XAUUSDm,US30m}_M1.npz  (~100k M1 bars) + _meta.json.
RUN   C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe explosion_ride_lab.py
NOTE  read-only research. No MT5 connection, no order_send. Writes
      data/lab_cache/explosion_ride_lab_results.json.
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")
RESULTS = os.path.join(CACHE, "explosion_ride_lab_results.json")

SYMBOLS = ["XAUUSDm", "US30m"]
TF = "M1"
ATR_PERIOD = 14
SPIKE_K = 2.0            # body explosion threshold (xATR)
VOL_Z = 3.0             # volume surge: vol >= VOL_Z * rolling median(50)
VOL_LOOKBACK = 50
SL_ATR = 1.0            # initial risk R = SL_ATR * ATR at entry
R_MULT = (1.0, 2.0)     # fixed-R take-profits to test
TRAIL_ATR = 2.0         # chandelier trailing-stop distance (xATR) for the ride
HORIZON = 30            # forward bars (=30 min on M1) time stop
LAGS = (0, 1, 2, 4, 8)  # entry latency in bars (8 ≈ our live lateness)
NEWS_SPREAD = {"XAUUSDm": [0.50, 1.00, 1.50], "US30m": [3.0, 5.0, 8.0]}
MID = 1
N_BLOCKS = 4
IS_FRACTION = 0.67
MIN_OOS = 30
BOOT = 2000
SEED = 17
BIG_LOT = 1.0


def load_bars(sym):
    p = os.path.join(CACHE, f"{sym}_{TF}.npz")
    if not os.path.exists(p):
        return None
    d = np.load(p)
    return (d["t"].astype(np.int64), d["o"].astype(float), d["h"].astype(float),
            d["l"].astype(float), d["c"].astype(float), d["v"].astype(float))


def load_meta(sym):
    p = os.path.join(CACHE, f"{sym}_meta.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8-sig"))
    return {}


def money_per_unit(meta):
    tv, ts = meta.get("trade_tick_value"), meta.get("trade_tick_size") or meta.get("point")
    return float(tv) / float(ts) if (tv and ts and ts > 0) else 1.0


def atr(h, l, c, period=ATR_PERIOD):
    n = h.size
    pc = np.empty(n); pc[0] = c[0]; pc[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(n, np.nan)
    if n >= period:
        cs = np.cumsum(tr)
        out[period - 1:] = (cs[period - 1:] - np.concatenate(([0.0], cs[:-period]))) / period
    return out


def rolling_median(v, w=VOL_LOOKBACK):
    n = v.size
    out = np.full(n, np.nan)
    for i in range(w, n):
        out[i] = np.median(v[i - w:i])
    return out


def find_explosions(o, h, l, c, v, a, medv):
    """Causal explosions known at close of bar i. Returns list of dicts with
    confidence components measured ONLY from data <= i."""
    n = c.size
    out = []
    for i in range(max(ATR_PERIOD + 1, VOL_LOOKBACK + 1), n - max(LAGS) - HORIZON - 1):
        av = a[i - 1]
        if not np.isfinite(av) or av <= 0:
            continue
        body = c[i] - o[i]
        body_x = abs(body) / av
        mv = medv[i]
        vol_x = (v[i] / mv) if (np.isfinite(mv) and mv > 0) else 0.0
        is_exp = (body_x >= SPIKE_K) or (vol_x >= VOL_Z)
        if not is_exp:
            continue
        d = 1 if body > 0 else -1
        # streak: consecutive prior bars in same dir as the explosion body
        streak = 0
        for j in range(i - 1, max(i - 6, 0), -1):
            if np.sign(c[j] - o[j]) == d:
                streak += 1
            else:
                break
        out.append({"i": int(i), "dir": int(d), "atr": float(av),
                    "body_x": float(body_x), "vol_x": float(vol_x),
                    "streak": int(streak)})
    return out


def sim_fixed(h, l, c, entry_idx, d, entry, sl, tp_R, horizon):
    n = c.size
    R = abs(entry - sl)
    if R <= 0:
        return None
    tp = entry + tp_R * R if d > 0 else entry - tp_R * R
    last = min(entry_idx + horizon, n - 1)
    maa = mfa = 0.0
    for j in range(entry_idx + 1, last + 1):
        hi, lo = h[j], l[j]
        fav = (hi - entry) / R if d > 0 else (entry - lo) / R
        adv = (entry - lo) / R if d > 0 else (hi - entry) / R
        mfa = max(mfa, fav); maa = max(maa, adv)
        hit_sl = (lo <= sl) if d > 0 else (hi >= sl)
        hit_tp = (hi >= tp) if d > 0 else (lo <= tp)
        if hit_sl and hit_tp:
            return {"R": -1.0, "mfa": mfa, "maa": maa}
        if hit_sl:
            return {"R": -1.0, "mfa": mfa, "maa": maa}
        if hit_tp:
            return {"R": float(tp_R), "mfa": mfa, "maa": maa}
    px = c[last]
    rr = (px - entry) / R if d > 0 else (entry - px) / R
    return {"R": float(rr), "mfa": mfa, "maa": maa}


def sim_trail(h, l, c, a, entry_idx, d, entry, sl0, horizon):
    """ATR chandelier trailing stop. R unit = initial risk |entry-sl0|. No fixed
    TP — exit when trailing stop hit or horizon. Causal: stop updates off closed
    bars only; intrabar we check the CURRENT stop (set from prior bars)."""
    n = c.size
    R = abs(entry - sl0)
    if R <= 0:
        return None
    last = min(entry_idx + horizon, n - 1)
    stop = sl0
    extreme = entry
    maa = mfa = 0.0
    for j in range(entry_idx + 1, last + 1):
        hi, lo = h[j], l[j]
        fav = (hi - entry) / R if d > 0 else (entry - lo) / R
        adv = (entry - lo) / R if d > 0 else (hi - entry) / R
        mfa = max(mfa, fav); maa = max(maa, adv)
        # check CURRENT stop (computed from bars < j) intrabar first (pessimistic)
        hit = (lo <= stop) if d > 0 else (hi >= stop)
        if hit:
            rr = (stop - entry) / R if d > 0 else (entry - stop) / R
            return {"R": float(rr), "mfa": mfa, "maa": maa}
        # then update trailing stop off THIS now-closed bar
        av = a[j] if np.isfinite(a[j]) and a[j] > 0 else R
        if d > 0:
            extreme = max(extreme, hi)
            stop = max(stop, extreme - TRAIL_ATR * av)
        else:
            extreme = min(extreme, lo)
            stop = min(stop, extreme + TRAIL_ATR * av)
    px = c[last]
    rr = (px - entry) / R if d > 0 else (entry - px) / R
    return {"R": float(rr), "mfa": mfa, "maa": maa}


def build_entry(o, h, l, c, a, sp, lag):
    """RIDE entry at close of bar i+lag (causal). SL = SL_ATR*ATR(entry) against
    the trade. Returns (entry_idx, d, entry, sl) or None."""
    i = sp["i"]; d = sp["dir"]
    ei = i + lag
    if ei >= c.size - 1:
        return None
    entry = c[ei]
    av = a[ei] if np.isfinite(a[ei]) and a[ei] > 0 else sp["atr"]
    sl = entry - SL_ATR * av if d > 0 else entry + SL_ATR * av
    return ei, d, float(entry), float(sl)


def run(o, h, l, c, a, spikes, lag, exit_kind, tp_R, spread):
    netR, grossR, maa, mfa, conf = [], [], [], [], []
    for sp in spikes:
        be = build_entry(o, h, l, c, a, sp, lag)
        if be is None:
            continue
        ei, d, entry, sl = be
        R = abs(entry - sl)
        if exit_kind == "fixed":
            sim = sim_fixed(h, l, c, ei, d, entry, sl, tp_R, HORIZON)
        else:
            sim = sim_trail(h, l, c, a, ei, d, entry, sl, HORIZON)
        if sim is None:
            continue
        cost = spread / R
        netR.append(sim["R"] - cost); grossR.append(sim["R"])
        maa.append(sim["maa"]); mfa.append(sim["mfa"])
        conf.append(sp["body_x"] + sp["vol_x"] + 0.5 * sp["streak"])
    return {"netR": np.asarray(netR), "grossR": np.asarray(grossR),
            "maa": np.asarray(maa), "mfa": np.asarray(mfa),
            "conf": np.asarray(conf)}


def boot_ci(arr, rng):
    if arr.size == 0:
        return None
    m = np.empty(BOOT); n = arr.size
    for b in range(BOOT):
        m[b] = np.mean(arr[rng.integers(0, n, n)])
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def summ(arr, rng):
    if arr.size == 0:
        return {"n": 0, "expR": None, "wr": None, "ci95": None,
                "ci_pos": False, "ci_crosses_0": None}
    ci = boot_ci(arr, rng)
    return {"n": int(arr.size), "expR": float(np.mean(arr)),
            "wr": float(np.mean(arr > 0)), "ci95": ci,
            "ci_pos": bool(ci and ci[0] > 0),
            "ci_crosses_0": bool(ci and ci[0] <= 0 <= ci[1])}


def walk_forward(o, h, l, c, a, spikes, lag, exit_kind, tp_R, spread, n, rng):
    edges = [int(n * k / N_BLOCKS) for k in range(N_BLOCKS + 1)]
    per, pooled = [], []
    for b in range(N_BLOCKS):
        lo, hi = edges[b], edges[b + 1]
        blk = [s for s in spikes if lo <= s["i"] < hi]
        r = run(o, h, l, c, a, blk, lag, exit_kind, tp_R, spread)
        s = summ(r["netR"], rng); s["block"] = b; s["burn_in"] = (b == 0)
        per.append(s)
        if b >= 1:
            pooled.append(r["netR"])
    pa = np.concatenate(pooled) if pooled else np.array([])
    return {"per_block": per, "pooled_oos": summ(pa, rng)}


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
            sim = (sim_fixed(h, l, c, int(ei), int(d), float(entry), float(sl), tp_R, HORIZON)
                   if exit_kind == "fixed" else
                   sim_trail(h, l, c, a, int(ei), int(d), float(entry), float(sl), HORIZON))
            if sim:
                rs.append(sim["R"] - spread / R)
        avgs[b] = np.mean(rs) if rs else 0.0
    return {"mean": float(np.mean(avgs)), "ci_lo": float(np.percentile(avgs, 2.5)),
            "ci_hi": float(np.percentile(avgs, 97.5))}


def big_lot_ruin(o, h, l, c, a, spikes, lag, spread, mpu):
    wR = wR_m = wM = wM_r = 0.0
    maa_l = []; cont = nt = 0
    for sp in spikes:
        be = build_entry(o, h, l, c, a, sp, lag)
        if be is None:
            continue
        ei, d, entry, sl = be
        R = abs(entry - sl)
        sim = sim_fixed(h, l, c, ei, d, entry, sl, R_MULT[0], HORIZON)
        if sim is None:
            continue
        nt += 1
        netR = sim["R"] - spread / R
        maa_l.append(sim["maa"])
        if sim["maa"] >= 1.0:
            cont += 1
        money = netR * R * mpu * BIG_LOT
        if netR < wR:
            wR, wR_m = netR, money
        if money < wM:
            wM, wM_r = money, netR
    ma = np.asarray(maa_l)
    return {"n": nt, "p_adverse_ge_1R": float(cont / nt) if nt else None,
            "worst_R": float(wR), "worst_R_money_biglot": float(wR_m),
            "worst_money_biglot": float(wM), "worst_money_R": float(wM_r),
            "biglot": BIG_LOT,
            "maa_p50": float(np.percentile(ma, 50)) if ma.size else None,
            "maa_p90": float(np.percentile(ma, 90)) if ma.size else None,
            "maa_p99": float(np.percentile(ma, 99)) if ma.size else None}


def conf_buckets(o, h, l, c, a, spikes, lag, exit_kind, tp_R, spread, rng):
    r = run(o, h, l, c, a, spikes, lag, exit_kind, tp_R, spread)
    if r["conf"].size < 9:
        return {"n": int(r["conf"].size), "note": "too few for buckets"}
    q1, q2 = np.percentile(r["conf"], [33, 67])
    out = {}
    for name, mask in (("LOW", r["conf"] <= q1),
                       ("MID", (r["conf"] > q1) & (r["conf"] <= q2)),
                       ("HIGH", r["conf"] > q2)):
        out[name] = summ(r["netR"][mask], rng)
    out["thresholds"] = {"q33": float(q1), "q67": float(q2)}
    return out


def analyze(sym, rng):
    bars = load_bars(sym)
    if bars is None:
        return {"error": "no data"}
    t, o, h, l, c, v = bars
    n = c.size
    meta = load_meta(sym); mpu = money_per_unit(meta)
    a = atr(h, l, c); medv = rolling_median(v)
    spikes = find_explosions(o, h, l, c, v, a, medv)
    spreads = NEWS_SPREAD.get(sym, [0.0]); mid = spreads[MID]
    oos_i = int(n * IS_FRACTION)
    oos = [s for s in spikes if s["i"] >= oos_i]

    res = {"symbol": sym, "tf": TF, "bars": int(n), "span_days": float((t[-1] - t[0]) / 86400),
           "mpu": mpu, "n_explosions": len(spikes), "n_oos": len(oos),
           "spike_k": SPIKE_K, "vol_z": VOL_Z, "sl_atr": SL_ATR, "trail_atr": TRAIL_ATR,
           "horizon": HORIZON, "lags": list(LAGS), "spreads": spreads, "mid_spread": mid,
           "small_sample_oos": bool(len(oos) < MIN_OOS)}

    # (Q1/Q2) LATENCY SWEEP — fixed 1R and trail, OOS 67/33, mid spread
    lat = {}
    for exit_kind in ("fixed", "trail"):
        lat[exit_kind] = {}
        for lag in LAGS:
            r = run(o, h, l, c, a, oos, lag, exit_kind, R_MULT[0], mid)
            lat[exit_kind][f"lag{lag}"] = summ(r["netR"], rng)
    res["latency_sweep_oos_mid"] = lat

    # (Q3) exit comparison at lag0 (fixed 1R / fixed 2R / trail), OOS
    ex = {}
    for label, (ek, tp) in {"fixed_1R": ("fixed", 1.0), "fixed_2R": ("fixed", 2.0),
                            "trail": ("trail", None)}.items():
        r = run(o, h, l, c, a, oos, 0, ek, tp, mid)
        ex[label] = summ(r["netR"], rng)
    res["exit_compare_lag0_oos_mid"] = ex

    # (Q4) confidence buckets at lag0, trail (the user's "high confidence" lever)
    res["conf_buckets_lag0_trail_oos_mid"] = conf_buckets(o, h, l, c, a, oos, 0, "trail", None, mid, rng)
    res["conf_buckets_lag0_fixed1R_oos_mid"] = conf_buckets(o, h, l, c, a, oos, 0, "fixed", 1.0, mid, rng)

    # walk-forward on the BEST-case fast cell (lag0) for fixed1R and trail
    res["walk_forward_lag0"] = {
        "fixed_1R": walk_forward(o, h, l, c, a, spikes, 0, "fixed", 1.0, mid, n, rng),
        "trail": walk_forward(o, h, l, c, a, spikes, 0, "trail", None, mid, n, rng),
    }

    # random baseline (OOS) for lag0 fixed1R and trail
    dpf = float(np.mean([1.0 if s["dir"] > 0 else 0.0 for s in oos])) if oos else 0.5
    res["random_baseline_lag0_oos_mid"] = {
        "fixed_1R": random_baseline(o, h, l, c, a, oos_i, n, len(oos), dpf, "fixed", 1.0, mid, rng),
        "trail": random_baseline(o, h, l, c, a, oos_i, n, len(oos), dpf, "trail", None, mid, rng),
    }

    # spread sensitivity at lag0 trail (OOS)
    sw = {}
    for sp in spreads:
        r = run(o, h, l, c, a, oos, 0, "trail", None, sp)
        sw[f"spread_{sp}"] = summ(r["netR"], rng)
    res["spread_sensitivity_lag0_trail_oos"] = sw

    # big-lot ruin at lag0 (fast ride) on OOS
    res["big_lot_ruin_lag0_oos_mid"] = big_lot_ruin(o, h, l, c, a, oos, 0, mid, mpu)

    return res


def verdict(res_by_sym):
    """EDGE if ANY symbol has a fast (lag<=2) OOS cell with CI strictly>0,
    surviving walk-forward (pooled CI>0) AND beating random. Else NO_EDGE."""
    any_data = any_edge = False
    detail = {}
    for sym, r in res_by_sym.items():
        if "error" in r:
            continue
        any_data = True
        # check lag0 trail + fixed1R headline + walk-forward + random
        best = None
        for ek, wf_key in (("trail", "trail"), ("fixed", "fixed_1R")):
            cell = r["latency_sweep_oos_mid"][ek]["lag0"]
            if cell["n"] < MIN_OOS or not cell.get("ci_pos"):
                continue
            wf = r["walk_forward_lag0"][wf_key]["pooled_oos"]
            if not wf.get("ci_pos"):
                continue
            rb = r["random_baseline_lag0_oos_mid"][wf_key]
            if rb and cell["expR"] is not None and cell["expR"] <= rb["ci_hi"]:
                continue
            best = (ek, cell, wf)
            any_edge = True
        detail[sym] = "EDGE" if best else "no_edge"
    if any_edge:
        return "EDGE", detail
    return ("NO_EDGE" if any_data else "INCONCLUSIVE"), detail


def fmt(x):
    return "  n/a" if x is None else f"{x:+.3f}"


def main():
    rng = np.random.default_rng(SEED)
    print("=" * 88)
    print("explosion_ride_lab — RIDE an M1 explosion: does FAST entry pay, and what does latency cost?")
    print(f"explosion=|c-o|>={SPIKE_K}xATR OR vol>={VOL_Z}x med | lags={LAGS} | exits=fixed1R/2R/ATR-trail({TRAIL_ATR})")
    print(f"horizon={HORIZON}m | WIDE spread | OOS 67/33 + walk-fwd{N_BLOCKS} | boot={BOOT}")
    print("PRIOR: M5 FADE=-0.18..-0.72R (loser). M5 RIDE=NO_EDGE (gold +0.25 window-artifact).")
    print("=" * 88)
    res_by_sym = {}
    for sym in SYMBOLS:
        r = analyze(sym, rng); res_by_sym[sym] = r
        if "error" in r:
            print(f"\n{sym}: ERROR {r['error']}"); continue
        print(f"\n{'#'*88}\n{sym} {TF} bars={r['bars']} span={r['span_days']:.0f}d "
              f"explosions={r['n_explosions']} (OOS={r['n_oos']}) $/unit/lot={r['mpu']:.2f} "
              f"mid_spread={r['mid_spread']}")
        print("  -- LATENCY SWEEP (OOS, mid spread, expR) --")
        for ek in ("fixed", "trail"):
            cells = r["latency_sweep_oos_mid"][ek]
            s = "  ".join(f"lag{lg}={fmt(cells[f'lag{lg}']['expR'])}(n{cells[f'lag{lg}']['n']})" for lg in LAGS)
            print(f"     {ek:<6}: {s}")
        print("  -- EXIT COMPARE @lag0 (OOS) --")
        for k, s in r["exit_compare_lag0_oos_mid"].items():
            ci = s["ci95"]; cis = f"[{fmt(ci[0])},{fmt(ci[1])}]" if ci else "n/a"
            print(f"     {k:<10} n={s['n']:<4} expR={fmt(s['expR'])} wr={'n/a' if s['wr'] is None else f'{100*s['wr']:.0f}%'} CI={cis} {'CI>0' if s['ci_pos'] else ''}")
        print("  -- CONFIDENCE BUCKETS @lag0 trail (OOS) --")
        cb = r["conf_buckets_lag0_trail_oos_mid"]
        for k in ("LOW", "MID", "HIGH"):
            if k in cb:
                s = cb[k]; print(f"     {k:<5} n={s['n']:<4} expR={fmt(s['expR'])} {'CI>0' if s.get('ci_pos') else ''}")
        wf = r["walk_forward_lag0"]["trail"]["pooled_oos"]
        wci = wf["ci95"]
        print(f"  -- WALK-FWD lag0 trail pooled OOS: expR={fmt(wf['expR'])} n={wf['n']} CI={f'[{fmt(wci[0])},{fmt(wci[1])}]' if wci else 'n/a'}")
        rb = r["random_baseline_lag0_oos_mid"]["trail"]
        if rb:
            print(f"     random trail CI=[{fmt(rb['ci_lo'])},{fmt(rb['ci_hi'])}] mean {fmt(rb['mean'])}")
        rn = r["big_lot_ruin_lag0_oos_mid"]
        print(f"  -- BIG-LOT RUIN lag0 (lot {rn['biglot']}): P(adverse>=1R)={'n/a' if rn['p_adverse_ge_1R'] is None else f'{100*rn['p_adverse_ge_1R']:.0f}%'}")
        print(f"     worst-R={fmt(rn['worst_R'])}R(=${rn['worst_R_money_biglot']:.0f}) worst-$=${rn['worst_money_biglot']:.0f}(={fmt(rn['worst_money_R'])}R) [diff trades]")

    v, detail = verdict(res_by_sym)
    print("\n" + "=" * 88)
    print(f"VERDICT (fast RIDE has edge?): {v}   detail={detail}")
    print("=" * 88)
    out = {"ts": datetime.now(timezone.utc).isoformat(),
           "config": {"symbols": SYMBOLS, "tf": TF, "spike_k": SPIKE_K, "vol_z": VOL_Z,
                      "sl_atr": SL_ATR, "trail_atr": TRAIL_ATR, "r_mult": list(R_MULT),
                      "horizon": HORIZON, "lags": list(LAGS), "news_spread": NEWS_SPREAD,
                      "n_blocks": N_BLOCKS, "boot": BOOT, "seed": SEED, "big_lot": BIG_LOT,
                      "no_lookahead": "explosion confirmed at close i (ATR uses <=i-1, medvol uses [i-50:i]); "
                                      "entry=close[i+lag]; fwd sim bars>entry only; trail updates off closed bars; "
                                      "intrabar SL/stop-first pessimism; walk-fwd block0=burn-in",
                      "cost": "WIDE explosion-moment spread, round-trip in R"},
           "verdict": v, "verdict_detail": detail, "results": res_by_sym}
    os.makedirs(CACHE, exist_ok=True)
    json.dump(out, open(RESULTS, "w", encoding="utf-8"), indent=2)
    print(f"\nSaved -> {RESULTS}")
    return out


if __name__ == "__main__":
    main()
