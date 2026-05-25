"""genome_dedup.py — detect & heal duplicate deployed_genome IDs across symbols.

After a 2026-05-25 regression where a stale-bytecode lineage daemon re-seeded
11 symbols with the same parent ID `6EE942`, this module enforces the
invariant: NO two symbol_configs may share `deployed_genome.id`.

The seeder is the canonical writer; this is the safety net.

Usage:
    python -m r_native.genome_dedup audit         # report only
    python -m r_native.genome_dedup heal          # rewrite collisions
    python -m r_native.genome_dedup heal --dry    # report what heal would do

Called every 15 min by auto_ga_daemon so the system can never accumulate
duplicate genome IDs again.
"""
from __future__ import annotations

import json
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CONFIGS_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
DEDUP_LOG   = Path(r"C:\Users\Radhi\MT5\data\r_native\dedup_log.jsonl")


def _read(p: Path) -> Optional[dict]:
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


def _log(action: str, **kw) -> None:
    try:
        DEDUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DEDUP_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                 "action": action, **kw},
                                ensure_ascii=False) + "\n")
    except Exception: pass


def scan() -> dict:
    """Return {gid: [symbols sharing this id]} for every gid with >1 symbol."""
    by_id: dict = {}
    for p in CONFIGS_DIR.glob("*.json"):
        d = _read(p) or {}
        gid = (d.get("deployed_genome") or {}).get("id")
        if not gid: continue
        by_id.setdefault(gid, []).append(p.stem)
    return {gid: syms for gid, syms in by_id.items() if len(syms) > 1}


def heal(dry_run: bool = False) -> dict:
    """For each duplicated gid: keep the first symbol's id intact, give each
    other symbol a fresh hash ID (parent_id = original)."""
    dups = scan()
    out = {"detected_collisions": len(dups), "rewrites": 0,
           "details": [], "dry_run": dry_run}
    if not dups:
        out["status"] = "clean"
        return out

    for gid, symbols in dups.items():
        # Keep the alphabetically-first symbol's ID stable so the executor's
        # in-memory state for the original owner doesn't drift.
        keeper = sorted(symbols)[0]
        for sym in sorted(symbols):
            if sym == keeper: continue
            cfg_path = CONFIGS_DIR / f"{sym}.json"
            d = _read(cfg_path) or {}
            dg = d.get("deployed_genome") or {}
            old_id = dg.get("id")
            seed_key = f"{sym}|{gid}|{int(time.time() * 1000000)}"
            new_id = hashlib.sha256(seed_key.encode()).hexdigest()[:6].upper()
            # Astronomically unlikely, but guard collision against keeper
            while new_id == gid:
                seed_key += "x"
                new_id = hashlib.sha256(seed_key.encode()).hexdigest()[:6].upper()

            out["details"].append({"symbol": sym, "was": old_id,
                                    "now": new_id, "parent": gid})

            if dry_run: continue

            dg["id"]              = new_id
            dg["parent_id"]       = dg.get("parent_id") or gid
            dg["source"]          = f"dedup_heal_{gid}"
            dg["regenerated_at"]  = datetime.now(timezone.utc).isoformat()
            d["deployed_genome"]  = dg

            # Mirror new id into ga_strategies[0] if it referenced the old id
            for s in (d.get("ga_strategies") or []):
                if s.get("id") == old_id:
                    s["id"] = new_id
                    s["parent_id"] = gid
                    break

            cfg_path.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
            out["rewrites"] += 1
            _log("heal", symbol=sym, old=old_id, new=new_id, parent=gid)

    out["status"] = "healed" if not dry_run else "would_heal"
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="r_native.genome_dedup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit", help="report duplicates without changing anything")
    p_heal = sub.add_parser("heal", help="rewrite duplicates with fresh hash IDs")
    p_heal.add_argument("--dry", action="store_true", help="report only, no write")
    args = ap.parse_args()

    if args.cmd == "audit":
        print(json.dumps(scan(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(heal(dry_run=args.dry), ensure_ascii=False, indent=2))
