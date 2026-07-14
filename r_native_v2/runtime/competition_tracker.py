"""runtime/competition_tracker.py — Live leaderboard for the engine war.

Born 2026-05-28. The user said: "كلهم يشتغلون وايهم اللي ينتصر".
This is the scoreboard.

Every 5 seconds: query MT5 history, group by magic, score each engine.
Updates a terminal table — green for winners, red for losers,
with hourly + daily + all-time tabs.

Tracked engines (from shared/tokens.MAGICS):
  • 99777   claude_auto
  • 99778   CLAUDE_BRAIN_EA
  • 99779   palace_council
  • 99780   claude_simple
  • 99781   claude_smart
  • 99782   claude_genome  (LIVE evolved)
  • 20260600 FRIDAY_brain  (MQL5 EA on chart)
  • 20260605 algory_sniper
  • 0       MANUAL (user)

Run in its own window:
    python -m runtime.competition_tracker
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import MetaTrader5 as mt5

from runtime.shared.tokens import MAGICS, NAMES, PATHS

POLL_S = 5.0
SCOREBOARD = PATHS["brain_decisions"].parent / "competition_scoreboard.json"


# ──────────────────────────────────────────────────────────
# Internal: pull deals for a window, group by magic
# ──────────────────────────────────────────────────────────
def _stats_for_window(hours: float) -> dict[int, dict]:
    """Returns {magic: {trades, wins, losses, pnl, win_rate, expectancy, streak}}."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
    exits = [d for d in deals if int(d.entry) in (1, 2)]  # 1=OUT, 2=INOUT
    # Sort newest first for streak
    exits_sorted_desc = sorted(exits, key=lambda d: d.time, reverse=True)

    out: dict[int, dict] = {}
    for mag in MAGICS.values():
        my_exits = [d for d in exits if int(d.magic) == mag]
        if not my_exits:
            out[mag] = {
                "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0,
                "win_rate": 0.0, "expectancy": 0.0, "streak": 0, "last_trade_age_s": None,
            }
            continue

        wins = [d for d in my_exits if float(d.profit) > 0]
        losses = [d for d in my_exits if float(d.profit) < 0]
        total_pnl = sum(float(d.profit) for d in my_exits)
        win_pnl = sum(float(d.profit) for d in wins) if wins else 0.0
        loss_pnl = sum(float(d.profit) for d in losses) if losses else 0.0
        avg_win = win_pnl / len(wins) if wins else 0.0
        avg_loss = loss_pnl / len(losses) if losses else 0.0
        wr = len(wins) / len(my_exits) if my_exits else 0.0
        expectancy = wr * avg_win + (1 - wr) * avg_loss

        # Streak (most-recent run of wins or losses)
        streak = 0
        my_exits_desc = [d for d in exits_sorted_desc if int(d.magic) == mag]
        if my_exits_desc:
            sign = 1 if float(my_exits_desc[0].profit) > 0 else -1
            for d in my_exits_desc:
                this_sign = 1 if float(d.profit) > 0 else (-1 if float(d.profit) < 0 else 0)
                if this_sign == sign:
                    streak += sign
                else:
                    break

        last_age = time.time() - my_exits_desc[0].time if my_exits_desc else None
        out[mag] = {
            "trades": len(my_exits),
            "wins": len(wins),
            "losses": len(losses),
            "pnl": round(total_pnl, 2),
            "win_rate": round(wr * 100, 1),
            "expectancy": round(expectancy, 2),
            "streak": streak,
            "last_trade_age_s": int(last_age) if last_age is not None else None,
        }
    return out


def _open_per_magic() -> dict[int, dict]:
    """Live open-position floating PnL per magic."""
    pos = mt5.positions_get() or []
    out: dict[int, dict] = {}
    for mag in MAGICS.values():
        my_pos = [p for p in pos if int(p.magic) == mag]
        if my_pos:
            out[mag] = {
                "count": len(my_pos),
                "floating": round(sum(float(p.profit) for p in my_pos), 2),
                "volume": round(sum(float(p.volume) for p in my_pos), 2),
            }
        else:
            out[mag] = {"count": 0, "floating": 0.0, "volume": 0.0}
    return out


# ──────────────────────────────────────────────────────────
# Display
# ──────────────────────────────────────────────────────────
def _clear(): os.system("cls" if os.name == "nt" else "clear")


def _rank_emoji(rank: int) -> str:
    return {0: "🥇", 1: "🥈", 2: "🥉"}.get(rank, "  ")


def _color_pnl(pnl: float) -> str:
    if pnl > 0: return "🟢"
    if pnl < 0: return "🔴"
    return "⚪"


