"""Recompute OOS PF/net with overnight swap charged per held night."""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
ROOT = Path(r"C:\Users\Radhi\MT5\r_native_v2")
sys.path.insert(0, str(ROOT))
from runtime.gold_htf_trend import Bars, Config, backtest, load_bars
import runtime.gold_htf_trend as ght
from runtime.shared.cost_model import COSTS

SYMBOL="XAUUSDm"
def _slice(b,lo,hi):
    return Bars(symbol=b.symbol,timeframe=b.timeframe,time=b.time[lo:hi],
        open=b.open[lo:hi],high=b.high[lo:hi],low=b.low[lo:hi],close=b.close[lo:hi],source=b.source)
h1=load_bars(SYMBOL,"H1",days=760,source="auto")
h4=load_bars(SYMBOL,"H4",days=880,source="auto")
n=len(h1);split=int(n*0.67);oos=_slice(h1,split,n)
cfg=Config(htf="H4",trend_mode="ema",allow_long=True,allow_short=False,use_cot_gate=False,
    risk_dollars=10.0,tp_mode="chandelier",chandelier_atr_mult=3.0)
cap={"t":None};orig=ght._summarize
def grab(s,c,b1,bh,tr,eq,dd):
    cap["t"]=list(tr);return orig(s,c,b1,bh,tr,eq,dd)
ght._summarize=grab
try: backtest(SYMBOL,cfg=cfg,bars_h1=oos,bars_htf=h4)
finally: ght._summarize=orig
trades=cap["t"]

pv=COSTS[SYMBOL].point_value
swap_per_night=COSTS[SYMBOL].swap_long*pv  # $/night/lot (negative)

def parse(s):
    s=s.replace(" ","T")
    return datetime.fromisoformat(s)

# count actual calendar nights (rollovers ~ 21:00-22:00 UTC); approximate by
# number of UTC-midnight or 22:00 crossings. Use ceil of hours/24 as a simple,
# slightly conservative proxy already done; here count date changes 22:00 UTC.
def nights(dt0,dt1):
    c=0; cur=dt0
    # count 21:00 UTC rollovers strictly between entry and exit
    d=dt0.date()
    end=dt1
    t=datetime(d.year,d.month,d.day,21,0,tzinfo=timezone.utc)
    while t<=dt0: t=t+ (datetime(d.year,d.month,d.day)+__import__("datetime").timedelta(days=1)-datetime(d.year,d.month,d.day))
    import datetime as _d
    t=datetime(dt0.year,dt0.month,dt0.day,21,0,tzinfo=timezone.utc)
    if t<=dt0: t=t+_d.timedelta(days=1)
    while t<dt1:
        c+=1; t=t+_d.timedelta(days=1)
    return c

nets_with_swap=[]
nets_orig=[]
tot_swap=0.0
for t in trades:
    dt0=parse(t["entry_time"]); dt1=parse(t["exit_time"])
    if dt0.tzinfo is None: dt0=dt0.replace(tzinfo=timezone.utc)
    if dt1.tzinfo is None: dt1=dt1.replace(tzinfo=timezone.utc)
    nn=nights(dt0,dt1)
    sw=nn*swap_per_night*t["lot"]   # negative dollars
    tot_swap+=sw
    nets_orig.append(t["net"])
    nets_with_swap.append(t["net"]+sw)

def metrics(nets):
    w=[x for x in nets if x>0]; l=[x for x in nets if x<=0]
    gp=sum(w); gl=-sum(l)
    pf=gp/gl if gl>0 else float("inf")
    return len(nets), len(w)/len(nets), pf, sum(nets)

print(f"swap = {COSTS[SYMBOL].swap_long} pts/night/lot = ${swap_per_night:.2f}/night/lot")
print(f"total rollover-nights charged across 85 trades; total swap drag = ${tot_swap:.2f}")
print()
print("                 tr     WR      PF      net")
print("orig (no swap):  %d  %.4f  %.4f  %.2f" % metrics(nets_orig))
print("with swap:       %d  %.4f  %.4f  %.2f" % metrics(nets_with_swap))
