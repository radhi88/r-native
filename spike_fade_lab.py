"""
spike_fade_lab.py — FADE vs RIDE the spike. Which is right for him?

QUESTION (user)
---------------
Some spike-scalpers FADE the spike (bet it reverts/exhausts) instead of riding it.
On a spike (a single bar that moves >= k*ATR), do we make money ENTERING AGAINST
the spike (fade -> bet reversion) or ENTERING WITH it (ride -> bet continuation)?
Honest verdict: do spikes CONTINUE, REVERT, or NEITHER (no edge over random)?

SPIKE DEFINITION (STRICT no-lookahead)
--------------------------------------
ATR(14) is computed Wilder-style on bars <= i, but the THRESHOLD we compare the
spike bar against uses ATR at bar i-1 (a[i-1]) so the violent spike bar itself does
not inflate its own threshold. A bar i is a SPIKE if:
    |close[i] - close[i-1]| >= k * a[i-1]          (k in {2.0, 2.5, 3.0})
Direction = sign(close[i] - close[i-1]). UP spike => bullish bar.
Edge-triggered: bar i-1 was NOT itself a spike (so we don't fire on every bar of a
sustained run; we fire on the *onset* of the violent move).

ENTRY (no-lookahead)
--------------------
We confirm the spike at the CLOSE of bar i (all info known) and ENTER at the open of
bar i+1 (the next bar). We never read a future bar to decide entry.

  FADE  : enter AGAINST the spike. UP spike  -> SELL at o[i+1].  DOWN spike -> BUY.
          SL = beyond the spike EXTREME (UP: high[i]+buf ; DOWN: low[i]-buf).
          R = |entry - SL|.
          TP variants:
            - tp_1r   : entry -/+ 1.0 R           (partial retrace)
            - tp_15r  : entry -/+ 1.5 R           (deeper retrace)
            - tp_ema  : EMA20[i]  (revert to the mean)   <-- mean-target
  RIDE  : enter WITH the spike. UP spike -> BUY ; DOWN spike -> SELL.
          SL = beyond the spike ORIGIN extreme (UP: low[i]-buf ; DOWN: high[i]+buf).
          R = |entry - SL|.
          TP variants: tp_1r, tp_15r (continuation targets). (No EMA target: riding
          away from the mean, so EMA would be behind us — meaningless.)

SIMULATION
----------
Walk forward bar by bar from i+1 to i+N (N: M5=120, M15=60, H1=40). First of SL/TP
touched wins. If a single bar straddles both SL and TP, assume SL first (conservative).
If neither touched by i+N, exit at close[i+N] (time stop). Net of a realistic
round-trip cost (per-symbol points * point), reported in account money per min-lot
AND in R units.

BASELINE (is it better than luck?)
----------------------------------
For each (sym,tf,k,variant) we bootstrap 2000x a RANDOM-ENTRY strategy: pick the same
number of OOS entries as real events, at random eligible bars, with random direction,
using the SAME R sizing (R drawn from the same distribution as the real events at that
bar via ATR-scaled SL) and the SAME TP/SL/time-stop machinery & cost. We report the
random avg-R distribution and a 95% CI. EDGE only if the strategy's OOS avg-R lies
OUTSIDE the random 95% CI on the favorable side. We also bootstrap the strategy's own
events (resample with replacement) to get a 95% CI on its avg-R and check it does NOT
cross 0.

RIGOR
-----
- NO lookahead anywhere (indicators, spike threshold, entry, SL anchor).
- 67/33 IS/OOS split by time; REPORT OOS ONLY (IS kept only to honor the protocol).
- Require >= 40 OOS events else mark small_sample=True (still reported, flagged).
- Costs subtracted from every trade (round-trip), per-symbol.

OUTPUT: prints tables; saves data/lab_cache/spike_fade_lab_results.json
Run:  ./.venv/Scripts/python.exe spike_fade_lab.py
"""
import json
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")

