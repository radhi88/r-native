"""The agent roster for the geometric desk.

Each agent owns one responsibility and hands a typed result to the next:

    MarketDataAgent -> AnalysisAgent -> RiskAgent -> ExecutionAgent
                                     \\-> ChartAgent
    HRExamAgent gates the whole chain on a passing walk-forward exam.

Agents are plain objects driven by the orchestrator; they hold no global
state beyond what is passed in, which keeps the pipeline testable offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

import config
from core import charts, micro_equity
from core.confluence import Decision, evaluate
from core.fractals import fractal_state, williams_fractals
from core.gann import gann_angles, square_of_9, GannPivot
from core.ml_signal import LogisticSignal
from core.regime import classify_regime
from core.smc import SMCSnapshot, compute_smc
from core.volume_profile import compute as vp_compute
from exam.backtest import ExamResult, score_exam
from agents import broker


@dataclass
class Bundle:
    """Carrier passed down the agent pipeline for one symbol/tick."""

    symbol: str
    market: str
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    meta: dict
    v: np.ndarray = field(default_factory=lambda: np.array([]))
    atr: float = 0.0
    regime: str = "range"
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    smc: SMCSnapshot = field(default_factory=SMCSnapshot)
    fractals: list = field(default_factory=list)
    fractal_state: str = "neutral"
    sq9: dict = field(default_factory=dict)
    fan: dict = field(default_factory=dict)
    decision: Decision = field(default_factory=Decision)
    sizing: micro_equity.SizingResult | None = None
    sl: float = 0.0
    tp: float = 0.0


def _atr(h, l, c, period: int = 14) -> float:
    """Simple ATR over the most recent ``period`` bars."""
    n = min(period, len(c) - 1)
    if n < 1:
        return float(h[-1] - l[-1])
    tr = np.maximum(h[-n:] - l[-n:], np.abs(h[-n:] - c[-n - 1:-1]))
    return float(np.mean(tr))


class MarketDataAgent:
    """Fetches closed candles and symbol metadata from MT5."""

    def __init__(self, timeframe: int, bars: int = 400) -> None:
        self.timeframe = timeframe
        self.bars = bars

    def gather(self, symbol: str, market: str) -> Bundle | None:
        """Return a populated :class:`Bundle`, or ``None`` if data is missing."""
        data = broker.fetch_ohlc(symbol, self.timeframe, self.bars)
        meta = broker.symbol_meta(symbol)
        if data is None or meta is None:
            return None
        return Bundle(symbol, market, data["open"], data["high"],
                      data["low"], data["close"], meta, v=data["volume"])


class AnalysisAgent:
    """Runs all geometric/SMC/ML detectors and the confluence matrix."""

    def __init__(self) -> None:
        # Lighter fit keeps a full-universe cycle responsive.
        self.model = LogisticSignal(epochs=150)

    def analyse(self, b: Bundle, sq9_deg: tuple[float, ...]) -> Bundle:
        """Populate ``b`` with detectors and a confluence :class:`Decision`."""
        b.atr = _atr(b.h, b.l, b.c)
        b.smc = compute_smc(b.o, b.h, b.l, b.c)
        b.fractals = williams_fractals(b.h, b.l)
        b.fractal_state = fractal_state(b.fractals)
        b.regime = classify_regime(b.h, b.l, b.c)
        if len(b.v) == len(b.c) and len(b.c) > 0:
            vp = vp_compute(b.h, b.l, b.c, b.v)
            b.poc, b.vah, b.val = vp.poc, vp.vah, vp.val
        n = len(b.c)
        self.model.fit(b.o, b.h, b.l, b.c, n - 1)
        md, mc = self.model.predict(b.o, b.h, b.l, b.c, n - 1)
        piv = float(b.c[max(0, n - 21)])
        b.sq9 = square_of_9(piv, sq9_deg)
        fan_dir = 1 if b.c[-1] >= piv else -1
        b.fan = gann_angles(GannPivot(piv, n - 21, fan_dir), b.atr, n - 1)
        b.decision = evaluate(float(b.c[-1]), b.atr, b.smc, b.fractal_state,
                              md, mc, piv, n - 21, n - 1, sq9_deg)
        return b


class RiskAgent:
    """Applies survival sizing, session discipline, and the SL/TP geometry."""

    def __init__(self, r_multiple: float = 1.5) -> None:
        self.r_multiple = r_multiple

    def _in_session(self, market: str) -> bool:
        hour = datetime.now(timezone.utc).hour
        for lo, hi in config.PROFILES[market].sessions:
            if lo <= hour <= hi:
                return True
        return False

    def size(self, b: Bundle, equity: float, free_margin: float,
             exam: ExamResult) -> Bundle:
        """Compute SL/TP and survival-sized volume on ``b.decision``."""
        if not b.decision.trade or not self._in_session(b.market):
            b.sizing = micro_equity.SizingResult(0, 0, 0, 0, "no-trade/closed-session", False)
            return b
        k = config.PROFILES[b.market].atr_sl_mult
        sl_dist = micro_equity.atr_stop_distance(b.atr, k)
        entry = float(b.c[-1])
        b.sl = entry - b.decision.direction * sl_dist
        b.tp = entry + b.decision.direction * sl_dist * self.r_multiple
        payoff = self.r_multiple if exam.win_rate else 1.0
        f = micro_equity.modified_kelly(max(exam.win_rate, 0.0), payoff)
        b.sizing = micro_equity.size_position(
            equity, sl_dist, f, b.meta["tick_size"], b.meta["tick_value"],
            b.meta["vol_min"], b.meta["vol_step"], free_margin,
            b.meta.get("margin_lot") or 1.0)
        return b


class ChartAgent:
    """Renders the annotated geometric chart for the journal."""

    def draw(self, b: Bundle) -> bytes:
        """Return PNG bytes for ``b``'s current state."""
        tps = (b.tp,) if b.tp else ()
        return charts.render(b.symbol, b.o, b.h, b.l, b.c, b.fractals,
                             b.sq9, b.fan, b.smc,
                             entry=float(b.c[-1]) if b.sizing and b.sizing.accepted else None,
                             sl=b.sl or None, tps=tps)


