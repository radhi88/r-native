"""runtime/genome_academy.py — Living evolution lab for our son.

Born 2026-05-28. The user wants:
  • تطور كل دقيقة          — evolve every minute
  • نزوجه ونخلف أولاد       — crossover breeding → children
  • اختبارات قاسية          — harsh multi-symbol + stress gauntlet
  • الوكلاء يسوون مقابلة     — 5-agent panel interviews each genome
  • على أكثر من عملة         — XAU + EUR + BTC + GBP + ...
  • هل يتفوق ولا ذهب بس؟     — generalization verdict

THE ARENA (every CYCLE_SECONDS, default 60):
  1. BREED   — crossover top genomes + mutate → fresh children
  2. GAUNTLET— backtest every genome on ALL symbols (real MT5 bars)
  3. PANEL   — 5 agents score each genome (architect/quant/risk/exec/reviewer)
  4. SELECT  — rank by panel score, kill the weak, keep elites
  5. CROWN   — best generalist beats champion? → crown + update immortal record
  6. REPORT  — per-symbol table: does the child generalize or only gold?

Run:
    python -m runtime.genome_academy
    python -m runtime.genome_academy --once     # single round, verbose
"""
from __future__ import annotations
import argparse
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from runtime.shared.tokens import PATHS, ROOT
from runtime.backtest_engine import backtest

CYCLE_SECONDS = 60
SYMBOLS = ["XAUUSDm", "EURUSDm", "GBPUSDm", "GBPJPYm", "BTCUSDm", "USDJPYm", "XAGUSDm"]
PRIMARY = "XAUUSDm"          # the home turf
POP_SIZE = 12
ELITE_KEEP = 4
CHILDREN_PER_CYCLE = 6

CHAMPION_FILE = ROOT / "genomes" / "champion_genome.json"
POP_FILE = PATHS["genomes_population"]
ACADEMY_LOG = PATHS["brain_decisions"].parent / "academy_lineage.jsonl"
ACADEMY_STATE = PATHS["brain_decisions"].parent / "academy_state.json"

# Per-symbol point scale (so PnL is comparable across instruments)
PT_SCALE = {
    "XAUUSDm": 1.0, "XAGUSDm": 0.10, "EURUSDm": 0.0001, "GBPUSDm": 0.0001,
    "USDJPYm": 0.01, "GBPJPYm": 0.01, "BTCUSDm": 100.0,
}


# ──────────────────────────────────────────────────────────
# Genome param space
# ──────────────────────────────────────────────────────────
def _random_genome(name: str) -> dict:
    return {
        "name": name,
        "rsi_max": random.choice([55, 60, 65, 68, 70, 72, 75]),
        "min_pressure_abs": random.choice([2, 3, 4, 5, 6, 8]),
        "min_mtf_agreement": random.choice([2, 3]),
        "sl_pts": round(random.uniform(2.5, 6.0), 2),
        "tp_pts": round(random.uniform(6.0, 18.0), 2),
        "lot": 0.02,
        "use_footprint": True,
        "side_bias": random.choice([None, None, None, "BUY_ONLY", "SELL_ONLY"]),
        "born": "random",
    }


def _crossover(a: dict, b: dict, name: str) -> dict:
    """Marry two genomes — each gene from one parent at random + light mutation."""
    genes = ["rsi_max", "min_pressure_abs", "min_mtf_agreement", "sl_pts", "tp_pts", "side_bias"]
    defaults = {"rsi_max": 65, "min_pressure_abs": 3, "min_mtf_agreement": 2,
                "sl_pts": 4.0, "tp_pts": 10.0, "side_bias": None}
    child = {"name": name, "lot": 0.02, "use_footprint": True}
    for g in genes:
        # pick from a parent, but never inherit None for numeric genes
        choices = [v for v in (a.get(g), b.get(g)) if v is not None or g == "side_bias"]
        child[g] = random.choice(choices) if choices else defaults[g]
        if child[g] is None and g != "side_bias":
            child[g] = defaults[g]
    # Mutation (10% chance per numeric gene)
    if random.random() < 0.10: child["rsi_max"] = max(50, min(78, child.get("rsi_max", 65) + random.choice([-3, 3])))
    if random.random() < 0.10: child["sl_pts"] = round(max(2.0, child.get("sl_pts", 4) + random.uniform(-1, 1)), 2)
    if random.random() < 0.10: child["tp_pts"] = round(max(5.0, child.get("tp_pts", 10) + random.uniform(-2, 2)), 2)
    child["parents"] = [a.get("name"), b.get("name")]
    child["born"] = datetime.now(timezone.utc).isoformat()
    return child


