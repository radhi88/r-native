"""
reversion_lab.py — Test the user's 2nd thesis (mean reversion from overbought/extension).

THESIS (user, Arabic): "I saw the market rising and overbought ... it will drop."
i.e. when price gets overbought AND stretched far from its mean, it pulls back.

DEFINITIONS
-----------
overbought  := RSI(14) > 70  AND  close > EMA20 + k*ATR(14)   (extension up)
oversold    := RSI(14) < 30  AND  close < EMA20 - k*ATR(14)   (extension down)
k in {1.5, 2.0, 2.5}

EVENT (confirmation bar i): the FIRST bar that flips into the overbought/oversold
state after not being in it on bar i-1 (edge-triggered, so we don't double count a
sustained stretch). Everything used to detect the event at bar i uses data <= i.

REVERSION TEST (statistic): within the next N bars after i (M5 N=120, M15 60, H1 40),
does price touch EMA20 (re-mean) ? For an UP-extension we ask: does low[j] <= EMA20[i]
for some j in (i, i+N]?  (mirror for down). Hit-rate of re-meaning = reversion strength.

TRADABLE VERSION (net of cost, OOS only):
  - On an UP-extension event at bar i, SELL at next bar open (i+1 open) — counter-trend.
  - SL = beyond the recent swing high (confirmed pivot high within lookback) + buffer.
  - TP variant A = EMA20 at entry (the "revert to mean" target).
  - TP variant B = 1.5 R (R = |entry - SL|).
  - Walk forward bar by bar; first of SL/TP touched within N bars wins; else exit at
    bar i+N close (time stop). Costs subtracted = round-trip spread proxy (per symbol).
  - Mirror (BUY) for DOWN-extension (oversold) events.

RIGOR
-----
- NO lookahead. RSI/EMA/ATR at bar i use closes/highs/lows up to and including i only.
- Swing pivots are CONFIRMED with a forward window of `piv` bars; an event at bar i may
  only reference pivots whose confirmation bar <= i. So the SL anchor is known at entry.
- Entry is at i+1 open (the bar AFTER the confirmation bar). We never use a future bar to
  decide the entry.
- Split 67/33 IS/OOS by time. We report OOS ONLY. IS exists only to keep the protocol
  honest (we do not tune on OOS). Require >= 30 OOS events else label small-sample.

COST MODEL (round-trip, in price units) — conservative, per task guidance:
  XAUUSDm : ~25 points * point(0.001)         -> uses meta point
  EURUSDm : ~1.5 pip (15 points * 1e-5)
  US30m   : ~3.0 index pts (30 points * 0.1)
  BTCUSDm : ~45 USD  (4500 points * 0.01)
We convert the price-distance result to MONEY via trade_tick_value/trade_tick_size at
volume_min so "net of cost" is in real account currency per min-lot trade.

OUTPUT: prints a table; saves raw JSON to data/lab_cache/reversion_lab_results.json
"""
import json
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "lab_cache")

SYMBOLS = ["XAUUSDm", "EURUSDm", "US30m", "BTCUSDm"]
TFS = ["M5", "M15", "H1"]
N_BY_TF = {"M5": 120, "M15": 60, "H1": 40}
K_LIST = [1.5, 2.0, 2.5]

# round-trip cost in POINTS (multiply by meta['point'] for price distance)
COST_POINTS = {
    "XAUUSDm": 25.0,    # ~2.5 USD/oz spread+comm proxy on gold
    "EURUSDm": 15.0,    # ~1.5 pip
    "US30m":   30.0,    # ~3.0 index points
    "BTCUSDm": 4500.0,  # ~45 USD
}

RSI_LEN = 14
EMA_LEN = 20
ATR_LEN = 14
PIVOT_W = 5          # forward bars to confirm a swing pivot
SL_BUFFER_ATR = 0.25  # extra buffer beyond swing in ATR units


