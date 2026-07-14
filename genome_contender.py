"""genome_contender.py — Shadow-validates new genomes before they go live.

Flow:
  1) Read lineage_log.jsonl for recently-bred children (last hour)
  2) Pick the top scorers that beat their parent's score by ≥ 5%
  3) For each, re-simulate on the LATEST N bars (paper validation)
  4) If the live-bars test confirms PF ≥ 1.5 and WR ≥ 60%, promote to
     "contender" status in data/r_native/contenders.json
  5) UI displays contenders alongside champions; user can accept/reject

Run as daemon every 5 minutes:
  python -m r_native.genome_contender daemon --interval-min 5

Or one-shot:
  python -m r_native.genome_contender run-once
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

LINEAGE_LOG     = Path(r"C:\Users\Radhi\MT5\data\r_native\lineage_log.jsonl")
CONTENDERS      = Path(r"C:\Users\Radhi\MT5\data\r_native\contenders.json")
CFG_DIR         = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")

# Validation thresholds — child must beat these on LIVE bars (not the bars
# used to evolve it) to earn contender status.
VALIDATE_N_BARS = 2000
VALIDATE_MIN_PF = 1.5
VALIDATE_MIN_WR = 60
VALIDATE_MIN_TRADES = 10
VS_PARENT_IMPROVEMENT = 1.05    # must beat parent PF by ≥ 5%


def _load(p: Path, default):
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return default


def _save(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _recent_breed_events(hours: int = 6) -> list[dict]:
    """Parse the last N hours of round_complete + DEPLOYED entries from lineage."""
    if not LINEAGE_LOG.exists(): return []
    cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
    out = []
    for line in LINEAGE_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: ev = json.loads(line)
        except Exception: continue
        try:
            ts = datetime.fromisoformat(ev["ts"].replace("Z", "+00:00")).timestamp()
        except Exception: continue
        if ts < cutoff: continue
        out.append(ev)
    return out


def _validate(child_id: str, symbol: str, all_params: dict,
              active_genes: list) -> dict:
    """Re-simulate one child on LATEST bars and return stats."""
    try:
        import MetaTrader5 as mt5
        from r_native.genome_breeder import build_genome, simulate_on
        if not mt5.initialize(): return {"ok": False, "err": "mt5"}
        genome = build_genome(active_genes, all_params)
        res = simulate_on(genome, symbol, "M5", n_bars=VALIDATE_N_BARS)
        if not res.get("ok"): return {"ok": False, "err": res.get("error", "?")}
        return {"ok": True, "stats": res["stats"]}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def _qualifies(stats: dict, parent_pf: float) -> tuple[bool, str]:
    if stats.get("trades", 0) < VALIDATE_MIN_TRADES:
        return False, f"trades {stats.get('trades',0)} < {VALIDATE_MIN_TRADES}"
    pf = float(stats.get("profit_factor", 0))
    wr = float(stats.get("win_rate", 0))
    if pf < VALIDATE_MIN_PF: return False, f"PF {pf} < {VALIDATE_MIN_PF}"
    if wr < VALIDATE_MIN_WR: return False, f"WR {wr} < {VALIDATE_MIN_WR}"
    if parent_pf and pf < parent_pf * VS_PARENT_IMPROVEMENT:
        return False, f"PF {pf} < parent×{VS_PARENT_IMPROVEMENT} ({parent_pf*VS_PARENT_IMPROVEMENT:.2f})"
    return True, f"PF {pf}  WR {wr}%  trades {stats.get('trades')}"


def run_once() -> dict:
    """One sweep. Returns the new contenders list."""
    contenders = _load(CONTENDERS, []) or []
    existing_ids = {c["child_id"] for c in contenders}
    events = _recent_breed_events(hours=6)
    out = {"checked": 0, "promoted": 0, "rejected": 0, "details": []}

    for ev in events:
        if ev.get("event") != "round_complete": continue
        symbol = ev.get("symbol")
        cid    = ev.get("top_child_id")
        if not symbol or not cid or cid in existing_ids: continue
        out["checked"] += 1

        # Pull current deployed_genome for parent_pf reference
        cfg = _load(CFG_DIR / f"{symbol}.json", {}) or {}
        parent_pf = float((cfg.get("deployed_genome") or {}).get("profit_factor") or 0)

        # Find the child's params + genes in the recent ga_strategies entries
        # (lineage breeder writes survivors via hof.admit, but for the top child
        # only the round_complete event has summary — re-derive from cfg if there)
        target = None
        for s in (cfg.get("ga_strategies") or []):
            if s.get("id") == cid:
                target = s; break
        if not target:
            out["rejected"] += 1
            out["details"].append({"child_id": cid, "symbol": symbol,
                                    "reason": "child not in ga_strategies"})
            continue

        params = {
            "sl_atr_mult":  target.get("sl_atr_mult", 2.0),
            "tp_atr_mult":  target.get("tp_atr_mult", 4.0),
            "start_hour":   target.get("start_hour",  0),
            "end_hour":     target.get("end_hour",   23),
        }
        v = _validate(cid, symbol, params, target.get("active_genes") or [])
        if not v.get("ok"):
            out["rejected"] += 1
            out["details"].append({"child_id": cid, "symbol": symbol,
                                    "reason": v.get("err", "validate fail")})
            continue
        ok, why = _qualifies(v["stats"], parent_pf)
        if not ok:
            out["rejected"] += 1
            out["details"].append({"child_id": cid, "symbol": symbol,
                                    "reason": why})
            continue

        # Promote
        contenders.append({
            "child_id":   cid,
            "symbol":     symbol,
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "parent_pf":  parent_pf,
            "stats":      v["stats"],
            "genes":      target.get("active_genes") or [],
            "params":     params,
            "status":     "PENDING",   # PENDING | ACCEPTED | REJECTED
            "reason":     why,
        })
        out["promoted"] += 1
        out["details"].append({"child_id": cid, "symbol": symbol,
                                "reason": "PROMOTED — " + why})

    # Keep most-recent 50 contenders only
    contenders.sort(key=lambda c: c["promoted_at"], reverse=True)
    contenders = contenders[:50]
    _save(CONTENDERS, contenders)
    out["total_contenders"] = len(contenders)
    return out


def accept(child_id: str) -> dict:
    """Promote a contender to the symbol's deployed_genome."""
    contenders = _load(CONTENDERS, []) or []
    target = next((c for c in contenders if c["child_id"] == child_id), None)
    if not target: return {"ok": False, "err": "contender not found"}
    sym = target["symbol"]
    cfg = _load(CFG_DIR / f"{sym}.json", {}) or {}
    cfg["deployed_genome"] = {
        "id":            target["child_id"],
        "profit_factor": target["stats"].get("profit_factor"),
        "win_rate":      target["stats"].get("win_rate"),
        "trades":        target["stats"].get("trades"),
        "sl_atr_mult":   target["params"]["sl_atr_mult"],
        "tp_atr_mult":   target["params"]["tp_atr_mult"],
        "start_hour":    target["params"]["start_hour"],
        "end_hour":      target["params"]["end_hour"],
        "active_genes":  target["genes"],
        "source":        f"contender_accepted",
        "deployed_at":   datetime.now(timezone.utc).isoformat(),
    }
    _save(CFG_DIR / f"{sym}.json", cfg)
    target["status"] = "ACCEPTED"
    _save(CONTENDERS, contenders)
    return {"ok": True, "symbol": sym, "new_deployed": target["child_id"]}


