"""runtime/decision_log_query.py — Query the unified decision log.

Born 2026-05-28. The "give me back what every engine decided + how it turned out"
tool. Built on top of trading.db.entry_decisions.

EXAMPLES
    python -m runtime.decision_log_query                       # last 50, all engines
    python -m runtime.decision_log_query --side BUY            # only BUYs
    python -m runtime.decision_log_query --side SELL --win     # winning SELLs
    python -m runtime.decision_log_query --source claude_genome
    python -m runtime.decision_log_query --regime TREND_DOWN
    python -m runtime.decision_log_query --rank                # per-source scoreboard
    python -m runtime.decision_log_query --rank --side BUY     # who's best at BUYs?
"""
from __future__ import annotations
import argparse
from runtime.shared.db import db


def cmd_rank(args):
    """Per-source ranking with optional filters."""
    where = ["pnl IS NOT NULL"]
    params: list = []
    if args.side:
        where.append("side = ?"); params.append(args.side)
    if args.regime:
        where.append("regime = ?"); params.append(args.regime)
    sql = f"""
        SELECT source,
               COUNT(*) AS trades,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
               ROUND(SUM(pnl), 2) AS total_pnl,
               ROUND(AVG(pnl), 2) AS avg_pnl,
               ROUND(MAX(pnl), 2) AS best_win,
               ROUND(MIN(pnl), 2) AS worst_loss
        FROM entry_decisions
        WHERE {' AND '.join(where)}
        GROUP BY source
        ORDER BY total_pnl DESC
    """
    rows = db.query(sql, tuple(params))
    if not rows:
        print("  (no decisions match filters)"); return
    label = ""
    if args.side:   label += f" side={args.side}"
    if args.regime: label += f" regime={args.regime}"
    print(f"═══ DECISION LEADERBOARD{label} ═══")
    print(f"  {'Engine':18s} {'Trades':>7s} {'WR%':>5s} {'PnL':>9s} {'Avg':>7s} {'Best':>7s} {'Worst':>7s}")
    print(f"  {'─'*60}")
    for r in rows:
        wr = (r["wins"] / r["trades"] * 100) if r["trades"] else 0
        print(f"  {r['source']:18s} {r['trades']:>7d} {wr:>4.0f}  "
              f"${r['total_pnl']:>+7.2f}  ${r['avg_pnl']:>+5.2f}  "
              f"${r['best_win']:>+5.2f}  ${r['worst_loss']:>+5.2f}")


def cmd_list(args):
    where = ["1=1"]
    params: list = []
    if args.side:
        where.append("side = ?"); params.append(args.side)
    if args.source:
        where.append("source = ?"); params.append(args.source)
    if args.regime:
        where.append("regime = ?"); params.append(args.regime)
    if args.win:
        where.append("pnl > 0")
    if args.loss:
        where.append("pnl < 0")
    sql = f"""
        SELECT ts, source, side, entry, sl, tp, ticket, pnl, regime, session,
               rsi_m1, pressure_10m1, mtf_align, reason
        FROM entry_decisions
        WHERE {' AND '.join(where)}
        ORDER BY ts DESC
        LIMIT {args.limit}
    """
    rows = db.query(sql, tuple(params))
    if not rows:
        print("  (no matching decisions)"); return
    print(f"═══ LAST {len(rows)} DECISIONS ═══")
    print(f"  {'time':19s} {'engine':14s} {'side':5s} {'entry':>8s} "
          f"{'PnL':>7s} {'regime':10s} {'rsi':>5s} {'reason':30s}")
    print(f"  {'─'*100}")
    for r in rows:
        ts = (r["ts"] or "")[:19]
        pnl = r["pnl"]
        pnl_disp = f"${pnl:+.2f}" if pnl is not None else "  open"
        reason = (r["reason"] or "")[:30]
        regime = (r["regime"] or "?")[:10]
        side = r["side"]
        side_disp = "🟢"+side if pnl is not None and pnl > 0 else "🔴"+side if pnl is not None and pnl < 0 else " "+side
        rsi = r["rsi_m1"] or 0
        entry = r["entry"] or 0
        print(f"  {ts:19s} {r['source']:14s} {side_disp:5s} {entry:>8.2f}  "
              f"{pnl_disp:>7s}  {regime:10s} {rsi:>5.1f}  {reason}")


def cmd_summary(args):
    """High-level: total decisions, win rate, by side."""
    total = db.query("SELECT COUNT(*) AS n FROM entry_decisions")[0]["n"]
    with_pnl = db.query("SELECT COUNT(*) AS n FROM entry_decisions WHERE pnl IS NOT NULL")[0]["n"]
    wins = db.query("SELECT COUNT(*) AS n FROM entry_decisions WHERE pnl > 0")[0]["n"]
    losses = db.query("SELECT COUNT(*) AS n FROM entry_decisions WHERE pnl < 0")[0]["n"]
    open_n = total - with_pnl
    print(f"═══ DECISION LOG SUMMARY ═══")
    print(f"  Total decisions recorded: {total}")
    print(f"  Still open:               {open_n}")
    print(f"  Closed wins:              {wins}")
    print(f"  Closed losses:            {losses}")
    if with_pnl:
        wr = wins / with_pnl * 100
        pnl = db.query("SELECT ROUND(SUM(pnl),2) AS p FROM entry_decisions WHERE pnl IS NOT NULL")[0]["p"]
        print(f"  WR:                       {wr:.1f}%")
        print(f"  Net PnL:                  ${pnl:+.2f}")
    print()
    print("  By side:")
    for r in db.query("""
        SELECT side, COUNT(*) AS n,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS w,
               ROUND(SUM(pnl), 2) AS pnl
        FROM entry_decisions WHERE pnl IS NOT NULL GROUP BY side
    """):
        wr = r["w"] / r["n"] * 100 if r["n"] else 0
        print(f"    {r['side']:5s}  {r['n']:>4d}T  WR {wr:>4.0f}%  PnL ${r['pnl']:>+7.2f}")
    print()
    print("  By regime:")
    for r in db.query("""
        SELECT COALESCE(regime, '?') AS regime, COUNT(*) AS n,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS w,
               ROUND(SUM(pnl), 2) AS pnl
        FROM entry_decisions WHERE pnl IS NOT NULL GROUP BY regime
    """):
        wr = r["w"] / r["n"] * 100 if r["n"] else 0
        print(f"    {r['regime']:10s}  {r['n']:>4d}T  WR {wr:>4.0f}%  PnL ${r['pnl']:>+7.2f}")


def main():
    ap = argparse.ArgumentParser(description="Query the unified decision log")
    ap.add_argument("--side",   choices=["BUY", "SELL"], help="Filter by side")
    ap.add_argument("--source", help="Filter by engine name (claude_genome etc)")
    ap.add_argument("--regime", help="Filter by regime (TREND_UP, CHOP, etc)")
    ap.add_argument("--win",    action="store_true", help="Only winning trades")
    ap.add_argument("--loss",   action="store_true", help="Only losing trades")
    ap.add_argument("--limit",  type=int, default=50, help="Max rows to list")
    ap.add_argument("--rank",   action="store_true", help="Per-source ranking")
    ap.add_argument("--summary", action="store_true", help="High-level overview")
    args = ap.parse_args()

    if args.summary:
        cmd_summary(args)
    elif args.rank:
        cmd_rank(args)
    else:
        cmd_list(args)


if __name__ == "__main__":
    main()
