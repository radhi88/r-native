"""runtime/sql_dashboard.py — Single-pane live competition view.

Born 2026-05-28. The unified visualization layer for the unified DB.
Every panel = a SQL query. Refresh every 5s.

  ┌─────────────────────────────────────────────────────────────────┐
  │  💰 ACCOUNT  ·  🌡️  REGIME  ·  ⏰ time                          │
  ├─────────────────────────────────────────────────────────────────┤
  │  🏆 ENGINE LEADERBOARD (last 24h, from trades table)            │
  ├─────────────────────────────────────────────────────────────────┤
  │  🧬 GENOME COMPETITION (best children from decision_log)        │
  ├─────────────────────────────────────────────────────────────────┤
  │  📜 LATEST DECISIONS (last 8 entry_decisions, all engines)      │
  ├─────────────────────────────────────────────────────────────────┤
  │  📈 OPEN POSITIONS (per magic, floating PnL)                    │
  └─────────────────────────────────────────────────────────────────┘

Run:
    python -m runtime.sql_dashboard
"""
from __future__ import annotations
import os
import time
from datetime import datetime
from pathlib import Path

import MetaTrader5 as mt5

from runtime.shared.db import db
from runtime.shared.tokens import PATHS, NAMES

POLL_S = 5.0


def _clear(): os.system("cls" if os.name == "nt" else "clear")


