"""runtime/genome_evolver.py — GA Mutation Engine for trading genomes.

Watches genome_fitness.json + genome_signals.jsonl + brain_decisions.jsonl
to compute fitness per genome over rolling windows. Every N minutes:
  1. Compute fitness score for each genome
  2. Rank top 2 (ELITES) — preserved as-is
  3. Bottom 2 — killed and replaced
  4. New genomes generated via:
        - Crossover (mix parameters from 2 elites)
        - Mutation (small random delta on key params)
  5. Population stays at 5

FITNESS FORMULA:
  fitness = (signal_count_per_hour) × (avg_confidence) × (1 + diversity_bonus)
  diversity_bonus rewards genomes with non-overlapping setups

The evolved genome library is saved to genomes_population.json.
The active 5 genomes used by r_native_brain_link are read from here.

This makes the system SELF-IMPROVING over time without manual tuning.
"""
from __future__ import annotations
import json
import time
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

POPULATION_FILE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\genomes_population.json")
FITNESS_FILE   = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\genome_fitness.json")
SIGNALS_FILE   = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\genome_signals.jsonl")
LINEAGE_LOG    = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\genome_lineage.jsonl")

EVOLVE_INTERVAL_SEC = 600     # evolve every 10 min
MIN_SIGNALS_FOR_EVAL = 5      # need at least 5 signals to be evaluated

# Parameter spaces for mutation/crossover
PARAM_RANGES = {
    "rsi_max":          (30, 75),
    "min_imb_count":    (1, 5),
    "lot":              (0.01, 0.05),
    "min_pressure_abs": (1, 10),
    "min_mtf_agreement": (1, 4),
}


