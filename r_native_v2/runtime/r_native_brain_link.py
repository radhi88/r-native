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
POPULATION_FILE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\genomes_population.json")
POLL = 5.0
POPULATION_RELOAD_SEC = 60.0   # evolver rewrites the population every ~10 min


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


# ───────────── FALLBACK GENOMES (2026-05-27 seeds — used only if ─────────────
# ───────────── data\genomes_population.json is missing/corrupt)  ─────────────
FALLBACK_GENOMES = [
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

# Defaults for params a bred child may not carry (mirrors genome_evolver._PARAM_DEFAULTS)
_PARAM_DEFAULTS = {
    "rsi_max": 55, "min_imb_count": 2, "lot": 0.02,
    "min_pressure_abs": 3, "min_mtf_agreement": 2, "use_footprint": True,
}


def load_population() -> tuple[list, str]:
    """Load the LIVE GA population from data\\genomes_population.json.

    Returns (genomes, source_label). Fail-soft: on missing/corrupt file or
    empty/invalid genome list, returns the hardcoded 2026-05-27 seeds so the
    link is never blind."""
    data = _read_json(POPULATION_FILE)
    if isinstance(data, dict):
        raw = data.get("genomes")
        if isinstance(raw, list):
            genomes = [g for g in raw
                       if isinstance(g, dict) and isinstance(g.get("name"), str) and g["name"]]
            if genomes:
                gen = data.get("generation", "?")
                return genomes, f"population gen {gen}"
    return list(FALLBACK_GENOMES), "FALLBACK seeds (population file missing/corrupt)"


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

    # Genome params (bred children may lack some keys — fall back to defaults)
    min_mtf = genome.get("min_mtf_agreement", _PARAM_DEFAULTS["min_mtf_agreement"])
    rsi_max = genome.get("rsi_max", _PARAM_DEFAULTS["rsi_max"])
    min_pressure = genome.get("min_pressure_abs", _PARAM_DEFAULTS["min_pressure_abs"])
    use_fp = genome.get("use_footprint", _PARAM_DEFAULTS["use_footprint"])
    min_imb = genome.get("min_imb_count", _PARAM_DEFAULTS["min_imb_count"])

    # MTF alignment
    direction = None
    if up_count >= min_mtf:
        direction = "BUY"
    elif dn_count >= min_mtf:
        direction = "SELL"
    if not direction: return ("WAIT", 0)

    # Side bias (bred genomes may be BUY_ONLY / SELL_ONLY)
    side_bias = genome.get("side_bias", "BOTH")
    if side_bias == "BUY_ONLY" and direction != "BUY":
        return ("WAIT", 0)
    if side_bias == "SELL_ONLY" and direction != "SELL":
        return ("WAIT", 0)

    # RSI filter
    if rsi > rsi_max and direction == "BUY":
        return ("WAIT", 0)
    if rsi < (100 - rsi_max) and direction == "SELL":
        return ("WAIT", 0)

    # Pressure check
    if abs(pressure) < min_pressure:
        return ("WAIT", 0)
    if direction == "BUY" and pressure < 0:
        return ("WAIT", 0)
    if direction == "SELL" and pressure > 0:
        return ("WAIT", 0)

    # Footprint imbalance check
    if use_fp and fp:
        imb_buy = fp.get("imb_buy_count_3bars", 0)
        imb_sell = fp.get("imb_sell_count_3bars", 0)
        if direction == "BUY" and imb_buy < min_imb:
            return ("WAIT", 0)
        if direction == "SELL" and imb_sell < min_imb:
            return ("WAIT", 0)

    # Strong signal = high confidence
    confidence = min(1.0, (up_count if direction == "BUY" else dn_count) / 4.0)
    if use_fp and fp.get("in_supply_zone" if direction == "SELL" else "in_demand_zone"):
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
    genomes, source = load_population()
    print(f"[r_native_link] ONLINE — {len(genomes)} genomes active ({source})")
    for g in genomes:
        print(f"  • {g['name']}: rsi≤{g.get('rsi_max', '?')} "
               f"imb≥{g.get('min_imb_count', '?')} "
               f"lot {g.get('lot', '?')} FP={g.get('use_footprint', '?')}")

    state = _read_json(GENOME_STATE) or {}
    last_brain_ts = ""
    last_pop_load = time.time()
    known_names = {g["name"] for g in genomes}

    while True:
        try:
            # Reload the LIVE population periodically (evolver breeds every ~10 min)
            if time.time() - last_pop_load >= POPULATION_RELOAD_SEC:
                genomes, source = load_population()
                last_pop_load = time.time()
                names = {g["name"] for g in genomes}
                if names != known_names:
                    born = sorted(names - known_names)
                    gone = sorted(known_names - names)
                    print(f"[r_native_link] population changed ({source}): "
                           f"+{born} -{gone} → {len(genomes)} genomes")
                    known_names = names

            snap = _read_json(BRAIN_LIVE)
            if not snap or snap.get("ts") == last_brain_ts:
                time.sleep(POLL); continue
            last_brain_ts = snap.get("ts", "")

            # Evaluate each genome
            for genome in genomes:
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

            # Preserve meta keys other services write (genome_evolver sets
            # "_generation" between our saves — don't clobber it)
            disk = _read_json(GENOME_STATE)
            if isinstance(disk, dict):
                for k, v in disk.items():
                    if k.startswith("_"):
                        state[k] = v
            _save_atomic(GENOME_STATE, state)
        except KeyboardInterrupt:
            print("[r_native_link] stopped"); break
        except Exception as e:
            print(f"[r_native_link] err: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main_loop()
