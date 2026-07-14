import sys, datetime as _dt
from pathlib import Path
RUNTIME = Path(r"C:\Users\Radhi\MT5\r_native_v2\runtime")
sys.path.insert(0, str(RUNTIME)); sys.path.insert(0, str(RUNTIME / "shared"))
import numpy as np
import cot_ob_backtest as H
from shared.cost_model import round_trip_cost
from shared.cot_signal import supply_short_ok, supply_long_ok

gold = H.load_h1("XAUUSDm", days=730)
gbp = H.load_h1("GBPUSDm", days=730)

def split_date(rates, frac=0.67):
    t = rates["time"].astype(np.float64); n = t.size
    si = int(n*frac)
    return _dt.datetime.fromtimestamp(float(t[si]), _dt.timezone.utc), n, si

for nm, r in [("GOLD", gold), ("GBP", gbp)]:
    sd, n, si = split_date(r)
    first = _dt.datetime.fromtimestamp(float(r["time"][0]), _dt.timezone.utc)
    last = _dt.datetime.fromtimestamp(float(r["time"][-1]), _dt.timezone.utc)
    print(f"{nm}: {n} bars  {first.date()}..{last.date()}  OOS starts at idx {si} = {sd.date()}")

print("\n--- GBP short trades WITH gate (all splits) ---")
tr = H.simulate(gbp, "GBPUSDm", "short", "2R", gate_fn=supply_short_ok)
print("total gate-pass GBP short trades:", len(tr))
for t in tr:
    print(f"  entry {t['entry_time'][:10]} split={t['split']} outcome={t['outcome']} net={t['net']:.2f}")

print("\n--- GOLD long trades WITH gate ---")
trg = H.simulate(gold, "XAUUSDm", "long", "2R", gate_fn=supply_long_ok)
print("total gate-pass GOLD long trades:", len(trg))

# cost sanity: every trade net = gross - cost, cost > 0
print("\n--- cost application check (gold long no-gate 2R) ---")
trn = H.simulate(gold, "XAUUSDm", "long", "2R", gate_fn=None)
bad = [t for t in trn if abs((t["gross"]-t["cost"]) - t["net"]) > 1e-6 or t["cost"] <= 0]
print("trades:", len(trn), "with broken net/cost:", len(bad))
print("sample cost per trade:", round(trn[0]["cost"],2), "rt_cost ref:", round(round_trip_cost("XAUUSDm",0.10,trn[0]["entry"]),2))
print("avg cost:", round(sum(t["cost"] for t in trn)/len(trn),2))

# look-ahead probe: re-detect zones on prefix up to entry_bar and confirm zone exists
print("\n--- look-ahead probe (gold demand zones reproducible from prefix<=idx) ---")
from shared.order_blocks import detect_order_blocks
zones = detect_order_blocks(gold, swing=5, impulse_atr_mult=1.0, lookahead_impulse=3)
dz = [z for z in zones if z["type"]=="demand"][:8]
okc=True
for z in dz:
    pref = detect_order_blocks(gold[:z["idx"]+1], swing=5, impulse_atr_mult=1.0, lookahead_impulse=3)
    if not any(p["ob_bar"]==z["ob_bar"] and p["idx"]==z["idx"] and p["type"]=="demand" for p in pref):
        okc=False; print("  MISSING", z["idx"], z["ob_bar"])
print("causality reproduced:", okc)

# NZ look-ahead check: does NZ TP use opp zones with idx >= entry_bar? code filters oz["idx"]>=entry_bar -> skip
print("\n--- NZ opposing-zone causality: code requires oz idx < entry_bar (skips >=) ---")
print("see harness lines 187-188: 'if oz[idx] >= entry_bar: continue'")

# COT asof check: confirm gate uses last report <= entry date (no future)
print("\n--- COT asof spot check ---")
import shared.cot_signal as cs
st = cs.cot_state("GBPUSDm", _dt.datetime(2024,7,12, tzinfo=_dt.timezone.utc))
print("GBP cot_state asof 2024-07-12 ->", st["date"], st["comm_state"], st["retail_state"], "(must be <= 07-12)")
