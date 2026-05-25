"""genome_lineage.py — Continuous evolution: take HoF winners, mutate + crossover,
backtest children on recent bars, deploy improvers.

Adds gene-level mutations (add/remove/swap) on top of HoF's existing param-only
mutate() and crossover(). Runs single-shot via --run-once or as a daemon loop.

Usage:
  python -m r_native.genome_lineage --run-once
  python -m r_native.genome_lineage --run-once --symbols XAUUSDm,BTCUSDm
  python -m r_native.genome_lineage --daemon --interval-min 60
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from r_native import hall_of_fame as hof
from r_native.genome_breeder import GENE_CATEGORIES, build_genome, simulate_on


ALL_GENES = sorted(set(g for cat in GENE_CATEGORIES.values() for g in cat))
SIGNAL_GENES = list(GENE_CATEGORIES["SIGNAL"])
BIAS_GENES   = list(GENE_CATEGORIES["BIAS"])
FILTER_GENES = list(GENE_CATEGORIES["FILTER"])
MGMT_GENES   = list(GENE_CATEGORIES["MGMT"])
EXEC_GENES   = list(GENE_CATEGORIES["EXEC"])

CONFIGS_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
LINEAGE_LOG = Path(r"C:\Users\Radhi\MT5\data\r_native\lineage_log.jsonl")

# Survivor thresholds — child must beat parent by these margins to advance
MIN_TRADES_PARENT_COMP    = 15
MIN_PF_IMPROVEMENT        = 1.10   # child PF must be ≥ 1.1× parent PF
MIN_DEPLOY_PF             = 2.0    # never deploy a child with PF < this
MIN_DEPLOY_TRADES         = 20
MIN_DEPLOY_WR             = 60
DEPLOY_IMPROVEMENT_MARGIN = 1.05   # child must be 5%+ better than current deployed
MIN_GENES_PER_CHILD       = 5
MAX_GENES_PER_CHILD       = 22


# ───────────────────────────────────────────────────────────────────────
# Mutations (gene-level — HoF only mutates params)
# ───────────────────────────────────────────────────────────────────────

def _genes_of(parent: dict) -> list:
    return list(parent.get("active_genes") or [])


def _params_of(parent: dict) -> dict:
    # HoF uses "all_params"; symbol_configs entries use flat sl_atr_mult etc.
    if parent.get("all_params"):
        return dict(parent["all_params"])
    # Reconstruct from flat fields
    return {
        "sl_atr_mult": float(parent.get("sl_atr_mult") or 1.5),
        "tp_atr_mult": float(parent.get("tp_atr_mult") or 1.5),
        "start_hour":  int(parent.get("start_hour")  or 0),
        "end_hour":    int(parent.get("end_hour")    or 23),
    }


def _hash_id(genes: list, params: dict) -> str:
    """Deterministic 6-hex ID from genes+params (so duplicates collide)."""
    payload = json.dumps([sorted(genes), {k: round(v, 4) if isinstance(v, float) else v
                                          for k, v in sorted(params.items())}],
                         sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:6].upper()


def mutate_genes(parent: dict, intensity: int = 2) -> dict:
    """Add/remove a few genes from parent. Preserves params."""
    genes = _genes_of(parent)
    params = _params_of(parent)
    available = [g for g in ALL_GENES if g not in genes]
    for _ in range(intensity):
        action = random.choice(["add", "remove", "swap"])
        if action == "add" and available and len(genes) < MAX_GENES_PER_CHILD:
            new_g = random.choice(available)
            genes.append(new_g)
            available.remove(new_g)
        elif action == "remove" and len(genes) > MIN_GENES_PER_CHILD:
            # Don't remove all signal/bias genes — keep at least one of each
            removable = [g for g in genes
                         if not (g in SIGNAL_GENES
                                 and sum(1 for x in genes if x in SIGNAL_GENES) <= 1)
                         and not (g in BIAS_GENES
                                  and sum(1 for x in genes if x in BIAS_GENES) <= 1)]
            if removable:
                victim = random.choice(removable)
                genes.remove(victim)
                available.append(victim)
        elif action == "swap" and available and genes:
            cat = random.choice([SIGNAL_GENES, BIAS_GENES, FILTER_GENES])
            in_cat = [g for g in genes if g in cat]
            avail_in_cat = [g for g in available if g in cat]
            if in_cat and avail_in_cat:
                victim = random.choice(in_cat)
                replacement = random.choice(avail_in_cat)
                genes.remove(victim); available.append(victim)
                genes.append(replacement); available.remove(replacement)
    return {
        "active_genes":  sorted(set(genes)),
        "all_params":    params,
        "parents":       [parent.get("id")],
        "generation":    int(parent.get("generation", 0)) + 1,
        "birth_method":  "lineage_gene_mutate",
    }


def mutate_params(parent: dict) -> dict:
    """Perturb SL/TP multipliers and session window."""
    params = _params_of(parent)
    sl = float(params.get("sl_atr_mult", 1.5))
    tp = float(params.get("tp_atr_mult", 1.5))
    params["sl_atr_mult"] = round(max(0.5, sl * random.uniform(0.85, 1.20)), 3)
    params["tp_atr_mult"] = round(max(0.5, tp * random.uniform(0.85, 1.25)), 3)
    if random.random() < 0.3:
        # tweak window
        sh = int(params.get("start_hour", 0))
        eh = int(params.get("end_hour", 23))
        sh = max(0, min(20, sh + random.choice([-2, -1, 0, 1, 2])))
        eh = max(sh + 3, min(23, eh + random.choice([-2, -1, 0, 1, 2])))
        params["start_hour"] = sh
        params["end_hour"]   = eh
    return {
        "active_genes":  _genes_of(parent),
        "all_params":    params,
        "parents":       [parent.get("id")],
        "generation":    int(parent.get("generation", 0)) + 1,
        "birth_method":  "lineage_param_mutate",
    }


def cross_genes(parent_a: dict, parent_b: dict) -> dict:
    """Uniform gene crossover — each parent's gene has 50% chance to carry."""
    ga, gb = set(_genes_of(parent_a)), set(_genes_of(parent_b))
    shared = ga & gb
    unique = (ga ^ gb)
    child_genes = list(shared) + [g for g in unique if random.random() < 0.5]
    if len(child_genes) < MIN_GENES_PER_CHILD:
        child_genes.extend(random.sample(list(unique - set(child_genes)),
                                          min(MIN_GENES_PER_CHILD - len(child_genes),
                                              len(unique - set(child_genes)))))
    # Params: prefer parent_a's risk profile, parent_b's session
    pa = _params_of(parent_a)
    pb = _params_of(parent_b)
    child_params = {
        "sl_atr_mult": pa.get("sl_atr_mult"),
        "tp_atr_mult": pa.get("tp_atr_mult"),
        "start_hour":  pb.get("start_hour"),
        "end_hour":    pb.get("end_hour"),
    }
    return {
        "active_genes":  sorted(set(child_genes))[:MAX_GENES_PER_CHILD],
        "all_params":    child_params,
        "parents":       [parent_a.get("id"), parent_b.get("id")],
        "generation":    max(int(parent_a.get("generation", 0)),
                              int(parent_b.get("generation", 0))) + 1,
        "birth_method":  "lineage_crossover",
    }