SYMBOLS = ["XAUUSDm", "BTCUSDm", "EURUSDm", "US30m", "GBPUSDm"]
TFS = ["M5", "M15", "H1"]
N_BY_TF = {"M5": 120, "M15": 60, "H1": 40}
K_LIST = [2.0, 2.5, 3.0]          # spike size in ATR multiples (task: >= 2*ATR)

# round-trip cost in POINTS (multiply by meta['point'] for price distance).
# Same proxy table used by reversion_lab.py for consistency across the lab suite.
COST_POINTS = {
    "XAUUSDm": 25.0,    # ~2.5 USD/oz
    "EURUSDm": 15.0,    # ~1.5 pip
    "GBPUSDm": 18.0,    # ~1.8 pip
    "US30m":   30.0,    # ~3.0 index pts
    "BTCUSDm": 4500.0,  # ~45 USD
}

EMA_LEN = 20
ATR_LEN = 14
SL_BUFFER_ATR = 0.25   # buffer beyond the spike extreme, in ATR units
BOOT = 2000
SEED = 20260616


# ----------------------------- indicators (no lookahead) ----------------------------
def ema(x, n):
    a = 2.0 / (n + 1.0)
    out = np.empty_like(x, dtype=float)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def atr_wilder(high, low, close, n):
    prev_c = np.roll(close, 1)
    prev_c[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_c), np.abs(low - prev_c)))
    out = np.full(len(close), np.nan)
    if len(close) <= n:
        return out
    out[n] = tr[1:n + 1].mean()
    for i in range(n + 1, len(close)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    out[:n] = out[n]   # back-fill leading so indexing never crashes (events start later)
    return out


def load(sym, tf):
    d = np.load(os.path.join(CACHE, f"{sym}_{tf}.npz"))
    return (d["t"].astype(np.int64), d["o"].astype(float), d["h"].astype(float),
            d["l"].astype(float), d["c"].astype(float), d["v"].astype(float))


def load_or_fetch(sym, tf):
    """Cache-first; fall back to live MT5 copy_rates_from_pos if cache missing."""
    p = os.path.join(CACHE, f"{sym}_{tf}.npz")
    if os.path.exists(p):
        return load(sym, tf)
    import MetaTrader5 as mt5
    tf_map = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    nbars = {"M5": 40000, "M15": 30000, "H1": 20000}[tf]
    if not mt5.initialize():
        raise RuntimeError(f"cache miss for {sym}_{tf} and mt5.initialize failed: {mt5.last_error()}")
    mt5.symbol_select(sym, True)
    r = mt5.copy_rates_from_pos(sym, tf_map[tf], 0, nbars)
    mt5.shutdown()
    if r is None or len(r) == 0:
        raise RuntimeError(f"cache miss for {sym}_{tf} and copy_rates empty")
    return (r["time"].astype(np.int64), r["open"].astype(float), r["high"].astype(float),
            r["low"].astype(float), r["close"].astype(float), r["tick_volume"].astype(float))


def load_meta(sym):
    with open(os.path.join(CACHE, f"{sym}_meta.json")) as f:
        return json.load(f)


# ----------------------------- core simulation ------------------------------------
def simulate(side, entry, sl, tp, i, jmax, h, l, c):
    """First touch of SL/TP within (i, jmax]; SL wins ties (conservative). Returns
    (pl_price, outcome, dur). side: +1 long, -1 short."""
    long = side > 0
    for j in range(i + 1, jmax + 1):
        if long:
            hit_sl = l[j] <= sl
            hit_tp = h[j] >= tp
        else:
            hit_sl = h[j] >= sl
            hit_tp = l[j] <= tp
        if hit_sl and hit_tp:
            return (-(entry - sl) if long else -(sl - entry)), "SL_tie", j - i
        if hit_sl:
            return (-(entry - sl) if long else -(sl - entry)), "SL", j - i
        if hit_tp:
            return ((tp - entry) if long else (entry - tp)), "TP", j - i
    exitp = c[jmax]
    return ((exitp - entry) if long else (entry - exitp)), "TIME", jmax - i


def run_one(sym, tf, k, meta, bars):
    t, o, h, l, c, v = bars
    n = len(c)
    N = N_BY_TF[tf]

    e = ema(c, EMA_LEN)
    a = atr_wilder(h, l, c, ATR_LEN)

    point = meta["point"]
    tick_val = meta["trade_tick_value"]
    tick_size = meta["trade_tick_size"]
    vmin = meta["volume_min"]
    cost_price = COST_POINTS[sym] * point
    money_per_price = (tick_val / tick_size) * vmin   # money per 1.0 price unit @ min lot

    warm = ATR_LEN + EMA_LEN + 2
    split = int(n * 0.67)

    move = c - np.roll(c, 1)              # close-to-close move
    move[0] = 0.0
    thresh = k * np.roll(a, 1)            # threshold uses a[i-1] (no lookahead)
    is_spike = np.abs(move) >= thresh
    is_spike[:warm] = False

    events = []
    eligible_bars = []   # bars where we COULD have entered (for random baseline)
    for i in range(warm, n - 1):
        eligible_bars.append(i)
        if not is_spike[i] or is_spike[i - 1]:
            continue   # need spike onset, edge-triggered
        up = move[i] > 0
        entry = o[i + 1]
        jmax = min(i + N, n - 1)
        a_i = a[i]
        if not np.isfinite(a_i) or a_i <= 0:
            continue
        buf = SL_BUFFER_ATR * a_i

        # ---- FADE: against the spike ----
        if up:   # up spike -> SELL (short)
            f_side = -1
            f_sl = h[i] + buf
            f_R = f_sl - entry
            f_tp_1r = entry - 1.0 * f_R
            f_tp_15r = entry - 1.5 * f_R
            f_tp_ema = e[i]
        else:    # down spike -> BUY (long)
            f_side = +1
            f_sl = l[i] - buf
            f_R = entry - f_sl
            f_tp_1r = entry + 1.0 * f_R
            f_tp_15r = entry + 1.5 * f_R
            f_tp_ema = e[i]

        # ---- RIDE: with the spike ----
        if up:   # up spike -> BUY (long)
            r_side = +1
            r_sl = l[i] - buf
            r_R = entry - r_sl
            r_tp_1r = entry + 1.0 * r_R
            r_tp_15r = entry + 1.5 * r_R
        else:    # down spike -> SELL (short)
            r_side = -1
            r_sl = h[i] + buf
            r_R = entry - r_sl if False else (r_sl - entry)
            r_tp_1r = entry - 1.0 * r_R
            r_tp_15r = entry - 1.5 * r_R

        # skip degenerate (risk below cost) on EITHER side -> not tradable sensibly
        if (f_R <= cost_price * 0.5 or r_R <= cost_price * 0.5
                or not np.isfinite(f_R) or not np.isfinite(r_R)):
            continue

        # EMA-target only sane for fade if it's actually a retrace toward us
        ema_ok = (f_tp_ema < entry) if up else (f_tp_ema > entry)

        rec = {
            "i": int(i), "t": int(t[i]), "up": bool(up), "is": i < split,
            "f_R": float(f_R), "r_R": float(r_R),
        }
        # fade variants
        for tag, tp, R, ok in (("fade_1r", f_tp_1r, f_R, True),
                               ("fade_15r", f_tp_15r, f_R, True),
                               ("fade_ema", f_tp_ema, f_R, ema_ok)):
            if not ok:
                rec[tag + "_pl"] = None
                continue
            pl, out, dur = simulate(f_side, entry, f_sl, tp, i, jmax, h, l, c)
            rec[tag + "_pl"] = float(pl)
            rec[tag + "_out"] = out
            rec[tag + "_R"] = float(R)
        # ride variants
        for tag, tp, R in (("ride_1r", r_tp_1r, r_R), ("ride_15r", r_tp_15r, r_R)):
            pl, out, dur = simulate(r_side, entry, r_sl, tp, i, jmax, h, l, c)
            rec[tag + "_pl"] = float(pl)
            rec[tag + "_out"] = out
            rec[tag + "_R"] = float(R)
        events.append(rec)

    oos = [ev for ev in events if not ev["is"]]
    n_oos = len(oos)
    rng = np.random.default_rng(SEED + hash((sym, tf, k)) % 100000)

    def summarize(tag):
        pls, Rs, outs = [], [], []
        for ev in oos:
            if ev.get(tag + "_pl") is None:
                continue
            pls.append(ev[tag + "_pl"])
            Rs.append(ev[tag + "_R"])
            outs.append(ev[tag + "_out"])
        if not pls:
            return None
        pls = np.array(pls); Rs = np.array(Rs); outs = np.array(outs)
        net_price = pls - cost_price
        net_money = net_price * money_per_price
        rmult = net_price / Rs
        wins = outs == "TP"
        gpos = net_money[net_money > 0].sum()
        gneg = -net_money[net_money < 0].sum()
        pf = (gpos / gneg) if gneg > 1e-9 else float("inf")
        # bootstrap own avg-R 95% CI
        m = len(rmult)
        idx = rng.integers(0, m, size=(BOOT, m))
        boot_means = rmult[idx].mean(axis=1)
        ci_lo, ci_hi = np.percentile(boot_means, [2.5, 97.5])
        return {
            "n": int(m),
            "win_rate": float(wins.mean()),
            "avg_R": float(rmult.mean()),
            "avg_R_ci95": [float(ci_lo), float(ci_hi)],
            "avg_R_ci_crosses_0": bool(ci_lo < 0 < ci_hi),
            "expectancy_R": float(rmult.mean()),
            "net_money_total": float(net_money.sum()),
            "net_money_mean": float(net_money.mean()),
            "profit_factor": float(pf) if np.isfinite(pf) else 999.0,
            "tp_count": int((outs == "TP").sum()),
            "sl_count": int(((outs == "SL") | (outs == "SL_tie")).sum()),
            "time_count": int((outs == "TIME").sum()),
        }

    # ---------- RANDOM baseline (bootstrap) ----------
    # Random entries at random eligible OOS bars, random direction, same R sizing logic
    # (R = ATR-scaled SL = distance to spike-equivalent extreme; we approximate R by the
    # empirical mean R of real events so cost ratio is comparable), 1R TP, same machinery.
    def random_baseline(tag_R_mean, n_entries):
        if n_entries <= 0:
            return None
        oos_bars = [b for b in eligible_bars if b >= split and b < n - 1]
        if len(oos_bars) < 5:
            return None
        oos_bars = np.array(oos_bars)
        avgR = tag_R_mean
        boot_means = np.empty(BOOT)
        for bsi in range(BOOT):
            picks = rng.choice(oos_bars, size=n_entries, replace=True)
            sides = rng.choice([-1, 1], size=n_entries)
            rs = np.empty(n_entries)
            for q in range(n_entries):
                i = int(picks[q]); side = int(sides[q])
                entry = o[i + 1]
                jmax = min(i + N, n - 1)
                a_i = a[i]
                if not np.isfinite(a_i) or a_i <= 0:
                    rs[q] = 0.0
                    continue
                R = avgR if avgR > cost_price * 0.5 else cost_price
                if side > 0:
                    sl = entry - R
                    tp = entry + R
                else:
                    sl = entry + R
                    tp = entry - R
                pl, out, dur = simulate(side, entry, sl, tp, i, jmax, h, l, c)
                rs[q] = (pl - cost_price) / R
            boot_means[bsi] = rs.mean()
        lo, hi = np.percentile(boot_means, [2.5, 97.5])
        return {"mean": float(boot_means.mean()),
                "ci95": [float(lo), float(hi)],
                "n_entries": int(n_entries)}

    out = {
        "symbol": sym, "tf": tf, "k": k, "N_bars": N,
        "n_events_total": len(events),
        "n_events_oos": n_oos,
        "n_events_is": len(events) - n_oos,
        "small_sample": n_oos < 40,
        "cost_price": float(cost_price),
        "money_per_price_unit_minlot": float(money_per_price),
        "fade": {}, "ride": {}, "random_baseline": {},
    }
    for tag in ("fade_1r", "fade_15r", "fade_ema"):
        s = summarize(tag)
        out["fade"][tag] = s
        if s is not None:
            # R mean for random baseline matched to this variant's R distribution
            Rmean = float(np.mean([ev[tag + "_R"] for ev in oos if ev.get(tag + "_pl") is not None]))
            out["random_baseline"][tag] = random_baseline(Rmean, s["n"])
    for tag in ("ride_1r", "ride_15r"):
        s = summarize(tag)
        out["ride"][tag] = s
        if s is not None:
            Rmean = float(np.mean([ev[tag + "_R"] for ev in oos if ev.get(tag + "_pl") is not None]))
            out["random_baseline"][tag] = random_baseline(Rmean, s["n"])

    # quick continuation/reversion stat: of all OOS spikes, did price extend further in
    # spike direction (continuation) or retrace to EMA (reversion) FIRST within N bars?
    cont = 0; rev = 0; both0 = 0
    for ev in oos:
        i = ev["i"]; up = ev["up"]
        jmax = min(i + N, n - 1)
        emah = e[i]
        ext_target = h[i] if up else l[i]   # beyond spike extreme = continuation
        got_cont = None; got_rev = None
        for j in range(i + 1, jmax + 1):
            if up:
                if got_cont is None and h[j] > ext_target:
                    got_cont = j
                if got_rev is None and l[j] <= emah:
                    got_rev = j
            else:
                if got_cont is None and l[j] < ext_target:
                    got_cont = j
                if got_rev is None and h[j] >= emah:
                    got_rev = j
            if got_cont is not None and got_rev is not None:
                break
        if got_cont is None and got_rev is None:
            both0 += 1
        elif got_rev is None:
            cont += 1
        elif got_cont is None:
            rev += 1
        elif got_cont < got_rev:
            cont += 1
        else:
            rev += 1
    out["first_event_oos"] = {
        "continuation_first": cont, "reversion_first": rev, "neither": both0,
        "n": n_oos,
        "cont_rate": (cont / n_oos) if n_oos else None,
        "rev_rate": (rev / n_oos) if n_oos else None,
    }
    return out


def verdict_for(out):
    """Honest per-cell verdict comparing fade & ride avg-R to random CI."""
    best = None
    rb = out.get("random_baseline", {})
    for kind in ("fade", "ride"):
        for tag, s in out[kind].items():
            if s is None:
                continue
            base = rb.get(tag)
            beats_random = False
            if base is not None:
                beats_random = s["avg_R"] > base["ci95"][1]   # above random upper CI
            edge = beats_random and (not s["avg_R_ci_crosses_0"]) and s["avg_R"] > 0
            cand = (s["avg_R"], kind, tag, edge, beats_random, s)
            if best is None or cand[0] > best[0]:
                best = cand
    return best


def main():
    rng_seed_note = SEED
    results = {}
    metas = {}
    for sym in SYMBOLS:
        metas[sym] = load_meta(sym)

    for sym in SYMBOLS:
        for tf in TFS:
            for k in K_LIST:
                key = f"{sym}_{tf}_k{k}"
                try:
                    bars = load_or_fetch(sym, tf)
                    results[key] = run_one(sym, tf, k, metas[sym], bars)
                except Exception as ex:
                    results[key] = {"error": repr(ex), "symbol": sym, "tf": tf, "k": k}

    out_path = os.path.join(CACHE, "spike_fade_lab_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    # ---------------- pretty print ----------------
    print("=" * 130)
    print("SPIKE FADE vs RIDE LAB  (single-bar move >= k*ATR ; OOS only ; 67/33 split ; no-lookahead ; net of cost)")
    print("FADE = enter against spike (bet reversion). RIDE = enter with spike (bet continuation).")
    print("avg_R = mean R per trade net of cost. 'beats?' = avg_R above random-entry 95%% CI upper bound.")
    print("=" * 130)
    hdr = (f"{'SYM':9}{'TF':4}{'k':5}{'OOSev':6}{'cont%':7}{'rev%':7} | "
           f"{'BEST':10}{'avgR':7}{'WR':6}{'PF':6}{'net$':9}{'CI0?':5}{'>rand?':7}{'VERDICT':12}")
    print(hdr)
    print("-" * 130)
    summary_rows = []
    for sym in SYMBOLS:
        for tf in TFS:
            for k in K_LIST:
                rd = results[f"{sym}_{tf}_k{k}"]
                if "error" in rd:
                    print(f"{sym:9}{tf:4}{k:<5}ERROR {rd['error'][:70]}")
                    continue
                fe = rd["first_event_oos"]
                contp = f"{fe['cont_rate']*100:5.1f}" if fe['cont_rate'] is not None else "  n/a"
                revp = f"{fe['rev_rate']*100:5.1f}" if fe['rev_rate'] is not None else "  n/a"
                ss = "*" if rd["small_sample"] else " "
                best = verdict_for(rd)
                if best is None:
                    print(f"{sym:9}{tf:4}{k:<5}{rd['n_events_oos']:4d}{ss}  {contp}  {revp} |  (no tradable variant)")
                    continue
                avgR, kind, tag, edge, beats, s = best
                v = "EDGE" if edge else ("WEAK" if (beats or s['avg_R'] > 0) else "NO_EDGE")
                ci0 = "Y" if s["avg_R_ci_crosses_0"] else "N"
                br = "Y" if beats else "N"
                label = f"{kind[:4]}:{tag.split('_')[-1]}"
                print(f"{sym:9}{tf:4}{k:<5}{rd['n_events_oos']:4d}{ss}  {contp}  {revp} | "
                      f"{label:10}{avgR:+6.2f} {s['win_rate']*100:4.0f}% {s['profit_factor']:5.2f} "
                      f"{s['net_money_total']:+8.1f}  {ci0:3}  {br:5}  {v:12}")
                summary_rows.append((sym, tf, k, kind, tag, avgR, edge, beats, rd["small_sample"]))
        print("-" * 130)
    print("* = small sample (<40 OOS events) — treat as unreliable.")
    print("VERDICT: EDGE = beats random 95%% CI AND own avg-R CI excludes 0 AND avg-R>0.")
    print("         WEAK = positive-ish but inside random noise / CI crosses 0.   NO_EDGE = not positive / worse than random.")

    # ---------- aggregate honest finding ----------
    edges = [r for r in summary_rows if r[6] and not r[8]]
    fade_edges = [r for r in edges if r[3] == "fade"]
    ride_edges = [r for r in edges if r[3] == "ride"]
    print("\n" + "=" * 130)
    print("AGGREGATE FINDING (non-small-sample cells with a real EDGE):")
    print(f"  cells with EDGE: {len(edges)}   (fade={len(fade_edges)}, ride={len(ride_edges)})")
    if edges:
        for r in sorted(edges, key=lambda x: -x[5]):
            print(f"    {r[0]:8} {r[1]:3} k{r[2]}  {r[3]}:{r[4]:9}  avg_R={r[5]:+.2f}")
    else:
        print("    NONE — neither fade nor ride beats random with a CI that excludes 0 on any liquid cell.")
    print(f"\nRaw results saved -> {out_path}")
    return results


if __name__ == "__main__":
    main()
