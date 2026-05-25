"""hall_of_fame.py — Permanent genome vault with lineage tracking.

Every genome that ever scored well gets saved here forever. They become:
  • elite seeds for future GA cycles (so we don't restart from scratch)
  • breeding parents for crossover/mutation
  • the user's named, pinnable favorites
  • the historical record of what worked when

Layout:
  data/r_native/hall_of_fame/
    index.json                    — flat list, indexed by id
    by_symbol/
      BTCUSDm.json                — ranked list for this symbol
      XAUUSDm.json
    pinned.json                   — user-pinned (immortal) genome ids

Each entry:
  {
    "id":            "DF9F6C",
    "nickname":      "BTC-REVERSION-G3-DF9F6C",
    "symbol":        "BTCUSDm",
    "tf":            "M5",
    "born_at":       "2026-05-24T01:25:25Z",
    "birth_method":  "ga_random" | "elite_carry" | "crossover" | "mutation" | "manual",
    "parents":       ["E11DC2", "BF56A6"],
    "generation":    3,
    "score":         44.16,
    "stats":         {trades, wins, win_rate, profit_factor, ...},
    "all_params":    {...},
    "active_genes":  [...],
    "deployments":   [{at, symbol, duration_h}],
    "live_pnl":      0.0,
    "live_trades":   0,
    "pinned":        false,
    "killed":        false,
    "kill_reason":   null,
    "notes":         ""  -- user notes
  }
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HOF_DIR     = Path(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame")
INDEX_PATH  = HOF_DIR / "index.json"
PINNED_PATH = HOF_DIR / "pinned.json"
BY_SYMBOL   = HOF_DIR / "by_symbol"


# ─── Nickname generator ───────────────────────────────────────────────
ADJECTIVES = ["Steady", "Silent", "Bold", "Cunning", "Ruthless", "Patient",
              "Swift", "Iron", "Phantom", "Apex", "Stoic", "Cobra",
              "Eclipse", "Tempest", "Crimson", "Mercury", "Tundra", "Nova",
              "Onyx", "Specter", "Hawk", "Wolf", "Falcon", "Sniper",
              "Reaper", "Architect", "Oracle", "Vanguard", "Maverick",
              "Sentinel", "Drifter", "Shogun", "Khan", "Pharaoh", "Tycoon"]


def _gen_nickname(symbol: str, archetype: Optional[str], generation: int,
                  genome_id: str) -> str:
    """Generate a memorable name like 'BTC-Apex-Reaper-G3-DF9F6C'."""
    short_sym = symbol.replace("USDm", "").replace("USD", "").replace("m", "")[:4]
    arch = (archetype or "MIXED")[:4].upper()
    # Pick deterministic adjective from id so same id always gets same name
    seed = int(genome_id[:6], 16) if all(c in "0123456789ABCDEFabcdef"
                                          for c in genome_id[:6]) else hash(genome_id)
    adj1 = ADJECTIVES[seed % len(ADJECTIVES)]
    adj2 = ADJECTIVES[(seed // len(ADJECTIVES)) % len(ADJECTIVES)]
    return f"{short_sym}-{adj1}-{adj2}-{arch}-G{generation}-{genome_id[:6]}"


# ─── File I/O ─────────────────────────────────────────────────────────
def _ensure_dirs():
    HOF_DIR.mkdir(parents=True, exist_ok=True)
    BY_SYMBOL.mkdir(parents=True, exist_ok=True)


def _read_json(p: Path, default):
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return default


def _write_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_index() -> dict:
    """Return {genome_id: entry, ...}"""
    return _read_json(INDEX_PATH, {})


def load_pinned() -> list[str]:
    return _read_json(PINNED_PATH, [])


def load_symbol(symbol: str) -> list[dict]:
    """Ranked list of all genomes ever produced for this symbol (best first)."""
    return _read_json(BY_SYMBOL / f"{symbol}.json", [])


# ─── Public API ───────────────────────────────────────────────────────
def admit(genome: dict, symbol: str, tf: str, score: float,
          stats: dict, all_params: dict = None, active_genes: list = None,
          parents: list[str] = None, birth_method: str = "ga_random",
          generation: int = 1, archetype: str = None) -> dict:
    """Admit a new genome to the Hall of Fame, or update if exists.

    Returns the saved entry.
    """
    _ensure_dirs()
    genome_id = genome.get("id") if isinstance(genome, dict) else genome
    if not genome_id:
        raise ValueError("genome has no id")

    index = load_index()
    existing = index.get(genome_id) or {}

    entry = {
        "id":            genome_id,
        "nickname":      existing.get("nickname")
                         or _gen_nickname(symbol, archetype, generation, genome_id),
        "symbol":        symbol,
        "tf":            tf,
        "born_at":       existing.get("born_at")
                         or datetime.now(timezone.utc).isoformat(),
        "birth_method":  existing.get("birth_method", birth_method),
        "parents":       existing.get("parents", parents or []),
        "generation":    existing.get("generation", generation),
        "archetype":     archetype or existing.get("archetype", "MIXED"),
        "score":         float(score),
        "stats":         stats or {},
        "all_params":    all_params or existing.get("all_params", {}),
        "active_genes":  active_genes or existing.get("active_genes", []),
        "deployments":   existing.get("deployments", []),
        "live_pnl":      existing.get("live_pnl", 0.0),
        "live_trades":   existing.get("live_trades", 0),
        "pinned":        existing.get("pinned", False),
        "killed":        existing.get("killed", False),
        "kill_reason":   existing.get("kill_reason"),
        "notes":         existing.get("notes", ""),
        "last_updated":  datetime.now(timezone.utc).isoformat(),
    }
    index[genome_id] = entry
    _write_json(INDEX_PATH, index)

    # Update per-symbol ranked list
    by_sym = load_symbol(symbol)
    by_sym = [e for e in by_sym if e.get("id") != genome_id]
    by_sym.append(entry)
    by_sym.sort(key=lambda e: e.get("score", 0), reverse=True)
    _write_json(BY_SYMBOL / f"{symbol}.json", by_sym)

    return entry


def record_deployment(genome_id: str, symbol: str) -> None:
    """Note that this genome went live on this symbol just now."""
    _ensure_dirs()
    index = load_index()
    entry = index.get(genome_id)
    if not entry: return
    entry.setdefault("deployments", []).append({
        "at":     datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
    })
    entry["last_updated"] = datetime.now(timezone.utc).isoformat()
    index[genome_id] = entry
    _write_json(INDEX_PATH, index)


def record_live_trade(genome_id: str, pnl: float) -> None:
    """Update live P/L after a closed trade."""
    _ensure_dirs()
    index = load_index()
    entry = index.get(genome_id)
    if not entry: return
    entry["live_trades"] = int(entry.get("live_trades", 0)) + 1
    entry["live_pnl"]    = float(entry.get("live_pnl", 0)) + float(pnl)
    entry["last_updated"] = datetime.now(timezone.utc).isoformat()
    index[genome_id] = entry
    _write_json(INDEX_PATH, index)


def pin(genome_id: str) -> bool:
    """Pin a genome — it survives kills and ages forever.
    Idempotent: returns False if already pinned (no-op)."""
    pinned = set(load_pinned())
    if genome_id in pinned:
        return False
    pinned.add(genome_id)
    _write_json(PINNED_PATH, sorted(pinned))
    index = load_index()
    if genome_id in index:
        index[genome_id]["pinned"] = True
        _write_json(INDEX_PATH, index)
    return True


def unpin(genome_id: str) -> bool:
    """Remove pin. Idempotent: returns False if not pinned (no-op)."""
    pinned = set(load_pinned())
    if genome_id not in pinned:
        return False
    pinned.discard(genome_id)
    _write_json(PINNED_PATH, sorted(pinned))
    index = load_index()
    if genome_id in index:
        index[genome_id]["pinned"] = False
        _write_json(INDEX_PATH, index)
    return True


def is_deployed_anywhere(genome_id: str) -> str | None:
    """Return the symbol where this genome is currently deployed, or None.
    Used to refuse killing live-trading genomes."""
    try:
        from pathlib import Path as _P
        cfg_dir = _P(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        if not cfg_dir.exists(): return None
        for p in cfg_dir.glob("*.json"):
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
                if (cfg.get("deployed_genome") or {}).get("id") == genome_id:
                    return p.stem
            except Exception:
                continue
    except Exception:
        pass
    return None


def kill(genome_id: str, reason: str) -> bool:
    """Mark a genome as killed (won't be carried forward). Protected:
      • pinned genomes cannot be killed
      • currently-deployed genomes cannot be killed (would orphan the
        symbol's trading config)
      • directional specialists (e.g. BUY-only with WR ≥ 65% over ≥5 trades)
        cannot be killed — they are kept as ensemble candidates
    """
    pinned = set(load_pinned())
    if genome_id in pinned: return False
    deployed_on = is_deployed_anywhere(genome_id)
    if deployed_on:
        try:
            print(f"[hof.kill] refused: {genome_id} is currently deployed on {deployed_on}",
                  flush=True)
        except Exception: pass
        return False
    # Asymmetry-based protection: BUY/SELL specialists kept for ensemble pairing
    try:
        from r_native.genome_asymmetry import is_kill_protected
        protected, why = is_kill_protected(genome_id)
        if protected:
            try:
                print(f"[hof.kill] refused: {genome_id} kill-protected — {why}",
                      flush=True)
            except Exception: pass
            return False
    except Exception:
        pass    # never block a kill on missing/broken asymmetry module
    index = load_index()
    entry = index.get(genome_id)
    if not entry: return False
    # Idempotent: if already killed, return False so callers don't double-report
    if entry.get("killed"):
        return False
    entry["killed"]      = True
    entry["kill_reason"] = reason
    entry["last_updated"] = datetime.now(timezone.utc).isoformat()
    index[genome_id] = entry
    _write_json(INDEX_PATH, index)
    return True


def get_elites(symbol: str, n: int = 10, include_pinned: bool = True) -> list[dict]:
    """Return top N genomes for this symbol (not killed). Pinned always included."""
    by_sym = load_symbol(symbol)
    pinned = set(load_pinned())
    alive  = [e for e in by_sym if not e.get("killed")]
    top    = alive[:n]
    if include_pinned:
        for e in alive:
            if e.get("id") in pinned and e not in top:
                top.append(e)
    return top


def get_breeding_pool(symbol: str, n: int = 20) -> list[dict]:
    """Return parents suitable for crossover — alive, top-scoring, has params."""
    by_sym = load_symbol(symbol)
    pool = [e for e in by_sym
            if not e.get("killed") and e.get("all_params")]
    return pool[:n]


def crossover(parent_a: dict, parent_b: dict, child_id: str = None) -> dict:
    """Genetic crossover — produce a child by mixing two parents' params.

    Returns the child genome dict (NOT yet evaluated — caller must backtest).
    """
    pa = parent_a.get("all_params", {})
    pb = parent_b.get("all_params", {})
    if not pa or not pb:
        raise ValueError("both parents need all_params for crossover")

    # Uniform crossover: each param independently from A or B
    child_params = {}
    for k in set(pa.keys()) | set(pb.keys()):
        if k in pa and k in pb:
            child_params[k] = random.choice([pa[k], pb[k]])
        else:
            child_params[k] = pa.get(k, pb.get(k))

    # Generation = max(parents) + 1
    gen = max(int(parent_a.get("generation", 0)),
              int(parent_b.get("generation", 0))) + 1

    return {
        "all_params":   child_params,
        "active_genes": list(set((parent_a.get("active_genes") or []) +
                                  (parent_b.get("active_genes") or []))),
        "parents":      [parent_a.get("id"), parent_b.get("id")],
        "generation":   gen,
        "birth_method": "crossover",
        "_pending_id":  child_id,  # caller fills in real id after hashing
    }


def mutate(parent: dict, mutation_rate: float = 0.15) -> dict:
    """Mutation — return a copy with `mutation_rate` of params perturbed."""
    pp = parent.get("all_params", {})
    if not pp:
        raise ValueError("parent needs all_params for mutation")
    child_params = dict(pp)
    for k, v in pp.items():
        if random.random() < mutation_rate:
            if isinstance(v, bool):
                child_params[k] = not v
            elif isinstance(v, int):
                child_params[k] = max(1, int(v * random.uniform(0.7, 1.3)))
            elif isinstance(v, float):
                child_params[k] = round(v * random.uniform(0.8, 1.2), 4)

    gen = int(parent.get("generation", 0)) + 1
    return {
        "all_params":   child_params,
        "active_genes": list(parent.get("active_genes") or []),
        "parents":      [parent.get("id")],
        "generation":   gen,
        "birth_method": "mutation",
    }


def summary() -> dict:
    """High-level stats for the UI."""
    _ensure_dirs()
    index  = load_index()
    pinned = load_pinned()
    by_symbol = {}
    for sym_file in BY_SYMBOL.glob("*.json"):
        sym = sym_file.stem
        lst = _read_json(sym_file, [])
        alive = [e for e in lst if not e.get("killed")]
        if alive:
            by_symbol[sym] = {
                "total":      len(lst),
                "alive":      len(alive),
                "top_score":  alive[0].get("score") if alive else 0,
                "top_id":     alive[0].get("id") if alive else None,
                "top_nickname": alive[0].get("nickname") if alive else None,
            }
    return {
        "total_genomes":  len(index),
        "pinned_count":   len(pinned),
        "killed_count":   sum(1 for e in index.values() if e.get("killed")),
        "by_symbol":      by_symbol,
    }


if __name__ == "__main__":
    print(json.dumps(summary(), indent=2, ensure_ascii=False))
