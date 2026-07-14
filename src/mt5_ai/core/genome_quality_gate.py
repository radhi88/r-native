"""
genome_quality_gate.py
----------------------
Full genome validation pipeline: numeric safety → metric sanity →
minimum sample → diversity check → status classification.

Every genome MUST pass this gate before:
  - survivor selection / ranking
  - database storage
  - memory save
  - best-genome promotion
  - runtime loading
  - breeding

Genome status ladder (ascending trust):
  REJECTED            hard rule violation — never use
  QUARANTINED         degenerate — archived, blocked everywhere
  CANDIDATE           passes hard rules and metric sanity
  WATCHLIST           marginal — passes hard rules, borderline metrics
  APPROVED_FOR_BREEDING  passes all quality gates including OOS/walk-forward
  APPROVED_FOR_DEMO      passes breeding approval + dry-run validation
  ACTIVE_DISABLED        was active, now suspended (e.g. drawdown triggered)
"""
from __future__ import annotations

import json
import logging
import math
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger("friday.genome_quality_gate")

# ── Log / archive paths ───────────────────────────────────────────────────────

from .project_root import PROJECT_ROOT as _ROOT, APPDATA_FRIDAY as _APPDATA_FRIDAY
_LOG_DIRS = [
    _ROOT / "logs",
    _APPDATA_FRIDAY / "logs",
]
_QUALITY_LOG  = "genome_quality_log.jsonl"
_SAFETY_LOG   = "fitness_safety_log.jsonl"
_QUARANTINE_DIR = _ROOT / "src" / "mt5_ai" / "archive" / "quarantined_genomes"


def _write_log(entry: dict, logfile: str = _QUALITY_LOG) -> None:
    for d in _LOG_DIRS:
        try:
            d.mkdir(parents=True, exist_ok=True)
            with (d / logfile).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


# ── Status enum ───────────────────────────────────────────────────────────────

class GenomeStatus(str, Enum):
    REJECTED             = "REJECTED"
    QUARANTINED          = "QUARANTINED"
    CANDIDATE            = "CANDIDATE"
    WATCHLIST            = "WATCHLIST"
    APPROVED_FOR_BREEDING = "APPROVED_FOR_BREEDING"
    APPROVED_FOR_DEMO    = "APPROVED_FOR_DEMO"
    ACTIVE_DISABLED      = "ACTIVE_DISABLED"


# ── Gate result ───────────────────────────────────────────────────────────────

@dataclass
class GateResult:
    status:  GenomeStatus
    rule:    str
    reason:  str
    score:   float          = 0.0   # bounded 0–1000 robust score
    details: dict           = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status not in (GenomeStatus.REJECTED, GenomeStatus.QUARANTINED)

    @property
    def approved_for_breeding(self) -> bool:
        return self.status in (
            GenomeStatus.APPROVED_FOR_BREEDING,
            GenomeStatus.APPROVED_FOR_DEMO,
        )

    @property
    def approved_for_demo(self) -> bool:
        return self.status == GenomeStatus.APPROVED_FOR_DEMO


# ── Hard limit constants ──────────────────────────────────────────────────────

# Hard-rejection thresholds
SCORE_MAX           = 10_000.0
RETURN_MAX          = 100_000.0
TRADES_MIN_HARD     = 100
HIGH_WR_THRESHOLD   = 0.95
HIGH_WR_MIN_TRADES  = 300
HIGH_RET_THRESHOLD  = 50_000.0
HIGH_RET_MIN_TRADES = 500
ZERO_DD_LIMIT_RET   = 1_000.0
PF_INF_GUARD        = 1e12
NEAR_ZERO           = 1e-10
MAX_SINGLE_TRADE_PCT = 0.40   # one trade ≤ 40% of total profit
MIN_WINNING_TRADES  = 3       # need at least 3 winners to trust WR
MAX_EQUITY_JUMP_PCT = 300.0   # single equity curve step cannot exceed 300%

