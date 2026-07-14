"""
Prev-Day H/L mean-reversion fade, session-gated. STRICT walk-forward.
Signal at bar i uses ONLY data <= i. Entry at OPEN of i+1.
Intrabar resolved conservatively (SL before TP). Cost subtracted in price units.
IS = first 67% by time (param pick). OOS = last 33% (measure only).
"""
import json, os, sys
import numpy as np
import datetime as dt

LAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lab_cache")

SYM = sys.argv[1] if len(sys.argv) > 1 else "XAUUSDm"
TF  = sys.argv[2] if len(sys.argv) > 2 else "M15"
COST = float(sys.argv[3]) if len(sys.argv) > 3 else 0.35   # gold round-trip price units ($)

ATR_LEN = 14
MAX_HOLD = 96          # bars max hold (96 M15 = 24h)
IS_FRAC = 0.67
MIN_N_IS = 50
SEED = 12345

def atr(h,l,c,length):
    n=len(c); tr=np.empty(n); tr[0]=h[0]-l[0]
    for i in range(1,n):
        tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
    out=np.empty(n); out[0]=tr[0]; a=1.0/length
    for i in range(1,n):
        out[i]=a*tr[i]+(1-a)*out[i-1]
    return out

def load(sym,tf):
    d=np.load(os.path.join(LAB,f"{sym}_{tf}.npz"))
    return (d["t"].astype(np.int64), d["o"].astype(float), d["h"].astype(float),
            d["l"].astype(float), d["c"].astype(float))

def prev_day_hl(t,h,l):
    """For each bar, PDH/PDL = high/low of the previous completed UTC calendar day."""
    n=len(t)
    days=np.array([dt.datetime.utcfromtimestamp(int(x)).toordinal() for x in t])
    # per-day hi/lo
    day_hi={}; day_lo={}
    for i in range(n):
        d=days[i]
        if d not in day_hi:
            day_hi[d]=h[i]; day_lo[d]=l[i]
        else:
            if h[i]>day_hi[d]: day_hi[d]=h[i]
            if l[i]<day_lo[d]: day_lo[d]=l[i]
    pdh=np.full(n,np.nan); pdl=np.full(n,np.nan)
    for i in range(n):
        pd=days[i]-1
        # find most recent prior day that exists (handle weekends)
        k=pd; tries=0
        while k not in day_hi and tries<5:
            k-=1; tries+=1
        if k in day_hi:
            pdh[i]=day_hi[k]; pdl[i]=day_lo[k]
    hours=np.array([dt.datetime.utcfromtimestamp(int(x)).hour for x in t])
    return pdh,pdl,hours

def resolve(h,l,c,entry_idx,direction,sl,tp):
    n=len(c); end=min(n,entry_idx+MAX_HOLD)
    for j in range(entry_idx,end):
        hi,lo=h[j],l[j]
        if direction==1:
            if lo<=sl: return sl,j
            if hi>=tp: return tp,j
        else:
            if hi>=sl: return sl,j
            if lo<=tp: return tp,j
    return c[end-1],end-1

def gen_trades(t,o,h,l,c,atr_v,pdh,pdl,hours,sess,sl_atr,tp_r,cost):
    """Return list of (entry_idx, R). Fade prev-day extreme touch during session."""
    n=len(c); trades=[]
    lo_h,hi_h=sess
    armed_day=-1; last_day=-1
    for i in range(ATR_LEN+2,n-1):
        a=atr_v[i]
        if not np.isfinite(a) or a<=0: continue
        if not np.isfinite(pdh[i]): continue
        hr=hours[i]
        in_sess = (lo_h<=hr<hi_h) if lo_h<hi_h else (hr>=lo_h or hr<hi_h)
        if not in_sess: continue
        # SHORT fade at PDH: bar high pierces PDH
        if h[i]>=pdh[i] and c[i] < h[i]:  # touched high, closed back
            entry_idx=i+1; entry=o[entry_idx]
            sl=entry+sl_atr*a; dist=sl-entry
            if dist<=0: continue
            tp=entry-tp_r*dist
            ep,ei=resolve(h,l,c,entry_idx,-1,sl,tp)
            raw=entry-ep; r=(raw-cost)/dist
            trades.append((entry_idx,r))
        # LONG fade at PDL
        elif l[i]<=pdl[i] and c[i] > l[i]:
            entry_idx=i+1; entry=o[entry_idx]
            sl=entry-sl_atr*a; dist=entry-sl
            if dist<=0: continue
            tp=entry+tp_r*dist
            ep,ei=resolve(h,l,c,entry_idx,1,sl,tp)
            raw=ep-entry; r=(raw-cost)/dist
            trades.append((entry_idx,r))
    return trades

