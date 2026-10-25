"""order_guard.py — no R-Native code sends orders to MT5 directly (2026-10-25).

install() wraps MetaTrader5.order_send for the whole process. Many built-in
agents (volatility_hunter, pending_orders, position_aging, night_shift,
breakeven_lock, dynamic_tp, sl_safety_tightener, ...) call mt5.order_send
themselves; with the guard on:
- a new market/pending entry is handed to the employee (employee_link.submit)
  and the caller gets a rejected result (retcode 10017, nothing filled);
- SL/TP moves, closes and order removals are refused: trades opened through
  the employee belong to the employee and its central gateway.
R_ROUTE=direct_demo leaves order_send untouched (debugging only).
"""
from __future__ import annotations

import os
from types import SimpleNamespace

REJECT = 10017   # TRADE_RETCODE_REJECT
_ORIG = None


def _result(comment: str) -> SimpleNamespace:
    return SimpleNamespace(retcode=REJECT, order=0, deal=0, volume=0.0, price=0.0,
                           bid=0.0, ask=0.0, comment=comment[:64], request_id=0)


def guarded(mt5, request: dict):
    req = dict(request or {})
    action = req.get("action")
    entry = action in (getattr(mt5, "TRADE_ACTION_DEAL", 1), getattr(mt5, "TRADE_ACTION_PENDING", 5)) \
        and not req.get("position")
    if not entry:
        return _result("guard: employee owns trades")
    from r_native.employee_link import submit
    side = "BUY" if req.get("type") in (0, 2, 4) else "SELL"
    ok, res = submit(req.get("symbol", ""), side, req.get("volume", 0.0), req.get("sl", 0.0),
                     req.get("tp", 0.0), str(req.get("comment") or "agent"), price=req.get("price"))
    return _result("guard: queued for employee" if ok else "guard: " + str(res.get("reason")))


def install() -> bool:
    """Wrap order_send once per process. Returns True when the guard is active."""
    global _ORIG
    if os.environ.get("R_ROUTE", "employee") == "direct_demo":
        return False
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return False
    if _ORIG is None:
        _ORIG = mt5.order_send
        mt5.order_send = lambda request=None, *a, **k: guarded(mt5, request)
    return True