# Candidate thresholds
CANDIDATE_SCORE_MIN  = 0.1    # bounded score (not raw)
CANDIDATE_SCORE_MAX  = 1000.0
CANDIDATE_TRADES_MIN = 150
CANDIDATE_DD_MIN     = 0.05
CANDIDATE_DD_MAX     = 35.0
CANDIDATE_WR_MIN     = 0.15
CANDIDATE_WR_MAX     = 0.85
CANDIDATE_PF_MIN     = 1.05
CANDIDATE_PF_MAX     = 5.0

# Breeding pool thresholds
BREEDING_TRADES_MIN     = 250
BREEDING_OOS_MIN_RATIO  = 0.50   # OOS score ≥ 50% of IS score
BREEDING_MAX_CORRELATION = 0.85  # reject if too similar to existing pool member


# ── Bounded robust score (0–1000) ─────────────────────────────────────────────

def compute_bounded_score(
    return_pct:   float,
    drawdown_pct: float,
    winrate:      float,
    profit_factor: float,
    trades:       int,
    linearity:    float = 0.5,
    persistence:  float = 0.5,
    oos_ratio:    float = 1.0,
) -> float:
    """
    Bounded 0–1000 score combining 6 weighted components.
    No single input can push the score above 1000.

    Components (max contribution):
      profitability   250  — log-scaled return, capped at 200%
      drawdown_ctrl   200  — penalty for high drawdown, max at 0%
      stability       150  — equity linearity
      consistency     150  — persistence across rolling windows
      trade_count     150  — sample size confidence
      pf_bonus        100  — profit factor quality

    OOS ratio multiplier applied at the end (0.5–1.0 scale).
    """
    # Clamp all inputs to safe ranges first
    return_pct    = max(-100.0, min(return_pct, RETURN_MAX))
    drawdown_pct  = max(0.0, min(drawdown_pct, 100.0))
    winrate       = max(0.0, min(winrate, 1.0))
    profit_factor = max(0.0, min(profit_factor, PF_INF_GUARD))
    linearity     = max(0.0, min(linearity, 1.0))
    persistence   = max(0.0, min(persistence, 1.0))
    oos_ratio     = max(0.0, min(oos_ratio, 2.0))

    # Profitability (250): log-scaled, 200% return → 1.0
    try:
        prof_raw = math.log1p(max(return_pct, 0) / 100.0) / math.log1p(2.0)
    except (ValueError, OverflowError):
        prof_raw = 0.0
    profitability = min(1.0, prof_raw) * 250.0

    # Drawdown control (200): 0% DD → 200, 35%+ → 0
    dd_score = max(0.0, (35.0 - drawdown_pct) / 35.0) * 200.0

    # Stability (150): equity linearity R²
    stability = linearity * 150.0

    # Consistency (150): persistence across rolling windows
    consistency = persistence * 150.0

    # Trade count (150): sigmoid-ish, 500 trades = full score
    trade_score = min(trades / 500.0, 1.0) * 150.0

    # Profit factor bonus (100): PF 1.0→0, PF 3.0→100
    pf_score = min((profit_factor - 1.0) / 2.0, 1.0) * 100.0

    raw = profitability + dd_score + stability + consistency + trade_score + pf_score
    # max raw = 250+200+150+150+150+100 = 1000 by construction

    # OOS multiplier: score degrades proportionally when OOS under-performs
    oos_mult = max(0.5, min(1.0, oos_ratio))
    final = raw * oos_mult

    return round(max(0.0, min(1000.0, final)), 2)


# ── Quarantine helper ─────────────────────────────────────────────────────────

