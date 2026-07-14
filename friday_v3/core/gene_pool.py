"""
gene_pool.py — Population manager for FRIDAY v3 genetic dip-buyer.

Maintains 20 active genes. Each cycle:
  1. Run dip detector
  2. Each gene independently decides: trade or skip
  3. Track each gene's stats
  4. Every N=50 trades: evolve (kill worst, breed best)

The pool is persisted to friday_v3/data/gene_pool.json — surviving restarts.
"""
from __future__ import annotations
import json
import random
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from friday_v3.core.gene import Gene, GeneDNA

POOL_FILE = Path(r"C:\Users\Radhi\MT5\friday_v3\data\gene_pool.json")
POOL_SIZE = 20
EVOLVE_EVERY_TRADES = 50      # evolve after this many total pool trades
EVOLVE_KILL_BOTTOM_N = 5      # kill 5 worst, replace with offspring of top 5
ELITE_SIZE = 5                # top N preserved unchanged each evolution


class GenePool:
    def __init__(self):
        self.genes: list[Gene] = []
        self.generation = 1
        self.total_trades_at_last_evolution = 0
        self.evolutions = 0
        self._load()

    # ─────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not POOL_FILE.exists():
            self._seed_initial_pool()
            self._save()
            return
        try:
            data = json.loads(POOL_FILE.read_text(encoding="utf-8"))
            self.generation = data.get("generation", 1)
            self.evolutions = data.get("evolutions", 0)
            self.total_trades_at_last_evolution = data.get("total_trades_at_last_evolution", 0)
            self.genes = [Gene.from_dict(g) for g in data.get("genes", [])]
            if len(self.genes) < POOL_SIZE:
                self._top_up()
        except Exception as e:
            print(f"[GenePool] load error: {e} — re-seeding")
            self._seed_initial_pool()

    def _save(self) -> None:
        POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "ts":         datetime.utcnow().isoformat(),
            "generation": self.generation,
            "evolutions": self.evolutions,
            "total_trades_at_last_evolution": self.total_trades_at_last_evolution,
            "pool_size":  len(self.genes),
            "best_fitness": max((g.stats.fitness for g in self.genes), default=0),
            "total_pool_trades": sum(g.stats.trades for g in self.genes),
            "total_pool_pl":     round(sum(g.stats.total_pl for g in self.genes), 2),
            "genes": [g.to_dict() for g in self.genes],
        }
        tmp = POOL_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(POOL_FILE)

    def _seed_initial_pool(self) -> None:
        """Build initial pool: 1 conservative + 1 aggressive + 18 random."""
        self.genes = []
        # Conservative seed
        conservative = Gene(generation=1)
        conservative.dna = GeneDNA(
            min_dip_score=70, min_drop_atr=1.5, max_rsi_m1=25,
            require_hammer=True, require_multi_tf=True,
            profit_target_usd=0.10, sl_atr_mult=1.0,
            max_hold_minutes=5, lot_base=0.01, cooldown_seconds=300,
        )
        self.genes.append(conservative)
        # Aggressive seed
        aggressive = Gene(generation=1)
        aggressive.dna = GeneDNA(
            min_dip_score=40, min_drop_atr=0.8, max_rsi_m1=40,
            require_hammer=False, require_multi_tf=False,
            profit_target_usd=0.20, sl_atr_mult=2.5,
            max_hold_minutes=30, lot_base=0.02, cooldown_seconds=60,
        )
        self.genes.append(aggressive)
        # 18 random
        for _ in range(POOL_SIZE - 2):
            g = Gene(generation=1)
            g.dna = GeneDNA.random()
            self.genes.append(g)
        print(f"[GenePool] seeded {len(self.genes)} initial genes")

    def _top_up(self) -> None:
        """Maintain POOL_SIZE — top up with random new genes."""
        while len(self.genes) < POOL_SIZE:
            g = Gene(generation=self.generation)
            g.dna = GeneDNA.random()
            self.genes.append(g)

    # ─────────────────────────────────────────────────────────────────
    # Decision: which genes want to act on a signal?
    # ─────────────────────────────────────────────────────────────────

    def vote_on_signal(self, sig) -> list[tuple[Gene, str]]:
        """Returns list of (gene, reason) for genes that approve this dip."""
        now = time.time()
        approvers = []
        for g in self.genes:
            if not g.can_trade(now):
                continue
            ok, why = g.evaluate_dip(sig)
            if ok:
                approvers.append((g, why))
        return approvers

    def select_executor(self, approvers: list[tuple[Gene, str]]) -> Gene | None:
        """Pick the best approver to execute. Fitness-weighted.
        If multiple approve, fittest gene gets first chance (with diversity bonus for young genes)."""
        if not approvers:
            return None
        # Compute weighted score: fitness + youth bonus + random tiebreaker
        ranked = []
        for g, why in approvers:
            weight = g.stats.fitness + 0.1 if g.stats.trades < 5 else g.stats.fitness
            ranked.append((weight + random.random() * 0.05, g))
        ranked.sort(key=lambda x: -x[0])
        return ranked[0][1]

    # ─────────────────────────────────────────────────────────────────
    # Trade outcome callback
    # ─────────────────────────────────────────────────────────────────

    def record_outcome(self, gene_id: str, profit: float) -> None:
        for g in self.genes:
            if g.id == gene_id:
                g.record_trade_result(profit)
                break
        self._save()
        self._maybe_evolve()

    def mark_signal_sent(self, gene_id: str) -> None:
        for g in self.genes:
            if g.id == gene_id:
                g.last_signal_ts = time.time()
                break
        self._save()

    # ─────────────────────────────────────────────────────────────────
    # EVOLUTION
    # ─────────────────────────────────────────────────────────────────

    def _maybe_evolve(self) -> None:
        total_trades = sum(g.stats.trades for g in self.genes)
        if total_trades - self.total_trades_at_last_evolution >= EVOLVE_EVERY_TRADES:
            self._evolve()
            self.total_trades_at_last_evolution = total_trades
            self._save()

    def _evolve(self) -> None:
        """Survival of the fittest:
           - Sort by fitness
           - Kill bottom N (those with worst performance)
           - Breed N new genes from top N (mutation + crossover)
        """
        self.evolutions += 1
        self.generation += 1

        # Sort by fitness desc
        self.genes.sort(key=lambda g: -g.stats.fitness)

        # Only evolve if there are enough seasoned genes
        seasoned = [g for g in self.genes if g.stats.trades >= 5]
        if len(seasoned) < ELITE_SIZE + EVOLVE_KILL_BOTTOM_N:
            return

        elite = seasoned[:ELITE_SIZE]
        # Kill bottom N (seasoned ones)
        survivors = seasoned[:-EVOLVE_KILL_BOTTOM_N]
        # Keep all unseasoned genes (still being evaluated)
        unseasoned = [g for g in self.genes if g.stats.trades < 5]

        new_genes = []
        # Breed offspring from elite
        for _ in range(EVOLVE_KILL_BOTTOM_N):
            if len(elite) >= 2:
                parents = random.sample(elite, 2)
                child_dna = GeneDNA.crossover(parents[0].dna, parents[1].dna).mutate(0.10)
                child = Gene(generation=self.generation,
                             parent_ids=[parents[0].id, parents[1].id])
                child.dna = child_dna
                new_genes.append(child)
            else:
                # Fallback: random
                g = Gene(generation=self.generation)
                g.dna = GeneDNA.random()
                new_genes.append(g)

        self.genes = survivors + unseasoned + new_genes
        # Cap at POOL_SIZE
        if len(self.genes) > POOL_SIZE:
            self.genes.sort(key=lambda g: -g.stats.fitness)
            self.genes = self.genes[:POOL_SIZE]

        print(f"[GenePool] EVOLUTION #{self.evolutions}  Gen {self.generation}: "
              f"killed {EVOLVE_KILL_BOTTOM_N}, bred {len(new_genes)}")

    # ─────────────────────────────────────────────────────────────────
    # Reporting
    # ─────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        total_trades = sum(g.stats.trades for g in self.genes)
        total_pl = sum(g.stats.total_pl for g in self.genes)
        winners = sorted(self.genes, key=lambda g: -g.stats.fitness)[:5]
        losers  = sorted(self.genes, key=lambda g: g.stats.fitness)[:5]
        return {
            "generation":   self.generation,
            "evolutions":   self.evolutions,
            "pool_size":    len(self.genes),
            "total_trades": total_trades,
            "total_pl":     round(total_pl, 2),
            "best_fitness": max((g.stats.fitness for g in self.genes), default=0),
            "top_5":        [g.to_dict() for g in winners],
            "bottom_5":     [g.to_dict() for g in losers],
        }


if __name__ == "__main__":
    p = GenePool()
    s = p.summary()
    print(f"Pool gen {s['generation']} ({s['pool_size']} genes, {s['evolutions']} evolutions)")
    print(f"Total trades: {s['total_trades']}, P/L: ${s['total_pl']}")
    print(f"Best fitness: {s['best_fitness']}")
    print(f"\nTop 5 genes:")
    for g in s["top_5"][:3]:
        print(f"  {g['id']} gen{g['generation']}  fitness={g['fitness']}  "
              f"trades={g['stats']['trades']} wr={g['win_rate']:.0%} "
              f"PL=${g['stats']['total_pl']:.2f}")
