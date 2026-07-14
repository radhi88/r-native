"""
algory_watcher.py — READ-ONLY watcher for Algory.exe genetic factory.

Mission:
  • Monitor Algory.exe processes (PIDs change between runs)
  • Snapshot Algory's vault index, diagnostics, gene_fitness
  • Compute live gene rankings (which indicators actually pass OOS)
  • Surface insights to /api/algory in brain_server
  • Mirror the vault into friday_v3/data/algory_mirror/ for our use

Critical: NEVER write to Algory's files. Pure read-only learning.

Algory paths:
  C:\\Users\\Radhi\\AppData\\Local\\Algory\\
    Algory.exe + Engine.exe
    gene_fitness_v2.json
    factory_config.json
    dashboard_settings.json
    Generated_Strategies/
      _vault_index.json
      <campaign_id>/*.json
"""
from __future__ import annotations
import json
import shutil
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil

ALGORY_HOME    = Path(r"C:\Users\Radhi\AppData\Local\Algory")
ALGORY_VAULT   = ALGORY_HOME / "Generated_Strategies"
ALGORY_FITNESS = ALGORY_HOME / "gene_fitness_v2.json"
ALGORY_CONFIG  = ALGORY_HOME / "dashboard_settings.json"
ALGORY_BOOT    = ALGORY_HOME / "_debug_boot.txt"

FRIDAY_ROOT    = Path(r"C:\Users\Radhi\MT5\friday_v3")
MIRROR_DIR     = FRIDAY_ROOT / "data" / "algory_mirror"
REPORT_FILE    = FRIDAY_ROOT / "data" / "algory_report.json"


# ─── Gene whitelist / blacklist derived from Algory's own history ───
# These are the rules WE inherit; updated each scan.
def derive_gene_rankings(fitness: dict) -> dict:
    """Score each gene by mid_oos_pass rate across all symbols."""
    out = {}
    glb = fitness.get("_global", {}).get("genes", {})
    for gene, stats in glb.items():
        p = stats.get("mid_oos_pass", 0)
        f = stats.get("mid_oos_fail", 0)
        total = p + f
        rate = (p / total * 100) if total > 0 else 0
        appearances = stats.get("appearances", 0)
        out[gene] = {
            "pass":        p,
            "fail":        f,
            "appearances": appearances,
            "pass_rate":   round(rate, 1),
            "verdict":     "TRUSTED" if rate >= 50 and total >= 5 else
                           "AVOID"   if rate <  10 and total >= 5 else
                           "NEUTRAL",
        }
    return dict(sorted(out.items(), key=lambda x: -x[1]["pass_rate"]))


def derive_symbol_specific(fitness: dict, symbol: str = "XAUUSDm",
                           tf: str = "H1") -> dict:
    """Same but for a specific symbol/timeframe."""
    block = fitness.get(symbol, {}).get(tf, {}).get("genes", {})
    out = {}
    for gene, stats in block.items():
        p = stats.get("mid_oos_pass", 0)
        f = stats.get("mid_oos_fail", 0)
        total = p + f
        rate = (p / total * 100) if total > 0 else 0
        out[gene] = {
            "pass":  p, "fail":  f, "total": total,
            "pass_rate": round(rate, 1),
            "verdict": "TRUSTED" if rate >= 50 and total >= 3 else
                       "AVOID"   if rate <  10 and total >= 3 else
                       "NEUTRAL",
        }
    return dict(sorted(out.items(), key=lambda x: -x[1]["pass_rate"]))


def find_algory_processes() -> list[dict]:
    """Return list of running Algory.exe + Engine.exe processes.

    Strict match: process must live under the Algory install dir.
    """
    procs = []
    for p in psutil.process_iter(["pid", "name", "create_time", "memory_info",
                                   "num_threads", "exe"]):
        try:
            n = (p.info["name"] or "").lower()
            exe = (p.info.get("exe") or "").replace("\\", "/").lower()
            if n in ("algory.exe", "engine.exe") and "/algory/" in exe:
                procs.append({
                    "pid":     p.info["pid"],
                    "name":    p.info["name"],
                    "exe":     p.info.get("exe", ""),
                    "started": datetime.fromtimestamp(p.info["create_time"]).isoformat(),
                    "mem_mb":  round((p.info["memory_info"].rss or 0) / 1024 / 1024, 1) if p.info.get("memory_info") else 0,
                    "threads": p.info.get("num_threads", 0),
                })
        except Exception:
            continue
    return procs


