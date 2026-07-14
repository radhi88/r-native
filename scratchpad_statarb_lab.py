"""
Stat-arb / cointegration pairs lab (OFFLINE, strict walk-forward).
Log-spread mean reversion on correlated pairs.

- s_t = log(A_t) - beta*log(B_t), beta = OLS hedge ratio fit on IN-SAMPLE only.
- Causal rolling mean/std over window W -> z-score. All from data <= i.
- Entry when |z|>=z_entry (fade). Exit when |z|<=z_exit (revert) OR |z|>=z_stop (blowout) OR max_hold.
- Signal at close i, FILL at open i+1 (both legs). No lookahead.
- Cost: round-trip in price units on BOTH legs, converted to log units at fill price, leg B scaled by |beta|.
- R = net_log_pnl / risk_log, risk = (z_stop - z_entry)*sigma_at_entry (log-spread units).
- Params (W, z_entry, z_stop) chosen on IS by best IS mean-R (IS n>=30). z_exit fixed.
- Report OOS ONLY: mean R (net), t-stat, n, max drawdown (R), PF, win rate.
"""
import numpy as np, json, os, itertools, sys

LAB = "data/lab_cache"

# round-trip cost in PRICE units per leg (established: FX ~1.5-2pip, XAU 0.30, XAG ~0.03)
COST = {
    "AUDUSDm": 0.00015, "NZDUSDm": 0.00015, "EURUSDm": 0.00015, "GBPUSDm": 0.00020,
    "USDCADm": 0.00020, "USDCHFm": 0.00020, "EURGBPm": 0.00020,
    "XAUUSDm": 0.30, "XAGUSDm": 0.03,
    "US500m": 0.5, "US30m": 3.0, "USTECm": 1.5, "DE30m": 2.0,
    "BTCUSDm": 10.0, "ETHUSDm": 1.5,
    "EURJPYm": 0.015, "GBPJPYm": 0.02, "USDJPYm": 0.015,
}

IS_FRAC = 0.67
Z_EXIT = 0.5
MAX_HOLD = 120

def load(sym, tf):
    d = np.load(f"{LAB}/{sym}_{tf}.npz")
    return d["t"], d["o"].astype(float), d["h"].astype(float), d["l"].astype(float), d["c"].astype(float)

def align(symA, symB, tf):
    tA,oA,hA,lA,cA = load(symA,tf); tB,oB,hB,lB,cB = load(symB,tf)
    # inner join on timestamp
    _, ia, ib = np.intersect1d(tA, tB, return_indices=True)
    ia.sort(); ib.sort()
    # recompute index arrays properly
    sa = {t:i for i,t in enumerate(tA)}
    common = [t for t in tB if t in sa]
    common = np.array(common)
    idxA = np.array([sa[t] for t in common]);
    sb = {t:i for i,t in enumerate(tB)}
    idxB = np.array([sb[t] for t in common])
    return (common, oA[idxA],cA[idxA], oB[idxB],cB[idxB])

def rolling_ms(s, W):
    n=len(s); mu=np.full(n,np.nan); sd=np.full(n,np.nan)
    cs=np.cumsum(s); cs2=np.cumsum(s*s)
    for i in range(W-1,n):
        lo=i-W+1
        ssum = cs[i]-(cs[lo-1] if lo>0 else 0.0)
        ssum2= cs2[i]-(cs2[lo-1] if lo>0 else 0.0)
        m=ssum/W; v=ssum2/W-m*m
        mu[i]=m; sd[i]=np.sqrt(v) if v>0 else np.nan
    return mu,sd

