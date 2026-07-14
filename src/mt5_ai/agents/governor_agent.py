"""governor_agent.py — Position management contributor.

Reads open positions, evaluates them using the governor_v2 decision logic,
and returns PositionManagementRequest objects. Never calls mt5.order_send.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any

from ..core.signal_schema import PositionManagementRequest, PositionAction
from ..core.structured_logger import log_error

log = logging.getLogger("governor_agent")

# Gene score gates (matches original governor_v2 thresholds)
_BLOCK_CLOSE_REVERSE = 0.30
_BLOCK_ALL_CLOSE     = 0.15


@dataclass
class _GovernorDecision:
    action: str          # HOLD | CLOSE | CLOSE_AND_REVERSE | TRAIL_PROFIT | PROTECT_POSITION | EXTEND_TP
    proposed_sl: float
    proposed_tp: float
    reason: str
    reverse_side: str | None  # BUY or SELL


def _position_type_str(pos_type_int: int) -> str:
    try:
        import MetaTrader5 as mt5
        return "BUY" if pos_type_int == mt5.POSITION_TYPE_BUY else "SELL"
    except ImportError:
        return "BUY" if pos_type_int == 0 else "SELL"


def _decide(pos, signal, genes: dict[str, Any], cfg: dict[str, Any]) -> _GovernorDecision:
    """Pure decision logic — no I/O, no MT5 calls."""
    pos_type = _position_type_str(int(pos.type))
    profit   = float(pos.profit)

    close_gap        = float(cfg.get("close_score_gap", 2.2))
    probation_gap    = float(cfg.get("probation_score_gap", 3.2))
    min_adverse_pts  = float(cfg.get("min_adverse_points", 900.0))
    min_loss_usd     = float(cfg.get("min_loss_usd", -1.20))
    hard_loss_usd    = float(cfg.get("hard_loss_usd", -3.00))
    take_profit_rev  = float(cfg.get("take_profit_if_reversal_usd", 0.45))

    trust_map = {k: float(v.get("score", 1.0)) for k, v in (genes.get("advisor_trust") or {}).items()}
    trust_score = 1.0

    agrees   = (pos_type == "BUY"  and getattr(signal, "action_bias", "") == "BUY") or \
               (pos_type == "SELL" and getattr(signal, "action_bias", "") == "SELL")

    buy_score  = float(getattr(signal, "buy_score",  0.0) or 0.0)
    sell_score = float(getattr(signal, "sell_score", 0.0) or 0.0)

    if pos_type == "BUY":
        opposite_gap  = sell_score - buy_score
        favorable_gap = buy_score  - sell_score
        reverse_side  = "SELL"
    else:
        opposite_gap  = buy_score  - sell_score
        favorable_gap = sell_score - buy_score
        reverse_side  = "BUY"

    required_gap = close_gap if trust_score >= 0.75 else probation_gap
    action       = "HOLD"
    reason_parts: list[str] = []

    if profit <= hard_loss_usd:
        action = "CLOSE"
        reason_parts.append(f"hard_loss:{profit:.2f}")
    elif agrees and favorable_gap >= 0.60:
        action = "HOLD"
        reason_parts.append(f"direction_valid:fav={favorable_gap:.2f}")
    else:
        entry = float(pos.price_open)
        curr  = float(pos.price_current)
        try:
            import MetaTrader5 as mt5
            info = mt5.symbol_info(pos.symbol)
            point = float(info.point) if info else 0.00001
        except Exception:
            point = 0.00001

        if pos_type == "BUY":
            adverse_pts = max(0.0, (entry - curr) / point)
        else:
            adverse_pts = max(0.0, (curr - entry) / point)

        if profit >= 0.20:
            required_gap *= 1.6
            take_profit_rev = max(take_profit_rev, 2.00)
            reason_parts.append(f"patience_mode:profit={profit:.2f}")

        if adverse_pts >= min_adverse_pts and opposite_gap >= required_gap:
            action = "CLOSE_AND_REVERSE"
            reason_parts.append("structure_invalidated")
        elif profit <= min_loss_usd and opposite_gap >= required_gap:
            action = "CLOSE_AND_REVERSE"
            reason_parts.append("loss_plus_confirmed_opposite")
        elif profit >= take_profit_rev and opposite_gap >= required_gap * 0.85:
            action = "CLOSE"
            reason_parts.append("bank_profit_reversal")
        else:
            action = "HOLD"
            reason_parts.append("not_enough_proof")

    # Gene score gating
    gov_gid   = f"{pos.symbol}:governor_close:{pos_type}"
    gov_score = float((genes.get("genes") or {}).get(gov_gid, {}).get("score", 1.0) or 1.0)
    is_hard   = profit <= hard_loss_usd

    if action == "CLOSE_AND_REVERSE":
        if gov_score < _BLOCK_ALL_CLOSE and not is_hard:
            action = "HOLD"
            reason_parts.append(f"gene_gate_blocked:{gov_score:.3f}")
            reverse_side = None
        elif gov_score < _BLOCK_CLOSE_REVERSE:
            action = "CLOSE"
            reason_parts.append(f"gene_gate_no_reverse:{gov_score:.3f}")
            reverse_side = None
    elif action == "CLOSE" and gov_score < _BLOCK_ALL_CLOSE and not is_hard:
        action = "HOLD"
        reason_parts.append(f"gene_gate_blocked:{gov_score:.3f}")

    return _GovernorDecision(
        action=action,
        proposed_sl=0.0,
        proposed_tp=0.0,
        reason="|".join(reason_parts),
        reverse_side=reverse_side if action == "CLOSE_AND_REVERSE" else None,
    )


class GovernorAgent:
    """Reads open positions and emits PositionManagementRequest objects.

    Call evaluate_positions() each cycle. The caller passes the results to
    PositionManager → ExecutionManager for actual execution.
    """
    source = "governor_agent"

    def evaluate_positions(
        self,
        positions: list,
        get_signal_fn,
        genes: dict[str, Any],
        cfg: dict[str, Any] | None = None,
    ) -> list[PositionManagementRequest]:
        cfg = cfg or {}
        requests: list[PositionManagementRequest] = []

        for pos in positions:
            try:
                symbol = str(pos.symbol)
                ticket = int(pos.ticket)
                signal = get_signal_fn(symbol)
                if signal is None:
                    continue

                dec = _decide(pos, signal, genes, cfg)
                log.info("governor %s #%d action=%s reason=%s", symbol, ticket, dec.action, dec.reason)

                if dec.action == "CLOSE":
                    requests.append(PositionManagementRequest(
                        position_ticket=ticket,
                        symbol=symbol,
                        action=PositionAction.FULL_CLOSE,
                        reason=dec.reason,
                        source=self.source,
                    ))

                elif dec.action == "CLOSE_AND_REVERSE":
                    requests.append(PositionManagementRequest(
                        position_ticket=ticket,
                        symbol=symbol,
                        action=PositionAction.FULL_CLOSE,
                        reason=f"REVERSE|{dec.reason}",
                        source=self.source,
                    ))

                elif dec.action in ("TRAIL_PROFIT", "PROTECT_POSITION"):
                    requests.append(PositionManagementRequest(
                        position_ticket=ticket,
                        symbol=symbol,
                        action=PositionAction.TRAIL,
                        proposed_sl=dec.proposed_sl,
                        proposed_tp=dec.proposed_tp,
                        reason=dec.reason,
                        source=self.source,
                    ))

            except Exception as exc:
                log_error(self.source, str(exc), {"symbol": getattr(pos, "symbol", "?"), "ticket": getattr(pos, "ticket", 0)})

        return requests
