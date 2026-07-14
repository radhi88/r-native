"""
scratch_orb_lab.py  (offline, no MT5)
Opening-Range Breakout, session-gated, ATR filter. Strict walk-forward.
Reuses full_scan_lab cost/resolve conventions:
 - signal uses data<=i, entry at open of i+1
 - intrabar conservative: SL assumed first if SL&TP same bar
 - cost subtracted in PRICE units before R
 - IS/OOS 67/33 by time; params picked on IS, measured on OOS only
"""
import json, os, datetime as dt
import numpy as np

LAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lab_cache")

# round-trip cost in PRICE units (conservative retail)
COST = {"EURUSDm":0.00015, "GBPUSDm":0.00020, "DE30m":2.0, "US30m":4.0,
        "US500m":0.6, "USTECm":3.0, "USDJPYm":0.015}
ATR_LEN=14; MAX_HOLD_DAYEND=True; IS_FRAC=0.67

def atr(h,l,c,length):
    n=len(c); tr=np.empty(n); tr[0]=h[0]-l[0]
    for i in range(1,n):
        tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
    out=np.empty(n); out[0]=tr[0]; a=1.0/length
    for i in range(1,n): out[i]=a*tr[i]+(1-a)*out[i-1]
    return out

def load(sym,tf):
    d=np.load(os.path.join(LAB,f"{sym}_{tf}.npz"))
    return (d["t"].astype(np.int64), d["o"].astype(float), d["h"].astype(float),
            d["l"].astype(float), d["c"].astype(float))

def resolve(h,l,c,entry_idx,day_end_idx,direction,sl,tp):
    end=day_end_idx+1
    for j in range(entry_idx,end):
        hi,lo=h[j],l[j]
        if direction==1:
            if lo<=sl and hi>=tp: return sl,j
            if lo<=sl: return sl,j
            if hi>=tp: return tp,j
        else:
            if hi>=sl and lo<=tp: return sl,j
            if hi>=sl: return sl,j
            if lo<=tp: return tp,j
    return c[end-1], end-1   # forced close at day end (no overnight)

def build_days(t):
    """map each bar to broker calendar day index; return list of (day, [bar idxs])"""
    days={}
    for i,ts in enumerate(t):
        d=dt.datetime.utcfromtimestamp(int(ts))
        key=(d.year,d.month,d.day)
        days.setdefault(key,[]).append(i)
    return [days[k] for k in sorted(days.keys())]

def gen_trades(sym, t,o,h,l,c, atr_v, H, K, tp_r, atr_cap):
    """Return list of (entry_idx, R). One trade per day, first breakout."""
    trades=[]
    day_bars=build_days(t)
    hours=np.array([dt.datetime.utcfromtimestamp(int(x)).hour for x in t])
    cost=COST[sym]
    for bars in day_bars:
        # find first bar of session hour H
        sbars=[b for b in bars if hours[b]==H]
        if len(sbars)<K+1: continue
        s=sbars[0]
        or_bars=range(s, s+K)
        if s+K-1 >= len(c): continue
        or_hi=max(h[b] for b in or_bars); or_lo=min(l[b] for b in or_bars)
        width=or_hi-or_lo
        a=atr_v[s+K-1]
        if not np.isfinite(a) or a<=0: continue
        if atr_cap<900 and width>atr_cap*a: continue   # ATR filter: skip too-wide OR
        if width<=0: continue
        day_end=bars[-1]
        # scan from first bar after OR to day end for first breakout close
        took=False
        for i in range(s+K, day_end+1):
            if i+1>=len(c) or i+1>day_end: break
            ci=c[i]
            direction=0
            if ci>or_hi: direction=1
            elif ci<or_lo: direction=-1
            if direction==0: continue
            entry_idx=i+1
            entry=o[entry_idx]
            if direction==1:
                sl=or_lo; dist=entry-sl
            else:
                sl=or_hi; dist=sl-entry
            if dist<=0: continue
            tp = entry+tp_r*dist if direction==1 else entry-tp_r*dist
            ex,exidx=resolve(h,l,c,entry_idx,day_end,direction,sl,tp)
            raw=(ex-entry) if direction==1 else (entry-ex)
            net=raw-cost
            trades.append((entry_idx, net/dist))
            took=True
            break
        _=took
    return trades

def stats(rs):
    rs=np.asarray(rs,float); n=len(rs)
    if n==0: return dict(n=0,exp=0,t=0,pf=0,wr=0,maxdd=0)
    exp=rs.mean(); sd=rs.std()
    tval=exp/(sd+1e-9)*np.sqrt(n)
    g=rs[rs>0].sum(); ls=-rs[rs<0].sum()
    pf=(g/ls) if ls>0 else float('inf')
    wr=float((rs>0).mean())
    eq=np.cumsum(rs); peak=np.maximum.accumulate(eq); dd=(eq-peak).min()
    return dict(n=n,exp=float(exp),t=float(tval),pf=float(pf),wr=wr,maxdd=float(dd))

def run(sym, tf="M5"):
    t,o,h,l,c=load(sym,tf)
    atr_v=atr(h,l,c,ATR_LEN)
    n=len(c); split=int(n*IS_FRAC)
    grid=[]
    for H in (8,14):
        for K in (3,6,12):
            for tp_r in (1.0,2.0):
                for atr_cap in (2.5,999):
                    grid.append((H,K,tp_r,atr_cap))
    # tune on IS
    best=None
    for (H,K,tp_r,atr_cap) in grid:
        tr=gen_trades(sym,t,o,h,l,c,atr_v,H,K,tp_r,atr_cap)
        is_rs=[r for (ei,r) in tr if ei<split]
        st=stats(is_rs)
        if st["n"]>=20 and (best is None or st["exp"]>best[1]["exp"]):
            best=((H,K,tp_r,atr_cap),st,tr)
    if best is None: return None
    (H,K,tp_r,atr_cap),is_st,tr=best
    oos_rs=[r for (ei,r) in tr if ei>=split]
    oos=stats(oos_rs)
    return dict(sym=sym,tf=tf,params=dict(H=H,K=K,tp_r=tp_r,atr_cap=atr_cap),
                is_n=is_st["n"],is_exp=round(is_st["exp"],4),
                oos=oos, oos_n=oos["n"])

if __name__=="__main__":
    np.seterr(all="ignore")
    for sym in ["DE30m","US30m","EURUSDm","GBPUSDm","US500m","USTECm"]:
        try:
            r=run(sym)
        except Exception as e:
            print(sym,"ERR",e); continue
        if r is None: print(sym,"no IS trades"); continue
        p=r["params"]; oo=r["oos"]
        print(f"{sym:8s} best[H={p['H']} K={p['K']} tpR={p['tp_r']} cap={p['atr_cap']}] "
              f"IS n={r['is_n']} exp={r['is_exp']} | OOS n={oo['n']:4d} "
              f"exp={oo['exp']:+.4f} t={oo['t']:+.2f} pf={oo['pf']:.2f} "
              f"wr={oo['wr']:.2f} maxdd={oo['maxdd']:.1f}R")
