"""
MTF confluence threshold test — strict walk-forward, cost-inclusive, no lookahead.

Family: does requiring MORE timeframes to agree (M5+M15+H1 trend) improve OOS?

Base trigger (M5): CONTINUATION pullback (same as full_scan_lab):
  long  = ema8>ema21 and low<=ema8 and close>ema8
  short = ema8<ema21 and high>=ema8 and close<ema8
Confluence gate: count HTFs in {M15,H1} whose EMA8/EMA21 trend agrees with base dir.
  score = 1 (M5 alone) .. 3 (M5+M15+H1 all agree). Threshold k in {1,2,3}.
Exit: SL=1.5*ATR(M5), TP=2R. Cost round-trip in PRICE units. MAX_HOLD=200.
Causality: HTF vote uses only HTF bars whose CLOSE time <= close time of M5 bar i.
Entry at open of M5 bar i+1. Intrabar conservative SL-before-TP.
Walk-forward: pool R across FX basket (R unit-free). IS=first 67% by entry time,
OOS=last 33%. Optimize k on IS (max IS mean-R, IS n>=MIN_IS), lock, measure OOS.
"""
import json, os, numpy as np

LAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lab_cache")
EMA_FAST, EMA_SLOW, ATR_LEN = 8, 21, 14
SL_ATR, TP_R, MAX_HOLD = 1.5, 2.0, 200
IS_FRAC = 0.67
MIN_IS = 50
SEED = 12345

# FX basket with defensible round-trip cost in PRICE units.
COST = {
    "EURUSDm":0.00015,"GBPUSDm":0.00015,"AUDUSDm":0.00015,"NZDUSDm":0.00015,
    "USDCADm":0.00015,"USDCHFm":0.00015,"USDJPYm":0.015,
    "EURGBPm":0.00018,"EURAUDm":0.00020,"GBPAUDm":0.00022,
    "EURJPYm":0.015,"AUDJPYm":0.015,"CADJPYm":0.015,"NZDJPYm":0.015,"GBPJPYm":0.020,
}
TF_SEC = {"M5":300, "M15":900, "H1":3600}

def ema(x, length):
    a = 2.0/(length+1.0); out = np.empty_like(x, dtype=np.float64); out[0]=x[0]
    for i in range(1,len(x)): out[i]=a*x[i]+(1-a)*out[i-1]
    return out

def atr(h,l,c,length):
    n=len(c); tr=np.empty(n); tr[0]=h[0]-l[0]
    for i in range(1,n): tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
    out=np.empty(n); out[0]=tr[0]; a=1.0/length
    for i in range(1,n): out[i]=a*tr[i]+(1-a)*out[i-1]
    return out

def resolve(h,l,c,eidx,direction,sl,tp):
    n=len(c); end=min(n,eidx+MAX_HOLD)
    for j in range(eidx,end):
        hi,lo=h[j],l[j]
        if direction==1:
            if lo<=sl: return sl,j
            if hi>=tp: return tp,j
        else:
            if hi>=sl: return sl,j
            if lo<=tp: return tp,j
    return c[end-1],end-1

def htf_vote(t_m5_close, t_htf, ema_f, ema_s):
    """For each M5 close-time, vote = sign(ema8-ema21) of last HTF bar closed by then."""
    htf_close = t_htf + (t_htf[1]-t_htf[0])          # close time of each HTF bar
    idx = np.searchsorted(htf_close, t_m5_close, side="right") - 1  # last closed HTF bar
    votes = np.zeros(len(t_m5_close), dtype=np.int8)
    valid = idx >= 0
    vi = idx[valid]
    diff = ema_f[vi] - ema_s[vi]
    v = np.where(diff>0, 1, np.where(diff<0, -1, 0)).astype(np.int8)
    votes[valid] = v
    return votes

def build_symbol(sym):
    d5 = np.load(os.path.join(LAB, f"{sym}_M5.npz"))
    o,h,l,c,t = (d5["o"].astype(float),d5["h"].astype(float),d5["l"].astype(float),
                 d5["c"].astype(float),d5["t"].astype(np.int64))
    ema_f=ema(c,EMA_FAST); ema_s=ema(c,EMA_SLOW); atr_v=atr(h,l,c,ATR_LEN)
    t_close = t + TF_SEC["M5"]
    votes={}
    for htf in ("M15","H1"):
        dh=np.load(os.path.join(LAB, f"{sym}_{htf}.npz"))
        hf=ema(dh["c"].astype(float),EMA_FAST); hs=ema(dh["c"].astype(float),EMA_SLOW)
        votes[htf]=htf_vote(t_close, dh["t"].astype(np.int64), hf, hs)
    return o,h,l,c,t,ema_f,ema_s,atr_v,votes

