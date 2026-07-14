"""runtime/footprint_brain_bridge.py — Bridges MQL5 footprint to Python brain.

Reads footprint_cells.json (written by CLAUDE_FOOTPRINT_v1.mq5) and merges
into brain_live.json so Python rules can use real footprint imbalance data.

User mandate 2026-05-27: "كلهم لا توقف تطوير ارجوك"
This is the missing link between the visual footprint and the trading brain.

Run as background process alongside brain_v1.py.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

FOOTPRINT_JSON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files\footprint_cells.json")
BRAIN_LIVE     = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_live.json")
BRAIN_MEMORY   = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_memory.jsonl")
POLL_SEC = 2.0


def _read_json(p: Path) -> dict | None:
    if not p.exists(): return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return None


def _save_atomic(p: Path, obj: dict):
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    tmp.replace(p)


def compute_footprint_signals(footprint: dict) -> dict:
    """Distill footprint data into actionable signals for brain rules."""
    bars = footprint.get("bars", [])
    if not bars: return {}
    last_bar = bars[-1]
    recent = bars[-3:]

    # Aggregated imbalance counts (last 3 bars)
    total_imb_buy  = sum(b.get("imb_buy", 0)  for b in recent)
    total_imb_sell = sum(b.get("imb_sell", 0) for b in recent)
    imb_dominance = "BUY" if total_imb_buy > total_imb_sell * 1.5 \
                    else "SELL" if total_imb_sell > total_imb_buy * 1.5 \
                    else "NEUTRAL"

    # CVD acceleration (last 3 bars delta sum vs prior 3)
    cvd_recent = sum(b.get("delta", 0) for b in bars[-3:]) if len(bars) >= 3 else 0
    cvd_prior  = sum(b.get("delta", 0) for b in bars[-6:-3]) if len(bars) >= 6 else 0
    cvd_acceleration = cvd_recent - cvd_prior

    # POC trajectory (rising/falling/stable)
    if len(bars) >= 3:
        pocs = [b.get("poc", 0) for b in bars[-3:] if b.get("poc", 0) > 0]
        if len(pocs) >= 2:
            poc_change = pocs[-1] - pocs[0]
            poc_trend = "RISING" if poc_change > 0.5 else ("FALLING" if poc_change < -0.5 else "STABLE")
        else:
            poc_trend = "UNKNOWN"
    else:
        poc_trend = "UNKNOWN"

    # Recent max delta (single-bar peak buying or selling)
    deltas = [abs(b.get("delta", 0)) for b in recent]
    max_recent_delta = max(deltas) if deltas else 0

    # In supply or demand zone?
    sd_zones = footprint.get("sd_zones", [])
    last_close = last_bar.get("c", 0)
    in_supply = False
    in_demand = False
    for z in sd_zones:
        if z["bot"] <= last_close <= z["top"]:
            if z["is_supply"]: in_supply = True
            else: in_demand = True

    return {
        "footprint": {
            "imb_dominance": imb_dominance,
            "imb_buy_count_3bars": total_imb_buy,
            "imb_sell_count_3bars": total_imb_sell,
            "cvd_acceleration": cvd_acceleration,
            "cvd_recent_3bars": cvd_recent,
            "poc_trend": poc_trend,
            "last_bar_poc": last_bar.get("poc", 0),
            "last_bar_delta": last_bar.get("delta", 0),
            "max_recent_delta": max_recent_delta,
            "in_supply_zone": in_supply,
            "in_demand_zone": in_demand,
            "svp_poc": footprint.get("svp_poc", 0),
            "svp_vah": footprint.get("svp_vah", 0),
            "svp_val": footprint.get("svp_val", 0),
            "signal_meter": footprint.get("signal_value", 0),
            "signal_label": footprint.get("signal_label", ""),
            "cum_delta_running": footprint.get("cum_delta", 0),
            "sd_zone_count": len(sd_zones),
            "footprint_ts": footprint.get("ts", 0),
        }
    }


def main_loop():
    print(f"[footprint_bridge] ONLINE")
    print(f"  source: {FOOTPRINT_JSON}")
    print(f"  target: {BRAIN_LIVE}")
    print(f"  poll:   {POLL_SEC}s")

    last_fp_ts = 0
    while True:
        try:
            fp = _read_json(FOOTPRINT_JSON)
            if fp is None:
                time.sleep(POLL_SEC); continue

            fp_ts = fp.get("ts", 0)
            if fp_ts == last_fp_ts:
                time.sleep(POLL_SEC); continue
            last_fp_ts = fp_ts

            signals = compute_footprint_signals(fp)
            if not signals:
                time.sleep(POLL_SEC); continue

            brain = _read_json(BRAIN_LIVE) or {}
            brain.update(signals)
            brain["footprint_bridge_ts"] = datetime.now(timezone.utc).isoformat()
            _save_atomic(BRAIN_LIVE, brain)

            sig = signals["footprint"]
            print(f"[{datetime.now():%H:%M:%S}] merged: imb {sig['imb_dominance']} "
                   f"({sig['imb_buy_count_3bars']}↑ {sig['imb_sell_count_3bars']}↓) "
                   f"CVDΔ {sig['cvd_acceleration']:+d} POC {sig['poc_trend']} "
                   f"meter {sig['signal_meter']:+.0f}{' SD!' if (sig['in_supply_zone'] or sig['in_demand_zone']) else ''}")

        except KeyboardInterrupt:
            print("[footprint_bridge] stopped"); break
        except Exception as e:
            print(f"[footprint_bridge] err: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main_loop()
