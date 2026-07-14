"""
algory_campaign.py
------------------
Multi-phase strategy factory for FRIDAY — replicates Algory's campaign pipeline.

Phases (from Algory terminal uplink):
  1. Proving Grounds (PG)  — 4000 random candidates, quick filter
  2. Tribe A Evolution     — 200 genomes × 20 generations
  3. Tribe B Evolution     — 200 genomes × 20 generations (independent)
  4. War                   — Tribes merge, 200 survivors × 20 generations
  5. Review                — Top 200 × 10 gens, stagnation limit = 5
  6. OOS Validation        — 33% holdout test
  7. Purge                 — Algory purge criteria applied

Stagnation / CRYO-FREEZE:
  When Heat reaches stagnation_limit (5), champions are frozen and the
  remaining population is partially re-seeded (Algory's CRYO-FREEZING).

Tribe population size: 200 (observed in terminal: "Survivors 189/200")
Generation counts match Algory dashboard_settings exactly.
"""

from __future__ import annotations

import json
import logging
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .algory_dna import (
    AlgoryGenome,
    CAMPAIGN_SETTINGS,
    PURGE_CRITERIA,
    ALL_BINARY_GENES,
    EXIT_GENES,
)
from .config import DATA_DIR
from .core.genome_quality_gate import get_quality_gate

log = logging.getLogger("friday.algory_campaign")

# ─────────────────────────────────────────────────────────────────────────────
#  Phase enum
# ─────────────────────────────────────────────────────────────────────────────

class CampaignPhase(Enum):
    PROVING_GROUNDS = "pg"
    TRIBE_A         = "tribe_a"
    TRIBE_B         = "tribe_b"
    WAR             = "war"
    REVIEW          = "review"
    OOS             = "oos"
    DONE            = "done"


# ─────────────────────────────────────────────────────────────────────────────
#  Internal constants (matching Algory's observed behaviour)
# ─────────────────────────────────────────────────────────────────────────────

TRIBE_SIZE       = 200   # population per tribe — from terminal: "Survivors X/200"
PG_QUICK_THRESH  = 5     # min trades in PG quick-eval for a genome to survive
ELITE_FREEZE     = 10    # top N survivors cryo-frozen on stagnation
MUTATION_RATE    = 0.15  # per-gene flip / Gaussian sigma fraction
CRYO_RESEED_PCT  = 0.60  # fraction of non-elite replaced on CRYO-FREEZE


# ─────────────────────────────────────────────────────────────────────────────
#  Fitness evaluator (pluggable — caller injects backtest function)
# ─────────────────────────────────────────────────────────────────────────────

FitnessFunc = Callable[[AlgoryGenome, str, str], None]
"""
Callable(genome, symbol, phase) → None
Must call genome.record_trade(...) for each simulated trade.
After returning, genome.modern_score() should be meaningful.
"""