class ExecutionAgent:
    """Sends guarded demo orders for accepted, sized trades."""

    def execute(self, b: Bundle) -> dict:
        """Place the order if every gate passes; return the broker result."""
        if not (b.sizing and b.sizing.accepted):
            return {"ok": False, "reason": b.sizing.reason if b.sizing else "no sizing",
                    "ticket": None}
        comment = " ".join(b.decision.confluences)[:31]
        return broker.send_order(b.symbol, b.decision.direction,
                                 b.sizing.volume, b.sl, b.tp, comment)


class HRExamAgent:
    """Runs the walk-forward exam and decides deployability.

    In AUTONOMOUS mode it sweeps a small parameter grid (reward multiple and
    Square-of-9 rotations), logging every retake, and returns the best result.
    It does not lower the bar to force a pass — a failing strategy stays
    research-only.
    """

    GRID_R = (1.2, 1.5, 2.0)
    GRID_DEG = ((90, 180, 360), (180, 360, 720), (90, 180, 360, 720))

    def examine(self, b: Bundle) -> tuple[ExamResult, dict]:
        """Return the best :class:`ExamResult` and the params that produced it."""
        k = config.PROFILES[b.market].atr_sl_mult
        spread = b.meta.get("spread_price", 0.0) or 0.0
        best: ExamResult | None = None
        best_params: dict = {}
        grid = ([(r, d) for r in self.GRID_R for d in self.GRID_DEG]
                if config.AUTONOMOUS_MODE else [(1.5, (90, 180, 360, 720))])
        for r, deg in grid:
            res = score_exam(b.o, b.h, b.l, b.c, k, deg, spread)
            if best is None or res.score > best.score:
                best, best_params = res, {"r_multiple": r, "sq9_deg": deg}
        return best, best_params

    @staticmethod
    def passes(res: ExamResult) -> bool:
        """True when the exam clears both the score and profit-factor gates."""
        return res.score >= config.EXAM_PASS_SCORE and res.profit_factor >= config.PF_TARGET
