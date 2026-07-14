"""Second-pass cost scrutiny: lot sizes, swap omission, hold duration."""
from __future__ import annotations
import sys
from datetime import datetime
from pathlib import Path
import numpy as np
ROOT = Path(r"C:\Users\Radhi\MT5\r_native_v2")
sys.path.insert(0, str(ROOT))
from runtime.gold_htf_trend import Bars, Config, backtest, load_bars
import runtime.gold_htf_trend as ght
from runtime.shared.cost_model import round_trip_cost, COSTS

SYMBOL = "XAUUSDm"

def _slice(b, lo, hi):
    return Bars(symbol=b.symbol, timeframe=b.timeframe, time=b.time[lo:hi],
                open=b.open[lo:hi], high=b.high[lo:hi], low=b.low[lo:hi],
                close=b.close[lo:hi], source=b.source)

h1 = load_bars(SYMBOL, "H1", days=760, source="auto")
h4 = load_bars(SYMBOL, "H4", days=880, source="auto")
n = len(h1); split = int(n*0.67)
oos = _slice(h1, split, n)
cfg = Config(htf="H4", trend_mode="ema", allow_long=True, allow_short=False,
             use_cot_gate=False, risk_dollars=10.0, tp_mode="chandelier",
             chandelier_atr_mult=3.0)

cap = {"t": None}
orig = ght._summarize
def grab(s,c,b1,bh,tr,eq,dd):
    cap["t"]=list(tr); return orig(s,c,b1,bh,tr,eq,dd)
ght._summarize = grab
try:
    backtest(SYMBOL, cfg=cfg, bars_h1=oos, bars_htf=h4)
finally:
    ght._summarize = orig
trades = cap["t"]

lots = [t["lot"] for t in trades]
print(f"lot range {min(lots)}..{max(lots)} mean {np.mean(lots):.3f}; min_lot floor=0.01")
at_floor = sum(1 for l in lots if l <= 0.01001)
print(f"trades pinned at min_lot 0.01: {at_floor}/{len(trades)}")

# Independently recompute round_trip_cost for a sample and compare to logged cost
print("\nSpot-check cost vs cost_model.round_trip_cost():")
for t in trades[:5]:
    expect = round_trip_cost(SYMBOL, t["lot"], t["entry"])
    print(f"  lot={t['lot']} entry={t['entry']} logged_cost={t['cost']} recomputed={expect:.2f} "
          f"{'OK' if abs(expect-t['cost'])<0.02 else 'MISMATCH'}")

# Hold duration (swap exposure). swap_long is informational only -> NOT charged.
def _pt(s):
    try: return datetime.fromisoformat(s)
    except: return datetime.fromisoformat(s.replace(" ", "T"))
holds_h = []
for t in trades:
    try:
        dt0 = _pt(t["entry_time"]); dt1 = _pt(t["exit_time"])
        holds_h.append((dt1-dt0).total_seconds()/3600.0)
    except Exception:
        pass
holds_h = np.array(holds_h)
nights = holds_h/24.0
swap_per_night_per_lot = COSTS[SYMBOL].swap_long  # -547.6 (points basis)
pv = COSTS[SYMBOL].point_value  # $0.10/point/lot
swap_dollars_per_night_per_lot = swap_per_night_per_lot * pv  # convert pts->$
print(f"\nhold hours: median={np.median(holds_h):.1f} mean={np.mean(holds_h):.1f} max={np.max(holds_h):.1f}")
print(f"approx nights held: median={np.median(nights):.1f} mean={np.mean(nights):.2f} max={np.max(nights):.1f}")
print(f"swap_long={swap_per_night_per_lot} pts -> ${swap_dollars_per_night_per_lot:.2f}/night/lot")
est_swap = sum(n_*swap_dollars_per_night_per_lot*l for n_,l in zip(nights, lots))
print(f"ESTIMATED uncharged swap cost over all OOS trades: ${est_swap:.2f}")
print(f"  (net before swap = $642.02; net AFTER est swap = ${642.02+est_swap:.2f})")