def gen_trades(sym):
    o,h,l,c,t,ema_f,ema_s,atr_v,votes = build_symbol(sym)
    cost = COST[sym]; n=len(c)
    start = max(EMA_SLOW,ATR_LEN)+1
    v15,vH1 = votes["M15"],votes["H1"]
    trades=[]  # (entry_time, dir, score, R)
    for i in range(start, n-1):
        a=atr_v[i]
        if not np.isfinite(a) or a<=0: continue
        ci=c[i]
        d=0
        if ema_f[i]>ema_s[i] and l[i]<=ema_f[i] and ci>ema_f[i]: d=1
        elif ema_f[i]<ema_s[i] and h[i]>=ema_f[i] and ci<ema_f[i]: d=-1
        else: continue
        score = 1 + (1 if v15[i]==d else 0) + (1 if vH1[i]==d else 0)
        eidx=i+1; entry=o[eidx]; dist=SL_ATR*a
        sl = entry-dist if d==1 else entry+dist
        tp = entry+TP_R*dist if d==1 else entry-TP_R*dist
        xp,xi = resolve(h,l,c,eidx,d,sl,tp)
        raw = (xp-entry) if d==1 else (entry-xp)
        R = (raw-cost)/dist
        trades.append((int(t[eidx]), d, score, R))
    return trades

def stats(rs):
    rs=np.asarray(rs,float); n=len(rs)
    if n<2: return n, float('nan'), float('nan'), float('nan')
    m=rs.mean(); sd=rs.std(ddof=1)
    tstat = m/(sd/np.sqrt(n)) if sd>0 else float('nan')
    g=rs[rs>0].sum(); ls=-rs[rs<0].sum(); pf=(g/ls) if ls>0 else float('inf')
    return n, m, tstat, pf

def main():
    np.seterr(all="ignore")
    all_tr=[]
    for sym in COST:
        try: all_tr.extend(gen_trades(sym))
        except Exception as e: print("skip",sym,e)
    all_tr.sort(key=lambda x:x[0])
    times=np.array([x[0] for x in all_tr])
    split_t = np.quantile(times, IS_FRAC)
    IS=[x for x in all_tr if x[0]< split_t]
    OOS=[x for x in all_tr if x[0]>=split_t]
    print(f"Total pooled trades={len(all_tr)}  IS={len(IS)} OOS={len(OOS)}  split_t={int(split_t)}")
    print(f"{'k':>2} | {'IS_n':>6} {'IS_expR':>8} {'IS_t':>6} {'IS_PF':>6} | {'OOS_n':>6} {'OOS_expR':>9} {'OOS_t':>6} {'OOS_PF':>6}")
    res={}
    for k in (1,2,3):
        isr=[x[3] for x in IS if x[2]>=k]; oor=[x[3] for x in OOS if x[2]>=k]
        ni,mi,ti,pfi=stats(isr); no,mo,to,pfo=stats(oor)
        res[k]=dict(is_n=ni,is_expR=mi,is_t=ti,is_pf=pfi,oos_n=no,oos_expR=mo,oos_t=to,oos_pf=pfo)
        print(f"{k:>2} | {ni:>6} {mi:>8.4f} {ti:>6.2f} {pfi:>6.2f} | {no:>6} {mo:>9.4f} {to:>6.2f} {pfo:>6.2f}")
    # IS-optimize k: max IS mean-R with IS n>=MIN_IS
    cand=[k for k in (1,2,3) if res[k]["is_n"]>=MIN_IS]
    best=max(cand, key=lambda k:res[k]["is_expR"])
    r=res[best]
    print(f"\nIS-selected k={best} (max IS expR among n>= {MIN_IS})")
    print(f"LOCKED OOS: n={r['oos_n']} expR={r['oos_expR']:.4f} t={r['oos_t']:.2f} PF={r['oos_pf']:.2f}")
    net_pos = r['oos_expR']>0
    survives = net_pos and r['oos_n']>=30 and (r['oos_t']==r['oos_t'] and r['oos_t']>=2)
    print(f"survives(OOS>0 & n>=30 & t>=2 & cost incl)= {survives}")
    json.dump({"selected_k":best,"per_k":{str(k):res[k] for k in res},"survives":bool(survives)},
              open(os.path.join(os.path.dirname(__file__),"scratchpad_mtf_result.json"),"w"),indent=2,default=str)

if __name__=="__main__":
    main()