def simulate(oA,cA,oB,cB, beta, W, z_entry, z_stop, costA, costB, i_start, i_end):
    """Return list of R for trades ENTERED within [i_start, i_end)."""
    lcA=np.log(cA); lcB=np.log(cB)
    s = lcA - beta*lcB
    mu,sd = rolling_ms(s, W)
    z = (s-mu)/sd
    n=len(s)
    Rs=[]; i=max(W, 1)
    pos=0
    while i < n-1:
        if pos==0:
            zi=z[i]
            if not np.isfinite(zi): i+=1; continue
            if i < i_start or i >= i_end: i+=1; continue
            if abs(zi) < z_entry: i+=1; continue
            direction = -1 if zi>0 else 1   # z>0: spread rich -> short spread (dir -1 on s)
            sigma_e = sd[i]
            # fill at open i+1
            ei = i+1
            aE=oA[ei]; bE=oB[ei]
            s_entry = np.log(aE) - beta*np.log(bE)
            risk = (z_stop - z_entry)*sigma_e
            if risk<=0: i+=1; continue
            # walk forward to exit
            exit_i=None
            for j in range(ei, min(n-1, ei+MAX_HOLD)):
                zj=z[j]
                if not np.isfinite(zj): continue
                if abs(zj) <= Z_EXIT or abs(zj) >= z_stop:
                    exit_i=j+1  # fill next open
                    break
            if exit_i is None:
                exit_i=min(n-1, ei+MAX_HOLD)
            aX=oA[exit_i]; bX=oB[exit_i]
            s_exit=np.log(aX)-beta*np.log(bX)
            pnl = direction*(s_exit - s_entry)
            cost_log = costA/aE + abs(beta)*costB/bE
            net = pnl - cost_log
            Rs.append(net/risk)
            i=exit_i+1
        else:
            i+=1
    return Rs

def tstat(rs):
    rs=np.asarray(rs)
    if len(rs)<2: return 0.0
    return rs.mean()/(rs.std()+1e-9)*np.sqrt(len(rs))

def maxdd(rs):
    eq=np.cumsum(rs); peak=np.maximum.accumulate(eq)
    return float((eq-peak).min()) if len(rs) else 0.0

def run_pair(symA, symB, tf):
    common, oA,cA, oB,cB = align(symA,symB,tf)
    n=len(common)
    if n<2000: return None
    split=int(n*IS_FRAC)
    costA=COST[symA]; costB=COST[symB]
    # beta on IS
    lA=np.log(cA[:split]); lB=np.log(cB[:split])
    beta = np.polyfit(lB,lA,1)[0]
    # grid search on IS
    best=None
    for W in (60,120,240):
        for z_entry in (1.5,2.0,2.5):
            for z_stop in (3.5,4.5):
                rs=simulate(oA,cA,oB,cB,beta,W,z_entry,z_stop,costA,costB,W,split)
                if len(rs)>=30:
                    e=np.mean(rs)
                    if best is None or e>best[0]:
                        best=(e,W,z_entry,z_stop,len(rs))
    if best is None: return None
    _,W,z_entry,z_stop,is_n = best
    # OOS
    oos=simulate(oA,cA,oB,cB,beta,W,z_entry,z_stop,costA,costB,split,n)
    rs=np.asarray(oos)
    if len(rs)==0: return None
    wr=float((rs>0).mean())
    return {
        "pair":f"{symA}/{symB}","tf":tf,"beta":round(float(beta),4),
        "params":{"W":W,"z_entry":z_entry,"z_stop":z_stop,"z_exit":Z_EXIT},
        "is_n":is_n,"is_expR":round(float(best[0]),4),
        "n_oos":int(len(rs)),"oos_expR":round(float(rs.mean()),4),
        "oos_t":round(float(tstat(rs)),3),"max_dd_R":round(maxdd(rs),3),
        "pf":round(float(rs[rs>0].sum()/(-rs[rs<0].sum()+1e-9)),3),
        "win_rate":round(wr,3),
    }

PAIRS=[("AUDUSDm","NZDUSDm"),("EURUSDm","GBPUSDm"),("XAUUSDm","XAGUSDm"),
       ("BTCUSDm","ETHUSDm"),("US500m","US30m"),("US500m","USTECm"),
       ("EURUSDm","AUDUSDm"),("EURJPYm","GBPJPYm")]

if __name__=="__main__":
    np.seterr(all="ignore")
    results=[]
    for a,b in PAIRS:
        for tf in ("H1","M15"):
            try:
                r=run_pair(a,b,tf)
            except Exception as e:
                r={"pair":f"{a}/{b}","tf":tf,"error":str(e)}
            if r: results.append(r)
            if r and "oos_expR" in r:
                print(f"{r['pair']:18s} {tf:3s} beta={r['beta']:7.3f} "
                      f"IS(n={r['is_n']},e={r['is_expR']:+.3f}) | "
                      f"OOS n={r['n_oos']:4d} expR={r['oos_expR']:+.4f} "
                      f"t={r['oos_t']:+.2f} dd={r['max_dd_R']:.1f} pf={r['pf']:.2f} wr={r['win_rate']:.2f}")
            elif r:
                print(f"{a}/{b} {tf}: {r.get('error')}")
    json.dump(results, open(f"{LAB}/statarb_lab_results.json","w"), indent=2)
    print("\nsaved statarb_lab_results.json")
