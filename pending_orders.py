"""pending_orders.py — manage MT5 pending limit/stop orders.

Used by GapHunter, VolatilitySpikeHunter, and SessionSpecialist agents
that want to QUEUE orders at specific price levels instead of firing
at market.

Order types:
  • BUY_LIMIT  — buy if price drops to X (we expect a bounce up from there)
  • SELL_LIMIT — sell if price rises to X (we expect a rejection down)
  • BUY_STOP   — buy if price breaks above X (breakout entry)
  • SELL_STOP  — sell if price breaks below X (breakdown entry)

All pending orders carry our magic 20260605 and a comment R-P-<gid>-<reason>
so we can attribute fills back to the originating agent.

Pending orders auto-expire after N hours (default 24h) so stale orders
don't trigger days later in completely different market conditions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json


PENDING_LOG = Path(r"C:\Users\Radhi\MT5\data\r_native\pending_orders.json")
R_MAGIC = 20260605


def place_pending(*, symbol: str, side: str, order_kind: str, price: float,
                  sl: float, tp: float, lot: float = 0.01,
                  reason: str = "agent", expiry_hours: int = 24,
                  agent_name: str = "?") -> dict:
    """Place a pending order on MT5.

    side: BUY | SELL
    order_kind: LIMIT | STOP
    Returns {ok, ticket, error}
    """
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
        si = mt5.symbol_info(symbol)
        if not si or not si.visible:
            mt5.symbol_select(symbol, True)
            si = mt5.symbol_info(symbol)
        if not si: return {"ok": False, "error": f"symbol {symbol} not found"}

        # Map to MT5 order type constant
        order_type_map = {
            ("BUY",  "LIMIT"): mt5.ORDER_TYPE_BUY_LIMIT,
            ("SELL", "LIMIT"): mt5.ORDER_TYPE_SELL_LIMIT,
            ("BUY",  "STOP"):  mt5.ORDER_TYPE_BUY_STOP,
            ("SELL", "STOP"):  mt5.ORDER_TYPE_SELL_STOP,
        }
        mt5_type = order_type_map.get((side.upper(), order_kind.upper()))
        if mt5_type is None:
            return {"ok": False, "error": f"bad combo {side}/{order_kind}"}

        # Comment is capped at 31 chars in MT5
        comment = f"R-P-{agent_name[:6]}-{reason[:8]}"[:31]

        # External bridge — respect Claude orchestrator's regime decision
        try:
            from r_native.external_gate import can_trade
            allowed, gate_reason = can_trade(R_MAGIC)
            if not allowed:
                return {"ok": False, "vetoed": True,
                        "error": f"orchestrator: {gate_reason}"}
        except Exception:
            pass  # fail-open

        # Expiry — broker may not honor; we'll also do soft cleanup
        expiry_dt = datetime.now() + timedelta(hours=expiry_hours)
        req = {
            "action":       mt5.TRADE_ACTION_PENDING,
            "symbol":       symbol,
            "volume":       lot,
            "type":         mt5_type,
            "price":        round(price, si.digits),
            "sl":           round(sl, si.digits),
            "tp":           round(tp, si.digits),
            "magic":        R_MAGIC,
            "comment":      comment,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "type_time":    mt5.ORDER_TIME_GTC,
        }
        r = mt5.order_send(req)
        if r is None:
            return {"ok": False, "error": "order_send returned None"}
        if r.retcode != mt5.TRADE_RETCODE_DONE:
            return {"ok": False, "error": f"retcode {r.retcode} {r.comment}"}

        # Log it
        _log_pending({
            "ticket":      int(r.order),
            "symbol":      symbol,
            "side":        side,
            "order_kind":  order_kind,
            "price":       price,
            "sl":          sl, "tp": tp, "lot": lot,
            "agent":       agent_name,
            "reason":      reason,
            "placed_at":   datetime.now(timezone.utc).isoformat(),
            "expiry_at":   expiry_dt.isoformat(),
        })
        return {"ok": True, "ticket": int(r.order), "price": price,
                "comment": comment}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _log_pending(entry: dict):
    PENDING_LOG.parent.mkdir(parents=True, exist_ok=True)
    arr = []
    if PENDING_LOG.exists():
        try: arr = json.loads(PENDING_LOG.read_text(encoding="utf-8"))
        except Exception: pass
    arr.append(entry)
    PENDING_LOG.write_text(json.dumps(arr[-200:], ensure_ascii=False, indent=2),
                            encoding="utf-8")


def list_r_pending() -> list:
    """Return all live R-magic pending orders from MT5."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
        orders = mt5.orders_get() or []
        return [
            {"ticket": o.ticket, "symbol": o.symbol,
             "type": _human_type(o.type), "price": float(o.price_open),
             "sl": float(o.sl), "tp": float(o.tp),
             "comment": o.comment or "",
             "magic": int(o.magic)}
            for o in orders if int(o.magic) == R_MAGIC
        ]
    except Exception:
        return []


def cancel_expired(max_age_hours: int = 24) -> int:
    """Cancel any R-magic pending orders older than `max_age_hours`."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
        orders = mt5.orders_get() or []
        cancelled = 0
        now = datetime.now()
        for o in orders:
            if int(o.magic) != R_MAGIC: continue
            age_hours = (now.timestamp() - int(o.time_setup)) / 3600
            if age_hours < max_age_hours: continue
            req = {"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket}
            r = mt5.order_send(req)
            if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                cancelled += 1
        return cancelled
    except Exception:
        return 0


def _human_type(t):
    try:
        import MetaTrader5 as mt5
        return {mt5.ORDER_TYPE_BUY_LIMIT:  "BUY_LIMIT",
                mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
                mt5.ORDER_TYPE_BUY_STOP:   "BUY_STOP",
                mt5.ORDER_TYPE_SELL_STOP:  "SELL_STOP"}.get(int(t), str(t))
    except Exception:
        return str(t)
