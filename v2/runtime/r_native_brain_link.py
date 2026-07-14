"""runtime/r_native_brain_link.py — Feed brain decisions to R Native genomes.

R Native v2 (Palace) uses GA-evolved genomes. This link feeds them:
  1. Real-time brain_live.json (input features)
  2. brain_decisions.jsonl (training signals for fitness scoring)
  3. footprint signals (new features for genome evolution)
  4. Performance per-engine (so genomes know what's winning)

Each genome can be a candidate trading strategy with parameters like:
  • rsi_threshold (35 / 40 / 45 / 50)
  • imb_min_count (2 / 3 / 4 / 5)
  • entry_size_lot (0.01 / 0.02 / 0.03)
  • use_footprint (true / false)

The link computes per-genome fitness from outcomes — best genomes get
promoted to live trading via genome_executor.py.

Run as background. Writes data/genome_signals.jsonl per genome decision.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

BRAIN_LIVE  = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_live.json")
DECISIONS   = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_decisions.jsonl")
PERF        = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\engine_performance.json")
GENOME_DIR  = Path(r"C:\Users\Radhi\MT5\r_native_v2\genomes")
GENOME_SIG  = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\genome_signals.jsonl")
GENOME_STATE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\genome_fitness.json")
POLL = 5.0


def _read_json(p: Path) -> dict | None:
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except: return None


def _append(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def _save_atomic(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    tmp.replace(p)


# ───────────────── GENOMES (initial 5 candidates) ─────────────────
GENOMES = [
    {
        "name": "GEN-CONSERVATIVE",
        "rsi_max": 45,
        "min_imb_count": 3,
        "lot": 0.01,
        "use_footprint": True,
        "min_pressure_abs": 5,
        "min_mtf_agreement": 3,   # 3 of 4 TFs same direction
    },
    {
        "name": "GEN-AGGRESSIVE",
        "rsi_max": 60,
        "min_imb_count": 2,
        "lot": 0.03,
        "use_footprint": True,
        "min_pressure_abs": 3,
        "min_mtf_agreement": 2,
    },
    {
        "name": "GEN-SCALPER",
        "rsi_max": 55,
        "min_imb_count": 2,
        "lot": 0.02,
        "use_footprint": False,
        "min_pressure_abs": 4,
        "min_mtf_agreement": 2,
    },
    {
        "name": "GEN-FP-PURE",
        "rsi_max": 70,    # ignore rsi
        "min_imb_count": 4,
        "lot": 0.02,
        "use_footprint": True,
        "min_pressure_abs": 0,
        "min_mtf_agreement": 1,
    },
    {
        "name": "GEN-CONFLUENCE",
        "rsi_max": 50,
        "min_imb_count": 3,
        "lot": 0.02,
        "use_footprint": True,
        "min_pressure_abs": 5,
        "min_mtf_agreement": 4,
    },
]


def evaluate_genome(genome: dict, snap: dict) -> tuple[str, float]:
    """Return (action, confidence) for this genome based on current snapshot."""
    if not snap: return ("WAIT", 0)
    bias_m1 = snap.get("bias", {}).get("m1", "?")
    bias_m5 = snap.get("bias", {}).get("m5", "?")
    bias_m15 = snap.get("bias", {}).get("m15", "?")
    bias_h1 = snap.get("bias", {}).get("h1", "?")
    rsi = snap.get("rsi", {}).get("m1", 50)
    pressure = snap.get("pressure_10m1", 0)
    fp = snap.get("footprint", {})

    biases = [bias_m1, bias_m5, bias_m15, bias_h1]
    up_count = biases.count("UP")
    dn_count = biases.count("DOWN")

    # MTF alignment
    direction = None
    if up_count >= genome["min_mtf_agreement"]:
        direction = "BUY"
    elif dn_count >= genome["min_mtf_agreement"]:
        direction = "SELL"
    if not direction: return ("WAIT", 0)

    # RSI filter
    if rsi > genome["rsi_max"] and direction == "BUY":
        return ("WAIT", 0)
    if rsi < (100 - genome["rsi_max"]) and direction == "SELL":
        return ("WAIT", 0)

    # Pressure check
    if abs(pressure) < genome["min_pressure_abs"]:
        return ("WAIT", 0)
    if direction == "BUY" and pressure < 0:
        return ("WAIT", 0)
    if direction == "SELL" and pressure > 0:
        return ("WAIT", 0)

    # Footprint imbalance check
    if genome["use_footprint"] and fp:
        imb_buy = fp.get("imb_buy_count_3bars", 0)
        imb_sell = fp.get("imb_sell_count_3bars", 0)
        if direction == "BUY" and imb_buy < genome["min_imb_count"]:
            return ("WAIT", 0)
        if direction == "SELL" and imb_sell < genome["min_imb_count"]:
            return ("WAIT", 0)

    # Strong signal = high confidence
    confidence = min(1.0, (up_count if direction == "BUY" else dn_count) / 4.0)
    if genome["use_footprint"] and fp.get("in_supply_zone" if direction == "SELL" else "in_demand_zone"):
        confidence = min(1.0, confidence + 0.2)
    return (direction, confidence)


def update_genome_fitness(state: dict, genome_name: str, action: str, confidence: float):
    """Track each genome's decision count + fitness over time."""
    if genome_name not in state:
        state[genome_name] = {
            "total_signals": 0,
            "buy_signals": 0,
            "sell_signals": 0,
            "wait_signals": 0,
            "avg_confidence_on_signal": 0,
            "last_signal_ts": "",
        }
    g = state[genome_name]
    g["total_signals"] += 1
    if action == "BUY": g["buy_signals"] += 1
    elif action == "SELL": g["sell_signals"] += 1
    else: g["wait_signals"] += 1
    if action != "WAIT":
        # rolling avg
        n_sigs = g["buy_signals"] + g["sell_signals"]
        if n_sigs > 0:
            g["avg_confidence_on_signal"] = round(
                ((g["avg_confidence_on_signal"] * (n_sigs - 1)) + confidence) / n_sigs, 2)
        g["last_signal_ts"] = datetime.now(timezone.utc).isoformat()


