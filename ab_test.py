"""ab_test.py — J.13 — Champion vs Challenger comparison framework.

Run two genomes side-by-side on different symbols (or the same symbol on
different accounts). Track live performance. Auto-promote the winner after
N trades or M days.

Pattern: "champion" = currently deployed genome.
         "challenger" = candidate to replace it.

Usage:
  python -m r_native.ab_test start CHAMP_ID CHALL_ID BTCUSDm
  python -m r_native.ab_test status
  python -m r_native.ab_test resolve   # auto-pick winner
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\ab_test.json")
JOURNAL     = Path(r"C:\Users\Radhi\MT5\data\r_native\ab_test_log.jsonl")


def start_test(champion_id: str, challenger_id: str, symbol: str,
               max_trades: int = 30, max_days: int = 14) -> dict:
    """Begin an A/B test. Challenger runs in PAPER on virtual P/L."""
    cfg = {
        "active":          True,
        "symbol":          symbol,
        "champion_id":     champion_id,
        "challenger_id":   challenger_id,
        "started_at":      datetime.now(timezone.utc).isoformat(),
        "max_trades":      max_trades,
        "max_days":        max_days,
        "champion_trades":   [],
        "challenger_trades": [],
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return cfg


def load() -> dict | None:
    if not CONFIG_PATH.exists(): return None
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def record_trade(role: str, pl: float, symbol: str = None) -> None:
    """Record a closed trade for the active A/B test.
    role: 'champion' or 'challenger'"""
    cfg = load()
    if not cfg or not cfg.get("active"): return
    if symbol and cfg.get("symbol") != symbol: return
    key = f"{role}_trades"
    cfg[key].append({
        "pl": round(float(pl), 4),
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    # Append to journal
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "role": role, "symbol": symbol, "pl": pl,
        }) + "\n")


def status() -> dict:
    """Return current A/B test status with cumulative stats."""
    cfg = load()
    if not cfg: return {"active": False}

    def stats(trades):
        if not trades: return {"n": 0, "wins": 0, "wr": 0, "total": 0, "avg": 0}
        n     = len(trades)
        pls   = [t["pl"] for t in trades]
        wins  = sum(1 for p in pls if p > 0)
        total = sum(pls)
        return {"n": n, "wins": wins,
                "wr": round(wins / n * 100, 1) if n else 0,
                "total": round(total, 2),
                "avg":   round(total / n, 4) if n else 0}

    champ = stats(cfg.get("champion_trades", []))
    chall = stats(cfg.get("challenger_trades", []))

    # Determine winner
    winner = None
    if champ["n"] >= 5 and chall["n"] >= 5:
        if chall["total"] > champ["total"] * 1.2:    winner = "challenger"
        elif champ["total"] > chall["total"] * 1.2:  winner = "champion"

    started = datetime.fromisoformat(cfg["started_at"])
    days_elapsed = (datetime.now(timezone.utc) - started).days
    return {
        "active":         cfg["active"],
        "symbol":         cfg["symbol"],
        "champion":       {"id": cfg["champion_id"], **champ},
        "challenger":     {"id": cfg["challenger_id"], **chall},
        "winner":         winner,
        "days_elapsed":   days_elapsed,
        "max_days":       cfg["max_days"],
        "trades_to_go":   max(0, cfg["max_trades"] - max(champ["n"], chall["n"])),
    }


def resolve() -> dict:
    """Conclude the A/B test. If winner is challenger, swap deployment."""
    st = status()
    if not st["active"]: return {"ok": False, "reason": "no active test"}
    winner = st["winner"]
    if not winner:
        return {"ok": False, "reason": "no clear winner yet"}

    cfg = load()
    cfg["active"] = False
    cfg["winner"] = winner
    cfg["resolved_at"] = datetime.now(timezone.utc).isoformat()
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    promoted = None
    if winner == "challenger":
        try:
            from r_native.actions import deploy_genome_to_live
            r = deploy_genome_to_live(cfg["symbol"], cfg["challenger_id"], "M5")
            promoted = r.get("ok")
        except Exception as e:
            print(f"[ab_test] promotion err: {e}")

    return {"ok": True, "winner": winner, "promoted": promoted,
            "stats": st}


def _cli():
    p = argparse.ArgumentParser(prog="r_native.ab_test")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("start"); ps.add_argument("champion"); ps.add_argument("challenger"); ps.add_argument("symbol")
    sub.add_parser("status")
    sub.add_parser("resolve")
    args = p.parse_args()
    if args.cmd == "start":
        print(json.dumps(start_test(args.champion, args.challenger, args.symbol), indent=2))
    elif args.cmd == "status":
        print(json.dumps(status(), indent=2))
    elif args.cmd == "resolve":
        print(json.dumps(resolve(), indent=2))


if __name__ == "__main__":
    _cli()
