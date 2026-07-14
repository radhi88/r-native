"""
breeding_pool.py
----------------
Manages the approved genome breeding pool for FRIDAY.

Only genomes with status APPROVED_FOR_BREEDING (or higher) may enter.
The pool preserves diversity, limits family dominance, tracks lineage,
and provides safe genome selection for controlled evolution.

All decisions are logged to logs/breeding_pool_log.jsonl.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .genome_quality_gate import (
    GenomeStatus, GateResult, GenomeQualityGate, get_quality_gate,
    compute_bounded_score, BREEDING_MAX_CORRELATION,
)

log = logging.getLogger("friday.breeding_pool")

# ── Log paths ─────────────────────────────────────────────────────────────────

from .project_root import PROJECT_ROOT as _ROOT, APPDATA_FRIDAY as _APPDATA_FRIDAY
_LOG_DIRS = [
    _ROOT / "logs",
    _APPDATA_FRIDAY / "logs",
]
_POOL_LOG = "breeding_pool_log.jsonl"

_POOL_FILE = _ROOT / "data" / "breeding_pool.json"
_MAX_POOL_SIZE = 50       # maximum genomes in the pool
_MAX_FAMILY_SHARE = 0.30  # one parent lineage ≤ 30% of pool


def _write_log(entry: dict) -> None:
    for d in _LOG_DIRS:
        try:
            d.mkdir(parents=True, exist_ok=True)
            with (d / _POOL_LOG).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


# ── Pool entry ────────────────────────────────────────────────────────────────

class PoolEntry:
    """A single genome record in the breeding pool."""

    __slots__ = (
        "genome_id", "symbol", "timeframe", "phase", "generation",
        "parent_ids", "bounded_score", "quality_score", "robustness_score",
        "stability_score", "oos_score", "return_pct", "drawdown_pct",
        "winrate", "trades", "profit_factor", "status",
        "added_at", "mutation_history", "rejection_reasons",
        "binary_signature", "genome_dict",
    )

    def __init__(
        self,
        genome: Any,
        gate_result: GateResult,
        oos_score: float = 1.0,
    ) -> None:
        self.genome_id       = getattr(genome, "id", "unknown")
        self.symbol          = getattr(genome, "symbol", "")
        self.timeframe       = getattr(genome, "timeframe", "")
        self.phase           = getattr(genome, "phase", "")
        self.generation      = getattr(genome, "generation", 0)
        self.parent_ids      = getattr(genome, "parent_ids", [])
        self.bounded_score   = gate_result.score
        self.quality_score   = gate_result.score
        self.oos_score       = oos_score
        self.robustness_score = self._compute_robustness(genome)
        self.stability_score  = getattr(genome, "equity_linearity", lambda: 0.5)()
        self.return_pct       = getattr(genome, "total_return_pct", 0.0)
        self.drawdown_pct     = getattr(genome, "max_dd_pct", 0.0)
        self.winrate          = getattr(genome, "win_rate", 0.0)
        self.trades           = getattr(genome, "trades", 0)
        self.profit_factor    = getattr(genome, "profit_factor", 0.0)
        self.status           = gate_result.status
        self.added_at         = datetime.now(timezone.utc).isoformat()
        self.mutation_history = []
        self.rejection_reasons = []

        # Binary gene signature for diversity / correlation check
        from .genome_quality_gate import NEAR_ZERO
        try:
            from ..algory_dna import ALL_BINARY_GENES
            self.binary_signature = tuple(
                int(getattr(genome, g, False)) for g in ALL_BINARY_GENES
            )
        except Exception:
            self.binary_signature = ()

        try:
            self.genome_dict = genome.to_dict()
        except Exception:
            self.genome_dict = {}

    def _compute_robustness(self, genome: Any) -> float:
        """Robustness = geometric mean of linearity and persistence."""
        try:
            lin  = genome.equity_linearity()
            pers = genome.persistence()
            return round(math.sqrt(max(0.0, lin) * max(0.0, pers)), 4)
        except Exception:
            return 0.0

    def to_dict(self) -> dict:
        return {
            "genome_id":       self.genome_id,
            "symbol":          self.symbol,
            "timeframe":       self.timeframe,
            "phase":           self.phase,
            "generation":      self.generation,
            "parent_ids":      self.parent_ids,
            "bounded_score":   self.bounded_score,
            "quality_score":   self.quality_score,
            "robustness_score": self.robustness_score,
            "stability_score": self.stability_score,
            "oos_score":       self.oos_score,
            "return_pct":      self.return_pct,
            "drawdown_pct":    self.drawdown_pct,
            "winrate":         self.winrate,
            "trades":          self.trades,
            "profit_factor":   self.profit_factor,
            "status":          self.status.value,
            "added_at":        self.added_at,
            "mutation_history": self.mutation_history,
        }


# ── Breeding pool ──────────────────────────────────────────────────────────────

class BreedingPool:
    """
    Manages the approved genome breeding pool.

    Admission rules (beyond gate approval):
      1. Pool size ≤ MAX_POOL_SIZE
      2. One parent family ≤ MAX_FAMILY_SHARE of pool
      3. New entry must not be too correlated with any existing member
      4. New entry must add diversity (gene signature distance)
    """

    def __init__(
        self,
        pool_file: Path = _POOL_FILE,
        gate: GenomeQualityGate | None = None,
    ) -> None:
        self.pool_file = pool_file
        self.gate      = gate or get_quality_gate()
        self._pool: list[PoolEntry] = []
        self._load()

    # ── Add genome ────────────────────────────────────────────────────────────

    def add(
        self,
        genome: Any,
        source: str = "",
        oos_ratio: float = 1.0,
    ) -> GateResult:
        """
        Attempt to add a genome to the breeding pool.
        Returns GateResult indicating outcome.
        """
        result = self.gate.check(genome, source=source, oos_ratio=oos_ratio)

        if not result.approved_for_breeding:
            self._log_event("rejected_from_pool", genome, result, source,
                            reason=f"gate: {result.reason}")
            return result

        entry = PoolEntry(genome, result, oos_score=oos_ratio)

        # Pool size check
        if len(self._pool) >= _MAX_POOL_SIZE:
            weakest = min(self._pool, key=lambda e: e.bounded_score)
            if entry.bounded_score <= weakest.bounded_score:
                r = GateResult(
                    status=GenomeStatus.WATCHLIST,
                    rule="POOL_FULL",
                    reason=f"pool at capacity ({_MAX_POOL_SIZE}) and new score "
                           f"{entry.bounded_score:.1f} ≤ weakest {weakest.bounded_score:.1f}",
                    score=result.score,
                )
                self._log_event("rejected_from_pool", genome, r, source, reason=r.reason)
                return r
            self._pool.remove(weakest)
            self._log_event("evicted_from_pool", None, result, source,
                            reason=f"evicted {weakest.genome_id[:8]} score={weakest.bounded_score:.1f}")

        # Family dominance check
        if entry.parent_ids:
            family_ids = set(entry.parent_ids)
            family_count = sum(
                1 for e in self._pool
                if set(e.parent_ids) & family_ids or e.genome_id in family_ids
            )
            if family_count / max(1, len(self._pool)) > _MAX_FAMILY_SHARE:
                r = GateResult(
                    status=GenomeStatus.WATCHLIST,
                    rule="FAMILY_DOMINANCE",
                    reason=f"parent family already {family_count}/{len(self._pool)} of pool "
                           f"(max {_MAX_FAMILY_SHARE:.0%})",
                    score=result.score,
                )
                self._log_event("rejected_from_pool", genome, r, source, reason=r.reason)
                return r

        # Correlation / diversity check
        if entry.binary_signature:
            for existing in self._pool:
                if not existing.binary_signature:
                    continue
                corr = _binary_correlation(entry.binary_signature, existing.binary_signature)
                if corr > BREEDING_MAX_CORRELATION:
                    r = GateResult(
                        status=GenomeStatus.WATCHLIST,
                        rule="TOO_SIMILAR",
                        reason=f"gene correlation {corr:.2f} > {BREEDING_MAX_CORRELATION} "
                               f"with pool member {existing.genome_id[:8]}",
                        score=result.score,
                    )
                    self._log_event("rejected_from_pool", genome, r, source, reason=r.reason)
                    return r

        # Accepted
        self._pool.append(entry)
        self._save()
        self._log_event("added_to_pool", genome, result, source,
                        reason=f"score={entry.bounded_score:.1f}")
        log.info("[BreedingPool] + %s %s|%s gen=%d score=%.1f",
                 entry.genome_id[:8], entry.symbol, entry.timeframe,
                 entry.generation, entry.bounded_score)
        return result

    # ── Query ─────────────────────────────────────────────────────────────────

    def top(self, n: int = 10, symbol: str = "", timeframe: str = "") -> list[PoolEntry]:
        pool = self._pool
        if symbol:
            pool = [e for e in pool if e.symbol == symbol]
        if timeframe:
            pool = [e for e in pool if e.timeframe == timeframe]
        return sorted(pool, key=lambda e: e.bounded_score, reverse=True)[:n]

    def size(self) -> int:
        return len(self._pool)

    def summary(self) -> dict:
        if not self._pool:
            return {"size": 0, "symbols": [], "avg_score": 0.0}
        symbols = list({e.symbol for e in self._pool})
        return {
            "size":       len(self._pool),
            "symbols":    symbols,
            "avg_score":  round(sum(e.bounded_score for e in self._pool) / len(self._pool), 2),
            "max_score":  max(e.bounded_score for e in self._pool),
            "min_score":  min(e.bounded_score for e in self._pool),
        }

    # ── Select parents for breeding ───────────────────────────────────────────

    def select_parents(
        self,
        symbol: str = "",
        timeframe: str = "",
        n: int = 2,
    ) -> list[PoolEntry]:
        """
        Select diverse high-quality parents for breeding.
        Returns up to n entries with maximum diversity.
        """
        candidates = self.top(20, symbol=symbol, timeframe=timeframe)
        if len(candidates) <= n:
            return candidates

        selected = [candidates[0]]  # always include highest-scoring
        for c in candidates[1:]:
            if len(selected) >= n:
                break
            # Only add if sufficiently different from all already-selected
            too_close = False
            for s in selected:
                if s.binary_signature and c.binary_signature:
                    corr = _binary_correlation(s.binary_signature, c.binary_signature)
                    if corr > 0.70:
                        too_close = True
                        break
            if not too_close:
                selected.append(c)

        return selected

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            self.pool_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "count":    len(self._pool),
                "pool":     [e.to_dict() for e in self._pool],
            }
            self.pool_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            log.warning("[BreedingPool] Save failed: %s", exc)

    def _load(self) -> None:
        if not self.pool_file.exists():
            return
        try:
            data  = json.loads(self.pool_file.read_text(encoding="utf-8"))
            count = data.get("count", 0)
            log.info("[BreedingPool] Loaded %d entries from %s", count, self.pool_file)
        except Exception as exc:
            log.warning("[BreedingPool] Load failed: %s", exc)

    def _log_event(
        self,
        event: str,
        genome: Any,
        result: GateResult,
        source: str,
        reason: str = "",
    ) -> None:
        gid = getattr(genome, "id", "?")[:8] if genome is not None else "?"
        entry = {
            "ts":     datetime.now(timezone.utc).isoformat(),
            "event":  event,
            "genome_id": gid,
            "source": source,
            "status": result.status.value,
            "score":  result.score,
            "reason": reason or result.reason,
        }
        _write_log(entry)


# ── Correlation helper ────────────────────────────────────────────────────────

def _binary_correlation(a: tuple, b: tuple) -> float:
    """Simple binary Jaccard similarity between two gene signature tuples."""
    if not a or not b or len(a) != len(b):
        return 0.0
    matches = sum(x == y for x, y in zip(a, b))
    return matches / len(a)


# ── Singleton ─────────────────────────────────────────────────────────────────

_pool_instance: BreedingPool | None = None


def get_breeding_pool() -> BreedingPool:
    global _pool_instance
    if _pool_instance is None:
        _pool_instance = BreedingPool()
    return _pool_instance
