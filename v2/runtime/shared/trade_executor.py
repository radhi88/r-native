"""shared/trade_executor.py — Professional order_send wrapper.

Born 2026-05-28 via /design-system Phase 4.

Replaces the ~40 lines of order_send boilerplate every trader copies.
TradeSignal in → TradeRecord out, with retry/contract/log built in.

USAGE:
    from runtime.shared.trade_executor import execute_signal
    from runtime.shared.contracts import TradeSignal

    sig = TradeSignal(symbol="XAUUSDm", side="BUY", lot=0.01,
                      sl=4450.0, tp=4458.0, source="claude_genome",
                      magic=99782, reason="MTF3/3 RSI55 P+4")
    record = execute_signal(sig, log_path=PATHS["claude_genome_trades"])
    if record.accepted:
        risk.mark_trade()

DESIGN:
  • Validates the TradeSignal contract before touching MT5
  • Attempts FOK first, falls back to IOC (deals with broker filling rules)
  • Always returns a TradeRecord (even on failure) — log it always
  • Logs exit-by-exit reason into the magic-specific trade log
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import MetaTrader5 as mt5

from runtime.shared.contracts import (
    TradeSignal, TradeRecord, validate, ContractError,
)


# ──────────────────────────────────────────────────────────
# Internal: append JSONL
# ──────────────────────────────────────────────────────────
def _append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


# ──────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────
def execute_signal(
    sig: TradeSignal,
    log_path: Optional[Path] = None,
    regime: Optional[str] = None,
    session: Optional[str] = None,
    deviation: int = 50,
    comment: Optional[str] = None,
) -> TradeRecord:
    """Validate → send → log → return TradeRecord.

    The caller's only job is to provide a well-formed TradeSignal,
    then check `record.accepted` to decide if to mark_trade() on the sentinel.
    """
    try:
        validate(sig)
    except ContractError as e:
        record = TradeRecord(
            ts=datetime.now(timezone.utc).isoformat(),
            source=sig.source, magic=sig.magic, symbol=sig.symbol,
            side=sig.side, lot=sig.lot, entry=0.0,
            sl=sig.sl, tp=sig.tp, ticket=0, accepted=False,
            error=f"contract: {e}", reason=sig.reason,
            confidence=sig.confidence, regime_at_fire=regime, session_at_fire=session,
        )
        if log_path: _append_jsonl(log_path, record.to_dict())
        return record

    tick = mt5.symbol_info_tick(sig.symbol)
    if not tick:
        record = TradeRecord(
            ts=datetime.now(timezone.utc).isoformat(),
            source=sig.source, magic=sig.magic, symbol=sig.symbol,
            side=sig.side, lot=sig.lot, entry=0.0,
            sl=sig.sl, tp=sig.tp, ticket=0, accepted=False,
            error="no tick", reason=sig.reason, confidence=sig.confidence,
            regime_at_fire=regime, session_at_fire=session,
        )
        if log_path: _append_jsonl(log_path, record.to_dict())
        return record

    entry_price = tick.ask if sig.side == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if sig.side == "BUY" else mt5.ORDER_TYPE_SELL

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": sig.symbol,
        "volume": float(sig.lot),
        "type": order_type,
        "price": entry_price,
        "sl": float(sig.sl),
        "tp": float(sig.tp),
        "deviation": deviation,
        "magic": int(sig.magic),
        "comment": (comment or f"{sig.source[:8]}_{sig.side}")[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    r = mt5.order_send(req)
    if not r or r.retcode != mt5.TRADE_RETCODE_DONE:
        req["type_filling"] = mt5.ORDER_FILLING_IOC
        r = mt5.order_send(req)

    accepted = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)

    record = TradeRecord(
        ts=datetime.now(timezone.utc).isoformat(),
        source=sig.source, magic=sig.magic, symbol=sig.symbol,
        side=sig.side, lot=sig.lot,
        entry=float(r.price) if accepted else float(entry_price),
        sl=float(sig.sl), tp=float(sig.tp),
        ticket=int(r.order) if accepted else 0,
        accepted=accepted,
        error=None if accepted else f"retcode {getattr(r, 'retcode', '?')}",
        reason=sig.reason,
        confidence=sig.confidence,
        regime_at_fire=regime,
        session_at_fire=session,
    )
    if log_path: _append_jsonl(log_path, record.to_dict())
    return record


__all__ = ["execute_signal"]