# ───────────────────────────────────────────────────────────────────────
# Simulation + scoring
# ───────────────────────────────────────────────────────────────────────

def _score(stats: dict) -> float:
    """Composite score balancing PF, WR, sample size, drawdown."""
    tr  = int(stats.get("trades", 0))
    pf  = float(stats.get("profit_factor", 0))
    wr  = float(stats.get("win_rate", 0))
    dd  = float(stats.get("max_drawdown_pct", 999))
    shp = float(stats.get("sharpe", 0))
    if tr < MIN_TRADES_PARENT_COMP: return 0.0
    # weight: sharpe + bounded pf + sqrt(trades penalty) - dd penalty
    return round(shp * 2 + min(pf, 20) * 0.8 + (tr ** 0.5) * 0.3
                 - max(0, (dd - 30)) * 0.05, 3)


def _simulate(child_proto: dict, symbol: str, tf: str, n_bars: int) -> Optional[dict]:
    """Convert a lineage child proto into a genome and simulate it."""
    genome = build_genome(child_proto["active_genes"], child_proto["all_params"])
    res = simulate_on(genome, symbol, tf, n_bars=n_bars)
    if not res.get("ok"): return None
    stats = res["stats"]
    gid = _hash_id(child_proto["active_genes"], child_proto["all_params"])
    return {
        "id":           gid,
        "active_genes": child_proto["active_genes"],
        "all_params":   child_proto["all_params"],
        "parents":      child_proto.get("parents", []),
        "generation":   child_proto.get("generation", 1),
        "birth_method": child_proto.get("birth_method", "unknown"),
        "stats":        stats,
        "score":        _score(stats),
    }


# ───────────────────────────────────────────────────────────────────────
# Per-symbol lineage round
# ───────────────────────────────────────────────────────────────────────

