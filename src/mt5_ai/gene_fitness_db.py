"""
gene_fitness_db.py
------------------
Gene Fitness Database — replicated from Algory's gene_fitness_v2.json.

Tracks historical performance of each gene, gene combination, and exec mode
across campaigns. Used to bias Proving Grounds seeding (Smart Mode).

Schema (mirrors Algory's gene_fitness_v2.json exactly):

{
  "<symbol>": {
    "<timeframe>": {
      "genes": {
        "<gene_name>": {
          "wins": int,           # campaigns where this gene was in winning strategy
          "fails": int,          # campaigns where this gene was in failing strategy
          "mid_oos_pass": int,   # OOS validation passes with this gene
          "mid_oos_fail": int,   # OOS validation fails with this gene
          "avg_return": float,   # average return when this gene is present
          "avg_dd": float,       # average drawdown when present
          "best_return": float,  # best return seen with this gene
          "appearances": int,    # total times gene appeared in evaluated strategies
          "last_seen": "YYYY-MM-DD"
        }
      },
      "combos": {
        "<gene1+gene2+...>": {
          "wins": int,
          "fails": int,
          "avg_return": float,
          "last_seen": "YYYY-MM-DD"
        }
      },
      "exec_modes": {
        "<exec_name>": {
          "wins": int,
          "fails": int,
          "avg_return": float,
          "last_seen": "YYYY-MM-DD"
        }
      },
      "params": {},
      "total_campaigns": int
    }
  },
  "_global": { ... same structure ... }
}
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .algory_dna import (
    ALL_BINARY_GENES,
    BIAS_GENES, SIGNAL_GENES, FILTER_GENES, EXIT_GENES, EXEC_GENES,
    AlgoryGenome,
)
from .config import DATA_DIR

log = logging.getLogger("friday.gene_fitness_db")

GENE_FITNESS_PATH = DATA_DIR / "gene_fitness_v2.json"
MAX_COMBO_GENES   = 6   # max genes in a tracked combination (Algory uses variable length)
MAX_COMBOS_STORED = 500  # limit stored combos per symbol/tf to avoid bloat


# ─────────────────────────────────────────────────────────────────────────────
#  Gene record (single gene stats)
# ─────────────────────────────────────────────────────────────────────────────

def _empty_gene_record() -> dict:
    return {
        "wins":         0,
        "fails":        0,
        "mid_oos_pass": 0,
        "mid_oos_fail": 0,
        "avg_return":   0.0,
        "avg_dd":       0.0,
        "best_return":  0.0,
        "appearances":  0,
        "last_seen":    "",
    }


def _empty_combo_record() -> dict:
    return {
        "wins":       0,
        "fails":      0,
        "avg_return": 0.0,
        "last_seen":  "",
    }


def _empty_exec_record() -> dict:
    return {
        "wins":       0,
        "fails":      0,
        "avg_return": 0.0,
        "last_seen":  "",
    }


# ─────────────────────────────────────────────────────────────────────────────
#  GeneFitnessDB
# ─────────────────────────────────────────────────────────────────────────────

class GeneFitnessDB:
    """
    Persistent gene fitness database — mirrors Algory's gene_fitness_v2.json.

    Records wins/fails per gene, per combo, and per exec mode.
    Used to bias the Proving Grounds seeding in Smart Mode.
    """

    def __init__(self, path: Path = GENE_FITNESS_PATH) -> None:
        self.path = path
        self._db: dict[str, Any] = {}
        self._load()

    # ── Write: record campaign result ─────────────────────────────────────────

    def record_genome_result(
        self,
        genome:     AlgoryGenome,
        won:        bool,
        oos_passed: bool,
        symbol:     str,
        timeframe:  str = "H1",
    ) -> None:
        """
        Record the outcome of a genome (strategy) evaluation.

        won        = True if genome passed purge criteria (IS performance)
        oos_passed = True if genome also passed OOS validation
        """
        # Quality gate — never store degenerate stats in fitness DB
        from .core.genome_quality_gate import get_quality_gate as _gqg
        gr = _gqg().check(genome, source=f"gene_fitness_db:{symbol}|{timeframe}")
        if not gr.ok:
            log.warning("[GeneFitnessDB] Blocked genome %s (%s): %s",
                        genome.id[:8], gr.rule, gr.reason)
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ret   = genome.total_return_pct
        dd    = genome.max_dd_pct

        active_genes = [g for g in ALL_BINARY_GENES if getattr(genome, g, False)]
        exec_modes   = [g.replace("exec_", "") for g in EXEC_GENES if getattr(genome, g, False)]

        for scope in [(symbol, timeframe), ("_global", "_global")]:
            sym_key, tf_key = scope
            bucket = self._get_bucket(sym_key, tf_key)
            bucket["total_campaigns"] = bucket.get("total_campaigns", 0) + 1

            # Individual gene stats
            for gene in active_genes:
                rec = bucket["genes"].setdefault(gene, _empty_gene_record())
                rec["appearances"] += 1
                rec["last_seen"]    = today
                if won:
                    rec["wins"]       += 1
                    rec["avg_return"]  = _running_avg(rec["avg_return"], ret, rec["wins"])
                    rec["avg_dd"]      = _running_avg(rec["avg_dd"],     dd,  rec["wins"])
                    rec["best_return"] = max(rec["best_return"], ret)
                else:
                    rec["fails"] += 1
                if oos_passed:
                    rec["mid_oos_pass"] += 1
                else:
                    rec["mid_oos_fail"] += 1

            # Gene combo stats (only non-exit genes, max MAX_COMBO_GENES)
            core_genes = [g for g in active_genes if g not in EXIT_GENES][:MAX_COMBO_GENES]
            if core_genes:
                combo_key = "+".join(
                    g.replace("use_bias_", "bias_")
                     .replace("use_sig_",  "sig_")
                     .replace("use_filt_", "filt_")
                     .replace("exec_",     "exec_")
                    for g in sorted(core_genes)
                )
                combos = bucket["combos"]
                if combo_key not in combos and len(combos) < MAX_COMBOS_STORED:
                    combos[combo_key] = _empty_combo_record()
                if combo_key in combos:
                    rec = combos[combo_key]
                    rec["last_seen"] = today
                    if won:
                        rec["wins"]       += 1
                        rec["avg_return"]  = _running_avg(rec["avg_return"], ret, rec["wins"])
                    else:
                        rec["fails"] += 1

            # Exec mode stats
            for mode in exec_modes:
                rec = bucket["exec_modes"].setdefault(mode, _empty_exec_record())
                rec["last_seen"] = today
                if won:
                    rec["wins"]       += 1
                    rec["avg_return"]  = _running_avg(rec["avg_return"], ret, rec["wins"])
                else:
                    rec["fails"] += 1

        self._save()

    # ── Read: Smart Mode seeding bias ────────────────────────────────────────

    def gene_win_rate(self, gene: str, symbol: str, timeframe: str = "H1") -> float:
        """
        Return the historical win rate for a gene on this symbol/tf.
        Falls back to global rate, then 0.5 (neutral) if no data.
        """
        for scope in [(symbol, timeframe), ("_global", "_global")]:
            sym_key, tf_key = scope
            bucket = self._get_bucket(sym_key, tf_key)
            rec    = bucket["genes"].get(gene)
            if rec and (rec["wins"] + rec["fails"]) >= 3:
                return rec["wins"] / (rec["wins"] + rec["fails"])
        return 0.5

    def gene_oos_pass_rate(self, gene: str, symbol: str, timeframe: str = "H1") -> float:
        """Historical OOS pass rate for a gene."""
        for scope in [(symbol, timeframe), ("_global", "_global")]:
            bucket = self._get_bucket(*scope)
            rec    = bucket["genes"].get(gene)
            if rec:
                total = rec["mid_oos_pass"] + rec["mid_oos_fail"]
                if total >= 3:
                    return rec["mid_oos_pass"] / total
        return 0.5

    def exec_win_rate(self, exec_mode: str, symbol: str, timeframe: str = "H1") -> float:
        for scope in [(symbol, timeframe), ("_global", "_global")]:
            bucket = self._get_bucket(*scope)
            rec    = bucket["exec_modes"].get(exec_mode)
            if rec and (rec["wins"] + rec["fails"]) >= 3:
                return rec["wins"] / (rec["wins"] + rec["fails"])
        return 0.5

    def smart_seed_probability(
        self,
        gene:      str,
        symbol:    str,
        timeframe: str  = "H1",
        alpha:     float = 0.6,   # weight given to historical data vs random (0.5)
    ) -> float:
        """
        Compute biased probability for including gene in a new random genome.

        alpha=0: fully random (0.5 baseline)
        alpha=1: fully history-driven
        """
        wr = self.gene_win_rate(gene, symbol, timeframe)
        return (1 - alpha) * 0.5 + alpha * wr

    def biased_random_genome(
        self,
        symbol:    str,
        campaign:  str = "",
        timeframe: str  = "H1",
        alpha:     float = 0.6,
    ) -> AlgoryGenome:
        """
        Generate a genome with gene probabilities biased by historical performance.
        Used in Smart Mode Proving Grounds.
        """
        import uuid, random
        from datetime import datetime, timezone

        genome_id = str(uuid.uuid4())[:12]
        kw: dict[str, Any] = {
            "id":         genome_id,
            "generation": 0,
            "parent_ids": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "symbol":     symbol,
            "campaign":   campaign,
            "phase":      "pg",
        }

        from .algory_dna import NUMERIC_BOUNDS, INT_PARAMS, EXIT_GENES as EG
        import random

        for gene in ALL_BINARY_GENES:
            if gene in EG:
                kw[gene] = False
            else:
                p = self.smart_seed_probability(gene, symbol, timeframe, alpha)
                kw[gene] = random.random() < p

        for param, (lo, hi) in NUMERIC_BOUNDS.items():
            val = random.uniform(lo, hi)
            kw[param] = int(round(val)) if param in INT_PARAMS else round(val, 4)

        return AlgoryGenome(**kw)

    # ── Summary ────────────────────────────────────────────────────────────────

    def top_genes(
        self,
        symbol:    str,
        timeframe: str = "H1",
        top_n:     int = 10,
        min_appearances: int = 3,
    ) -> list[dict]:
        """Return top N genes by win rate on this symbol/tf."""
        bucket = self._get_bucket(symbol, timeframe)
        rows   = []
        for gene, rec in bucket["genes"].items():
            total = rec["wins"] + rec["fails"]
            if total < min_appearances:
                continue
            wr      = rec["wins"] / total
            oos_wr  = (rec["mid_oos_pass"] / max(1, rec["mid_oos_pass"] + rec["mid_oos_fail"]))
            rows.append({
                "gene":         gene,
                "win_rate":     round(wr, 3),
                "oos_pass_rate": round(oos_wr, 3),
                "appearances":  rec["appearances"],
                "avg_return":   round(rec["avg_return"], 2),
                "best_return":  round(rec["best_return"], 2),
            })
        return sorted(rows, key=lambda r: r["win_rate"], reverse=True)[:top_n]

    def top_combos(self, symbol: str, timeframe: str = "H1", top_n: int = 10) -> list[dict]:
        bucket = self._get_bucket(symbol, timeframe)
        rows   = []
        for combo, rec in bucket["combos"].items():
            total = rec["wins"] + rec["fails"]
            if total < 2:
                continue
            rows.append({
                "combo":    combo,
                "win_rate": round(rec["wins"] / total, 3),
                "wins":     rec["wins"],
                "fails":    rec["fails"],
                "avg_ret":  round(rec["avg_return"], 2),
            })
        return sorted(rows, key=lambda r: r["win_rate"], reverse=True)[:top_n]

    def summary(self, symbol: str, timeframe: str = "H1") -> dict:
        bucket = self._get_bucket(symbol, timeframe)
        return {
            "symbol":           symbol,
            "timeframe":        timeframe,
            "total_campaigns":  bucket.get("total_campaigns", 0),
            "genes_tracked":    len(bucket["genes"]),
            "combos_tracked":   len(bucket["combos"]),
            "top_genes":        self.top_genes(symbol, timeframe, top_n=5),
        }

    # ── Persistence ────────────────────────────────────────────────────────────

    def _get_bucket(self, symbol: str, timeframe: str) -> dict:
        sym = self._db.setdefault(symbol, {})
        return sym.setdefault(timeframe, {
            "genes":           {},
            "combos":          {},
            "exec_modes":      {},
            "params":          {},
            "total_campaigns": 0,
        })

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._db = json.loads(self.path.read_text(encoding="utf-8"))
                log.info("[GeneFitnessDB] Loaded from %s", self.path)
            except Exception as exc:
                log.warning("[GeneFitnessDB] Load failed: %s — starting fresh", exc)
                self._db = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._db, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("[GeneFitnessDB] Save failed: %s", exc)

    def import_algory_json(self, source_path: Path) -> None:
        """Import Algory's gene_fitness_v2.json into this database."""
        if not source_path.exists():
            log.warning("[GeneFitnessDB] Source not found: %s", source_path)
            return
        try:
            algory_data = json.loads(source_path.read_text(encoding="utf-8"))
            for sym, sym_data in algory_data.items():
                if not isinstance(sym_data, dict):
                    continue
                for tf, tf_data in sym_data.items():
                    if not isinstance(tf_data, dict):
                        continue
                    bucket = self._get_bucket(sym, tf)
                    # Merge genes
                    for gene, rec in tf_data.get("genes", {}).items():
                        existing = bucket["genes"].setdefault(gene, _empty_gene_record())
                        for k in ("wins", "fails", "mid_oos_pass", "mid_oos_fail", "appearances"):
                            existing[k] = existing.get(k, 0) + rec.get(k, 0)
                        existing["best_return"] = max(
                            existing.get("best_return", 0.0),
                            rec.get("best_return", 0.0),
                        )
                        if rec.get("last_seen"):
                            existing["last_seen"] = rec["last_seen"]
                    # Merge combos
                    for combo, rec in tf_data.get("combos", {}).items():
                        existing = bucket["combos"].setdefault(combo, _empty_combo_record())
                        for k in ("wins", "fails"):
                            existing[k] = existing.get(k, 0) + rec.get(k, 0)
                        if rec.get("last_seen"):
                            existing["last_seen"] = rec["last_seen"]
                    # Merge exec modes
                    for mode, rec in tf_data.get("exec_modes", {}).items():
                        existing = bucket["exec_modes"].setdefault(mode, _empty_exec_record())
                        for k in ("wins", "fails"):
                            existing[k] = existing.get(k, 0) + rec.get(k, 0)
                        if rec.get("last_seen"):
                            existing["last_seen"] = rec["last_seen"]
            self._save()
            log.info("[GeneFitnessDB] Imported Algory data from %s", source_path)
        except Exception as exc:
            log.error("[GeneFitnessDB] Import failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _running_avg(current: float, new_value: float, n: int) -> float:
    """Online running average update."""
    if n <= 1:
        return new_value
    return current + (new_value - current) / n


# ─────────────────────────────────────────────────────────────────────────────
#  Singleton accessor
# ─────────────────────────────────────────────────────────────────────────────

_db_instance: GeneFitnessDB | None = None


def get_gene_fitness_db() -> GeneFitnessDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = GeneFitnessDB()
        # Auto-import Algory's existing data if available
        from .core.project_root import APPDATA_ALGORY as _APPDATA_ALGORY
        algory_source = _APPDATA_ALGORY / "gene_fitness_v2.json"
        if algory_source.exists():
            _db_instance.import_algory_json(algory_source)
    return _db_instance