def render():
    acc = mt5.account_info()
    if acc is None:
        print("[competition_tracker] mt5 not connected")
        return

    hour    = _stats_for_window(1)
    day     = _stats_for_window(24)
    all7d   = _stats_for_window(24 * 7)
    open_pm = _open_per_magic()

    # Rank by 24h PnL (only engines that have traded)
    ranked = sorted(
        [(mag, day[mag]) for mag in day if day[mag]["trades"] > 0],
        key=lambda kv: kv[1]["pnl"], reverse=True,
    )

    _clear()
    width = 78
    print("╔" + "═" * width + "╗")
    print("║" + f"  🏆  ENGINE COMPETITION LEADERBOARD  ·  {datetime.now():%H:%M:%S}".ljust(width) + "║")
    print("╠" + "═" * width + "╣")
    print("║" + f"  💰 Balance ${acc.balance:>8.2f}  ·  Equity ${acc.equity:>8.2f}  ·  Floating ${acc.profit:>+7.2f}".ljust(width) + "║")
    print("╠" + "═" * width + "╣")

    if not ranked:
        print("║" + f"  (no engines have traded in last 24h)".ljust(width) + "║")
    else:
        # Headers
        hdr = f"     Engine          Trades  WR%    PnL$    EV$    Strk  Open  Float$"
        print("║ " + hdr.ljust(width - 1) + "║")
        print("║" + ("─" * width) + "║")
        for rank, (mag, st) in enumerate(ranked):
            name = NAMES.get(mag, str(mag))[:14]
            wr   = st["win_rate"]
            pnl  = st["pnl"]
            ev   = st["expectancy"]
            strk = st["streak"]
            strk_disp = f"+{strk}" if strk > 0 else str(strk) if strk < 0 else "·"
            op   = open_pm.get(mag, {"count": 0, "floating": 0.0})
            line = (f"  {_rank_emoji(rank)} {_color_pnl(pnl)} {name:14s} "
                    f"{st['trades']:>4d}  {wr:>4.0f}  {pnl:>+7.2f}  {ev:>+5.2f}  "
                    f"{strk_disp:>4s}  {op['count']:>3d}  {op['floating']:>+6.2f}")
            print("║ " + line.ljust(width - 1) + "║")

    # 1-hour mini table
    print("╠" + "═" * width + "╣")
    print("║" + f"  📊 LAST HOUR".ljust(width) + "║")
    h_active = [(m, s) for m, s in hour.items() if s["trades"] > 0]
    if not h_active:
        print("║" + f"     (no trades in last hour)".ljust(width) + "║")
    else:
        for mag, st in sorted(h_active, key=lambda kv: kv[1]["pnl"], reverse=True):
            name = NAMES.get(mag, str(mag))[:14]
            line = f"     {_color_pnl(st['pnl'])} {name:14s} {st['trades']:>3d}T WR {st['win_rate']:>3.0f}%  ${st['pnl']:>+6.2f}"
            print("║ " + line.ljust(width - 1) + "║")

    # 7-day mini table
    print("╠" + "═" * width + "╣")
    print("║" + f"  📅 LAST 7 DAYS".ljust(width) + "║")
    d7_active = [(m, s) for m, s in all7d.items() if s["trades"] > 0]
    if not d7_active:
        print("║" + f"     (no trades in last 7d)".ljust(width) + "║")
    else:
        for mag, st in sorted(d7_active, key=lambda kv: kv[1]["pnl"], reverse=True):
            name = NAMES.get(mag, str(mag))[:14]
            line = f"     {_color_pnl(st['pnl'])} {name:14s} {st['trades']:>3d}T WR {st['win_rate']:>3.0f}%  ${st['pnl']:>+7.2f}  EV ${st['expectancy']:>+5.2f}"
            print("║ " + line.ljust(width - 1) + "║")

    print("╚" + "═" * width + "╝")
    print(f"  Refresh {POLL_S}s · Ctrl+C to exit")

    # Persist scoreboard for any other dashboard
    SCOREBOARD.parent.mkdir(parents=True, exist_ok=True)
    SCOREBOARD.write_text(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "account": {"balance": acc.balance, "equity": acc.equity, "floating": acc.profit},
        "hour": {NAMES.get(m, str(m)): s for m, s in hour.items()},
        "day":  {NAMES.get(m, str(m)): s for m, s in day.items()},
        "week": {NAMES.get(m, str(m)): s for m, s in all7d.items()},
        "open": {NAMES.get(m, str(m)): s for m, s in open_pm.items()},
        "leader_24h": NAMES.get(ranked[0][0], "—") if ranked else None,
    }, indent=2, default=str), encoding="utf-8")


def main():
    if not mt5.initialize() and not mt5.initialize():
        print("[competition_tracker] cannot initialize MT5"); return
    print("[competition_tracker] starting...")
    time.sleep(1)
    while True:
        try:
            render()
            time.sleep(POLL_S)
        except KeyboardInterrupt:
            mt5.shutdown()
            print("\n[competition_tracker] stopped"); break
        except Exception as e:
            print(f"err: {e}")
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
