"""تشغيل حملة GA واحدة لرمزٍ ما (يدويّاً أو من الوصيّ/الديمون).
Usage: python run_ga_campaign.py XAUUSDm [n_bars]"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

sym = sys.argv[1] if len(sys.argv) > 1 else "XAUUSDm"
n_bars = int(sys.argv[2]) if len(sys.argv) > 2 else 3000

import MetaTrader5 as mt5
from r_native.scanner import full_scan, update_symbol_configs_from_scan

mt5.initialize()
print(f"GA campaign start: {sym} n_bars={n_bars}", flush=True)
r = full_scan(symbols=[sym], n_bars=n_bars,
              progress_cb=lambda s: print(s, flush=True))
if r and r.get("ok") is not False:
    update_symbol_configs_from_scan(r)
    print("configs updated", flush=True)
print("CAMPAIGN_DONE", flush=True)
