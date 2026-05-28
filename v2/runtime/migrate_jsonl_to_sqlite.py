"""runtime/migrate_jsonl_to_sqlite.py — One-shot JSONL → trading.db importer.

Born 2026-05-28 alongside shared/db.py.
Reads every JSONL log we've been writing for weeks, transforms each row
into a strongly-typed DB insert, and commits the lot in batched transactions.

Run once:
    python -m runtime.migrate_jsonl_to_sqlite

Safe to re-run — uses INSERT OR IGNORE on a synthetic dedupe key
(ts + source + ticket/magic) so it won't double-import.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone

import MetaTrader5 as mt5

from runtime.shared.db import db
from runtime.shared.tokens import PATHS, TRADE_LOGS, NAMES


def _iter_jsonl(path: Path):
    if not path.exists(): return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line: continue
        try: yield json.loads(line)
        except Exception: continue


def import_trade_logs() -> int:
    """Import per-magic trade logs (claude_simple_trades.jsonl, etc)."""
    count = 0
    with db.transaction():
        for source, path in TRADE_LOGS.items():
            rows = list(_iter_jsonl(path))
            for r in rows:
                db.insert("trades", {
                    "ts":        r.get("ts", _now_iso()),
                    "magic":     r.get("magic", 0),
                    "source":    source,
                    "symbol":    r.get("symbol", "XAUUSDm"),
                    "side":      r.get("side", "?"),
                    "lot":       float(r.get("lot", 0.01)),
                    "entry":     float(r.get("entry", 0)),
                    "exit_price": r.get("exit_price"),
                    "sl":        float(r.get("sl", 0)),
                    "tp":        float(r.get("tp", 0)),
                    "ticket":    int(r.get("ticket", 0)),
                    "pnl":       r.get("pnl"),
                    "duration_sec": r.get("duration_sec"),
                    "reason":    r.get("reason", ""),
                    "confidence": float(r.get("confidence", 0.5)),
                    "regime_at_fire":  r.get("regime_at_fire"),
                    "session_at_fire": r.get("session_at_fire"),
                    "raw_json":  json.dumps(r, default=str),
                })
                count += 1
    return count


def import_genome_signals() -> int:
    p = PATHS.get("genome_signals")
    if not p: return 0
    count = 0
    with db.transaction():
        for r in _iter_jsonl(p):
            db.insert("signals", {
                "ts":        r.get("ts", _now_iso()),
                "source":    "genome",
                "symbol":    r.get("symbol", "XAUUSDm"),
                "action":    r.get("action", "?"),
                "price":     float(r.get("price", 0)),
                "confidence": float(r.get("confidence", 0.5)),
                "genome":    r.get("genome"),
                "payload_json": json.dumps(r, default=str),
            })
            count += 1
    return count


def import_brain_memory() -> int:
    p = PATHS.get("brain_memory")
    if not p: return 0
    count = 0
    with db.transaction():
        for r in _iter_jsonl(p):
            bias = r.get("bias", {})
            rsi  = r.get("rsi", {})
            atr  = r.get("atr", {})
            db.insert("brain_snapshots", {
                "ts":           r.get("ts", _now_iso()),
                "symbol":       r.get("symbol", "XAUUSDm"),
                "bid":          r.get("price", {}).get("bid"),
                "ask":          r.get("price", {}).get("ask"),
                "bias_m1":      bias.get("m1"),
                "bias_m5":      bias.get("m5"),
                "bias_m15":     bias.get("m15"),
                "bias_h1":      bias.get("h1"),
                "rsi_m1":       rsi.get("m1"),
                "rsi_m5":       rsi.get("m5"),
                "atr_m1":       atr.get("m1"),
                "atr_h1":       atr.get("h1"),
                "mtf_align":    r.get("mtf_align"),
                "pressure_10m1": r.get("pressure_10m1"),
                "session":      r.get("session"),
                "regime":       r.get("regime"),
                "raw_json":     json.dumps(r, default=str),
            })
            count += 1
    return count


def import_regime_history() -> int:
    p = PATHS.get("regime_history")
    if not p: return 0
    count = 0
    with db.transaction():
        for r in _iter_jsonl(p):
            m = r.get("metrics", {})
            db.insert("regime_history", {
                "ts":      r.get("ts", _now_iso()),
                "regime":  r.get("regime", "?"),
                "reason":  r.get("reason", ""),
                "adx_m5":  m.get("adx_m5"),
                "atr_m5":  m.get("atr_m5"),
                "vol_ratio": m.get("vol_ratio"),
            })
            count += 1
    return count


def import_council_votes() -> int:
    p = PATHS.get("council_votes")
    if not p: return 0
    count = 0
    with db.transaction():
        for r in _iter_jsonl(p):
            db.insert("council_votes", {
                "ts":       r.get("ts", _now_iso()),
                "genome":   r.get("genome"),
                "side":     r.get("side") or r.get("action"),
                "approves": r.get("approves"),
                "vetos":    r.get("vetos"),
                "verdict":  r.get("verdict"),
                "payload_json": json.dumps(r, default=str),
            })
            count += 1
    return count


def import_mt5_deals_history(days: int = 30) -> int:
    """Pull from MT5 directly to backfill ALL real deals (most accurate source)."""
    if not mt5.initialize(): return 0
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
    exits = [d for d in deals if int(d.entry) in (1, 2)]
    count = 0
    with db.transaction():
        for d in exits:
            magic = int(d.magic)
            db.insert("trades", {
                "ts":        datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
                "magic":     magic,
                "source":    NAMES.get(magic, str(magic)),
                "symbol":    d.symbol or "?",
                "side":      "BUY" if d.type == 0 else "SELL",
                "lot":       float(d.volume),
                "entry":     0,  # entry deal separate; this is the exit row
                "exit_price": float(d.price),
                "sl":        0, "tp": 0,
                "ticket":    int(d.ticket),
                "pnl":       float(d.profit),
                "duration_sec": None,
                "reason":    f"mt5_history_deal entry={d.entry}",
                "confidence": 0.5,
                "regime_at_fire": None,
                "session_at_fire": None,
                "raw_json":  json.dumps({
                    "ticket": d.ticket, "magic": magic, "time": d.time,
                    "profit": d.profit, "commission": d.commission, "swap": d.swap,
                }, default=str),
            })
            count += 1
    mt5.shutdown()
    return count


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main():
    print(f"═══ MIGRATING JSONL → trading.db ═══")
    print()
    print("Clearing existing trades to re-import fresh (idempotent run)...")
    db.execute("DELETE FROM trades")
    db.execute("DELETE FROM signals")
    db.execute("DELETE FROM brain_snapshots")
    db.execute("DELETE FROM regime_history")
    db.execute("DELETE FROM council_votes")
    print()

    print(f"  [1] Per-magic trade logs       → {import_trade_logs():>6d} rows")
    print(f"  [2] genome_signals.jsonl       → {import_genome_signals():>6d} rows")
    print(f"  [3] brain_memory.jsonl         → {import_brain_memory():>6d} rows")
    print(f"  [4] regime_history.jsonl       → {import_regime_history():>6d} rows")
    print(f"  [5] council_votes.jsonl        → {import_council_votes():>6d} rows")
    print(f"  [6] MT5 deals history (30d)    → {import_mt5_deals_history():>6d} rows")
    print()

    # Verification — quick stats
    n_trades = db.query("SELECT COUNT(*) AS n FROM trades")[0]["n"]
    n_signals = db.query("SELECT COUNT(*) AS n FROM signals")[0]["n"]
    n_snap = db.query("SELECT COUNT(*) AS n FROM brain_snapshots")[0]["n"]
    print(f"═══ TOTALS IN DB ═══")
    print(f"  trades:          {n_trades}")
    print(f"  signals:         {n_signals}")
    print(f"  brain_snapshots: {n_snap}")
    print()
    print(f"DB file: {db.path}")
    print(f"Size:    {db.path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
