"""accuracy_updater.py — re-measures per-indicator OOS accuracy for the live/candidate symbols
every hour, so chart_read's learned weights keep IMPROVING from fresh market history.

This is the "updates from experience" loop: as new bars arrive, the measured hit-rate of each
indicator per symbol is refreshed, and chart_read picks up the new weights on its next read.
Read-only. Run:  python accuracy_updater.py --loop
"""
from __future__ import annotations
import argparse, time, sys
from pathlib import Path

_V2 = Path(__file__).resolve().parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

import indicator_accuracy as ia

import json
# always-on core; the rest is loaded dynamically from the gate's eligible list each round
CORE = [("XAUUSDm", "M15"), ("BTCUSDm", "M5"), ("US30m", "M5")]
INTERVAL = 600        # re-measure every 10 min (responsive — weights adjust soon after losses)


def _targets():
    """Learn EVERY gate-eligible pair (best TF each) + the core live symbols."""
    out = list(CORE); seen = {s for s, _ in CORE}
    try:
        g = json.loads((_V2 / "data" / "market_gate.json").read_text(encoding="utf-8"))
        for s, r in g.get("results", {}).items():
            if r.get("tier") in ("robust", "marginal"):
                best_tf, best_pf = None, -1
                for tf, x in (r.get("tf") or {}).items():
                    if x.get("pass") and x.get("pf", 0) > best_pf:
                        best_pf, best_tf = x["pf"], tf
                base = s.replace("_x100m", "m").replace("_x10m", "m")
                if best_tf and base not in seen:
                    seen.add(base); out.append((base, best_tf))
    except Exception:
        pass
    return out


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", action="store_true"); a = ap.parse_args(argv)
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    tfm = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    try:
        while True:
            for sym, tf in _targets():
                try:
                    r = mt5.copy_rates_from_pos(sym, tfm.get(tf, mt5.TIMEFRAME_M5), 0, 2000)
                    if r is None or len(r) < 400:
                        continue
                    close = [float(x["close"]) for x in r]; high = [float(x["high"]) for x in r]; low = [float(x["low"]) for x in r]
                    try: vol = [float(x["tick_volume"]) for x in r]
                    except Exception: vol = [1.0] * len(close)
                    acc = ia.measure(close, high, low, vol)
                    best = max(acc.items(), key=lambda kv: kv[1]["hit_rate"], default=("-", {"hit_rate": 0}))
                    ia.DATA.mkdir(parents=True, exist_ok=True)
                    import json
                    (ia.DATA / f"indicator_accuracy_{sym}.json").write_text(
                        json.dumps({"symbol": sym, "tf": tf, "horizon": ia.HORIZON, "accuracy": acc,
                                    "ts": time.time()}, ensure_ascii=False, indent=1), encoding="utf-8")
                    # CRITICAL: also write the WEIGHTS file chart_read actually reads — this is what
                    # makes the self-improvement reach the live decision (was the broken link).
                    w = ia.learned_weights(acc)
                    (ia.DATA / f"indicator_weights_{sym}.json").write_text(
                        json.dumps({"symbol": sym, "tf": tf, "weights": w, "ts": time.time(),
                                    "source": "accuracy_updater hourly"}, ensure_ascii=False, indent=1), encoding="utf-8")
                    print(f"[ACC] {sym} {tf}: best {best[0]} {best[1]['hit_rate']*100:.1f}% → weights updated ({len(acc)} ind)", flush=True)
                except Exception as e:
                    print(f"[ACC] {sym} err {e}", flush=True)
            if not a.loop:
                break
            time.sleep(INTERVAL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