# ----------------------------- indicators (no lookahead) ----------------------------
def ema(x, n):
    a = 2.0 / (n + 1.0)
    out = np.empty_like(x, dtype=float)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def rsi_wilder(close, n):
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    out = np.full(len(close), 50.0)
    if len(close) <= n:
        return out
    avg_g = gain[1:n + 1].mean()
    avg_l = loss[1:n + 1].mean()
    for i in range(n + 1, len(close)):
        avg_g = (avg_g * (n - 1) + gain[i]) / n
        avg_l = (avg_l * (n - 1) + loss[i]) / n
        rs = avg_g / avg_l if avg_l > 1e-12 else 999.0
        out[i] = 100.0 - 100.0 / (1.0 + rs)
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
    # back-fill leading NaNs with first valid so indexing never crashes (events start later)
    first = out[n]
    out[:n] = first
    return out


# ----------------------------- confirmed pivots (no lookahead at use time) -----------
def confirmed_pivots(high, low, w):
    """
    Returns two arrays the same length as bars:
      last_ph_idx[i] = index of the most recent CONFIRMED swing-high usable at bar i
      last_pl_idx[i] = index of the most recent CONFIRMED swing-low  usable at bar i
    A pivot at index p (high[p] strictly highest in [p-w, p+w]) is CONFIRMED at bar p+w.
    So at bar i we may reference any pivot p with p+w <= i. This guarantees the SL anchor
    is known before we act. -1 = none yet.
    """
    n = len(high)
    last_ph = np.full(n, -1, dtype=int)
    last_pl = np.full(n, -1, dtype=int)
    ph_idx = -1
    pl_idx = -1
    for i in range(n):
        # confirm pivot whose confirmation bar == i  (pivot center p = i - w)
        p = i - w
        if p - w >= 0 and p + w < n and p + w == i:
            seg_h = high[p - w:p + w + 1]
            seg_l = low[p - w:p + w + 1]
            if high[p] == seg_h.max() and (seg_h == high[p]).sum() == 1:
                ph_idx = p
            if low[p] == seg_l.min() and (seg_l == low[p]).sum() == 1:
                pl_idx = p
        last_ph[i] = ph_idx
        last_pl[i] = pl_idx
    return last_ph, last_pl


# ----------------------------- core test ------------------------------------------
def load(sym, tf):
    d = np.load(os.path.join(CACHE, f"{sym}_{tf}.npz"))
    return (d["t"].astype(np.int64), d["o"].astype(float), d["h"].astype(float),
            d["l"].astype(float), d["c"].astype(float), d["v"].astype(float))


