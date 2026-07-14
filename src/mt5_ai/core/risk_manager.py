"""risk_manager.py — Validates every trade before execution."""
from __future__ import annotations
import logging
from .signal_schema import DecisionResult, RiskDecision, Direction
from .config_loader import get
from .market_quality import spread_quality
from .structured_logger import log_risk

log = logging.getLogger("risk_manager")

class RiskManager:
    def validate(self, decision: DecisionResult, symbol: str,
                 spread_points: float = 0, open_positions: int = 0,
                 daily_loss_pct: float = 0, account_balance: float = 100_000) -> RiskDecision:

        if decision.action not in (Direction.BUY, Direction.SELL):
            return RiskDecision(approved=True, reason="no_trade_action")

        blocks, warnings = [], []

        # Kill switch
        from .config_loader import is_kill_switch
        if is_kill_switch():
            return RiskDecision(approved=False, reason="kill_switch", blocks=["kill_switch"])

        # Max spread — read nested config safely
        _spread_cfg = get("risk.max_spread_points") or {}
        if isinstance(_spread_cfg, dict):
            max_spread = float(_spread_cfg.get(symbol) or _spread_cfg.get("default") or 350)
        else:
            max_spread = float(_spread_cfg or 350)
        quality = spread_quality(symbol, spread_points, max_spread)
        spread_ok = spread_points <= max_spread
        if not spread_ok:
            blocks.append(f"spread_{spread_points:.1f}>{max_spread}")
        elif quality["spread_quality"] == "wide":
            warnings.append(f"spread_quality_wide:{spread_points:.1f}/{max_spread}")

        # Max open positions
        max_pos = get("risk.max_open_positions") or 3
        pos_ok = open_positions < max_pos
        if not pos_ok:
            blocks.append(f"positions_{open_positions}>={max_pos}")

        # Daily loss
        max_dd = get("risk.max_daily_loss_percent") or 2.0
        dd_ok = daily_loss_pct < max_dd
        if not dd_ok:
            blocks.append(f"daily_loss_{daily_loss_pct:.2f}%>={max_dd}%")

        # Confidence floor
        min_conf = get("confidence.min_decision_confidence") or 0.45
        if decision.confidence < min_conf:
            blocks.append(f"confidence_{decision.confidence:.2f}<{min_conf}")

        # Lot calculation
        max_lot = get("risk.max_lot") or 0.10
        approved = len(blocks) == 0
        reason   = " | ".join(blocks) if blocks else "risk_approved"

        log_risk(symbol, approved, max_lot, reason, warnings)
        return RiskDecision(
            approved=approved, reason=reason,
            max_lot=max_lot, adjusted_lot=max_lot,
            blocks=blocks, warnings=warnings,
            spread_ok=spread_ok, margin_ok=True,
            daily_loss_ok=dd_ok, position_limit_ok=pos_ok,
        )