def _load_symbol_parents(symbol: str, top_n: int = 5) -> list[dict]:
    """Pull top-N candidates for this symbol from symbol_configs ga_strategies.
    Falls back to HoF.by_symbol if config has none.
    """
    cfg_path = CONFIGS_DIR / f"{symbol}.json"
    parents: list[dict] = []
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            strats = cfg.get("ga_strategies", []) or []
            # Prefer DEPLOY-tier, alive
            deployable = [s for s in strats
                          if s.get("confidence") == "DEPLOY"
                          and s.get("active_genes")]
            deployable.sort(key=lambda s: -(s.get("profit_factor", 0)))
            parents.extend(deployable[:top_n])
        except Exception: pass
    if not parents:
        hof_pool = hof.get_breeding_pool(symbol, n=top_n)
        parents.extend(hof_pool)
    return parents


def _get_current_deployed(symbol: str) -> Optional[dict]:
    cfg_path = CONFIGS_DIR / f"{symbol}.json"
    if not cfg_path.exists(): return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return cfg.get("deployed_genome")
    except Exception: return None


def _deploy_candidate(symbol: str, child: dict) -> bool:
    """Replace symbol's deployed_genome if child is materially better."""
    current = _get_current_deployed(symbol) or {}
    current_pf = float(current.get("profit_factor") or 0)
    child_pf   = float(child["stats"].get("profit_factor", 0))
    if child_pf < MIN_DEPLOY_PF: return False
    if child["stats"].get("trades", 0) < MIN_DEPLOY_TRADES: return False
    if child["stats"].get("win_rate", 0) < MIN_DEPLOY_WR: return False
    if current_pf > 0 and child_pf < current_pf * DEPLOY_IMPROVEMENT_MARGIN:
        return False

    cfg_path = CONFIGS_DIR / f"{symbol}.json"
    cfg = {}
    if cfg_path.exists():
        try: cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception: pass

    cfg["deployed_genome"] = {
        "id":             child["id"],
        "profit_factor":  child_pf,
        "sl_atr_mult":    child["all_params"].get("sl_atr_mult"),
        "tp_atr_mult":    child["all_params"].get("tp_atr_mult"),
        "start_hour":     child["all_params"].get("start_hour"),
        "end_hour":       child["all_params"].get("end_hour"),
        "active_genes":   child["active_genes"],
        "win_rate":       child["stats"].get("win_rate"),
        "trades":         child["stats"].get("trades"),
        "sharpe":         child["stats"].get("sharpe"),
        "source":         f"lineage_breeder_gen{child['generation']}",
        "parents":        child.get("parents", []),
        "deployed_at":    datetime.now(timezone.utc).isoformat(),
    }
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return True


