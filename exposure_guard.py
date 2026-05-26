"""exposure_guard.py — Per-symbol risk gates that run BEFORE _send_order.

Stops the four patterns most likely to bleed an account quietly:
  1) **Churn**: opening the same symbol+side within seconds of a previous close
     (executor finds a "good" setup → opens → small TP → re-opens immediately → repeat
     until the streak breaks. The screenshot's 4× US30 BUYs in 10 minutes is this.)
  2) **Drawdown spiral**: a symbol that's already lost ≥ DAILY_LOSS_FLOOR today
     keeps getting opened. Pause that symbol for COOLDOWN_AFTER_DD minutes.
  3) **Position stacking**: same symbol + same side already has ≥ N positions open.
  4) **Churn cap**: too many entries on the same symbol per day, regardless of P/L.

API used by r_executor:
  can_open(symbol, side) -> (allowed:bool, reason:str)
  record_open(symbol, side, ticket)
  record_close(symbol, side, ticket, profit, exit_reason)

State persists to data/r_native/exposure_state.json so it survives restarts.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

STATE_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\exposure_state.json")

# ─── Tunables — USER OVERRIDE 2026-05-25 "no limits as long as winning" ───
# Only the DD floor remains as a real brake. Everything else effectively off.
COOLDOWN_AFTER_CLOSE_S    = 5         # was 60 — minimal cool-down to avoid same-tick double-fire
DAILY_LOSS_FLOOR_USD      = -5.0      # tighten DD a bit (was -3) to compensate for unlimited churn
COOLDOWN_AFTER_DD_S       = 900       # 15-min pause after hitting DD floor (was 30 min)
MAX_SAME_SIDE_PER_SYMBOL  = 3         # allow up to 3 same-side per symbol (was 1)
MAX_ENTRIES_PER_SYMBOL_PD = 9999      # effectively no daily cap (was 12)


# ───────────────────────────────────────────────────────────────────────
# State management
# ───────────────────────────────────────────────────────────────────────

def _load() -> dict:
    if not STATE_PATH.exists(): return {"_day": _today_utc()}
    try:
        d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        # Auto-reset if a new day rolled over
        if d.get("_day") != _today_utc():
            return {"_day": _today_utc()}
        return d
    except Exception:
        return {"_day": _today_utc()}


def _save(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception: pass


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _key(symbol: str, side: str) -> str:
    return f"{symbol}|{side}"


# ───────────────────────────────────────────────────────────────────────
# Recording hooks (called from r_executor)
# ───────────────────────────────────────────────────────────────────────

def record_open(symbol: str, side: str, ticket: int) -> None:
    """Called right after a successful _send_order."""
    state = _load()
    sym = state.setdefault(symbol, {"opens_today": 0, "net_today": 0.0})
    sym["opens_today"] = int(sym.get("opens_today", 0)) + 1
    sym["last_open_ts"] = time.time()
    sym.setdefault("open_tickets", []).append(int(ticket))
    _save(state)


def record_close(symbol: str, side: str, ticket: int, profit: float,
                  exit_reason: str = "") -> None:
    """Called when a position closes (from r_executor close-handler)."""
    state = _load()
    sym = state.setdefault(symbol, {"opens_today": 0, "net_today": 0.0})
    sym["last_close_ts"] = time.time()
    sym["net_today"] = float(sym.get("net_today", 0)) + float(profit or 0)
    # Track if we're in a DD freeze
    if sym["net_today"] < DAILY_LOSS_FLOOR_USD and not sym.get("dd_paused_at"):
        sym["dd_paused_at"] = time.time()
        sym["dd_paused_reason"] = (f"daily ${sym['net_today']:.2f} < "
                                    f"floor ${DAILY_LOSS_FLOOR_USD}")
    tickets = sym.get("open_tickets", [])
    if int(ticket) in tickets: tickets.remove(int(ticket))
    sym["open_tickets"] = tickets
    _save(state)


# ───────────────────────────────────────────────────────────────────────
# Gate: can_open
# ───────────────────────────────────────────────────────────────────────

def _reconcile_with_mt5(state: dict) -> bool:
    """Stale ticket cleanup — remove tickets from open_tickets that no
    longer exist as actual MT5 positions. The executor calls record_close
    on trades it cuts, but SL/TP hits + agent-driven closes can bypass it,
    leaving the state thinking there are positions that aren't really
    open. Result: exposure_guard falsely blocks legitimate new entries
    ("already 3 open" when 0 are actually open).

    Returns True if any cleanup happened (caller should re-save state).
    """
    try:
        import MetaTrader5 as _mt5
        if not _mt5.initialize(): _mt5.initialize()
        actual_tickets = {int(p.ticket) for p in (_mt5.positions_get() or [])
                          if int(p.magic) == 20260605}
    except Exception:
        return False
    changed = False
    for sym, info in state.items():
        if sym.startswith("_"): continue
        if not isinstance(info, dict): continue
        old_tickets = list(info.get("open_tickets", []) or [])
        live_tickets = [t for t in old_tickets if int(t) in actual_tickets]
        if len(live_tickets) != len(old_tickets):
            info["open_tickets"] = live_tickets
            changed = True
    return changed


def can_open(symbol: str, side: str) -> tuple[bool, str]:
    """Apply all four guards. Returns (allowed, reason).

    Note: side is "BUY"/"SELL"; reason is human-readable and goes to the log."""
    state = _load()
    # Cycle 28 fix: reconcile state with actual MT5 positions before
    # checking gates. Stops false-positive "already N open" blocks when
    # those positions actually closed via SL/TP/aging.
    if _reconcile_with_mt5(state):
        _save(state)
    sym = state.get(symbol, {})
    now = time.time()

    # 1) Daily DD floor — pause for COOLDOWN_AFTER_DD_S after the floor was hit
    if sym.get("dd_paused_at"):
        elapsed = now - float(sym["dd_paused_at"])
        if elapsed < COOLDOWN_AFTER_DD_S:
            mins_left = (COOLDOWN_AFTER_DD_S - elapsed) / 60
            return False, (f"DD pause: {sym.get('dd_paused_reason','')} — "
                            f"{mins_left:.1f} min left")
        else:
            # Cool-down expired; clear the pause if symbol bounced back above floor
            if sym.get("net_today", 0) >= DAILY_LOSS_FLOOR_USD:
                sym["dd_paused_at"] = None
                sym["dd_paused_reason"] = None
                _save(state)

    # 2) Per-symbol intraday cap
    if int(sym.get("opens_today", 0)) >= MAX_ENTRIES_PER_SYMBOL_PD:
        return False, (f"max-entries cap hit ({sym['opens_today']}/"
                        f"{MAX_ENTRIES_PER_SYMBOL_PD} today)")

    # 3) Cool-down after a close on this symbol (any side)
    last_close = sym.get("last_close_ts", 0)
    if last_close:
        since = now - float(last_close)
        if since < COOLDOWN_AFTER_CLOSE_S:
            return False, (f"cool-down: only {since:.0f}s since last "
                            f"{symbol} close (need {COOLDOWN_AFTER_CLOSE_S}s)")

    # 4) Same-symbol-same-side limit — block stacking
    same_side_open = len(sym.get("open_tickets", []))
    if same_side_open >= MAX_SAME_SIDE_PER_SYMBOL:
        return False, (f"already {same_side_open} open on {symbol} "
                        f"(cap {MAX_SAME_SIDE_PER_SYMBOL})")

    return True, "OK"


# ───────────────────────────────────────────────────────────────────────
# Read-only inspector for UI
# ───────────────────────────────────────────────────────────────────────

def snapshot() -> dict:
    """Compact snapshot of per-symbol exposure state for the UI."""
    state = _load()
    out = []
    for sym, info in state.items():
        if sym.startswith("_"): continue
        net = float(info.get("net_today", 0))
        paused = bool(info.get("dd_paused_at"))
        out.append({
            "symbol":       sym,
            "opens_today":  int(info.get("opens_today", 0)),
            "net_today":    round(net, 2),
            "open_tickets": list(info.get("open_tickets", []) or []),
            "dd_paused":    paused,
            "dd_reason":    info.get("dd_paused_reason") or "",
        })
    out.sort(key=lambda r: r["net_today"])     # worst first
    return {"day": state.get("_day"), "symbols": out}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="r_native.exposure_guard")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot", help="show per-symbol exposure state")
    p_chk = sub.add_parser("check", help="ask if a sym+side can open now")
    p_chk.add_argument("symbol"); p_chk.add_argument("side")
    p_rst = sub.add_parser("reset", help="wipe today's state")
    args = ap.parse_args()
    if args.cmd == "snapshot":
        print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
    elif args.cmd == "check":
        ok, why = can_open(args.symbol, args.side)
        print(json.dumps({"allowed": ok, "reason": why}, ensure_ascii=False, indent=2))
    elif args.cmd == "reset":
        STATE_PATH.unlink(missing_ok=True)
        print("reset OK")