def _null_fitness(genome: AlgoryGenome, symbol: str, phase: str) -> None:
    """Default no-op evaluator — caller must replace with real backtester."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
#  Generation statistics (what Algory's terminal shows per generation)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GenStats:
    phase:      str
    generation: int
    heat:       int
    score:      float
    survivors:  int
    total:      int
    ret_pct:    float
    dd_pct:     float
    win_rate:   float
    is_trades:  int
    best_genes: dict[str, list[str]]
    cryo_fired: bool = False
    ts:         str  = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def terminal_line(self) -> str:
        bg = self.best_genes
        bias  = "+".join(g.replace("use_bias_", "").upper() for g in bg.get("bias",    [])[:3]) or "None"
        filt  = "+".join(g.replace("use_filt_", "").upper() for g in bg.get("filters", [])[:4]) or "None"
        sig   = "+".join(g.replace("use_sig_",  "").upper() for g in bg.get("signals", [])[:2]) or "None"
        exec_ = "+".join(g.replace("exec_",     "").upper() for g in bg.get("exec",    [])[:2]) or "None"
        exits = "+".join(g.replace("use_",      "").upper() for g in bg.get("exits",   [])[:2]) or "None"

        cryo  = "  [CRYO-FREEZE]" if self.cryo_fired else ""
        return (
            f"── {self.phase.upper().replace('_', ' ')} Gen {self.generation}: "
            f"Score {self.score:.2f}{cryo} ──\n"
            f"   Heat {self.heat} | Survivors {self.survivors}/{self.total} | "
            f"Ret {self.ret_pct:.1f}% | DD {self.dd_pct:.1f}% | "
            f"WR {self.win_rate:.1f}% | IS Tr {self.is_trades}\n"
            f"   Bias:{bias} | Filt:{filt} | Sig:{sig} | Exec:{exec_} | Mgmt:{exits}"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  AlgoryCampaign
# ─────────────────────────────────────────────────────────────────────────────

class AlgoryCampaign:
    """
    Replicates Algory's full strategy factory pipeline for FRIDAY.

    Usage:
        def my_backtest(genome, symbol, phase):
            # run FRIDAY signals on genome, call genome.record_trade(...)
            ...

        campaign = AlgoryCampaign(symbol="XAUUSDm", fitness_fn=my_backtest)
        best = campaign.run_full_campaign()  # returns list of purge-passing genomes
    """

    def __init__(
        self,
        symbol:      str          = "XAUUSDm",
        timeframe:   str          = "H1",
        campaign_id: str          = "",
        fitness_fn:  FitnessFunc  = _null_fitness,
        broadcast_fn: Callable    = None,
        save_dir:    Path         = None,
        fitness_db:  Any          = None,   # ignored here; used by integrator
    ) -> None:
        self.symbol      = symbol
        self.timeframe   = timeframe
        self.campaign_id = campaign_id or datetime.now().strftime("%Y%m%d_%H%M")
        self.fitness_fn  = fitness_fn
        self._broadcast  = broadcast_fn or (lambda e, d: None)
        self.save_dir    = save_dir or (DATA_DIR / "campaigns" / self.campaign_id)
        self.save_dir.mkdir(parents=True, exist_ok=True)

        self.phase:      CampaignPhase = CampaignPhase.PROVING_GROUNDS
        self.gen_log:    list[GenStats] = []
        self.vault:      list[AlgoryGenome] = []   # all genomes that passed purge
        self._lock       = threading.Lock()

        log.info("[Campaign %s] Init — symbol=%s tf=%s", self.campaign_id, symbol, timeframe)

    # ── Public API ─────────────────────────────────────────────────────────────

    def run_full_campaign(self) -> list[AlgoryGenome]:
        """
        Run complete pipeline:
          PG → Tribe A → Tribe B → War → Review → OOS → Purge
        Returns list of genomes that passed all quality gates.
        """
        log.info("[Campaign %s] ─── PROVING GROUNDS ───", self.campaign_id)
        pg_survivors = self.run_proving_grounds()

        log.info("[Campaign %s] ─── TRIBE A ───", self.campaign_id)
        tribe_a = self.run_tribe(
            pg_survivors[:TRIBE_SIZE],
            phase=CampaignPhase.TRIBE_A,
            gens=CAMPAIGN_SETTINGS["tribe_gens_a"],
        )

        log.info("[Campaign %s] ─── TRIBE B ───", self.campaign_id)
        pg_b = pg_survivors[TRIBE_SIZE:TRIBE_SIZE * 2] or pg_survivors
        tribe_b = self.run_tribe(
            pg_b,
            phase=CampaignPhase.TRIBE_B,
            gens=CAMPAIGN_SETTINGS["tribe_gens_b"],
        )

        log.info("[Campaign %s] ─── WAR ───", self.campaign_id)
        war_pool = self.run_war(tribe_a, tribe_b)

        log.info("[Campaign %s] ─── REVIEW ───", self.campaign_id)
        review_pool = self.run_review(war_pool)

        log.info("[Campaign %s] ─── OOS VALIDATION ───", self.campaign_id)
        oos_pool = self.run_oos(review_pool)

        log.info("[Campaign %s] ─── PURGE ───", self.campaign_id)
        final = self.purge(oos_pool)

        self.vault.extend(final)
        self._save_vault()
        self.phase = CampaignPhase.DONE

        log.info(
            "[Campaign %s] DONE — vault=%d qualified strategies",
            self.campaign_id, len(self.vault),
        )
        self._broadcast("campaign_done", {
            "campaign_id": self.campaign_id,
            "symbol":      self.symbol,
            "vault_size":  len(self.vault),
            "top_score":   max((g.modern_score() for g in self.vault), default=0.0),
        })
        return self.vault

    # ── Phase 1: Proving Grounds ───────────────────────────────────────────────

    def run_proving_grounds(self) -> list[AlgoryGenome]:
        """
        Generate pg_candidates random genomes, run quick eval, sort by score.
        Returns up to TRIBE_SIZE*2 survivors for use by both tribes.
        """
        self.phase = CampaignPhase.PROVING_GROUNDS
        n_candidates = CAMPAIGN_SETTINGS["pg_candidates"]

        log.info("[PG] Generating %d candidates for %s", n_candidates, self.symbol)
        self._broadcast("phase_start", {"phase": "pg", "candidates": n_candidates})

        candidates: list[AlgoryGenome] = []
        for i in range(n_candidates):
            g = AlgoryGenome.random_genome(
                symbol=self.symbol,
                campaign=self.campaign_id,
                generation=0,
                phase="pg",
            )
            self.fitness_fn(g, self.symbol, "pg")
            candidates.append(g)

            if (i + 1) % 500 == 0:
                log.info("[PG] Evaluated %d/%d", i + 1, n_candidates)

        # Filter degenerate genomes before sorting (quality gate)
        _gate = get_quality_gate()
        safe_candidates = []
        for g in candidates:
            gr = _gate.check(g, source=f"pg:{self.symbol}")
            if gr.ok:
                safe_candidates.append(g)
            else:
                log.warning("[PG] Rejected genome %s (%s): %s", g.id[:8], gr.rule, gr.reason)

        # Sort by Modern score, take best TRIBE_SIZE*2
        survivors = sorted(safe_candidates, key=lambda g: g.modern_score(), reverse=True)
        survivors = [g for g in survivors if g.trades >= PG_QUICK_THRESH][:TRIBE_SIZE * 2]

        log.info(
            "[PG] %d/%d survived quick filter (min_trades=%d)",
            len(survivors), n_candidates, PG_QUICK_THRESH,
        )
        self._broadcast("pg_done", {
            "survivors": len(survivors),
            "top_score": survivors[0].modern_score() if survivors else 0.0,
        })
        return survivors

    # ── Phase 2/3: Tribe evolution ─────────────────────────────────────────────

    def run_tribe(
        self,
        seed_population: list[AlgoryGenome],
        phase: CampaignPhase,
        gens: int,
    ) -> list[AlgoryGenome]:
        """
        Evolve a tribe for `gens` generations with stagnation / CRYO-FREEZE.

        Heat counter increments when best score doesn't improve.
        At heat == stagnation_limit: CRYO-FREEZE champions + reseed rest.
        """
        pop = list(seed_population)[:TRIBE_SIZE]
        # seed up to TRIBE_SIZE if we have fewer
        while len(pop) < TRIBE_SIZE and pop:
            parent = random.choice(pop)
            pop.append(AlgoryGenome.mutate(parent, rate=0.25, generation=0, phase=phase.value))

        best_score = 0.0
        heat       = 0

        for gen in range(1, gens + 1):
            # Evaluate all (fresh genomes haven't been run yet)
            for g in pop:
                if g.trades == 0:
                    self.fitness_fn(g, self.symbol, phase.value)

            # Filter degenerate genomes before sorting (quality gate)
            _gate = get_quality_gate()
            safe_pop = []
            for g in pop:
                gr = _gate.check(g, source=f"{phase.value}:{self.symbol}:gen{gen}")
                if gr.ok:
                    safe_pop.append(g)
                else:
                    log.warning("[%s] Gen %d — genome %s rejected (%s): %s",
                                phase.value, gen, g.id[:8], gr.rule, gr.reason)
            pop = safe_pop if safe_pop else pop  # never empty the population

            # Sort by Modern score
            pop.sort(key=lambda g: g.modern_score(), reverse=True)
            champion   = pop[0]
            curr_score = champion.modern_score()

            # Stagnation detection
            if curr_score > best_score:
                best_score = curr_score
                heat       = 0
            else:
                heat += 1

            cryo_fired = False
            if heat >= CAMPAIGN_SETTINGS["stagnation_limit"]:
                cryo_fired = True
                heat       = 0
                pop = self._cryo_freeze(pop, gen, phase.value)
                log.info("[%s] Gen %d — CRYO-FREEZE fired", phase.value, gen)

            # Record generation stats
            stats = self._gen_stats(phase.value, gen, heat, pop, cryo_fired)
            self.gen_log.append(stats)
            log.info(stats.terminal_line())
            self._broadcast("gen_update", {
                "phase":      phase.value,
                "gen":        gen,
                "score":      curr_score,
                "heat":       heat,
                "survivors":  len(pop),
                "cryo":       cryo_fired,
            })

            if gen < gens:
                pop = self._breed_next_generation(pop, gen + 1, phase.value)

        return pop

    # ── Phase 4: War ───────────────────────────────────────────────────────────

    def run_war(
        self,
        tribe_a: list[AlgoryGenome],
        tribe_b: list[AlgoryGenome],
    ) -> list[AlgoryGenome]:
        """
        Merge both tribes, keep best TRIBE_SIZE, evolve for war_gens generations.
        """
        self.phase = CampaignPhase.WAR
        merged = sorted(tribe_a + tribe_b, key=lambda g: g.modern_score(), reverse=True)
        merged = merged[:TRIBE_SIZE]
        for g in merged:
            g.phase = "war"

        return self.run_tribe(
            merged,
            phase=CampaignPhase.WAR,
            gens=CAMPAIGN_SETTINGS["war_gens"],
        )

    # ── Phase 5: Review ────────────────────────────────────────────────────────

    def run_review(self, war_survivors: list[AlgoryGenome]) -> list[AlgoryGenome]:
        """
        Final refinement — top TRIBE_SIZE from war, 10 gens, stagnation_limit=5.
        """
        self.phase = CampaignPhase.REVIEW
        pool = sorted(war_survivors, key=lambda g: g.modern_score(), reverse=True)[:TRIBE_SIZE]
        for g in pool:
            g.phase = "review"

        return self.run_tribe(
            pool,
            phase=CampaignPhase.REVIEW,
            gens=CAMPAIGN_SETTINGS["rev_gens"],
        )

    # ── Phase 6: OOS Validation ────────────────────────────────────────────────

    def run_oos(
        self,
        candidates: list[AlgoryGenome],
        oos_fitness_fn: FitnessFunc | None = None,
    ) -> list[AlgoryGenome]:
        """
        Run each candidate on held-out OOS data (33%).
        Genomes whose OOS modern_score >= 50% of IS score are kept.
        """
        self.phase = CampaignPhase.OOS
        fn = oos_fitness_fn or self.fitness_fn

        validated: list[AlgoryGenome] = []
        for g in candidates:
            is_score = g.modern_score()
            # Create a clean copy with reset performance for OOS run
            oos_g = AlgoryGenome.from_dict({**g.to_dict(),
                "id": g.id + "_oos",
                "trades": 0, "wins": 0, "total_pnl": 0.0,
                "win_pnl": 0.0, "loss_pnl": 0.0, "max_dd_pct": 0.0,
                "equity_curve": [], "trade_log": [],
                "phase": "oos",
            })
            fn(oos_g, self.symbol, "oos")
            oos_score = oos_g.modern_score()

            # OOS must achieve at least 50% of IS performance
            if is_score <= 0 or (oos_score / is_score) >= 0.50:
                g.phase = "oos_passed"
                validated.append(g)
                log.info(
                    "[OOS] %s PASS — IS=%.2f OOS=%.2f (%.0f%%)",
                    g.id[:8], is_score, oos_score, oos_score / max(is_score, 0.001) * 100,
                )
            else:
                log.info(
                    "[OOS] %s FAIL — IS=%.2f OOS=%.2f",
                    g.id[:8], is_score, oos_score,
                )

        log.info("[OOS] %d/%d passed", len(validated), len(candidates))
        return validated

    # ── Phase 7: Purge ─────────────────────────────────────────────────────────

    def purge(self, candidates: list[AlgoryGenome]) -> list[AlgoryGenome]:
        """
        Apply Algory's exact purge criteria from config.
        Returns only genomes that pass all quality gates.
        """
        passed:  list[AlgoryGenome] = []
        removed: list[tuple[AlgoryGenome, str]] = []

        for g in candidates:
            ok, reason = g.passes_purge()
            if ok:
                g.phase = "live"
                g.is_protected = True
                passed.append(g)
            else:
                removed.append((g, reason))

        for g, reason in removed:
            log.info("[PURGE] %s removed — %s", g.id[:8], reason)

        log.info(
            "[PURGE] %d/%d passed quality gates",
            len(passed), len(candidates),
        )
        self._broadcast("purge_done", {
            "passed":   len(passed),
            "removed":  len(removed),
            "criteria": PURGE_CRITERIA,
        })
        return passed

    # ── Leaderboard ────────────────────────────────────────────────────────────

    def leaderboard(self, top_n: int = 20) -> list[dict]:
        all_genomes = self.vault
        ranked = sorted(all_genomes, key=lambda g: g.modern_score(), reverse=True)
        return [g.card_data() for g in ranked[:top_n]]

    def gen_log_summary(self, last_n: int = 20) -> list[dict]:
        return [
            {
                "phase": s.phase, "gen": s.generation, "heat": s.heat,
                "score": s.score, "survivors": s.survivors,
                "ret": s.ret_pct, "dd": s.dd_pct, "cryo": s.cryo_fired,
            }
            for s in self.gen_log[-last_n:]
        ]

    def status(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "symbol":      self.symbol,
            "phase":       self.phase.value,
            "vault_size":  len(self.vault),
            "gen_log_len": len(self.gen_log),
            "top_score":   max((g.modern_score() for g in self.vault), default=0.0),
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _cryo_freeze(
        self,
        pop: list[AlgoryGenome],
        gen: int,
        phase: str,
    ) -> list[AlgoryGenome]:
        """
        CRYO-FREEZING: freeze top ELITE_FREEZE champions, reseed the rest.

        Champions are cloned (preserved) + mutated to fill the population.
        This matches Algory's "CRYO-FREEZING CHAMPIONS & PARTIAL RESET".
        """
        champions  = pop[:ELITE_FREEZE]
        n_reseed   = int((len(pop) - ELITE_FREEZE) * CRYO_RESEED_PCT)
        n_keep     = len(pop) - ELITE_FREEZE - n_reseed

        keep_old   = pop[ELITE_FREEZE: ELITE_FREEZE + n_keep]
        new_seeds  = [
            AlgoryGenome.random_genome(
                symbol=self.symbol,
                campaign=self.campaign_id,
                generation=gen,
                phase=phase,
            )
            for _ in range(n_reseed)
        ]

        new_pop = champions + keep_old + new_seeds
        for g in new_pop:
            g.phase = phase
        return new_pop

    def _breed_next_generation(
        self,
        pop: list[AlgoryGenome],
        generation: int,
        phase: str,
    ) -> list[AlgoryGenome]:
        """
        Breed next generation:
        - Keep top 20% (elites) with reset performance stats
        - Fill rest with crossover + mutation offspring
        """
        elite_n    = max(2, len(pop) // 5)
        elites     = pop[:elite_n]
        parents    = pop[:max(4, len(pop) // 2)]
        new_pop    = []

        # Keep elites (clone with fresh performance)
        for g in elites:
            clone = AlgoryGenome.from_dict({
                **g.to_dict(),
                "id":          g.id,
                "generation":  generation,
                "phase":       phase,
                "trades":      0, "wins": 0, "total_pnl": 0.0,
                "win_pnl":     0.0, "loss_pnl": 0.0, "max_dd_pct": 0.0,
                "equity_curve": [], "trade_log": [],
            })
            new_pop.append(clone)

        # Breed offspring
        while len(new_pop) < TRIBE_SIZE:
            if len(parents) >= 2:
                p1, p2 = random.sample(parents[:max(4, len(parents))], 2)
                child  = AlgoryGenome.crossover(p1, p2, generation=generation, phase=phase)
            else:
                child  = AlgoryGenome.mutate(parents[0], rate=MUTATION_RATE,
                                             generation=generation, phase=phase)

            # Random mutation with low probability
            if random.random() < 0.25:
                child = AlgoryGenome.mutate(child, rate=0.10, generation=generation, phase=phase)

            new_pop.append(child)

        return new_pop[:TRIBE_SIZE]

    def _gen_stats(
        self,
        phase: str,
        gen: int,
        heat: int,
        pop: list[AlgoryGenome],
        cryo_fired: bool,
    ) -> GenStats:
        champion   = pop[0] if pop else None
        survivors  = len([g for g in pop if g.modern_score() > 0])
        score      = champion.modern_score() if champion else 0.0
        ret_pct    = champion.total_return_pct if champion else 0.0
        dd_pct     = champion.max_dd_pct if champion else 0.0
        win_rate   = (champion.win_rate * 100) if champion else 0.0
        is_trades  = champion.trades if champion else 0
        best_genes = champion.gene_summary() if champion else {}
        return GenStats(
            phase=phase, generation=gen, heat=heat, score=score,
            survivors=survivors, total=len(pop),
            ret_pct=ret_pct, dd_pct=dd_pct, win_rate=win_rate,
            is_trades=is_trades, best_genes=best_genes,
            cryo_fired=cryo_fired,
        )

    def _save_vault(self) -> None:
        path = self.save_dir / "vault.json"
        payload = {
            "campaign_id": self.campaign_id,
            "symbol":      self.symbol,
            "saved_at":    datetime.now(timezone.utc).isoformat(),
            "count":       len(self.vault),
            "genomes":     [g.to_dict() for g in self.vault],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("[Campaign %s] Vault saved → %s", self.campaign_id, path)

    @classmethod
    def load_vault(cls, campaign_id: str, save_dir: Path = None) -> list[AlgoryGenome]:
        base = save_dir or (DATA_DIR / "campaigns")
        path = base / campaign_id / "vault.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [AlgoryGenome.from_dict(d) for d in data.get("genomes", [])]


# ─────────────────────────────────────────────────────────────────────────────
#  Convenience — run a campaign in background thread
# ─────────────────────────────────────────────────────────────────────────────

def launch_campaign_async(
    symbol:       str,
    fitness_fn:   FitnessFunc,
    broadcast_fn: Callable = None,
    campaign_id:  str      = "",
) -> "CampaignHandle":
    """
    Start a campaign in a daemon thread. Returns a handle to check progress.
    """
    handle   = CampaignHandle(symbol=symbol, campaign_id=campaign_id or datetime.now().strftime("%Y%m%d_%H%M"))
    campaign = AlgoryCampaign(
        symbol=symbol,
        campaign_id=handle.campaign_id,
        fitness_fn=fitness_fn,
        broadcast_fn=broadcast_fn,
    )
    handle.campaign = campaign

    def _run():
        try:
            handle.result = campaign.run_full_campaign()
            handle.done   = True
        except Exception as exc:
            log.exception("[Campaign %s] Failed: %s", handle.campaign_id, exc)
            handle.error  = str(exc)
            handle.done   = True

    t = threading.Thread(target=_run, daemon=True, name=f"campaign-{handle.campaign_id}")
    t.start()
    handle.thread = t
    return handle


@dataclass
class CampaignHandle:
    symbol:      str
    campaign_id: str
    campaign:    Any = None
    thread:      Any = None
    result:      list = field(default_factory=list)
    done:        bool = False
    error:       str  = ""

    def status(self) -> dict:
        if self.campaign:
            return self.campaign.status()
        return {"campaign_id": self.campaign_id, "done": self.done}
