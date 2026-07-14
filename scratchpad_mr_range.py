"""
Mean-reversion at Bollinger/RSI extremes, ONLY in confirmed RANGE regime.
Strict no-lookahead walk-forward. Reuses full_scan_lab mechanics (ema/atr/
resolve_trade conservative intrabar, cost in price units, R = net/dist).

RULE (long; short mirrored):
  Regime filter (range):  ADX(14) < adx_thr        AND close between BB bands historically flat
  Entry trigger at bar i (data<=i only):
     close[i] < lowerBB(20, bb_std)  AND  RSI(14)[i] < rsi_lo
  Enter at OPEN of i+1.
  SL = entry - sl_atr*ATR(14)[i]      (risk = SL distance)
  TP = mid band SMA20[i]  (target back to mean); must be profitable side else skip.
  Short: close>upperBB AND RSI>rsi_hi -> short, TP=SMA20.

Params tuned on IN-SAMPLE (first 67% by time), measured ONLY on OOS (last 33%).
Tunable grid: rsi_lo in {25,30,35} (rsi_hi=100-rsi_lo), bb_std in {2.0,2.5},
              adx_thr in {20,25}.  -> 12 combos, pick best IS expectancy (with IS n>=30),
              then report that single combo OOS.
Cost included (round-trip, price units). Judge by OOS expR, t-stat, max DD in R.
"""
import json, os, sys
import numpy as np

LAB = r"C:\Users\Radhi\MT5\data\lab_cache"

# ---- reused mechanics ----
def sma(x, n):
    out = np.full_like(x, np.nan, dtype=np.float64)
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[n-1:] = (c[n:] - c[:-n]) / n
    return out

def rolling_std(x, n):
    out = np.full_like(x, np.nan, dtype=np.float64)
    for i in range(n-1, len(x)):
        out[i] = np.std(x[i-n+1:i+1])
    return out

def atr(h, l, c, length):
    n = len(c); tr = np.empty(n); tr[0] = h[0]-l[0]
    for i in range(1, n):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    out = np.empty(n); out[0] = tr[0]; a = 1.0/length
    for i in range(1, n):
        out[i] = a*tr[i] + (1-a)*out[i-1]
    return out

def rsi(c, length=14):
    n = len(c); out = np.full(n, np.nan)
    d = np.diff(c)
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au = up[:length].mean(); ad = dn[:length].mean()
    out[length] = 100 - 100/(1 + (au/ad if ad > 0 else np.inf))
    for i in range(length+1, n):
        au = (au*(length-1) + up[i-1]) / length
        ad = (ad*(length-1) + dn[i-1]) / length
        rs = au/ad if ad > 0 else np.inf
        out[i] = 100 - 100/(1+rs)
    return out

def adx(h, l, c, length=14):
    n = len(c); out = np.full(n, np.nan)
    tr = np.empty(n); plus_dm = np.zeros(n); minus_dm = np.zeros(n)
    tr[0] = h[0]-l[0]
    for i in range(1, n):
        up_move = h[i]-h[i-1]; dn_move = l[i-1]-l[i]
        plus_dm[i] = up_move if (up_move > dn_move and up_move > 0) else 0.0
        minus_dm[i] = dn_move if (dn_move > up_move and dn_move > 0) else 0.0
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    # Wilder smoothing
    atr_s = np.empty(n); pdm_s = np.empty(n); mdm_s = np.empty(n)
    atr_s[0]=tr[0]; pdm_s[0]=plus_dm[0]; mdm_s[0]=minus_dm[0]
    a = 1.0/length
    for i in range(1, n):
        atr_s[i] = a*tr[i] + (1-a)*atr_s[i-1]
        pdm_s[i] = a*plus_dm[i] + (1-a)*pdm_s[i-1]
        mdm_s[i] = a*minus_dm[i] + (1-a)*mdm_s[i-1]
    pdi = 100 * pdm_s / np.where(atr_s > 0, atr_s, np.nan)
    mdi = 100 * mdm_s / np.where(atr_s > 0, atr_s, np.nan)
    dx = 100 * np.abs(pdi - mdi) / np.where((pdi+mdi) > 0, (pdi+mdi), np.nan)
    out[length] = np.nanmean(dx[1:length+1])
    for i in range(length+1, n):
        out[i] = (out[i-1]*(length-1) + dx[i]) / length
    return out

MAX_HOLD = 200
def resolve_trade(h, l, c, entry_idx, direction, sl, tp):
    n = len(c); end = min(n, entry_idx + MAX_HOLD)
    for j in range(entry_idx, end):
        hi, lo = h[j], l[j]
        if direction == 1:
            if lo <= sl: return sl, j          # conservative: SL first
            if hi >= tp: return tp, j
        else:
            if hi >= sl: return sl, j
            if lo <= tp: return tp, j
    return c[end-1], end-1

def bootstrap_ci(rs, n_boot=2000, seed=12345):
    rs = np.asarray(rs);
    if len(rs) < 2: return (np.nan, np.nan)
    rng = np.random.default_rng(seed); n = len(rs)
    means = np.array([rs[rng.integers(0,n,n)].mean() for _ in range(n_boot)])
    return float(np.percentile(means,2.5)), float(np.percentile(means,97.5))