def load_vault_index() -> dict:
    p = ALGORY_VAULT / "_vault_index.json"
    if not p.exists():
        return {"disk_count": 0, "entries": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": str(e)}


def summarise_vault(vault: dict) -> dict:
    """Aggregate vault stats by symbol/TF/archetype."""
    entries = vault.get("entries", {})
    if isinstance(entries, dict):
        items = list(entries.values())
    elif isinstance(entries, list):
        items = entries
    else:
        items = []

    by_symbol = {}
    by_arch   = {}
    top_strats = []
    for e in items:
        data = e.get("data", {}) if isinstance(e, dict) else {}
        sym = data.get("symbol", "?"); tf = data.get("timeframe", "?")
        arch = data.get("archetype", "?")
        stats = data.get("stats", {}) or {}
        ret = stats.get("return_pct", 0)
        dd  = stats.get("drawdown_pct", 0)
        wr  = stats.get("win_rate", 0)
        tr  = stats.get("trades", 0)
        pf  = stats.get("profit_factor", 0)

        key = f"{sym}_{tf}"
        b = by_symbol.setdefault(key, {"count": 0, "avg_return": 0,
                                      "avg_dd": 0, "avg_wr": 0,
                                      "best_return": 0, "best_id": None})
        b["count"] += 1
        b["avg_return"] += ret; b["avg_dd"] += dd; b["avg_wr"] += wr
        if ret > b["best_return"]:
            b["best_return"] = ret
            b["best_id"] = data.get("id", "?")

        a = by_arch.setdefault(arch, {"count": 0, "avg_return": 0, "avg_dd": 0})
        a["count"] += 1; a["avg_return"] += ret; a["avg_dd"] += dd

        top_strats.append({
            "id": data.get("id"), "symbol": sym, "timeframe": tf,
            "return_pct": ret, "drawdown_pct": dd, "win_rate": wr,
            "trades": tr, "profit_factor": pf,
            "archetype": arch,
            "win_mechanism": data.get("win_mechanism"),
            "symbol_quality": data.get("symbol_quality"),
        })

    # Averages
    for b in by_symbol.values():
        n = b["count"] or 1
        b["avg_return"] = round(b["avg_return"]/n, 1)
        b["avg_dd"]     = round(b["avg_dd"]/n, 1)
        b["avg_wr"]     = round(b["avg_wr"]/n, 1)
    for a in by_arch.values():
        n = a["count"] or 1
        a["avg_return"] = round(a["avg_return"]/n, 1)
        a["avg_dd"]     = round(a["avg_dd"]/n, 1)

    top_strats.sort(key=lambda x: -(x.get("return_pct") or 0))
    return {
        "total_strategies": len(items),
        "by_symbol":         by_symbol,
        "by_archetype":      by_arch,
        "top_10":            top_strats[:10],
    }


def detect_current_campaign() -> Optional[dict]:
    """Detect if Algory is currently running a campaign."""
    if not ALGORY_VAULT.exists():
        return None
    # Look for any campaign folder modified in last 5 minutes
    cutoff = time.time() - 300
    active = []
    for sub in ALGORY_VAULT.iterdir():
        if not sub.is_dir(): continue
        try:
            mtime = sub.stat().st_mtime
            if mtime > cutoff:
                diag = sub / "diagnostics.json"
                d = None
                if diag.exists():
                    try: d = json.loads(diag.read_text(encoding="utf-8"))
                    except Exception: pass
                active.append({
                    "campaign": sub.name,
                    "mtime":    datetime.fromtimestamp(mtime).isoformat(),
                    "diag":     d,
                })
        except Exception:
            continue
    return active[0] if active else None


def build_report() -> dict:
    """One-shot snapshot of everything we can learn from Algory right now."""
    fitness = {}
    if ALGORY_FITNESS.exists():
        try:    fitness = json.loads(ALGORY_FITNESS.read_text(encoding="utf-8"))
        except Exception: pass
    config = {}
    if ALGORY_CONFIG.exists():
        try:    config = json.loads(ALGORY_CONFIG.read_text(encoding="utf-8"))
        except Exception: pass

    vault = load_vault_index()
    vsum  = summarise_vault(vault)
    procs = find_algory_processes()
    camp  = detect_current_campaign()
    glb_genes = derive_gene_rankings(fitness)
    xau_h1_genes = derive_symbol_specific(fitness, "XAUUSDm", "H1")

    # Derived recommendations FOR FRIDAY
    whitelist = [g for g, s in glb_genes.items() if s["verdict"] == "TRUSTED"]
    blacklist = [g for g, s in glb_genes.items() if s["verdict"] == "AVOID"]
    xau_white = [g for g, s in xau_h1_genes.items() if s["verdict"] == "TRUSTED"]
    xau_black = [g for g, s in xau_h1_genes.items() if s["verdict"] == "AVOID"]

    return {
        "ts":               datetime.now(timezone.utc).isoformat(),
        "algory_running":   len(procs) > 0,
        "processes":        procs,
        "current_campaign": camp,
        "vault_summary":    vsum,
        "gene_rankings_global":  glb_genes,
        "gene_rankings_xauh1":   xau_h1_genes,
        "friday_recommendations": {
            "global_whitelist": whitelist,
            "global_blacklist": blacklist,
            "xau_h1_whitelist": xau_white,
            "xau_h1_blacklist": xau_black,
        },
        "active_symbols":   [k for k, v in (config.get("assets") or {}).items() if v],
        "active_tfs":       [k for k, v in (config.get("tfs") or {}).items() if v],
        "algory_inputs":    config.get("inputs", {}),
        "purge_criteria":   config.get("purge", {}),
        "prop_firm_rules":  config.get("prop_firm", {}),
    }


def mirror_vault_index() -> int:
    """Copy vault index into our mirror dir for offline analysis."""
    MIRROR_DIR.mkdir(parents=True, exist_ok=True)
    src = ALGORY_VAULT / "_vault_index.json"
    if not src.exists(): return 0
    dst = MIRROR_DIR / f"vault_{datetime.now():%Y%m%d_%H%M%S}.json"
    try:
        shutil.copy2(src, dst)
        # Keep latest as well
        shutil.copy2(src, MIRROR_DIR / "vault_latest.json")
        return src.stat().st_size
    except Exception:
        return 0


def watch_loop(interval: int = 30):
    print(f"=== Algory Watcher — interval {interval}s ===")
    print(f"Monitoring: {ALGORY_HOME}")
    print(f"Mirror to:  {MIRROR_DIR}")
    print()
    # Import learning memory lazily
    try:
        from friday_v3.algory.learning_memory import absorb_snapshot
        learn_ok = True
    except Exception as e:
        print(f"  [warn] learning_memory unavailable: {e}")
        learn_ok = False

    while True:
        try:
            r = build_report()
            REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
            REPORT_FILE.write_text(json.dumps(r, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
            size = mirror_vault_index()

            iq_str = ""
            if learn_ok:
                try:
                    delta = absorb_snapshot(r)
                    iq = delta.get("iq", {})
                    iq_str = (f"  R-IQ={iq.get('raw',0):.0f} ({iq.get('level','?')})"
                              + (f" +{delta['new_strategies']}new" if delta['new_strategies'] else "")
                              + (f" Δgenes={delta['gene_changes']}" if delta['gene_changes'] else ""))
                except Exception as e:
                    iq_str = f"  [mem err: {e}]"

            procs = r["processes"]; vault = r["vault_summary"]
            camp = r["current_campaign"]
            print(f"[{datetime.now():%H:%M:%S}] "
                  f"algory={'●' if r['algory_running'] else '○'} "
                  f"procs={len(procs)} "
                  f"vault={vault['total_strategies']} strats "
                  f"campaign={camp['campaign'] if camp else 'idle'}"
                  f"{iq_str}")
        except KeyboardInterrupt:
            print("stopped."); break
        except Exception as e:
            print(f"  [error] {e}")
        time.sleep(interval)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="snapshot once and exit")
    ap.add_argument("--interval", type=int, default=30, help="loop interval seconds")
    args = ap.parse_args()
    if args.once:
        r = build_report()
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(json.dumps(r, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        mirror_vault_index()
        print(json.dumps({
            "algory_running": r["algory_running"],
            "processes": [p["pid"] for p in r["processes"]],
            "vault_count": r["vault_summary"]["total_strategies"],
            "current_campaign": (r["current_campaign"] or {}).get("campaign"),
            "global_whitelist": r["friday_recommendations"]["global_whitelist"],
            "global_blacklist_count": len(r["friday_recommendations"]["global_blacklist"]),
            "xau_whitelist":  r["friday_recommendations"]["xau_h1_whitelist"],
            "xau_blacklist":  r["friday_recommendations"]["xau_h1_blacklist"],
        }, ensure_ascii=False, indent=2))
    else:
        watch_loop(args.interval)