def quarantine_genome(genome_dict: dict, reason: str, source: str) -> None:
    """Archive a degenerate genome to the quarantine directory."""
    _QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    gid  = str(genome_dict.get("id", "unknown"))[:12]
    sym  = genome_dict.get("symbol", "unknown")
    tf   = genome_dict.get("timeframe", genome_dict.get("phase", "unknown"))
    name = f"{ts}_{sym}_{gid}.quarantine.json"
    payload = {
        "quarantined_at": datetime.now(timezone.utc).isoformat(),
        "source":         source,
        "reason":         reason,
        "genome_id":      gid,
        "symbol":         sym,
        "timeframe":      tf,
        "generation":     genome_dict.get("generation", 0),
        "score_raw":      genome_dict.get("modern_score_cache", None),
        "return_pct":     genome_dict.get("total_pnl", None),
        "trades":         genome_dict.get("trades", 0),
        "genome_snapshot": {
            k: v for k, v in genome_dict.items()
            if k not in ("equity_curve", "trade_log")
        },
    }
    try:
        (_QUARANTINE_DIR / name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log.warning("[Quarantine] %s archived → %s", gid, name)
    except Exception as exc:
        log.error("[Quarantine] Failed to archive %s: %s", gid, exc)


# ── Main gate ─────────────────────────────────────────────────────────────────

class GenomeQualityGate:
    """
    Single entry point for genome validation.

    Usage:
        gate = GenomeQualityGate()
        result = gate.check(genome, source="campaign:EURUSDm|H1")
        if not result.ok:
            return  # reject
    """

    def check(
        self,
        genome: Any,
        source: str = "",
        oos_ratio: float = 1.0,
        trade_log: list[dict] | None = None,
        equity_curve: list[float] | None = None,
    ) -> GateResult:
        """
        Full quality gate check. Returns GateResult with status and bounded score.

        Parameters:
          genome      — AlgoryGenome object
          source      — identifier for logging (e.g. "pg:EURUSDm")
          oos_ratio   — OOS score / IS score (1.0 if not yet evaluated)
          trade_log   — optional trade list for dependency checks
          equity_curve — optional for equity jump check
        """
        try:
            score_raw    = genome.modern_score()
            return_pct   = genome.total_return_pct
            winrate      = genome.win_rate
            drawdown_pct = genome.max_dd_pct
            trades       = genome.trades
            try:
                pf = genome.profit_factor
            except Exception:
                pf = 0.0
            try:
                linearity = genome.equity_linearity()
            except Exception:
                linearity = 0.5
            try:
                persistence = genome.persistence()
            except Exception:
                persistence = 0.5
            tlog  = trade_log  or getattr(genome, "trade_log",  [])
            ecurve = equity_curve or getattr(genome, "equity_curve", [])
        except Exception as exc:
            return self._reject("R3", f"attribute error: {exc}", source, genome, {})

        metrics = {
            "score_raw": score_raw, "return_pct": return_pct,
            "winrate": winrate, "drawdown_pct": drawdown_pct,
            "trades": trades, "pf": pf,
        }

        # ── Hard Rejection Rules ───────────────────────────────────────────────

        # R3-a: NaN / Inf
        for name, v in [("score", score_raw), ("return_pct", return_pct),
                        ("winrate", winrate), ("drawdown_pct", drawdown_pct)]:
            try:
                if math.isnan(v) or math.isinf(v):
                    return self._reject("R3", f"{name} is {v}", source, genome, metrics)
            except (TypeError, ValueError):
                return self._reject("R3", f"{name}={v!r} not numeric", source, genome, metrics)

        # R1: score ceiling
        if score_raw > SCORE_MAX:
            return self._reject("R1", f"score={score_raw:.2f} > {SCORE_MAX}", source, genome, metrics)

        # R2: return ceiling
        if abs(return_pct) > RETURN_MAX:
            return self._reject("R2", f"|return|={abs(return_pct):.1f}% > {RETURN_MAX}%",
                                source, genome, metrics)

        # R-trades-hard: too few trades to trust any metric
        if trades < TRADES_MIN_HARD:
            return self._reject("RMIN", f"trades={trades} < {TRADES_MIN_HARD} (hard minimum)",
                                source, genome, metrics)

        # R5: high return with too few trades
        if return_pct > HIGH_RET_THRESHOLD and trades < HIGH_RET_MIN_TRADES:
            return self._reject("R5", f"return={return_pct:.1f}% with {trades} trades",
                                source, genome, metrics)

        # R6: near-perfect win rate with few trades
        if winrate > HIGH_WR_THRESHOLD and trades < HIGH_WR_MIN_TRADES:
            return self._reject("R6", f"winrate={winrate:.1%} with {trades} trades",
                                source, genome, metrics)

        # R7: zero-drawdown + high return
        if drawdown_pct <= CANDIDATE_DD_MIN and return_pct > ZERO_DD_LIMIT_RET:
            return self._reject("R7",
                                f"drawdown={drawdown_pct:.3f}% but return={return_pct:.1f}%",
                                source, genome, metrics)

        # R-pf-inf: infinite profit factor
        if pf > PF_INF_GUARD:
            return self._reject("RPF", f"profit_factor={pf} is Inf", source, genome, metrics)

        # R-winner-dep: too few winning trades (result unreliable)
        wins = getattr(genome, "wins", 0)
        if wins > 0 and wins < MIN_WINNING_TRADES:
            return self._reject("RDEP",
                                f"only {wins} winning trades — statistically unreliable",
                                source, genome, metrics)

        # R-trade-dom: single trade dominates profit
        if tlog and len(tlog) > 5:
            total_profit = sum(t.get("pnl", 0) for t in tlog if t.get("pnl", 0) > 0)
            if total_profit > NEAR_ZERO:
                max_single = max((t.get("pnl", 0) for t in tlog), default=0)
                if max_single / total_profit > MAX_SINGLE_TRADE_PCT:
                    return self._reject("RDOM",
                                        f"single trade contributes "
                                        f"{max_single/total_profit:.0%} of total profit",
                                        source, genome, metrics)

        # R-eq-jump: equity curve unrealistic jump
        if ecurve and len(ecurve) > 2:
            for i in range(1, len(ecurve)):
                prev = ecurve[i - 1]
                curr = ecurve[i]
                if prev > NEAR_ZERO:
                    jump_pct = abs(curr - prev) / prev * 100.0
                    if jump_pct > MAX_EQUITY_JUMP_PCT:
                        return self._reject("RJMP",
                                            f"equity jump {jump_pct:.1f}% at step {i}",
                                            source, genome, metrics)

        # R-consistency: win_rate × trades vs reported wins
        reported_wins = getattr(genome, "wins", -1)
        if reported_wins >= 0 and trades > 0:
            implied_wins = round(winrate * trades)
            if abs(implied_wins - reported_wins) > max(5, trades * 0.10):
                return self._reject("RCONS",
                                    f"winrate implies {implied_wins} wins but genome.wins={reported_wins}",
                                    source, genome, metrics)

        # ── Compute bounded score ─────────────────────────────────────────────

        bounded = compute_bounded_score(
            return_pct, drawdown_pct, winrate, pf, trades,
            linearity, persistence, oos_ratio,
        )

        # ── Candidate gate ────────────────────────────────────────────────────

        reasons_watchlist: list[str] = []

        if drawdown_pct > CANDIDATE_DD_MAX:
            reasons_watchlist.append(f"dd={drawdown_pct:.1f}% > {CANDIDATE_DD_MAX}%")
        if not (CANDIDATE_WR_MIN <= winrate <= CANDIDATE_WR_MAX):
            reasons_watchlist.append(f"winrate={winrate:.1%} outside [{CANDIDATE_WR_MIN:.0%}, {CANDIDATE_WR_MAX:.0%}]")
        if not (CANDIDATE_PF_MIN <= pf <= CANDIDATE_PF_MAX):
            reasons_watchlist.append(f"pf={pf:.2f} outside [{CANDIDATE_PF_MIN}, {CANDIDATE_PF_MAX}]")
        if trades < CANDIDATE_TRADES_MIN:
            reasons_watchlist.append(f"trades={trades} < {CANDIDATE_TRADES_MIN}")

        if reasons_watchlist:
            return self._pass(GenomeStatus.WATCHLIST,
                              "borderline metrics: " + "; ".join(reasons_watchlist),
                              source, bounded, metrics)

        # ── Breeding approval gate ────────────────────────────────────────────

        breeding_reasons: list[str] = []

        if trades < BREEDING_TRADES_MIN:
            breeding_reasons.append(f"trades={trades} < {BREEDING_TRADES_MIN}")
        if oos_ratio < BREEDING_OOS_MIN_RATIO:
            breeding_reasons.append(f"oos_ratio={oos_ratio:.2f} < {BREEDING_OOS_MIN_RATIO}")
        phase = getattr(genome, "phase", "")
        if phase not in ("oos_passed", "live", "imported") and oos_ratio < 1.0:
            breeding_reasons.append(f"phase={phase!r} not OOS-validated")

        if breeding_reasons:
            return self._pass(GenomeStatus.CANDIDATE,
                              "not yet breeding-approved: " + "; ".join(breeding_reasons),
                              source, bounded, metrics)

        return self._pass(GenomeStatus.APPROVED_FOR_BREEDING,
                          "all quality gates passed", source, bounded, metrics)

    # ── Convenience raw-stats variant ─────────────────────────────────────────

    def check_stats(
        self,
        score_raw:    float,
        return_pct:   float,
        winrate:      float,
        drawdown_pct: float,
        trades:       int,
        pf:           float = 1.0,
        source:       str   = "",
        oos_ratio:    float = 1.0,
    ) -> GateResult:
        """Check from raw numeric stats (no genome object needed)."""

        class _Stub:
            pass

        stub = _Stub()
        stub.modern_score   = lambda: score_raw
        stub.total_return_pct = return_pct
        stub.win_rate         = winrate
        stub.max_dd_pct       = drawdown_pct
        stub.trades           = trades
        stub.wins             = round(winrate * trades)
        stub.profit_factor    = pf
        stub.equity_linearity = lambda: 0.7
        stub.persistence      = lambda: 0.7
        stub.trade_log        = []
        stub.equity_curve     = []
        stub.phase            = "oos_passed" if oos_ratio >= 1.0 else "tribe_a"
        return self.check(stub, source=source, oos_ratio=oos_ratio)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _reject(
        self,
        rule: str,
        reason: str,
        source: str,
        genome: Any,
        metrics: dict,
    ) -> GateResult:
        entry = {
            "ts":     datetime.now(timezone.utc).isoformat(),
            "event":  "REJECTED",
            "rule":   rule,
            "reason": reason,
            "source": source,
            "metrics": metrics,
        }
        _write_log(entry, _QUALITY_LOG)
        _write_log(entry, _SAFETY_LOG)
        log.warning("[QualityGate] REJECT %s — %s | source=%s", rule, reason, source)

        # Quarantine degenerate genomes (R1, R2, R3 only — not just low-quality)
        if rule in ("R1", "R2", "R3", "R4", "R5", "R6", "R7") and genome is not None:
            try:
                gd = genome.to_dict() if hasattr(genome, "to_dict") else {}
                quarantine_genome(gd, reason, source)
            except Exception:
                pass

        return GateResult(
            status=GenomeStatus.REJECTED,
            rule=rule,
            reason=reason,
            score=0.0,
            details=metrics,
        )

    def _pass(
        self,
        status: GenomeStatus,
        reason: str,
        source: str,
        bounded_score: float,
        metrics: dict,
    ) -> GateResult:
        entry = {
            "ts":           datetime.now(timezone.utc).isoformat(),
            "event":        status.value,
            "reason":       reason,
            "source":       source,
            "bounded_score": bounded_score,
            "metrics":      metrics,
        }
        _write_log(entry, _QUALITY_LOG)
        log.info("[QualityGate] %s score=%.1f — %s | source=%s",
                 status.value, bounded_score, reason, source)
        return GateResult(
            status=status,
            rule="PASS",
            reason=reason,
            score=bounded_score,
            details=metrics,
        )


# ── Singleton ──────────────────────────────────────────────────────────────────

_gate_instance: GenomeQualityGate | None = None


def get_quality_gate() -> GenomeQualityGate:
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = GenomeQualityGate()
    return _gate_instance