def stats(rs):
    rs=np.asarray(rs,float); n=len(rs)
    if n==0: return dict(n=0,mean=0,pf=0,t=0,net=0)
    mean=rs.mean(); sd=rs.std(ddof=1) if n>1 else 0
    t=mean/(sd/np.sqrt(n)) if sd>0 else 0
    g=rs[rs>0].sum(); loss=-rs[rs<0].sum()
    pf=(g/loss) if loss>0 else (float('inf') if g>0 else 0)
    return dict(n=n,mean=float(mean),pf=float(pf),t=float(t),net=float(rs.sum()))

def main():
    t,o,h,l,c=load(SYM,TF)
    atr_v=atr(h,l,c,ATR_LEN)
    pdh,pdl,hours=prev_day_hl(t,h,l)
    n=len(c); split=int(n*IS_FRAC)

    SESSIONS={"all":(0,24),"london":(7,16),"ny":(12,21),"londony":(7,21),"asia":(0,7)}
    SL_ATRS=[0.5,1.0,1.5]; TP_RS=[1.0,1.5,2.0]

    # ---- IS param search ----
    best=None
    grid=[]
    for sname,sess in SESSIONS.items():
        for sla in SL_ATRS:
            for tpr in TP_RS:
                tr=gen_trades(t,o,h,l,c,atr_v,pdh,pdl,hours,sess,sla,tpr,COST)
                is_rs=[r for ei,r in tr if ei<split]
                st=stats(is_rs)
                grid.append((sname,sla,tpr,st))
                if st['n']>=MIN_N_IS and st['mean']>0:
                    if best is None or st['mean']>best[3]['mean']:
                        best=(sname,sla,tpr,st)
    print("=== IS grid (n>=%d shown, sorted by mean) ==="%MIN_N_IS)
    for sname,sla,tpr,st in sorted([g for g in grid if g[3]['n']>=MIN_N_IS],key=lambda x:-x[3]['mean']):
        print(f"  {sname:8s} SL={sla} TP={tpr}  n={st['n']:4d} meanR={st['mean']:+.4f} pf={st['pf']:.2f} t={st['t']:+.2f}")

    if best is None:
        print("\nNO IS config with positive mean & n>=%d. Nothing to lock."%MIN_N_IS)
        # still report OOS of the single most-traded config for honesty
        return
    sname,sla,tpr,is_st=best
    print(f"\n=== LOCKED (best IS mean): session={sname} SL_ATR={sla} TP_R={tpr} ===")
    print(f"IS: n={is_st['n']} meanR={is_st['mean']:+.4f} pf={is_st['pf']:.2f} t={is_st['t']:+.2f}")

    # ---- OOS measure only ----
    tr=gen_trades(t,o,h,l,c,atr_v,pdh,pdl,hours,SESSIONS[sname],sla,tpr,COST)
    oos_rs=[r for ei,r in tr if ei>=split]
    oos=stats(oos_rs)
    print(f"\n=== OOS (held-out, measure only) ===")
    print(f"session={sname} SL_ATR={sla} TP_R={tpr} cost=${COST}")
    print(f"OOS: n={oos['n']} meanR={oos['mean']:+.4f} pf={oos['pf']:.2f} t={oos['t']:+.2f} netR={oos['net']:+.2f}")
    survives = oos['net']>0 and oos['n']>=30 and oos['t']>=2
    print(f"SURVIVES (OOS net>0 & n>=30 & t>=2 & cost incl): {survives}")

if __name__=="__main__":
    main()