def max_dd_R(rs):
    """worst peak-to-trough of cumulative R equity curve, in R."""
    eq = np.cumsum(rs); peak = np.maximum.accumulate(eq)
    return float((eq - peak).min()) if len(rs) else 0.0

def pf(rs):
    rs=np.asarray(rs); g=rs[rs>0].sum(); L=-rs[rs<0].sum()
    return float(g/L) if L>0 else (float('inf') if g>0 else 0.0)

# ---- signal generation for one param combo ----
BB_N=20; RSI_N=14; ATR_N=14; ADX_N=14; SL_ATR=1.5
def gen_trades(o,h,l,c, mid, dev, rsi_v, adx_v, atr_v, cost, bb_std, rsi_lo, rsi_hi, adx_thr):
    upper = mid + bb_std*dev; lower = mid - bb_std*dev
    trades = []  # (entry_idx, R)
    start = max(BB_N, RSI_N, ATR_N, ADX_N) + 2
    n = len(c)
    for i in range(start, n-1):
        a = atr_v[i]
        if not np.isfinite(a) or a<=0: continue
        if not np.isfinite(adx_v[i]) or adx_v[i] >= adx_thr: continue   # range regime only
        if not (np.isfinite(rsi_v[i]) and np.isfinite(lower[i]) and np.isfinite(upper[i])): continue
        direction=0
        if c[i] < lower[i] and rsi_v[i] < rsi_lo: direction=1
        elif c[i] > upper[i] and rsi_v[i] > rsi_hi: direction=-1
        else: continue
        entry_idx=i+1; entry=o[entry_idx]
        dist = SL_ATR*a
        sl = entry-dist if direction==1 else entry+dist
        tp = mid[i]
        if direction==1 and tp<=entry: continue
        if direction==-1 and tp>=entry: continue
        ex,_ = resolve_trade(h,l,c,entry_idx,direction,sl,tp)
        raw = (ex-entry) if direction==1 else (entry-ex)
        R = (raw - cost)/dist
        trades.append((entry_idx, R))
    return trades

def scan(sym, tf, cost):
    d = np.load(os.path.join(LAB, f"{sym}_{tf}.npz"))
    o,h,l,c = (d["o"].astype(float),d["h"].astype(float),d["l"].astype(float),d["c"].astype(float))
    n=len(c)
    mid=sma(c,BB_N); dev=rolling_std(c,BB_N); rsi_v=rsi(c,RSI_N)
    adx_v=adx(h,l,c,ADX_N); atr_v=atr(h,l,c,ATR_N)
    split=int(n*0.67)
    grid=[(bs,rl,100-rl,at) for bs in (2.0,2.5) for rl in (25,30,35) for at in (20,25)]
    best=None
    for (bs,rl,rh,at) in grid:
        trs=gen_trades(o,h,l,c,mid,dev,rsi_v,adx_v,atr_v,cost,bs,rl,rh,at)
        is_R=[R for (ei,R) in trs if ei<split]
        if len(is_R)<30: continue
        m=np.mean(is_R)
        if best is None or m>best[0]:
            best=(m,(bs,rl,rh,at),trs)
    if best is None:
        return {"symbol":sym,"tf":tf,"note":"no combo with IS n>=30"}
    m_is,params,trs=best
    oos=[R for (ei,R) in trs if ei>=split]
    oos=np.asarray(oos)
    n_oos=len(oos)
    if n_oos<2:
        return {"symbol":sym,"tf":tf,"params":params,"n_oos":n_oos,"note":"too few OOS"}
    exp=float(oos.mean()); sd=float(oos.std())
    t=exp/(sd+1e-9)*np.sqrt(n_oos)
    lo,hi=bootstrap_ci(oos)
    wr=float((oos>0).mean())
    return {"symbol":sym,"tf":tf,"params":{"bb_std":params[0],"rsi_lo":params[1],
            "rsi_hi":params[2],"adx_thr":params[3]},
            "is_expR":round(m_is,4),"is_n":sum(1 for(ei,R)in trs if ei<split),
            "n_oos":n_oos,"oos_expR":round(exp,5),"oos_t":round(t,3),
            "oos_pf":round(pf(oos),3),"max_dd_R":round(max_dd_R(oos),3),
            "ci_lo":round(lo,5),"ci_hi":round(hi,5),"win_rate":round(wr,4),
            "cost":cost}

COST={"EURUSDm":0.00015,"GBPUSDm":0.00018,"EURGBPm":0.00018,"USDCHFm":0.00018,
      "AUDUSDm":0.00016,"USDCADm":0.00018,"NZDUSDm":0.00020,"EURJPYm":0.015,
      "XAUUSDm":0.30,"USOILm":0.004}

if __name__=="__main__":
    targets=[("EURUSDm","M15"),("EURUSDm","H1"),("GBPUSDm","M15"),("EURGBPm","M15"),
             ("EURGBPm","H1"),("USDCHFm","M15"),("AUDUSDm","M15"),("EURJPYm","M15"),
             ("XAUUSDm","M15"),("USOILm","M15")]
    res=[]
    for sym,tf in targets:
        try: res.append(scan(sym,tf,COST[sym]))
        except Exception as e: res.append({"symbol":sym,"tf":tf,"error":str(e)})
    print(json.dumps(res,indent=2))