def main_loop():
    print(f"[r_native_link] ONLINE — {len(GENOMES)} genomes active")
    for g in GENOMES:
        print(f"  • {g['name']}: rsi≤{g['rsi_max']} imb≥{g['min_imb_count']} "
               f"lot {g['lot']} FP={g['use_footprint']}")

    state = _read_json(GENOME_STATE) or {}
    last_brain_ts = ""

    while True:
        try:
            snap = _read_json(BRAIN_LIVE)
            if not snap or snap.get("ts") == last_brain_ts:
                time.sleep(POLL); continue
            last_brain_ts = snap.get("ts", "")

            # Evaluate each genome
            for genome in GENOMES:
                action, confidence = evaluate_genome(genome, snap)
                update_genome_fitness(state, genome["name"], action, confidence)

                if action != "WAIT" and confidence >= 0.5:
                    signal = {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "genome": genome["name"],
                        "action": action,
                        "confidence": confidence,
                        "price": snap.get("bid"),
                        "rsi_m1": snap.get("rsi", {}).get("m1"),
                        "pressure": snap.get("pressure_10m1"),
                        "fp_imb_dom": snap.get("footprint", {}).get("imb_dominance"),
                    }
                    _append(GENOME_SIG, signal)
                    print(f"[{datetime.now():%H:%M:%S}] 🧬 {genome['name']:18} → "
                           f"{action} conf {confidence:.2f}")

            _save_atomic(GENOME_STATE, state)
        except KeyboardInterrupt:
            print("[r_native_link] stopped"); break
        except Exception as e:
            print(f"[r_native_link] err: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main_loop()