def _read_regime() -> dict:
    try:
        import json
        return json.loads(PATHS["market_regime"].read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_active() -> dict:
    try:
        import json
        return json.loads(PATHS["active_engines"].read_text(encoding="utf-8"))
    except Exception:
        return {}


def render():
    acc = mt5.account_info()
    if acc is None:
        print("[sql_dashboard] mt5 not connected"); return
    regime = _read_regime()
    active = _read_active()

    _clear()
    W = 76
    print("╔" + "═" * W + "╗")
    print("║" + f"  📊  SQL DASHBOARD  ·  {datetime.now():%Y-%m-%d %H:%M:%S}".ljust(W) + "║")
    print("╠" + "═" * W + "╣")
    print("║" + f"  💰 Bal ${acc.balance:>8.2f}  ·  Eq ${acc.equity:>8.2f}  ·  Float ${acc.profit:>+7.2f}  "
                f"·  Margin {acc.margin_level:>4.0f}%".ljust(W) + "║")
    reg = regime.get("regime", "?")
    adx = regime.get("metrics", {}).get("adx_m5", 0)
    active_m = active.get("active_magics", [])
    active_names = ", ".join(NAMES.get(m, str(m)) for m in active_m) or "(none)"
    print("║" + f"  🌡️ Regime {reg}  (ADX {adx:.1f})  ·  Active: {active_names}".ljust(W) + "║")

    # ── PANEL 1 — Engine leaderboard (last 24h) ──────────────────
    print("╠" + "═" * W + "╣")
    print("║" + "  🏆 ENGINE LEADERBOARD — last 24h".ljust(W) + "║")
    rows = db.query("""
        SELECT magic, source,
               COUNT(*) AS trades,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
               ROUND(SUM(pnl), 2) AS pnl
        FROM trades
        WHERE pnl IS NOT NULL AND ts > datetime('now', '-1 day')
        GROUP BY magic
        ORDER BY pnl DESC
    """)
    if not rows:
        print("║" + "     (no closed trades yet)".ljust(W) + "║")
    else:
        for i, r in enumerate(rows[:8]):
            name = (r["source"] or NAMES.get(r["magic"], str(r["magic"])))[:14]
            wr = r["wins"] / r["trades"] * 100 if r["trades"] else 0
            pnl = r["pnl"] or 0
            emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "  "
            mark = "🟢" if pnl > 0 else "🔴"
            line = f"  {emoji} {mark} {name:14s} {r['trades']:>3d}T  WR {wr:>4.0f}%  PnL ${pnl:>+7.2f}"
            print("║ " + line.ljust(W - 1) + "║")

    # ── PANEL 2 — Genome competition ─────────────────────────────
    print("╠" + "═" * W + "╣")
    print("║" + "  🧬 GENOME POOL — top by recent fitness".ljust(W) + "║")
    pop_path = PATHS.get("genomes_population")
    if pop_path and pop_path.exists():
        try:
            import json as _json
            pop = _json.loads(pop_path.read_text(encoding="utf-8"))
            genomes = pop.get("genomes", [])
            # Show 5 newest
            for g in genomes[-5:]:
                name = (g.get("name", "?"))[:22]
                parents = g.get("parents") or [g.get("mutated_from") or g.get("born", "seed")]
                p_str = "+".join(parents)[:30] if isinstance(parents, list) else str(parents)[:30]
                line = f"     {name:22s}  ← {p_str}"
                print("║ " + line.ljust(W - 1) + "║")
        except Exception as e:
            print("║" + f"     (genome pool err: {e})".ljust(W) + "║")
    else:
        print("║" + "     (no genome pool)".ljust(W) + "║")

    # ── PANEL 3 — Latest decisions feed ──────────────────────────
    print("╠" + "═" * W + "╣")
    print("║" + "  📜 LATEST DECISIONS — last 8 entries".ljust(W) + "║")
    dec_rows = db.query("""
        SELECT ts, source, side, entry, pnl, regime, rsi_m1, mtf_align
        FROM entry_decisions
        ORDER BY ts DESC LIMIT 8
    """)
    if not dec_rows:
        print("║" + "     (no decisions logged yet — restart traders to start logging)".ljust(W) + "║")
    else:
        for r in dec_rows:
            ts = (r["ts"] or "")[11:19]
            src = (r["source"] or "?")[:13]
            side = r["side"] or "?"
            entry = r["entry"] or 0
            pnl = r["pnl"]
            outcome = f"${pnl:+.2f}" if pnl is not None else " open "
            outcome_mark = "🟢" if (pnl or 0) > 0 else "🔴" if (pnl or 0) < 0 else "⌛"
            reg = (r["regime"] or "?")[:7]
            rsi = r["rsi_m1"] or 0
            line = f"  {ts} {src:13s} {side:4s}@{entry:>7.2f} {outcome_mark}{outcome:>7s} {reg:7s} RSI{rsi:>4.0f}"
            print("║ " + line.ljust(W - 1) + "║")

    # ── PANEL 4 — Open positions ─────────────────────────────────
    print("╠" + "═" * W + "╣")
    print("║" + "  📈 OPEN POSITIONS".ljust(W) + "║")
    positions = mt5.positions_get() or []
    if not positions:
        print("║" + "     (no open positions)".ljust(W) + "║")
    else:
        # Group by magic
        by_magic: dict[int, list] = {}
        for p in positions:
            by_magic.setdefault(int(p.magic), []).append(p)
        for mag, pos_list in sorted(by_magic.items()):
            name = NAMES.get(mag, str(mag))[:13]
            n = len(pos_list)
            float_pnl = sum(float(p.profit) for p in pos_list)
            vol = sum(float(p.volume) for p in pos_list)
            mark = "🟢" if float_pnl > 0 else "🔴" if float_pnl < 0 else "⚪"
            line = f"     {mark} {name:14s} {n:>2d} pos · {vol:.2f} lot · Float ${float_pnl:>+6.2f}"
            print("║ " + line.ljust(W - 1) + "║")

    # ── Footer with DB sizes ─────────────────────────────────────
    print("╠" + "═" * W + "╣")
    t_trades = db.query("SELECT COUNT(*) AS n FROM trades")[0]["n"]
    t_decisions = db.query("SELECT COUNT(*) AS n FROM entry_decisions")[0]["n"]
    t_signals = db.query("SELECT COUNT(*) AS n FROM signals")[0]["n"]
    db_size_kb = PATHS["brain_decisions"].parent.joinpath("trading.db").stat().st_size / 1024
    print("║" + f"  💾 DB: {t_trades} trades · {t_decisions} decisions · {t_signals} signals · {db_size_kb:.0f}KB".ljust(W) + "║")
    print("╚" + "═" * W + "╝")
    print(f"  Refresh {POLL_S}s · Ctrl+C to exit")


def main():
    if not mt5.initialize() and not mt5.initialize():
        print("[sql_dashboard] cannot init mt5"); return
    print("[sql_dashboard] starting...")
    time.sleep(1)
    while True:
        try:
            render()
            time.sleep(POLL_S)
        except KeyboardInterrupt:
            mt5.shutdown(); print("\n[sql_dashboard] stopped"); break
        except Exception as e:
            print(f"err: {e}"); time.sleep(POLL_S)


if __name__ == "__main__":
    main()