def run_one(sym, tf, k, meta):
    t, o, h, l, c, v = load(sym, tf)
    n = len(c)
    N = N_BY_TF[tf]

    e = ema(c, EMA_LEN)
    r = rsi_wilder(c, RSI_LEN)
    a = atr_wilder(h, l, c, ATR_LEN)
    last_ph, last_pl = confirmed_pivots(h, l, PIVOT_W)

    point = meta["point"]
    tick_val = meta["trade_tick_value"]
    tick_size = meta["trade_tick_size"]
    vmin = meta["volume_min"]
    cost_price = COST_POINTS[sym] * point  # round-trip cost in price units
    # money per 1.0 price unit of favorable move at min lot:
    money_per_price = (tick_val / tick_size) * vmin

    warm = max(RSI_LEN, EMA_LEN, ATR_LEN) + PIVOT_W + 2
    split = int(n * 0.67)

    # edge-triggered overbought / oversold
    over = (r > 70.0) & (c > (e + k * a))
    under = (r < 30.0) & (c < (e - k * a))

    events = []  # dict per event
    for i in range(warm, n - 1):  # need i+1 for entry; time stop handles the rest
        up_event = over[i] and not over[i - 1]
        dn_event = under[i] and not under[i - 1]
        if not (up_event or dn_event):
            continue
        side = "SELL" if up_event else "BUY"

        # ---- reversion statistic: does price touch EMA20[i] within N bars? ----
        emah = e[i]
        jmax = min(i + N, n - 1)
        reverted = False
        bars_to_revert = None
        for j in range(i + 1, jmax + 1):
            if up_event and l[j] <= emah:
                reverted = True
                bars_to_revert = j - i
                break
            if dn_event and h[j] >= emah:
                reverted = True
                bars_to_revert = j - i
                break

        # ---- tradable: entry at i+1 open ----
        entry = o[i + 1]
        # SL anchor = recent confirmed swing (known at bar i)
        if up_event:
            ph = last_ph[i]
            swing = h[ph] if ph >= 0 else h[max(0, i - PIVOT_W):i + 1].max()
            sl = max(swing, h[i]) + SL_BUFFER_ATR * a[i]
            risk = sl - entry
        else:
            pl = last_pl[i]
            swing = l[pl] if pl >= 0 else l[max(0, i - PIVOT_W):i + 1].min()
            sl = min(swing, l[i]) - SL_BUFFER_ATR * a[i]
            risk = entry - sl
        if risk <= cost_price * 0.5 or not np.isfinite(risk):
            # degenerate / sub-cost risk -> skip (cannot trade sensibly)
            continue

        tp_ema = emah
        tp_15r = entry - 1.5 * risk if up_event else entry + 1.5 * risk

        # walk forward from i+1 ... time stop at jmax. First touch wins.
        # intrabar tie-break: assume SL hit first if both SL and TP inside same bar (conservative).
        def simulate(tp):
            for j in range(i + 1, jmax + 1):
                hit_sl = (h[j] >= sl) if up_event else (l[j] <= sl)
                if up_event:
                    hit_tp = l[j] <= tp
                else:
                    hit_tp = h[j] >= tp
                if hit_sl and hit_tp:
                    return -risk, "SL_tie", j - i
                if hit_sl:
                    return -risk, "SL", j - i
                if hit_tp:
                    gain = (entry - tp) if up_event else (tp - entry)
                    return gain, "TP", j - i
            # time stop
            exitp = c[jmax]
            gain = (entry - exitp) if up_event else (exitp - entry)
            return gain, "TIME", jmax - i

        pl_ema, out_ema, dur_ema = simulate(tp_ema)
        pl_15r, out_15r, dur_15r = simulate(tp_15r)

        events.append({
            "i": int(i), "t": int(t[i]), "side": side, "is": i < split,
            "reverted": bool(reverted),
            "bars_to_revert": bars_to_revert,
            "risk_price": float(risk),
            "pl_ema_price": float(pl_ema), "out_ema": out_ema,
            "pl_15r_price": float(pl_15r), "out_15r": out_15r,
        })

    # ---- aggregate OOS ----
    oos = [ev for ev in events if not ev["is"]]
    n_oos = len(oos)

    def summarize(plkey, outkey):
        if n_oos == 0:
            return None
        pls = np.array([ev[plkey] for ev in oos], dtype=float)
        # net of cost in money per min-lot
        net_money = (pls - cost_price) * money_per_price
        wins = np.array([ev[outkey] == "TP" for ev in oos])
        gross_pos = net_money[net_money > 0].sum()
        gross_neg = -net_money[net_money < 0].sum()
        pf = (gross_pos / gross_neg) if gross_neg > 1e-9 else float("inf")
        # expectancy in R (price pl / risk), net of cost
        rs = (pls - cost_price) / np.array([ev["risk_price"] for ev in oos])
        return {
            "n": int(n_oos),
            "win_rate": float(wins.mean()),
            "net_money_total": float(net_money.sum()),
            "net_money_mean": float(net_money.mean()),
            "expectancy_R": float(rs.mean()),
            "profit_factor": float(pf) if np.isfinite(pf) else 999.0,
            "tp_count": int((np.array([ev[outkey] for ev in oos]) == "TP").sum()),
            "sl_count": int((np.array([ev[outkey] for ev in oos]) == "SL").sum())
                       + int((np.array([ev[outkey] for ev in oos]) == "SL_tie").sum()),
            "time_count": int((np.array([ev[outkey] for ev in oos]) == "TIME").sum()),
        }

    # reversion statistic OOS
    rev_flags = np.array([ev["reverted"] for ev in oos]) if n_oos else np.array([])
    btr = [ev["bars_to_revert"] for ev in oos if ev["reverted"]]
    rev_rate = float(rev_flags.mean()) if n_oos else None
    med_btr = float(np.median(btr)) if btr else None

    return {
        "symbol": sym, "tf": tf, "k": k, "N_bars": N,
        "n_events_total": len(events),
        "n_events_oos": n_oos,
        "n_events_is": len(events) - n_oos,
        "small_sample": n_oos < 30,
        "reversion_rate_oos": rev_rate,          # hit-rate of touching EMA20 within N
        "median_bars_to_revert_oos": med_btr,
        "trade_tp_ema_oos": summarize("pl_ema_price", "out_ema"),
        "trade_tp_15r_oos": summarize("pl_15r_price", "out_15r"),
        "cost_price": float(cost_price),
        "money_per_price_unit_minlot": float(money_per_price),
    }