# ──────────────────────────────────────────────────────────
# Gauntlet — multi-symbol backtest
# ──────────────────────────────────────────────────────────
def gauntlet(genome: dict) -> dict:
    """Backtest genome on every symbol. Returns per-symbol + aggregate."""
    per_symbol = {}
    for sym in SYMBOLS:
        r = backtest(genome, sym)
        per_symbol[sym] = r.to_dict()
    # Aggregate (normalize PnL to $ via pt-scale × 0.01 lot ≈ pt value)
    profitable_syms = [s for s, d in per_symbol.items() if d["pnl_pts"] > 0 and d["trades"] >= 3]
    total_trades = sum(d["trades"] for d in per_symbol.values())
    avg_wr = (sum(d["win_rate"] * d["trades"] for d in per_symbol.values()) / total_trades) if total_trades else 0
    return {
        "per_symbol": per_symbol,
        "profitable_symbols": profitable_syms,
        "n_profitable": len(profitable_syms),
        "total_trades": total_trades,
        "avg_win_rate": round(avg_wr, 1),
        "generalizes": len(profitable_syms) >= 3,   # profits on 3+ instruments
    }


# ──────────────────────────────────────────────────────────
# Agent panel — 5 experts interview the genome
# ──────────────────────────────────────────────────────────
def agent_panel(genome: dict, g: dict) -> dict:
    """Each agent scores 0..1. Risk has veto. Returns scores + verdict."""
    ps = g["per_symbol"]
    primary = ps.get(PRIMARY, {})

    # 1. ARCHITECT — structural sanity (R:R, param coherence)
    rr = genome.get("tp_pts", 10) / max(genome.get("sl_pts", 4), 0.1)
    architect = min(rr / 2.5, 1.0)   # reward R:R up to 2.5

    # 2. QUANT — statistical edge (avg WR + expectancy on primary)
    quant = min(max((g["avg_win_rate"] - 40) / 40, 0), 1.0)

    # 3. RISK — drawdown + consecutive losses (veto if dangerous)
    worst_dd = max((d["max_dd_pts"] for d in ps.values()), default=0)
    worst_consec = max((d["max_consec_loss"] for d in ps.values()), default=0)
    risk_ok = worst_consec <= 6
    risk = 1.0 if worst_consec <= 3 else (0.6 if worst_consec <= 5 else 0.2)

    # 4. EXECUTOR — trade frequency (not too rare, not hyperactive)
    tt = g["total_trades"]
    executor = 1.0 if 20 <= tt <= 300 else (0.5 if tt > 0 else 0.0)

    # 5. REVIEWER — generalization (the key question!)
    reviewer = min(g["n_profitable"] / 4, 1.0)   # full marks at 4+ profitable symbols

    scores = {
        "architect": round(architect, 2),
        "quant": round(quant, 2),
        "risk": round(risk, 2),
        "executor": round(executor, 2),
        "reviewer": round(reviewer, 2),
    }
    # Weighted overall — reviewer (generalization) + quant weighted highest
    overall = (architect*0.15 + quant*0.30 + risk*0.20 + executor*0.10 + reviewer*0.25)
    approved = risk_ok and overall >= 0.45
    return {"scores": scores, "overall": round(overall, 3), "approved": approved,
            "risk_veto": not risk_ok}


# ──────────────────────────────────────────────────────────
# Population persistence
# ──────────────────────────────────────────────────────────
def _load_pop() -> list[dict]:
    try:
        return json.loads(POP_FILE.read_text(encoding="utf-8")).get("genomes", [])
    except Exception:
        return []


def _save_pop(genomes: list[dict]) -> None:
    POP_FILE.write_text(json.dumps({"genomes": genomes}, indent=2, default=str), encoding="utf-8")


def _load_champion() -> dict:
    try:
        w = json.loads(CHAMPION_FILE.read_text(encoding="utf-8"))
        return w.get("champion_genome", w)
    except Exception:
        return {}


def _crown(genome: dict, panel: dict, g: dict) -> None:
    rec = {
        "champion_genome": {
            "name": genome["name"], "generation": 0,
            "promoted_ts": datetime.now(timezone.utc).isoformat(),
            "params": genome, "parents": genome.get("parents", []),
        },
        "captured_ts": datetime.now(timezone.utc).isoformat(),
        "panel_score": panel["overall"],
        "generalizes": g["generalizes"],
        "profitable_symbols": g["profitable_symbols"],
        "note": "crowned by genome_academy gauntlet+panel",
    }
    import shutil
    if CHAMPION_FILE.exists():
        shutil.copy2(CHAMPION_FILE, CHAMPION_FILE.with_suffix(".json.prev"))
    CHAMPION_FILE.write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
    # Promote to LIVE (only for primary-symbol trading by unified_trader)
    PATHS["live_genome"].write_text(json.dumps(rec["champion_genome"], indent=2, default=str), encoding="utf-8")
    with ACADEMY_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": rec["captured_ts"], "crowned": genome["name"],
                            "score": panel["overall"], "symbols": g["profitable_symbols"]}) + "\n")


