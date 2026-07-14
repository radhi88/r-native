"""
numeric_safety.py
-----------------
Hard validation gate for genome fitness scores. Rejects overflow, NaN, Inf,
and degenerate statistical patterns before they reach ranking, selection,
survivor registry, or storage.

Eight rejection rules:
  R1  score > 10 000               — impossible in valid Modern scoring
  R2  |return_pct| > 100 000       — overflow / simulation error
  R3  NaN or Inf in any metric     — corrupted computation
  R4  ERANGE (errno=34) overflow   — caller catches and calls reject_erange()
  R5  return_pct > 50 000 with < 500 trades  — too few trades for that return
  R6  winrate > 0.95 with < 300 trades       — statistical artefact
  R7  drawdown <= 0.05% with return > 1 000% — physically impossible
  R8  near-zero denominator in score calc    — guard_denominator() helper
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

log = logging.getLogger("friday.numeric_safety")

# ── Hard limits ───────────────────────────────────────────────────────────────

SCORE_MAX             = 10_000.0
RETURN_MAX            = 100_000.0
HIGH_RETURN_THRESHOLD = 50_000.0
HIGH_RETURN_MIN_TRADES = 500
HIGH_WR_THRESHOLD     = 0.95
HIGH_WR_MIN_TRADES    = 300
ZERO_DD_RETURN_LIMIT  = 1_000.0
NEAR_ZERO_DENOM       = 1e-10

# ── Log destinations ──────────────────────────────────────────────────────────

from .project_root import PROJECT_ROOT as _ROOT, APPDATA_FRIDAY as _APPDATA_FRIDAY
_LOG_DIRS = [
    _ROOT / "logs",
    _APPDATA_FRIDAY / "logs",
]
_LOGFILE = "fitness_safety_log.jsonl"


def _write_log(entry: dict) -> None:
    for d in _LOG_DIRS:
        try:
            d.mkdir(parents=True, exist_ok=True)
            with (d / _LOGFILE).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


# ── Result type ───────────────────────────────────────────────────────────────

class SafetyResult(NamedTuple):
    ok:     bool
    rule:   str
    reason: str


def _reject(rule: str, reason: str, source: str, vals: dict | None = None) -> SafetyResult:
    entry: dict = {
        "ts":     datetime.now(timezone.utc).isoformat(),
        "source": source,
        "rule":   rule,
        "reason": reason,
    }
    if vals:
        entry["vals"] = vals
    _write_log(entry)
    log.warning("[NumericSafety] REJECT %s — %s | source=%s", rule, reason, source)
    return SafetyResult(ok=False, rule=rule, reason=reason)


# ── Core validator ────────────────────────────────────────────────────────────

def validate_genome_stats(
    score:        float,
    return_pct:   float,
    winrate:      float,
    drawdown_pct: float,
    trades:       int,
    source:       str = "",
) -> SafetyResult:
    """
    Validate genome fitness metrics before ranking, selection, or storage.
    Returns SafetyResult(ok=True) if all 8 rules pass.
    """
    vals = {
        "score": score, "return_pct": return_pct,
        "winrate": winrate, "drawdown_pct": drawdown_pct, "trades": trades,
    }

    # R3 — NaN / Inf (must run before numeric comparisons)
    for name, v in [("score", score), ("return_pct", return_pct),
                    ("winrate", winrate), ("drawdown_pct", drawdown_pct)]:
        try:
            if math.isnan(v) or math.isinf(v):
                return _reject("R3", f"{name}={v} is NaN/Inf", source, vals)
        except (TypeError, ValueError):
            return _reject("R3", f"{name}={v!r} is not numeric", source, vals)

    # R1 — score ceiling
    if score > SCORE_MAX:
        return _reject("R1", f"score={score:.2f} > max {SCORE_MAX}", source, vals)

    # R2 — return_pct ceiling
    if abs(return_pct) > RETURN_MAX:
        return _reject("R2", f"return_pct={return_pct:.2f}% > ±{RETURN_MAX}%", source, vals)

    # R5 — very high return with too few trades
    if return_pct > HIGH_RETURN_THRESHOLD and trades < HIGH_RETURN_MIN_TRADES:
        return _reject(
            "R5",
            f"return={return_pct:.1f}% with only {trades} trades (min {HIGH_RETURN_MIN_TRADES})",
            source, vals,
        )

    # R6 — near-perfect win rate with too few trades
    if winrate > HIGH_WR_THRESHOLD and trades < HIGH_WR_MIN_TRADES:
        return _reject(
            "R6",
            f"winrate={winrate:.1%} with only {trades} trades (min {HIGH_WR_MIN_TRADES})",
            source, vals,
        )

    # R7 — near-zero drawdown with high return
    if drawdown_pct <= 0.05 and return_pct > ZERO_DD_RETURN_LIMIT:
        return _reject(
            "R7",
            f"drawdown={drawdown_pct:.3f}% but return={return_pct:.1f}%",
            source, vals,
        )

    return SafetyResult(ok=True, rule="PASS", reason="all rules passed")


def validate_genome(genome: Any, source: str = "") -> SafetyResult:
    """Validate an AlgoryGenome object directly."""
    try:
        score        = genome.modern_score()
        return_pct   = genome.total_return_pct
        winrate      = genome.win_rate
        drawdown_pct = genome.max_dd_pct
        trades       = genome.trades
    except Exception as exc:
        return _reject("R3", f"genome attribute error: {exc}", source)
    return validate_genome_stats(score, return_pct, winrate, drawdown_pct, trades, source)


def reject_erange(source: str = "", details: str = "") -> SafetyResult:
    """R4 — call this when OverflowError / ERANGE is caught during fitness eval."""
    return _reject("R4", f"ERANGE overflow: {details}", source, {"details": details})


def guard_denominator(value: float, fallback: float = 0.0) -> float:
    """R8 — replace near-zero denominators with fallback before division."""
    try:
        return value if abs(value) >= NEAR_ZERO_DENOM else fallback
    except (TypeError, ValueError):
        return fallback
