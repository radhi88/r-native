"""
Time-of-day seasonality — STRICT walk-forward, OFFLINE (no MT5).

Rule family (one precise testable rule):
  "At server-hour H, enter direction D at the OPEN of that H1 bar; exit at the
   CLOSE of the same bar (hold exactly 1 hour). Risk unit = Wilder ATR14 at
   entry (data<=i only). Net R = (D*(close-open) - cost) / ATR."

Walk-forward / honest model selection:
  * Split 67/33 by time (IS then OOS).
  * On IN-SAMPLE only: for every (hour 0..23, direction +/-1) compute mean R.
    Pick the SINGLE (hour,dir) with the highest IS mean R that has n_is>=MIN_IS.
  * On OUT-OF-SAMPLE only: measure that ONE chosen (hour,dir) cell.
  * Judge OOS by expectancy (mean R net cost) + t-stat + max drawdown (R).
  * survives = oos_expR>0 AND n_oos>=30 AND t>=3 AND cost included.

No lookahead: ATR at bar i uses bars<=i; entry uses open[i], exit uses close[i]
of the SAME completed bar's return (a decision made at bar-i open, resolved at
bar-i close — the hour's realized return). Cost subtracted in PRICE units.
"""
import json, os, numpy as np, datetime as dt

LAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lab_cache")

# round-trip cost in PRICE units per symbol (established values)
COST = {
    "XAUUSDm": 0.30, "XAUEURm": 0.30, "USOILm": 0.004,
    "EURUSDm": 0.00015, "GBPUSDm": 0.00020, "USDJPYm": 0.015,
    "EURJPYm": 0.015, "GBPJPYm": 0.020, "AUDJPYm": 0.015,
    "US30m": 3.0, "US500m": 0.5, "USTECm": 2.0, "DE30m": 3.0,
    "BTCUSDm": 40.0, "ETHUSDm": 3.0,
}
ATR_LEN = 14
IS_FRAC = 0.67
MIN_IS = 100     # need enough IS samples in the chosen hour to trust selection
SEED = 12345


def atr(h, l, c, length):
    n = len(c); tr = np.empty(n); tr[0] = h[0]-l[0]
    for i in range(1, n):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    out = np.empty(n); out[0] = tr[0]; a = 1.0/length
    for i in range(1, n):
        out[i] = a*tr[i] + (1-a)*out[i-1]
    return out


def tstat(rs):
    rs = np.asarray(rs, float)
    if len(rs) < 2: return 0.0
    return float(rs.mean() / (rs.std(ddof=1)+1e-12) * np.sqrt(len(rs)))


def max_dd_R(rs):
    """peak-to-trough drawdown of the cumulative-R equity curve, in R."""
    rs = np.asarray(rs, float)
    if len(rs) == 0: return 0.0
    eq = np.cumsum(rs); peak = np.maximum.accumulate(eq)
    return float((eq - peak).min())  # <=0


def build_R(sym, tf="H1"):
    d = np.load(os.path.join(LAB, f"{sym}_{tf}.npz"))
    o,h,l,c,t = (d["o"].astype(float), d["h"].astype(float), d["l"].astype(float),
                 d["c"].astype(float), d["t"].astype(np.int64))
    a = atr(h,l,c,ATR_LEN)
    hour = np.array([dt.datetime.utcfromtimestamp(int(x)).hour for x in t])
    cost = COST[sym]
    n = len(c)
    # per-bar realized R for LONG (short is the negation of raw part, cost re-subtracted)
    Rlong = np.full(n, np.nan); Rshort = np.full(n, np.nan)
    for i in range(ATR_LEN+1, n):
        ai = a[i]
        if not np.isfinite(ai) or ai <= 0: continue
        raw = c[i]-o[i]
        Rlong[i]  = ( raw - cost)/ai
        Rshort[i] = (-raw - cost)/ai
    return hour, Rlong, Rshort, n


def scan_symbol(sym):
    hour, Rlong, Rshort, n = build_R(sym)
    split = int(n*IS_FRAC)
    idx = np.arange(n)
    is_mask = (idx < split); oos_mask = (idx >= split)

    # choose best (hour,dir) on IS by mean R with n_is>=MIN_IS
    best = None
    for hh in range(24):
        for name, Rarr in (("LONG", Rlong), ("SHORT", Rshort)):
            m = is_mask & (hour == hh) & np.isfinite(Rarr)
            rs = Rarr[m]
            if len(rs) < MIN_IS: continue
            em = rs.mean()
            if best is None or em > best[0]:
                best = (em, hh, name, Rarr)
    if best is None:
        return None
    is_expR, chosen_h, chosen_dir, Rarr = best

    # measure ONLY the chosen cell on OOS
    om = oos_mask & (hour == chosen_h) & np.isfinite(Rarr)
    oos = Rarr[om]
    if len(oos) == 0:
        return None
    win = float((oos > 0).mean())
    return {
        "symbol": sym, "tf": "H1", "chosen_hour": chosen_h, "chosen_dir": chosen_dir,
        "is_expR": round(is_expR,5),
        "oos_n": int(len(oos)), "oos_expR": round(float(oos.mean()),5),
        "oos_t": round(tstat(oos),3), "oos_pf": round(
            float(oos[oos>0].sum()/(-oos[oos<0].sum()+1e-12)),3),
        "oos_win": round(win,3), "max_dd_R": round(max_dd_R(oos),3),
        "cost_included": True,
    }


def main():
    np.seterr(all="ignore")
    syms = ["XAUUSDm","XAUEURm","EURUSDm","GBPUSDm","USDJPYm","EURJPYm","GBPJPYm",
            "AUDJPYm","USOILm","US30m","US500m","USTECm","BTCUSDm","ETHUSDm"]
    rows = []
    for s in syms:
        try:
            r = scan_symbol(s)
        except Exception as e:
            print("ERR", s, e); continue
        if r: rows.append(r)
    rows.sort(key=lambda x: x["oos_t"], reverse=True)
    print(f"{'SYM':9s}{'hr':>3s} {'dir':6s}{'IS_expR':>9s}{'OOS_n':>6s}"
          f"{'OOS_expR':>10s}{'OOS_t':>7s}{'OOS_PF':>7s}{'win':>6s}{'maxDD_R':>9s}"
          f"  survives")
    print("-"*90)
    for r in rows:
        surv = (r["oos_expR"]>0 and r["oos_n"]>=30 and r["oos_t"]>=3)
        r["survives"] = surv
        print(f"{r['symbol']:9s}{r['chosen_hour']:>3d} {r['chosen_dir']:6s}"
              f"{r['is_expR']:>9.4f}{r['oos_n']:>6d}{r['oos_expR']:>10.4f}"
              f"{r['oos_t']:>7.2f}{r['oos_pf']:>7.2f}{r['oos_win']:>6.2f}"
              f"{r['max_dd_R']:>9.2f}  {'YES' if surv else 'no'}")
    out = os.path.join(LAB, "tod_seasonality_results.json")
    json.dump(rows, open(out,"w"), indent=2)
    print("\nsaved ->", out)


if __name__ == "__main__":
    main()
