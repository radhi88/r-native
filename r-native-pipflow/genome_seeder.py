"""genome_seeder.py — Make sure every symbol the executor wants to trade has
a deployed_genome before the trade fires.

Currently only XAUUSDm and BTCUSDm have ga_strategies + deployed_genome. Every
other symbol the scanner picks (US30m, DE30m, XAUEURm, ...) falls through to
the Algory archetype path, so the broker comment ends up `R_BREAKO` instead
of `R-<gid>-<side>`.

This module fixes that by AUTO-SEEDING: when called for a symbol that has no
`deployed_genome`, it clones the best available genome from Hall-of-Fame (or
from any existing symbol_config) into that symbol's config. From the next
cycle onward, the gate sees a deployed_genome and produces a real
genome_decision, so the executor's broker comment will be `R-<gid>-<side>`.

The lineage daemon will then EVOLVE that seed per-symbol over time.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CONFIGS_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
HOF_INDEX   = Path(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame\index.json")
SEED_LOG    = Path(r"C:\Users\Radhi\MT5\data\r_native\seed_log.jsonl")


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _read_json(p: Path, default=None):
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return default


def _has_deployed(symbol: str) -> bool:
    cfg = _read_json(CONFIGS_DIR / f"{symbol}.json", {}) or {}
    dg = cfg.get("deployed_genome")
    return bool(dg and dg.get("id"))


def _best_seed_from_hof() -> Optional[dict]:
    """Return the best living, deploy-grade genome from HoF index, or None."""
    idx = _read_json(HOF_INDEX, {}) or {}
    if not idx: return None
    # Filter: alive + not killed + has active_genes
    pool = [e for e in idx.values()
            if e.get("active_genes")
            and not e.get("killed")
            and (e.get("score") or 0) >= 15]   # any meaningfully-scored genome
    if not pool:
        # Fall back: anything alive with active_genes
        pool = [e for e in idx.values()
                if e.get("active_genes") and not e.get("killed")]
    if not pool: return None
    # Prefer ones with the most live trades, then highest score
    pool.sort(key=lambda e: (-int(e.get("live_trades") or 0),
                              -(e.get("score") or 0)))
    return pool[0]


def _best_seed_from_configs() -> Optional[dict]:
    """Return a sample deployed_genome from any existing symbol_config."""
    if not CONFIGS_DIR.exists(): return None
    best = None
    best_pf = 0
    for p in CONFIGS_DIR.glob("*.json"):
        cfg = _read_json(p, {}) or {}
        dg  = cfg.get("deployed_genome") or {}
        if not dg.get("id") or not dg.get("active_genes"): continue
        pf = float(dg.get("profit_factor") or 0)
        if pf > best_pf:
            best_pf = pf; best = dg
    return best


def _log_seed(symbol: str, source: str, gid: str, details: dict) -> None:
    try:
        SEED_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SEED_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _now(), "symbol": symbol, "source": source,
                "seeded_gid": gid, **details,
            }, ensure_ascii=False) + "\n")
    except Exception: pass


def ensure_seeded(symbol: str) -> tuple[bool, str]:
    """Idempotent: if `symbol` already has a deployed_genome, no-op.
    Otherwise clone the best HoF/config genome into its config. Returns
    (seeded_now, reason)."""
    if _has_deployed(symbol):
        return False, "already has deployed_genome"

    # Pick a source genome
    src_hof = _best_seed_from_hof()
    src_cfg = _best_seed_from_configs()
    src = src_hof or src_cfg
    if not src:
        return False, "no seed candidate in HoF or configs"

    # Build the deployed_genome dict — derive a UNIQUE per-symbol ID so each
    # currency shows a distinct genome in the UI, while keeping `parent_id`
    # pointing at the original donor so lineage tracking still works.
    parent_id = src.get("id") or "SEED"
    # Per-symbol unique ID: hash(symbol + parent + millisecond) → 6 hex chars.
    # Switched from minute → millisecond granularity after a regression where
    # 11 symbols seeded in the same minute window collided on the parent ID
    # because a stale daemon was running pre-fix bytecode.
    import hashlib as _hl, time as _t
    _seed_key = f"{symbol}|{parent_id}|{int(_t.time() * 1000)}"
    gid = _hl.sha256(_seed_key.encode()).hexdigest()[:6].upper()
    # Safety guard: if anything causes gid to equal parent (would never happen
    # with the hash above, but if a future bug ever copies the dict naively,
    # blow up loudly instead of silently breeding duplicates across symbols).
    if gid == parent_id:
        return False, f"refusing to seed: generated id collides with parent {parent_id}"
    seeded = {
        "id":            gid,
        "parent_id":     parent_id,            # lineage breadcrumb
        "active_genes":  list(src.get("active_genes") or []),
        "sl_atr_mult":   src.get("sl_atr_mult") or src.get("all_params", {}).get("sl_atr_mult", 2.0),
        "tp_atr_mult":   src.get("tp_atr_mult") or src.get("all_params", {}).get("tp_atr_mult", 4.0),
        "start_hour":    src.get("start_hour") or src.get("all_params", {}).get("start_hour", 0),
        "end_hour":      src.get("end_hour")   or src.get("all_params", {}).get("end_hour", 23),
        "profit_factor": src.get("profit_factor") or src.get("score") or 0,
        "win_rate":      src.get("win_rate") or 0,
        "trades":        src.get("trades") or 0,
        "source":        f"auto_seed_from_{src_hof and 'hof' or 'cfg'}_{parent_id}",
        "deployed_at":   _now(),
        "seed":          True,    # flag so we know lineage hasn't evolved it yet
    }

    # Write to symbol_configs
    cfg_path = CONFIGS_DIR / f"{symbol}.json"
    cfg = _read_json(cfg_path, {}) or {}
    cfg["symbol"]         = symbol
    cfg["last_scan"]      = _now()
    cfg["deployed_genome"] = seeded
    cfg["tradeable"]      = True
    cfg["lot"]            = cfg.get("lot", 0.01)
    cfg["max_concurrent"] = cfg.get("max_concurrent", 1)
    cfg.setdefault("ga_strategies", []).insert(0, {
        "id":            gid,
        "archetype":     "AUTO_SEEDED",
        "timeframe":     "M5",
        "score":         src.get("score") or 0,
        "trades":        src.get("trades") or 0,
        "win_rate":      src.get("win_rate") or 0,
        "profit_factor": src.get("profit_factor") or 0,
        "confidence":    "DEPLOY",
        "active_genes":  seeded["active_genes"],
        "sl_atr_mult":   seeded["sl_atr_mult"],
        "tp_atr_mult":   seeded["tp_atr_mult"],
        "start_hour":    seeded["start_hour"],
        "end_hour":      seeded["end_hour"],
        "source":        seeded["source"],
        "created_at":    _now(),
    })
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    _log_seed(symbol, "hof" if src_hof else "config", gid,
              {"genes": len(seeded["active_genes"]), "parent": parent_id})
    return True, (f"new id {gid} from parent {parent_id} "
                  f"({len(seeded['active_genes'])} genes)")


def ensure_all_open_positions_seeded() -> dict:
    """Quick batch: for every currently-traded R-magic symbol, ensure seeded."""
    out = {"checked": 0, "seeded": 0, "already": 0, "details": []}
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): return {"ok": False, "err": "mt5"}
        seen = set()
        for p in (mt5.positions_get(magic=20260605) or []):
            sym = p.symbol
            if sym in seen: continue
            seen.add(sym)
            out["checked"] += 1
            did, why = ensure_seeded(sym)
            if did: out["seeded"] += 1
            else:   out["already"] += 1
            out["details"].append({"symbol": sym, "seeded": did, "reason": why})
    except Exception as e:
        out["err"] = str(e)
    return out


def bootstrap_all_top_symbols(top_n: int = 30) -> dict:
    """Aggressive bootstrap: seed every symbol the scanner ranks in top-N.
    Use this once at startup to populate symbol_configs/ for everything the
    executor might pick. Lineage daemon then evolves each per-symbol."""
    out = {"top_n": top_n, "checked": 0, "seeded": 0, "already": 0, "details": []}
    try:
        import sys
        sys.path.insert(0, r"C:\Users\Radhi\MT5")
        from friday_v3.algory.r_multi_symbol import rank_symbols
        import MetaTrader5 as mt5
        if not mt5.initialize(): return {"ok": False, "err": "mt5"}
        ranking = rank_symbols(max_symbols=top_n)
        for c in (ranking.get("candidates") or [])[:top_n]:
            sym = c.get("symbol")
            if not sym: continue
            out["checked"] += 1
            did, why = ensure_seeded(sym)
            if did: out["seeded"] += 1
            else:   out["already"] += 1
            out["details"].append({"symbol": sym, "quality": c.get("quality"),
                                    "seeded": did, "reason": why})
    except Exception as e:
        out["err"] = str(e)
    return out


if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser(prog="r_native.genome_seeder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("ensure", help="seed one symbol if missing"); p1.add_argument("symbol")
    sub.add_parser("ensure-all-open", help="seed every symbol with an open R position")
    p_boot = sub.add_parser("bootstrap-all", help="seed every symbol in scanner's top-N")
    p_boot.add_argument("--top", type=int, default=30)
    sub.add_parser("show-source", help="show what the seeder would pick as source")
    args = ap.parse_args()
    if args.cmd == "ensure":
        did, why = ensure_seeded(args.symbol)
        print(json.dumps({"symbol": args.symbol, "seeded": did, "reason": why},
                          ensure_ascii=False, indent=2))
    elif args.cmd == "ensure-all-open":
        print(json.dumps(ensure_all_open_positions_seeded(), ensure_ascii=False, indent=2))
    elif args.cmd == "bootstrap-all":
        print(json.dumps(bootstrap_all_top_symbols(args.top), ensure_ascii=False, indent=2))
    elif args.cmd == "show-source":
        h = _best_seed_from_hof(); c = _best_seed_from_configs()
        print(json.dumps({"hof_pick":  h and {"id": h.get("id"), "score": h.get("score"),
                                                "genes": len(h.get("active_genes") or [])},
                          "cfg_pick":  c and {"id": c.get("id"),
                                                "pf": c.get("profit_factor"),
                                                "genes": len(c.get("active_genes") or [])}},
                          ensure_ascii=False, indent=2))