def main():
    metas = {}
    for sym in SYMBOLS:
        with open(os.path.join(CACHE, f"{sym}_meta.json")) as f:
            metas[sym] = json.load(f)

    results = {}
    for sym in SYMBOLS:
        for tf in TFS:
            for k in K_LIST:
                key = f"{sym}_{tf}_k{k}"
                try:
                    results[key] = run_one(sym, tf, k, metas[sym])
                except Exception as ex:
                    results[key] = {"error": repr(ex), "symbol": sym, "tf": tf, "k": k}

    out_path = os.path.join(CACHE, "reversion_lab_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    # ---------------- pretty print ----------------
    print("=" * 118)
    print("REVERSION LAB — overbought/extension -> revert to EMA20 ?  (OOS only, 67/33 split, no-lookahead)")
    print("=" * 118)
    hdr = (f"{'SYM':9}{'TF':4}{'k':5}{'OOS_ev':7}{'rev%':7}{'medBars':8} | "
           f"{'TPema:WR':9}{'expR':7}{'PF':6}{'net$':9} | {'TP1.5R:WR':10}{'expR':7}{'PF':6}{'net$':9}")
    print(hdr)
    print("-" * 118)
    for sym in SYMBOLS:
        for tf in TFS:
            for k in K_LIST:
                rdat = results[f"{sym}_{tf}_k{k}"]
                if "error" in rdat:
                    print(f"{sym:9}{tf:4}{k:<5}ERROR {rdat['error'][:60]}")
                    continue
                revp = rdat["reversion_rate_oos"]
                revs = f"{revp*100:5.1f}" if revp is not None else "  n/a"
                mb = rdat["median_bars_to_revert_oos"]
                mbs = f"{mb:6.0f}" if mb is not None else "   n/a"
                te = rdat["trade_tp_ema_oos"]
                tr = rdat["trade_tp_15r_oos"]
                ss = "*" if rdat["small_sample"] else " "

                def fmt(td):
                    if td is None:
                        return f"{'--':9}{'--':7}{'--':6}{'--':9}"
                    return (f"{td['win_rate']*100:6.1f}%  {td['expectancy_R']:+5.2f} "
                            f"{td['profit_factor']:5.2f} {td['net_money_total']:+8.1f}")
                print(f"{sym:9}{tf:4}{k:<5}{rdat['n_events_oos']:5d}{ss} {revs}  {mbs}  | "
                      f"{fmt(te)} | {fmt(tr)}")
        print("-" * 118)
    print("* = small sample (<30 OOS events) — treat as unreliable")
    print(f"\nRaw results saved -> {out_path}")
    return results


if __name__ == "__main__":
    main()
