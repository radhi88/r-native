"""shared/contracts.py — Interface Contracts between components.

Born 2026-05-28 via /design-system Phase 3.

These are the STRUCTURAL agreements between every layer of the trading
system. If a producer writes a snapshot, a consumer must know exactly
what fields exist, what types they have, and which are required.

CONTRACTS DEFINED:
  • BrainSnapshot       — what brain_live.json must contain
  • RegimeReport        — what market_regime.json must contain
  • OrchestratorDecision — what active_engines.json must contain
  • TradeSignal         — what every trader emits before order_send
  • TradeRecord         — what every trader logs after order_send
  • GenomeSpec          — what a live_genome.json must contain
  • GenomeFitness       — what a genome must report per cycle
  • CouncilVote         — what palace_council writes per round
  • FootprintCell       — what MT5 footprint indicator exports

USAGE:
    from runtime.shared.contracts import TradeSignal, validate
    sig = TradeSignal(symbol="XAUUSDm", side="BUY", lot=0.01,
                      sl=4452.0, tp=4460.0, source="claude_genome",
                      reason="MTF=3, RSI<60, pressure +4")
    validate(sig)              # raises on bad shape
    sig.to_dict()              # serializable form

DESIGN PRINCIPLE:
  Every IPC file in /data should have a contract here. If a new
  consumer joins later, it can validate the producer's output
  with one call instead of reverse-engineering the JSON.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal, Optional


# ─────────────────────────────────────────────────────────────────
# PRIMITIVES — common enums + shapes
# ─────────────────────────────────────────────────────────────────
Side       = Literal["BUY", "SELL"]
Regime     = Literal["TREND_UP", "TREND_DOWN", "CHOP", "SPIKE", "TRANSITION"]
Bias       = Literal["BULL", "BEAR", "FLAT"]
Quality    = Literal["best", "high", "medium", "low", "skip"]
Timeframe  = Literal["M1", "M5", "M15", "H1", "H4", "D1"]


def _now_iso() -> str:
    """Standard UTC timestamp for all contracts."""
    return datetime.now(timezone.utc).isoformat()


class ContractError(ValueError):
    """Raised when a contract is violated."""


# ─────────────────────────────────────────────────────────────────
# 1. BRAIN SNAPSHOT — produced by brain_capture, read by everyone
# ─────────────────────────────────────────────────────────────────
@dataclass
class BrainSnapshot:
    """Live market snapshot — written every TIMING['brain_capture'] seconds."""
    ts: str                              # UTC ISO
    symbol: str
    price: dict[str, float]              # {"bid": x, "ask": y}
    bias: dict[str, Bias]                # {"m1": "BULL", "m5": "BULL", ...}
    rsi: dict[str, float]                # {"m1": 55.3, "m5": 60.1, ...}
    atr: dict[str, float]                # {"m1": 0.3, "h1": 8.0}
    mtf_align: str                       # e.g. "3/3", "2/3", "MIXED"
    pressure_10m1: int                   # sum of bull−bear over last 10 m1 bars
    session: str                         # ASIAN | LONDON | NY_OVERLAP | NY_LATE | TRANSITION
    m1_last5: list[dict[str, Any]]       # last 5 m1 bars
    archetype: Optional[str] = None      # if pattern matched
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────
# 2. REGIME REPORT — produced by regime_classifier
# ─────────────────────────────────────────────────────────────────
@dataclass
class RegimeReport:
    """What the regime classifier writes to market_regime.json."""
    ts: str
    regime: Regime
    reason: str                          # human-readable why
    advice: str                          # e.g. "STAY OUT — high SL whipsaw risk"
    metrics: dict[str, float]            # adx_m5, plus_di, minus_di, atr_m5, vol_ratio, ema9/21/50, range_m5_20
    recommended_traders: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────
# 3. ORCHESTRATOR DECISION — picks active engines per regime
# ─────────────────────────────────────────────────────────────────
@dataclass
class OrchestratorDecision:
    """What trader_orchestrator writes to active_engines.json."""
    ts: str
    regime: Regime
    active_magics: list[int]             # engines allowed to enter trades NOW
    standby_magics: list[int]            # may only manage existing positions
    reasoning: list[str]                 # ordered bullets explaining decision
    regime_metrics: dict[str, float] = field(default_factory=dict)
    genome_live: str = "NONE"

    def to_dict(self) -> dict:
        return asdict(self)

    def is_active(self, magic: int) -> bool:
        """Cheap check before any trader fires an entry."""
        return magic in self.active_magics


# ─────────────────────────────────────────────────────────────────
# 4. TRADE SIGNAL — every trader emits this BEFORE order_send
# ─────────────────────────────────────────────────────────────────
@dataclass
class TradeSignal:
    """Pre-trade intent. Validate this before sending to MT5."""
    symbol: str
    side: Side
    lot: float
    sl: float                            # absolute price
    tp: float                            # absolute price
    source: str                          # which trader (e.g. "claude_genome")
    magic: int
    reason: str                          # human-readable confluence summary
    confidence: float = 0.5              # 0..1
    ts: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.lot <= 0:
            raise ContractError(f"{self.source}: lot must be > 0, got {self.lot}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ContractError(f"{self.source}: confidence must be in [0,1]")
        if self.side == "BUY" and self.sl >= self.tp:
            raise ContractError(f"{self.source}: BUY requires sl < tp")
        if self.side == "SELL" and self.sl <= self.tp:
            raise ContractError(f"{self.source}: SELL requires sl > tp")
        if self.magic <= 0:
            raise ContractError(f"{self.source}: magic must be > 0")

    @property
    def risk_pts(self) -> float:
        """Distance from entry to SL — used for risk sizing."""
        return abs(self.tp - self.sl)  # rough; producer should pass entry price too

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────
# 5. TRADE RECORD — every trader appends this AFTER order_send
# ─────────────────────────────────────────────────────────────────
@dataclass
class TradeRecord:
    """Post-trade log entry — append to TRADE_LOGS[source]."""
    ts: str
    source: str
    magic: int
    symbol: str
    side: Side
    lot: float
    entry: float
    sl: float
    tp: float
    ticket: int                          # MT5 ticket; 0 if rejected
    accepted: bool                       # True if MT5 accepted the order
    error: Optional[str] = None
    reason: str = ""                     # confluence summary at fire time
    confidence: float = 0.5
    regime_at_fire: Optional[Regime] = None
    session_at_fire: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────
# 6. GENOME SPEC — what live_genome.json must contain
# ─────────────────────────────────────────────────────────────────
@dataclass
class GenomeSpec:
    """A promoted genome ready for live trading."""
    name: str                            # e.g. "GEN-AGGRESSIVE", "GEN-50-W7"
    generation: int
    promoted_ts: str
    params: dict[str, Any]               # rsi_max, min_imb_count, min_pressure_abs,
                                         # min_mtf_agreement, use_footprint, lot, sl_pts, tp_pts
    parents: list[str] = field(default_factory=list)
    fitness_at_promotion: float = 0.0
    notes: str = ""

    REQUIRED_PARAMS = (
        "rsi_max", "min_imb_count", "min_pressure_abs",
        "min_mtf_agreement", "use_footprint", "lot", "sl_pts", "tp_pts",
    )

    def validate(self) -> None:
        missing = [p for p in self.REQUIRED_PARAMS if p not in self.params]
        if missing:
            raise ContractError(f"genome {self.name}: missing params {missing}")
        if self.params["lot"] <= 0:
            raise ContractError(f"genome {self.name}: lot must be > 0")

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────
# 7. GENOME FITNESS — per-cycle scorecard
# ─────────────────────────────────────────────────────────────────
@dataclass
class GenomeFitness:
    """How a genome scored over its evaluation window."""
    name: str
    generation: int
    cycles: int                          # snapshots evaluated
    buy_signals: int
    sell_signals: int
    wait_signals: int
    avg_confidence_on_signal: float
    realized_trades: int = 0
    realized_wins: int = 0
    realized_pnl: float = 0.0
    last_update_ts: str = field(default_factory=_now_iso)

    @property
    def signal_rate(self) -> float:
        total = self.buy_signals + self.sell_signals + self.wait_signals
        return 0.0 if total == 0 else (self.buy_signals + self.sell_signals) / total

    @property
    def win_rate(self) -> float:
        return 0.0 if self.realized_trades == 0 else self.realized_wins / self.realized_trades

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────
# 8. COUNCIL VOTE — palace_council per-round output
# ─────────────────────────────────────────────────────────────────
@dataclass
class CouncilVote:
    """Single round of the 5-expert vote."""
    ts: str
    round_id: int
    proposal: dict[str, Any]             # the trade idea on the table
    votes: dict[str, dict[str, Any]]     # {"architect": {"vote": "YES", "reason": "..."}}
    approved: bool                       # True if quorum (default 3/5 YES)
    executed: bool = False               # True if execute_approved fired order_send
    ticket: Optional[int] = None         # MT5 ticket if executed

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────
# 9. FOOTPRINT CELL — what the MT5 indicator exports
# ─────────────────────────────────────────────────────────────────
@dataclass
class FootprintCell:
    """One bid×ask cell from the footprint indicator."""
    ts: int                              # bar epoch seconds
    price_lo: float
    price_hi: float
    bid_vol: int
    ask_vol: int
    delta: int                           # ask_vol − bid_vol
    is_imbalance: bool = False           # passed imbalance ratio threshold
    imb_side: Optional[Side] = None      # which side caused imbalance

    @property
    def total_vol(self) -> int:
        return self.bid_vol + self.ask_vol

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────
# VALIDATION HELPERS
# ─────────────────────────────────────────────────────────────────
def validate(obj: Any) -> None:
    """Generic validation dispatcher.

    Any contract with a .validate() method gets called.
    Used as a one-liner gate in producers before writing/sending.
    """
    if hasattr(obj, "validate"):
        obj.validate()


def ensure_keys(d: dict, required: tuple[str, ...], label: str = "object") -> None:
    """Sanity-check a raw dict has the required keys.

    Useful when reading IPC files that haven't been wrapped in a dataclass yet.
    """
    missing = [k for k in required if k not in d]
    if missing:
        raise ContractError(f"{label}: missing keys {missing}")


# ─────────────────────────────────────────────────────────────────
# IPC CONTRACT MAP — file path → required keys
# ─────────────────────────────────────────────────────────────────
# Lets any consumer pre-flight a JSON file in one call:
#   from runtime.shared.contracts import IPC_REQUIRED
#   ensure_keys(json.load(...), IPC_REQUIRED["brain_live"], "brain_live")
IPC_REQUIRED: dict[str, tuple[str, ...]] = {
    "brain_live":     ("ts", "symbol", "bias", "rsi", "mtf_align", "session"),
    "market_regime":  ("ts", "regime", "reason", "metrics"),
    "active_engines": ("ts", "regime", "active_magics", "standby_magics"),
    "live_genome":    ("name", "generation", "promoted_ts", "params"),
}


__all__ = [
    # primitives
    "Side", "Regime", "Bias", "Quality", "Timeframe",
    "ContractError",
    # dataclasses
    "BrainSnapshot", "RegimeReport", "OrchestratorDecision",
    "TradeSignal", "TradeRecord",
    "GenomeSpec", "GenomeFitness",
    "CouncilVote", "FootprintCell",
    # helpers
    "validate", "ensure_keys", "IPC_REQUIRED",
]