def _log_event(event: dict) -> None:
    LINEAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    with open(LINEAGE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def breed_round(symbol: str, tf: str = "M5",
                children_per_parent: int = 4,
                n_bars: int = 4000,
                top_parents: int = 3) -> dict:
    """One full breeding cycle for one symbol. Returns summary."""
    parents = _load_symbol_parents(symbol, top_n=top_parents)
    if not parents:
        return {"ok": False, "symbol": symbol, "reason": "no parents"}

    children = []
    methods_used = []
    for parent in parents[:top_parents]:
        for _ in range(children_per_parent):
            method = random.choices(
                ["gene_mutate", "param_mutate", "crossover"],
                weights=[0.45, 0.30, 0.25])[0]
            try:
                if method == "gene_mutate":
                    proto = mutate_genes(parent, intensity=random.choice([1, 2, 3]))
                elif method == "param_mutate":
                    proto = mutate_params(parent)
                else:
                    mate = random.choice(parents)
                    if mate.get("id") == parent.get("id"):
                        mate = random.choice(parents)
                    proto = cross_genes(parent, mate)
                methods_used.append(method)
                sim = _simulate(proto, symbol, tf, n_bars)
                if sim: children.append(sim)
            except Exception as e:
                _log_event({"event": "child_err", "symbol": symbol,
                            "parent": parent.get("id"), "err": str(e)})

    if not children:
        return {"ok": False, "symbol": symbol, "reason": "all sims failed"}

    children.sort(key=lambda c: -c["score"])
    top = children[0]
    parent_pf_avg = (sum(float(p.get("profit_factor") or 0) for p in parents)
                     / max(1, len(parents)))
    survivors = [c for c in children
                 if c["stats"].get("trades", 0) >= MIN_TRADES_PARENT_COMP
                 and float(c["stats"].get("profit_factor", 0))
                     >= parent_pf_avg * MIN_PF_IMPROVEMENT]

    # Save survivors to HoF
    admitted_ids = []
    for c in survivors:
        try:
            genome_for_hof = {
                "id":           c["id"],
                "active_genes": c["active_genes"],
                "all_params":   c["all_params"],
                "parents":      c["parents"],
                "generation":   c["generation"],
                "birth_method": c["birth_method"],
            }
            hof.admit(genome_for_hof, symbol=symbol, tf=tf,
                      score=c["score"], stats=c["stats"])
            admitted_ids.append(c["id"])
        except Exception as e:
            _log_event({"event": "hof_admit_err", "id": c["id"], "err": str(e)})

    # Try to deploy the best survivor
    deployed = False
    if survivors:
        if _deploy_candidate(symbol, survivors[0]):
            deployed = True
            _log_event({
                "event": "DEPLOYED", "symbol": symbol,
                "child_id": survivors[0]["id"],
                "child_pf": survivors[0]["stats"].get("profit_factor"),
                "child_wr": survivors[0]["stats"].get("win_rate"),
                "child_trades": survivors[0]["stats"].get("trades"),
                "parents": survivors[0]["parents"],
                "method": survivors[0]["birth_method"],
                "generation": survivors[0]["generation"],
            })

    summary = {
        "ok": True,
        "symbol": symbol,
        "tf": tf,
        "parents_count": len(parents),
        "children_born": len(children),
        "survivors": len(survivors),
        "admitted_to_hof": admitted_ids,
        "deployed": deployed,
        "top_child_id": top["id"],
        "top_child_score": top["score"],
        "top_child_pf": top["stats"].get("profit_factor"),
        "top_child_wr": top["stats"].get("win_rate"),
        "top_child_trades": top["stats"].get("trades"),
        "methods_used": {m: methods_used.count(m)
                         for m in set(methods_used)},
    }
    _log_event({"event": "round_complete", **summary})
    return summary


# ───────────────────────────────────────────────────────────────────────
# CLI
# ───────────────────────────────────────────────────────────────────────

def _discover_deployable_symbols() -> list[str]:
    """All symbols that have a symbol_configs/<sym>.json file with ga_strategies."""
    if not CONFIGS_DIR.exists(): return []
    out = []
    for p in CONFIGS_DIR.glob("*.json"):
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            if cfg.get("ga_strategies"):
                out.append(p.stem)
        except Exception: pass
    return sorted(out)


def run_once(symbols: Optional[list[str]] = None,
             children_per_parent: int = 4,
             tf: str = "M5",
             n_bars: int = 4000) -> dict:
    """Run one breeding round for each symbol; return aggregate report."""
    if not symbols:
        symbols = _discover_deployable_symbols()
    if not symbols:
        return {"ok": False, "reason": "no symbols with ga_strategies found"}

    results = []
    for sym in symbols:
        try:
            r = breed_round(sym, tf=tf,
                            children_per_parent=children_per_parent,
                            n_bars=n_bars)
            results.append(r)
        except Exception as e:
            results.append({"ok": False, "symbol": sym, "err": str(e)})

    deployed = sum(1 for r in results if r.get("deployed"))
    admitted = sum(len(r.get("admitted_to_hof") or []) for r in results)
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat(),
            "symbols_processed": len(results),
            "deployed_count":    deployed,
            "hof_admitted":      admitted,
            "results":           results}


def _cli():
    ap = argparse.ArgumentParser(prog="r_native.genome_lineage")
    ap.add_argument("--run-once", action="store_true",
                    help="single round across all (or --symbols) and exit")
    ap.add_argument("--daemon", action="store_true",
                    help="loop forever every --interval-min minutes")
    ap.add_argument("--interval-min", type=int, default=60,
                    help="minutes between daemon rounds (default 60)")
    ap.add_argument("--symbols", type=str, default="",
                    help="comma-separated, e.g. XAUUSDm,BTCUSDm")
    ap.add_argument("--children-per-parent", type=int, default=4)
    ap.add_argument("--tf", default="M5", choices=["M5", "M15", "H1", "H4"])
    ap.add_argument("--n-bars", type=int, default=4000)
    args = ap.parse_args()

    syms = [s.strip() for s in args.symbols.split(",") if s.strip()] or None

    if args.run_once:
        rep = run_once(symbols=syms,
                       children_per_parent=args.children_per_parent,
                       tf=args.tf, n_bars=args.n_bars)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return

    if args.daemon:
        print(f"[lineage] daemon mode — interval {args.interval_min} min")
        while True:
            try:
                rep = run_once(symbols=syms,
                               children_per_parent=args.children_per_parent,
                               tf=args.tf, n_bars=args.n_bars)
                print(f"[{datetime.now(timezone.utc):%H:%M:%S}] "
                      f"processed={rep.get('symbols_processed')} "
                      f"deployed={rep.get('deployed_count')} "
                      f"hof+={rep.get('hof_admitted')}", flush=True)
            except Exception as e:
                print(f"[lineage] cycle err: {e}", flush=True)
            time.sleep(args.interval_min * 60)
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()