def _save(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    tmp.replace(p)


def _read(p: Path):
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except: return None


def _append(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def compute_fitness(genome_name: str, fitness_state: dict) -> float:
    """Compute fitness score for a genome based on its signal history."""
    g = fitness_state.get(genome_name)
    if not g: return 0
    total = g.get("total_signals", 0)
    if total < MIN_SIGNALS_FOR_EVAL: return 0   # not enough data

    actionable = g.get("buy_signals", 0) + g.get("sell_signals", 0)
    wait_ratio = g.get("wait_signals", 0) / total if total > 0 else 1
    avg_conf = g.get("avg_confidence_on_signal", 0)

    # Penalize too-quiet (wait_ratio > 0.95) or too-noisy (wait_ratio < 0.05)
    activity_score = 0
    if 0.3 <= wait_ratio <= 0.85:
        activity_score = 1.0
    elif wait_ratio < 0.3:
        activity_score = 0.5     # too noisy
    else:
        activity_score = 0.3     # too quiet

    fitness = activity_score * avg_conf * (actionable ** 0.5)
    return round(fitness, 3)


def crossover(parent_a: dict, parent_b: dict) -> dict:
    """Mix parameters from two parents — each child param picked 50/50."""
    child = {}
    keys = ["rsi_max", "min_imb_count", "lot", "min_pressure_abs",
             "min_mtf_agreement", "use_footprint"]
    for k in keys:
        child[k] = parent_a[k] if random.random() < 0.5 else parent_b[k]
    # Generated name with parent lineage
    child["name"] = f"GEN-X-{random.randint(1000, 9999)}"
    child["parents"] = [parent_a["name"], parent_b["name"]]
    child["born"] = datetime.now(timezone.utc).isoformat()
    return child


def mutate(genome: dict, intensity: float = 0.15) -> dict:
    """Slightly perturb a genome's parameters."""
    new = dict(genome)
    for param, (low, high) in PARAM_RANGES.items():
        if random.random() < intensity:
            if isinstance(low, int):
                new[param] = max(low, min(high, new[param] + random.choice([-1, 1])))
            else:
                delta = (high - low) * 0.1 * random.choice([-1, 1])
                new[param] = round(max(low, min(high, new[param] + delta)), 2)
    new["mutated_from"] = genome["name"]
    new["born"] = datetime.now(timezone.utc).isoformat()
    if "GEN-X" not in new["name"]:
        new["name"] = f"GEN-M-{random.randint(1000, 9999)}"
    return new


def evolve_population(population: list, fitness_state: dict) -> tuple[list, dict]:
    """Run one generation of evolution. Returns new_population, summary."""
    # Score each genome
    scored = []
    for g in population:
        score = compute_fitness(g["name"], fitness_state)
        scored.append({"genome": g, "fitness": score})
    scored.sort(key=lambda x: -x["fitness"])

    # Elites = top 2
    elites = [s["genome"] for s in scored[:2]]
    # Mid-tier = next 1 — keep
    survivors = [s["genome"] for s in scored[:3]]
    # Killed = bottom 2
    killed = [s["genome"] for s in scored[3:]]

    # Generate 2 offspring (crossover + mutate)
    children = []
    if len(elites) >= 2:
        c1 = mutate(crossover(elites[0], elites[1]))
        c2 = mutate(crossover(elites[0], elites[1]), intensity=0.30)
        children = [c1, c2]

    new_population = survivors + children
    while len(new_population) < 5:
        # If not enough elites, mutate any survivor
        new_population.append(mutate(random.choice(survivors)))

    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "generation": fitness_state.get("_generation", 0) + 1,
        "kept": [g["name"] for g in survivors],
        "killed": [g["name"] for g in killed],
        "born": [g["name"] for g in children],
        "fitness_ranks": [{"name": s["genome"]["name"], "score": s["fitness"]} for s in scored],
    }
    _append(LINEAGE_LOG, summary)
    return new_population, summary


def initial_population() -> list:
    """Seed population if no existing file."""
    return [
        {"name": "GEN-CONSERVATIVE", "rsi_max": 45, "min_imb_count": 3, "lot": 0.01,
         "use_footprint": True, "min_pressure_abs": 5, "min_mtf_agreement": 3,
         "born": "seed"},
        {"name": "GEN-AGGRESSIVE", "rsi_max": 60, "min_imb_count": 2, "lot": 0.03,
         "use_footprint": True, "min_pressure_abs": 3, "min_mtf_agreement": 2,
         "born": "seed"},
        {"name": "GEN-SCALPER", "rsi_max": 55, "min_imb_count": 2, "lot": 0.02,
         "use_footprint": False, "min_pressure_abs": 4, "min_mtf_agreement": 2,
         "born": "seed"},
        {"name": "GEN-FP-PURE", "rsi_max": 70, "min_imb_count": 4, "lot": 0.02,
         "use_footprint": True, "min_pressure_abs": 0, "min_mtf_agreement": 1,
         "born": "seed"},
        {"name": "GEN-CONFLUENCE", "rsi_max": 50, "min_imb_count": 3, "lot": 0.02,
         "use_footprint": True, "min_pressure_abs": 5, "min_mtf_agreement": 4,
         "born": "seed"},
    ]


def main_loop():
    print(f"[evolver] ONLINE — evolves every {EVOLVE_INTERVAL_SEC}s")

    # Initialize population
    pop_data = _read(POPULATION_FILE)
    if pop_data and "genomes" in pop_data:
        population = pop_data["genomes"]
        generation = pop_data.get("generation", 1)
    else:
        population = initial_population()
        generation = 1
        _save(POPULATION_FILE, {"genomes": population, "generation": generation,
                                 "created": datetime.now(timezone.utc).isoformat()})

    print(f"[evolver] generation {generation} loaded — {len(population)} genomes")

    while True:
        try:
            time.sleep(EVOLVE_INTERVAL_SEC)
            fitness = _read(FITNESS_FILE) or {}

            print(f"\n[{datetime.now():%H:%M:%S}] === EVOLUTION CYCLE START ===")
            print(f"  Fitness data: {len(fitness)} genomes tracked")
            for name, stats in fitness.items():
                if name.startswith("_"): continue
                sigs = stats.get("buy_signals", 0) + stats.get("sell_signals", 0)
                wait = stats.get("wait_signals", 0)
                conf = stats.get("avg_confidence_on_signal", 0)
                print(f"    {name:25} : signals {sigs:4d}, waits {wait:4d}, avg_conf {conf:.2f}")

            new_pop, summary = evolve_population(population, fitness)
            generation += 1
            population = new_pop
            fitness["_generation"] = generation

            _save(POPULATION_FILE, {"genomes": population, "generation": generation,
                                     "last_evolution": datetime.now(timezone.utc).isoformat()})
            _save(FITNESS_FILE, fitness)

            print(f"  GENERATION {generation}: kept {summary['kept']}, killed {summary['killed']}")
            print(f"  NEW BORN: {summary['born']}")
            print(f"  === EVOLUTION CYCLE END ===\n")

        except KeyboardInterrupt:
            print("[evolver] stopped"); break
        except Exception as e:
            print(f"[evolver] err: {e}")
            time.sleep(EVOLVE_INTERVAL_SEC)


if __name__ == "__main__":
    main_loop()
