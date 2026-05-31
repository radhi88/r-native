"""strategy_performance.py — compute a Performance summary from closed trades.

Pure function core (compute_performance) takes a list of closed-trade records
and returns the Performance dict the dashboard shows. The live path
(live_performance) pulls MT5 deal history and feeds the core, optionally
filtered by magic number (R's magic is 20260605).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from r_native.strategy_types import Performance


R_MAGIC = 20260605


def compute_performance(trades: list[dict], *,
                        starting_balance: float = 0.0) -> dict:
    """trades: [{profit: float, ...}, ...] (closed legs only).

    pnlPct is computed against starting_balance when given (>0); otherwise it
    is the net profit in account currency expressed as-is (callers that lack a
    balance can still show absolute net P/L)."""
    net = 0.0
    gross_win = 0.0
    gross_loss = 0.0
    wins = losses = 0
    for t in trades:
        pnl = float(t.get("profit", 0.0))
        net += pnl
        if pnl > 0:
            wins += 1; gross_win += pnl
        elif pnl < 0:
            losses += 1; gross_loss += abs(pnl)
    total = wins + losses
    winrate = (wins / total * 100.0) if total else 0.0
    if gross_loss > 0:
        pf = gross_win / gross_loss
    else:
        pf = float("inf") if gross_win > 0 else 0.0
    if starting_balance and starting_balance > 0:
        pnl_pct = net / starting_balance * 100.0
    else:
        pnl_pct = net  # absolute (no balance reference)
    perf = Performance(
        totalTrades=total, wins=wins, losses=losses,
        winratePct=round(winrate, 1),
        profitFactor=(round(pf, 2) if pf != float("inf") else 999.99),
        pnlPct=round(pnl_pct, 2),
    )
    return perf.to_dict()


def live_performance(*, magic: Optional[int] = R_MAGIC,
                     since_hours: int = 168,
                     symbol: Optional[str] = None) -> dict:
    """Pull closed deals from MT5 and summarize. Returns {ok, performance, ...}."""
    try:
        import MetaTrader5 as mt5
    except Exception:
        return {"ok": False, "reason": "MetaTrader5 unavailable"}
    try:
        if not mt5.initialize():
            mt5.initialize()
        since = datetime.now() - timedelta(hours=since_hours)
        deals = mt5.history_deals_get(since, datetime.now()) or []
        trades = []
        for d in deals:
            if getattr(d, "entry", None) != 1:   # closing legs only
                continue
            if magic is not None and int(getattr(d, "magic", 0)) != magic:
                continue
            if symbol and getattr(d, "symbol", "") != symbol:
                continue
            trades.append({
                "ticket": int(getattr(d, "position_id", 0)),
                "symbol": getattr(d, "symbol", ""),
                "profit": float(getattr(d, "profit", 0.0))
                          + float(getattr(d, "swap", 0.0))
                          + float(getattr(d, "commission", 0.0)),
                "time":   int(getattr(d, "time", 0)),
            })
        bal = 0.0
        try:
            info = mt5.account_info()
            if info: bal = float(info.balance)
        except Exception:
            pass
        perf = compute_performance(trades, starting_balance=bal)
        return {"ok": True, "performance": perf,
                "magic": magic, "symbol": symbol,
                "since_hours": since_hours, "sample": len(trades)}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
