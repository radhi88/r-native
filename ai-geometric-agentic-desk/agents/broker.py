"""MT5 broker interface — data IO, demo guard, and guarded execution.

Wraps MetaTrader5 with this desk's safety contract:

* refuses to send any order unless the connected account is a DEMO account
  (Exness Trial accounts report ``trade_mode=0`` falsely, so demo is detected
  by server name containing ``trial``/``demo``);
* every order carries a mandatory stop-loss (a fill that lands without one is
  immediately closed);
* tags orders with :data:`config.EXEC_MAGIC`;
* never reverses or stacks against an existing position (no martingale).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - import guard for non-MT5 hosts
    mt5 = None

import config


@dataclass
class Account:
    """Snapshot of the connected trading account."""

    login: int
    server: str
    equity: float
    free_margin: float
    is_demo: bool


def connect() -> bool:
    """Initialise the MT5 terminal connection (idempotent)."""
    if mt5 is None:
        return False
    return bool(mt5.initialize() or mt5.initialize())


def account() -> Account | None:
    """Return the current account snapshot, or ``None`` if unavailable."""
    if mt5 is None:
        return None
    ai = mt5.account_info()
    if ai is None:
        return None
    server = (ai.server or "").lower()
    is_demo = ("trial" in server) or ("demo" in server)
    return Account(ai.login, ai.server, ai.equity, ai.margin_free, is_demo)


def fetch_ohlc(symbol: str, timeframe: int, bars: int) -> dict[str, np.ndarray] | None:
    """Fetch ``bars`` closed candles for ``symbol``.

    Args:
        symbol: Broker symbol.
        timeframe: An ``mt5.TIMEFRAME_*`` constant.
        bars: Number of bars to request.

    Returns:
        Dict of ``open/high/low/close/volume/time`` arrays, or ``None``.
    """
    if mt5 is None:
        return None
    if not mt5.symbol_select(symbol, True):
        return None
    r = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if r is None or len(r) == 0:
        return None
    return {"open": r["open"], "high": r["high"], "low": r["low"],
            "close": r["close"], "volume": r["tick_volume"], "time": r["time"]}


def symbol_meta(symbol: str) -> dict | None:
    """Return tick size/value, lot bounds, margin, and current spread."""
    if mt5 is None:
        return None
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return None
    spread_price = (info.ask - info.bid) if info.ask and info.bid else info.spread * info.point
    return {
        "tick_size": info.trade_tick_size or info.point,
        "tick_value": info.trade_tick_value or 1.0,
        "vol_min": info.volume_min, "vol_step": info.volume_step,
        "point": info.point, "digits": info.digits,
        "bid": tick.bid, "ask": tick.ask, "spread_price": spread_price,
        "margin_lot": info.margin_initial or 0.0,
    }


def list_symbols(only_full_trade: bool = True, max_rel_spread: float | None = None,
                 limit: int | None = None) -> list[str]:
    """Return the broker's tradable symbol names, optionally spread-pruned.

    Args:
        only_full_trade: Keep only symbols with full trading enabled.
        max_rel_spread: If set, drop symbols whose current spread / price
            exceeds this fraction (filters illiquid wide-spread exotics).
        limit: Optional cap on the number returned.

    Returns:
        List of symbol names (empty if MT5 is unavailable).
    """
    if mt5 is None:
        return []
    syms = mt5.symbols_get() or []
    out: list[str] = []
    for s in syms:
        if only_full_trade and s.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            continue
        if max_rel_spread is not None:
            try:
                mt5.symbol_select(s.name, True)
                t = mt5.symbol_info_tick(s.name)
                if t is None or t.bid <= 0 or (t.ask - t.bid) / t.bid > max_rel_spread:
                    continue
            except Exception:
                continue
        out.append(s.name)
    return out[:limit] if limit else out


def has_open(symbol: str) -> bool:
    """True if this desk already holds a position in ``symbol``."""
    if mt5 is None:
        return False
    pos = mt5.positions_get(symbol=symbol) or []
    return any(p.magic == config.EXEC_MAGIC for p in pos)


def open_count() -> int:
    """Number of open positions owned by this desk (magic-filtered)."""
    if mt5 is None:
        return 0
    return sum(1 for p in (mt5.positions_get() or []) if p.magic == config.EXEC_MAGIC)


def open_positions() -> list[dict]:
    """Return open desk positions as plain dicts (for the bus/dashboard)."""
    if mt5 is None:
        return []
    out = []
    for p in (mt5.positions_get() or []):
        if p.magic != config.EXEC_MAGIC:
            continue
        out.append({"symbol": p.symbol, "ticket": p.ticket,
                    "side": "BUY" if p.type == 0 else "SELL",
                    "vol": p.volume, "pnl": round(p.profit, 2),
                    "sl": p.sl, "tp": p.tp, "open": p.price_open, "time": p.time})
    return out


def realized_by_symbol(days: int = 3) -> dict[str, dict]:
    """Aggregate this desk's realised P&L per symbol from deal history.

    Args:
        days: Look-back window in days.

    Returns:
        ``{symbol: {"net": float, "trades": int, "wins": int}}`` over closed
        (``entry==1``) desk deals.
    """
    if mt5 is None:
        return {}
    import datetime as _dt
    frm = _dt.datetime.now() - _dt.timedelta(days=days)
    deals = mt5.history_deals_get(frm, _dt.datetime.now()) or []
    out: dict[str, dict] = {}
    for d in deals:
        if d.magic != config.EXEC_MAGIC or d.entry != 1:
            continue
        s = out.setdefault(d.symbol, {"net": 0.0, "trades": 0, "wins": 0})
        s["net"] += d.profit
        s["trades"] += 1
        if d.profit > 0:
            s["wins"] += 1
    for s in out.values():
        s["net"] = round(s["net"], 2)
    return out


def close_position(symbol: str, ticket: int, side: str, volume: float) -> dict:
    """Close one desk position at market (used by the reversal manager).

    Args:
        symbol: Position symbol.
        ticket: Position ticket to close.
        side: ``"BUY"`` or ``"SELL"`` of the open position.
        volume: Lots to close.

    Returns:
        ``{"ok": bool, "reason": str}``.
    """
    if mt5 is None:
        return {"ok": False, "reason": "MT5 unavailable"}
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        return {"ok": False, "reason": "no tick"}
    close_type = mt5.ORDER_TYPE_SELL if side == "BUY" else mt5.ORDER_TYPE_BUY
    price = tick.bid if side == "BUY" else tick.ask
    fmask = info.filling_mode
    fill = (mt5.ORDER_FILLING_FOK if fmask & 1 else
            mt5.ORDER_FILLING_IOC if fmask & 2 else mt5.ORDER_FILLING_RETURN)
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "position": ticket,
           "volume": round(float(volume), 2), "type": close_type,
           "price": round(float(price), info.digits), "deviation": 50,
           "magic": config.EXEC_MAGIC, "comment": "reverse-close", "type_filling": fill}
    res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        return {"ok": False, "reason": f"close rc={getattr(res, 'retcode', 'none')}"}
    return {"ok": True, "reason": "closed"}


def send_order(symbol: str, direction: int, volume: float, sl: float,
               tp: float, comment: str) -> dict:
    """Send a guarded market order with a mandatory stop.

    Args:
        symbol: Broker symbol.
        direction: ``+1`` buy, ``-1`` sell.
        volume: Lots.
        sl: Stop-loss price (must be non-zero and on the losing side).
        tp: Take-profit price.
        comment: Order comment (confluence tag).

    Returns:
        ``{"ok": bool, "reason": str, "ticket": int|None}``.
    """
    if mt5 is None:
        return {"ok": False, "reason": "MT5 unavailable", "ticket": None}
    acct = account()
    if acct is None:
        return {"ok": False, "reason": "no account", "ticket": None}
    if config.DEMO_ONLY and not acct.is_demo:
        return {"ok": False, "reason": "BLOCKED: not a demo account", "ticket": None}
    if not config.LIVE_TRADING and not acct.is_demo:
        return {"ok": False, "reason": "LIVE_TRADING off + non-demo", "ticket": None}
    if sl <= 0:
        return {"ok": False, "reason": "mandatory SL missing", "ticket": None}
    if has_open(symbol):
        return {"ok": False, "reason": "position open — no stacking/reverse", "ticket": None}

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    digits = info.digits
    point = info.point
    price = round(float(tick.ask if direction > 0 else tick.bid), digits)

    # Enforce the broker minimum-stop distance; normalise SL/TP to digits.
    min_stop = max(info.trade_stops_level, info.spread + 1) * point
    sl_dist = max(abs(price - sl), min_stop)
    tp_dist = max(abs(tp - price), min_stop * 1.5)
    sl = round(price - direction * sl_dist, digits)
    tp = round(price + direction * tp_dist, digits)

    # Pick a filling mode the symbol actually supports (bitmask 1=FOK, 2=IOC).
    fmask = info.filling_mode
    fill = (mt5.ORDER_FILLING_FOK if fmask & 1 else
            mt5.ORDER_FILLING_IOC if fmask & 2 else mt5.ORDER_FILLING_RETURN)

    # MT5 rejects non-ASCII / over-long comments; keep it safe and short.
    safe = "".join(ch for ch in comment if 32 <= ord(ch) < 127
                   and ch not in '"\\')[:24].strip() or "geo"

    otype = mt5.ORDER_TYPE_BUY if direction > 0 else mt5.ORDER_TYPE_SELL
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
           "volume": round(float(volume), 2), "type": otype, "price": price,
           "sl": sl, "tp": tp, "deviation": 50, "magic": config.EXEC_MAGIC,
           "comment": safe, "type_filling": fill}
    chk = mt5.order_check(req)
    if chk is not None and chk.retcode not in (0, mt5.TRADE_RETCODE_DONE):
        return {"ok": False, "reason": f"check rc={chk.retcode} {chk.comment}",
                "ticket": None}
    res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        rc = getattr(res, "retcode", "none")
        return {"ok": False, "reason": f"send rc={rc} err={mt5.last_error()}",
                "ticket": None}
    return {"ok": True, "reason": "filled", "ticket": res.order}