def reject(child_id: str) -> dict:
    contenders = _load(CONTENDERS, []) or []
    target = next((c for c in contenders if c["child_id"] == child_id), None)
    if not target: return {"ok": False, "err": "not found"}
    target["status"] = "REJECTED"
    _save(CONTENDERS, contenders)
    return {"ok": True}


def list_contenders() -> dict:
    return {"ok": True, "contenders": _load(CONTENDERS, []) or []}


def _cli():
    ap = argparse.ArgumentParser(prog="r_native.genome_contender")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run-once")
    sub.add_parser("list")
    p_acc = sub.add_parser("accept"); p_acc.add_argument("child_id")
    p_rej = sub.add_parser("reject"); p_rej.add_argument("child_id")
    p_dmn = sub.add_parser("daemon"); p_dmn.add_argument("--interval-min", type=int, default=5)
    args = ap.parse_args()
    if args.cmd == "run-once":
        print(json.dumps(run_once(), ensure_ascii=False, indent=2))
    elif args.cmd == "list":
        print(json.dumps(list_contenders(), ensure_ascii=False, indent=2))
    elif args.cmd == "accept":
        print(json.dumps(accept(args.child_id), ensure_ascii=False, indent=2))
    elif args.cmd == "reject":
        print(json.dumps(reject(args.child_id), ensure_ascii=False, indent=2))
    elif args.cmd == "daemon":
        print(f"[contender] daemon — every {args.interval_min} min", flush=True)
        while True:
            try:
                r = run_once()
                print(f"[{datetime.now(timezone.utc):%H:%M:%S}] "
                      f"checked={r.get('checked')} "
                      f"promoted={r.get('promoted')} "
                      f"rejected={r.get('rejected')} "
                      f"total={r.get('total_contenders')}", flush=True)
            except Exception as e:
                print(f"[contender] err: {e}", flush=True)
            time.sleep(args.interval_min * 60)


if __name__ == "__main__":
    _cli()
