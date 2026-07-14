"""Market scanner that wraps existing agents without executing orders."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from mt5_ai.agents.fractal_agent import FractalAgent
from mt5_ai.agents.ict_sweep_agent import IctSweepAgent
from mt5_ai.agents.smc_agent import SmcAgent
from mt5_ai.core.conflict_guard import ConflictGuard
from mt5_ai.core.decision_router import DecisionRouter
from mt5_ai.core.indicators import atr as calc_atr
from mt5_ai.core.market_quality import current_market_session, spread_quality
from mt5_ai.core.risk_manager import RiskManager
from mt5_ai.core.signal_arbiter import SignalArbiter
from mt5_ai.core.signal_schema import Direction

from qader_app.assistant.permissions_guard import PermissionsGuard
from qader_app.assistant.memory import QaderMemory
from qader_app.services.mt5_service import MT5Service
from qader_app.storage.audit_log import log_action


@dataclass(slots=True)
class MarketScanResult:
    symbol: str
    timeframe: str
    fractal_result: str = "NONE"
    smc_result: str = "NONE"
    ict_result: str = "NONE"
    arbiter_result: str = "HOLD"
    confidence: float = 0.0
    reason: str = ""
    risk_status: str = "not_evaluated"
    spread: float = 0.0
    spread_quality: str = "unknown"
    spread_limit: float = 0.0
    spread_ratio: float = 0.0
    session: str = "unknown"
    atr: float = 0.0
    final_action: str = "HOLD"
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ScannerService:
    def __init__(
        self,
        mt5_service: MT5Service | None = None,
        guard: PermissionsGuard | None = None,
        memory: QaderMemory | None = None,
    ):
        self.guard = guard or PermissionsGuard()
        self.mt5_service = mt5_service or MT5Service(self.guard)
        self.memory = memory or QaderMemory()
        self.router = DecisionRouter()
        self.conflict_guard = ConflictGuard()
        self.risk = RiskManager()
        self.arbiter = SignalArbiter()

    def scan_symbols(self, symbols: list[str], timeframes: list[str] | None = None) -> list[dict[str, Any]]:
        timeframes = timeframes or ["M1"]
        results = []
        for symbol in symbols:
            for timeframe in timeframes:
                results.append(self.scan_symbol(symbol, timeframe).to_dict())
        return results

    def scan_symbol(self, symbol: str, timeframe: str = "M1") -> MarketScanResult:
        perm = self.guard.check("can_scan_market", "scan_symbol", "scanner_service")
        if not perm.allowed:
            return MarketScanResult(symbol, timeframe, error=perm.reason, reason=perm.reason)
        read_perm = self.guard.check("can_read_mt5", "read_mt5_for_scan", "scanner_service")
        if not read_perm.allowed:
            return MarketScanResult(symbol, timeframe, error=read_perm.reason, reason=read_perm.reason)

        df = self.mt5_service.fetch_bars(symbol, timeframe)
        if df is None or len(df) < 50:
            reason = "offline_or_insufficient_mt5_data"
            log_action("scan_symbol", "can_scan_market", False, reason, "scanner_service", metadata={"symbol": symbol, "timeframe": timeframe})
            return MarketScanResult(symbol, timeframe, reason=reason, error=reason)

        raw_signals = []
        agent_outputs: dict[str, str] = {"fractal_agent": "NONE", "smc_agent": "NONE", "ict_sweep_agent": "NONE"}
        for agent in (FractalAgent(), SmcAgent(), IctSweepAgent()):
            try:
                sig = agent.analyse(df, symbol, timeframe)
                if sig:
                    raw_signals.append(sig)
                    agent_outputs[sig.source] = sig.direction.value
            except Exception as exc:
                agent_outputs[getattr(agent, "source", agent.__class__.__name__)] = f"ERROR:{exc}"

        arb = self.arbiter.decide(raw_signals, symbol, timeframe)
        spread = self.mt5_service.spread_points(symbol)
        quality = spread_quality(symbol, spread)
        result = MarketScanResult(
            symbol=symbol,
            timeframe=timeframe,
            fractal_result=agent_outputs.get("fractal_agent", "NONE"),
            smc_result=agent_outputs.get("smc_agent", "NONE"),
            ict_result=agent_outputs.get("ict_sweep_agent", "NONE"),
            arbiter_result=arb.final_direction.value,
            confidence=round(float(arb.final_confidence), 4),
            reason=arb.reason,
            spread=spread,
            spread_quality=str(quality["spread_quality"]),
            spread_limit=float(quality["spread_limit"]),
            spread_ratio=float(quality["spread_ratio"]),
            session=current_market_session(),
            atr=round(calc_atr(df, 14), 6),
            final_action=arb.final_direction.value,
        )

        if arb.final_direction in (Direction.BUY, Direction.SELL):
            arb_signal = arb.to_signal_proposal()
            decision = self.router.route([arb_signal], symbol, timeframe)
            allow, conflicts = self.conflict_guard.check(decision, [arb_signal], {})
            if not allow:
                result.risk_status = "conflict_blocked:" + ",".join(conflicts)
                result.final_action = "HOLD"
            else:
                risk_decision = self.risk.validate(decision, symbol, spread_points=result.spread, open_positions=0)
                result.risk_status = "approved" if risk_decision.approved else f"risk_blocked:{risk_decision.reason}"
                if not risk_decision.approved:
                    result.final_action = "HOLD"
        else:
            result.risk_status = "not_reached"

        payload = result.to_dict()
        self.memory.set_last_decision(payload)
        log_action("scan_symbol", "can_scan_market", True, "scan_complete_no_execution", "scanner_service", result=payload)
        return result
