"""strategy_types.py — shared data contracts for the Prompt-Trading / Pipflow
feature set (mirrors the TS types in the spec, adapted to Python).

These are plain dataclasses with to_dict/from_dict so they round-trip through
JSON (the project's storage convention) and across the Flask /api boundary.

Used by:
  strategy_store.py      — persistence
  strategy_builder.py    — Claude "Polish" output (Strategy)
  live_indicators.py     — IndicatorStatus
  chart_analysis.py      — ChartAnalysis
  signal_engine.py       — unified confluence + structure logic
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Literal


Direction = Literal["LONG", "SHORT", "NONE"]
Methodology = Literal["SMC", "HYBRID", "TECHNICAL", "VOLATILITY"]
Timeframe = Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

# The canonical indicator set used by the dashboard + confluence engine.
INDICATOR_KEYS = [
    "sma_cross", "ema_cross", "macd", "rsi", "supertrend",
    "stochastic", "bollinger", "ao", "sar", "cci", "adx",
]

INDICATOR_LABELS = {
    "sma_cross":  "SMA Cross",
    "ema_cross":  "EMA Cross",
    "macd":       "MACD",
    "rsi":        "RSI",
    "supertrend": "Supertrend",
    "stochastic": "Stochastic",
    "bollinger":  "Bollinger",
    "ao":         "Awesome Osc",
    "sar":        "Parabolic SAR",
    "cci":        "CCI",
    "adx":        "ADX",
}

# Map the project's internal MT5/MTF timeframe names to the spec's labels.
TF_TO_MT5_NAME = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D1",
}


@dataclass
class IndicatorStatus:
    key: str
    label: str
    status: Literal["BULLISH", "BEARISH", "NEUTRAL"] = "NEUTRAL"
    standaloneWR: float = 0.0     # 0..100 win-rate of this indicator alone
    enabled: bool = True

    def to_dict(self) -> dict: return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "IndicatorStatus":
        return cls(
            key=d.get("key", ""), label=d.get("label", d.get("key", "")),
            status=d.get("status", "NEUTRAL"),
            standaloneWR=float(d.get("standaloneWR", 0.0)),
            enabled=bool(d.get("enabled", True)),
        )


@dataclass
class EntryCondition:
    side: Literal["BUY", "SELL", "BOTH"]
    text: str
    confidence: float = 0.0        # 0..100

    def to_dict(self) -> dict: return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EntryCondition":
        return cls(side=d.get("side", "BOTH"), text=d.get("text", ""),
                   confidence=float(d.get("confidence", 0.0)))


@dataclass
class RiskConfig:
    maxPerTradePct: float = 1.0
    dailyLossLimitPct: float = 5.0
    maxOpenTrades: int = 1
    maxPerSymbol: int = 1
    atrLength: int = 14
    slAtrMult: float = 1.0
    tpAtrMults: list = field(default_factory=lambda: [1.0, 2.0, 3.0])
    trailAtrMult: float | None = None
    minConfidence: float = 70.0

    def to_dict(self) -> dict: return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RiskConfig":
        d = d or {}
        tpm = d.get("tpAtrMults") or [1.0, 2.0, 3.0]
        # Coerce to exactly 3 multipliers
        tpm = (list(tpm) + [1.0, 2.0, 3.0])[:3]
        return cls(
            maxPerTradePct=float(d.get("maxPerTradePct", 1.0)),
            dailyLossLimitPct=float(d.get("dailyLossLimitPct", 5.0)),
            maxOpenTrades=int(d.get("maxOpenTrades", 1)),
            maxPerSymbol=int(d.get("maxPerSymbol", 1)),
            atrLength=int(d.get("atrLength", 14)),
            slAtrMult=float(d.get("slAtrMult", 1.0)),
            tpAtrMults=[float(x) for x in tpm],
            trailAtrMult=(None if d.get("trailAtrMult") in (None, "", "null")
                          else float(d["trailAtrMult"])),
            minConfidence=float(d.get("minConfidence", 70.0)),
        )


@dataclass
class Strategy:
    id: str
    name: str
    rawPrompt: str = ""
    systemPrompt: str = ""
    methodology: Methodology = "HYBRID"
    pairs: list = field(default_factory=list)
    timeframe: Timeframe = "15m"
    indicators: list = field(default_factory=list)      # list[IndicatorStatus]
    entryConditions: list = field(default_factory=list)  # list[EntryCondition]
    risk: RiskConfig = field(default_factory=RiskConfig)
    status: Literal["ACTIVE", "PAUSED", "STOPPED"] = "PAUSED"
    createdAt: str = ""

    @staticmethod
    def new_id() -> str:
        return "strat_" + uuid.uuid4().hex[:10]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "rawPrompt": self.rawPrompt,
            "systemPrompt": self.systemPrompt, "methodology": self.methodology,
            "pairs": list(self.pairs), "timeframe": self.timeframe,
            "indicators": [i.to_dict() for i in self.indicators],
            "entryConditions": [e.to_dict() for e in self.entryConditions],
            "risk": self.risk.to_dict(), "status": self.status,
            "createdAt": self.createdAt,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Strategy":
        return cls(
            id=d.get("id") or cls.new_id(),
            name=d.get("name", "Untitled"),
            rawPrompt=d.get("rawPrompt", ""),
            systemPrompt=d.get("systemPrompt", ""),
            methodology=d.get("methodology", "HYBRID"),
            pairs=list(d.get("pairs", [])),
            timeframe=d.get("timeframe", "15m"),
            indicators=[IndicatorStatus.from_dict(i) for i in d.get("indicators", [])],
            entryConditions=[EntryCondition.from_dict(e) for e in d.get("entryConditions", [])],
            risk=RiskConfig.from_dict(d.get("risk", {})),
            status=d.get("status", "PAUSED"),
            createdAt=d.get("createdAt") or _now_iso(),
        )

    @classmethod
    def default(cls, name: str = "New Strategy") -> "Strategy":
        """A sane default strategy with all indicators enabled."""
        return cls(
            id=cls.new_id(), name=name, createdAt=_now_iso(),
            indicators=[IndicatorStatus(k, INDICATOR_LABELS[k]) for k in INDICATOR_KEYS],
            risk=RiskConfig(),
        )


@dataclass
class ChartAnalysis:
    symbol: str
    timeframe: str
    direction: Direction = "NONE"
    entry: float = 0.0
    stop: float = 0.0
    targets: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    riskPct: float = 0.0
    rr: float = 0.0
    confidence: float = 0.0
    structure: str = ""
    rationale: str = ""

    def to_dict(self) -> dict: return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ChartAnalysis":
        tg = d.get("targets") or [0.0, 0.0, 0.0]
        tg = (list(tg) + [0.0, 0.0, 0.0])[:3]
        return cls(
            symbol=d.get("symbol", ""), timeframe=d.get("timeframe", ""),
            direction=d.get("direction", "NONE"),
            entry=float(d.get("entry", 0)), stop=float(d.get("stop", 0)),
            targets=[float(x) for x in tg],
            riskPct=float(d.get("riskPct", 0)), rr=float(d.get("rr", 0)),
            confidence=float(d.get("confidence", 0)),
            structure=d.get("structure", ""), rationale=d.get("rationale", ""),
        )


@dataclass
class Performance:
    totalTrades: int = 0
    wins: int = 0
    losses: int = 0
    winratePct: float = 0.0
    profitFactor: float = 0.0
    pnlPct: float = 0.0

    def to_dict(self) -> dict: return asdict(self)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── LogEntry helper (decision_log already persists; this is the live feed) ──
def log_entry(level: str, tag: str, text: str) -> dict:
    return {"ts": _now_iso(), "level": level, "tag": tag, "text": text}