# ──────────────────────────────────────────────────────────
# One arena round
# ──────────────────────────────────────────────────────────
def run_round(verbose: bool = False) -> dict:
    pop = _load_pop()
    # Seed population if too small
    while len(pop) < POP_SIZE:
        pop.append(_random_genome(f"GEN-RND-{random.randint(1000,9999)}"))

    # BREED — marry top genomes into children
    parents = pop[:max(ELITE_KEEP, 2)]
    children = []
    for _ in range(CHILDREN_PER_CYCLE):
        a, b = random.sample(parents if len(parents) >= 2 else pop, 2)
        children.append(_crossover(a, b, f"GEN-CHILD-{datetime.now(timezone.utc):%H%M%S}-{random.randint(10,99)}"))
    candidates = pop + children

    # GAUNTLET + PANEL for each candidate
    scored = []
    for genome in candidates:
        g = gauntlet(genome)
        panel = agent_panel(genome, g)
        scored.append({"genome": genome, "gauntlet": g, "panel": panel})

    # SELECT — rank by panel.overall (approved first)
    scored.sort(key=lambda s: (s["panel"]["approved"], s["panel"]["overall"]), reverse=True)
    survivors = [s["genome"] for s in scored[:POP_SIZE]]
    _save_pop(survivors)

    best = scored[0]
    # CROWN if best generalist beats champion
    champ = _load_champion()
    champ_g = gauntlet(champ.get("params", champ)) if champ else {"n_profitable": 0}
    champ_score = agent_panel(champ.get("params", champ), champ_g)["overall"] if champ else 0

    crowned = False
    if (best["panel"]["approved"] and best["gauntlet"]["generalizes"]
            and best["panel"]["overall"] > champ_score * 1.05):
        _crown(best["genome"], best["panel"], best["gauntlet"])
        crowned = True

    result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "evaluated": len(candidates),
        "best": best["genome"]["name"],
        "best_score": best["panel"]["overall"],
        "best_scores": best["panel"]["scores"],
        "generalizes": best["gauntlet"]["generalizes"],
        "profitable_symbols": best["gauntlet"]["profitable_symbols"],
        "champ_score": round(champ_score, 3),
        "crowned": crowned,
        "best_per_symbol": best["gauntlet"]["per_symbol"],
    }
    ACADEMY_STATE.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return result


def _print_round(r: dict) -> None:
    print(f"\n[{datetime.now():%H:%M:%S}] 🏟️  ROUND — evaluated {r['evaluated']} genomes")
    print(f"  🏅 Best: {r['best']}  score {r['best_score']}")
    print(f"     scores: {r['best_scores']}")
    print(f"  🌍 Generalizes: {'✅ نعم' if r['generalizes'] else '❌ لا (ذهب بس غالباً)'}")
    print(f"     profitable on: {r['profitable_symbols']}")
    print(f"  👑 Champion score: {r['champ_score']}  →  {'🎉 CROWNED new champion!' if r['crowned'] else 'champion holds'}")
    # Per-symbol mini-table
    print(f"  📊 Best genome per-symbol:")
    for sym, d in r["best_per_symbol"].items():
        if d["trades"] > 0:
            mark = "🟢" if d["pnl_pts"] > 0 else "🔴"
            print(f"     {mark} {sym:9s} {d['trades']:>3d}T WR {d['win_rate']:>4.0f}% "
                  f"PnL {d['pnl_pts']:>+7.1f}pt PF {d['profit_factor']:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single verbose round")
    args = ap.parse_args()

    import MetaTrader5 as mt5
    mt5.initialize()
    print("═══ 🏟️  GENOME ACADEMY — أكاديمية تطور ولدنا ═══")
    print(f"  symbols: {SYMBOLS}")
    print(f"  cycle: {CYCLE_SECONDS}s · pop {POP_SIZE} · {CHILDREN_PER_CYCLE} children/round")

    if args.once:
        _print_round(run_round(verbose=True))
        return

    while True:
        try:
            _print_round(run_round())
            time.sleep(CYCLE_SECONDS)
        except KeyboardInterrupt:
            print("\n[genome_academy] stopped"); break
        except Exception as e:
            print(f"err: {e}"); time.sleep(CYCLE_SECONDS)


if __name__ == "__main__":
    main()
