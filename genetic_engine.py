"""genetic_engine.py - Multi-process genetic algorithm (Algory-style).

Pipeline (mirrors Algory's flow):
  1. PROVING GROUNDS — generate PG=4000 random genomes, evaluate, keep top survivors
  2. TRIBE A — N gens of evolution on survivors, with crossover+mutation
  3. TRIBE B — parallel branch, different starting seed
  4. WAR    — both tribes compete head-to-head, weakest extinguished
  5. REVIVAL — re-introduce mutated copies of best long-dead genomes
  6. RETRAIN — final fine-tune on the elite

Uses ProcessPoolExecutor to parallelize evaluation across all CPU cores.
Each genome → spawn-able evaluation function (must be top-level for pickling).
"""
from __future__ import annotations
import json
import time
import random
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from r_native.genes import Genome, ALL_GENES, modern_score, algory_purge_check


CAMPAIGN_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\campaigns")


@dataclass
class CampaignConfig:
    symbol:           str
    timeframe:        str = "M5"
    bars:             int = 4000
    pg_candidates:    int = 4000
    tribe_a_gens:     int = 20
    tribe_b_gens:     int = 20
    war_gens:         int = 20
    revival_gens:     int = 10
    retrain_gens:     int = 10
    train_split:      float = 0.67
    stagnation_limit: int = 5
    elite_pct:        float = 0.20   # top 20% survive each generation
    mutation_rate:    float = 0.15
    n_workers:        int = max(1, (mp.cpu_count() or 2) - 1)
    purge: dict = None              # uses Algory defaults if None


# ─── Worker-side evaluation (must be top-level for pickling) ───
def _evaluate_genome_worker(payload: tuple) -> dict:
    """payload = (genome_dict, symbol, tf_name, bars_back). Returns {id, stats, score}."""
    genome_d, symbol, tf_name, bars_back = payload
    try:
        # Import inside worker (sub-process)
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return {"id": genome_d.get("id"), "ok": False, "error": "mt5 init"}

        tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                  "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
                  "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
                  "D1": mt5.TIMEFRAME_D1}
        tf = tf_map.get(tf_name, mt5.TIMEFRAME_M5)
        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return {"id": genome_d.get("id"), "ok": False, "error": "no symbol"}
        bars = mt5.copy_rates_from_pos(symbol, tf, 0, bars_back)
        if bars is None or len(bars) < 100:
            return {"id": genome_d.get("id"), "ok": False, "error": "no bars"}

        # Lazy import simulator (heavy)
        from r_native.ga_simulator import simulate_genome
        stats = simulate_genome(genome_d, bars, sym_info)
        score = modern_score(stats)
        return {
            "id": genome_d.get("id"), "ok": True,
            "score": score, "stats": stats,
            "genome": genome_d,
        }
    except Exception as e:
        return {"id": genome_d.get("id"), "ok": False, "error": str(e)}


# ─── Engine ───
class GeneticEngine:
    def __init__(self, cfg: CampaignConfig,
                 progress_cb: Optional[Callable] = None):
        self.cfg = cfg
        self.progress_cb = progress_cb or (lambda phase, msg, done, total: None)
        self.elites: list[dict] = []       # top genomes seen across all phases
        self.vault:  list[dict] = []       # all genomes that passed purge
        self.killed_genome_ids: set = set()

    def _emit(self, phase, msg, done=0, total=0):
        try: self.progress_cb(phase, msg, done, total)
        except Exception: pass

    # ── Generation evaluator (parallel) ──
    def _evaluate_population(self, population: list[Genome], phase: str) -> list[dict]:
        payloads = [(g.to_dict(), self.cfg.symbol, self.cfg.timeframe, self.cfg.bars)
                    for g in population]
        results = []
        done = 0
        total = len(payloads)
        with ProcessPoolExecutor(max_workers=self.cfg.n_workers) as ex:
            futs = {ex.submit(_evaluate_genome_worker, p): p for p in payloads}
            for f in as_completed(futs):
                done += 1
                try:    r = f.result()
                except Exception as e: r = {"ok": False, "error": str(e)}
                if r.get("ok"):
                    results.append(r)
                if done % 50 == 0 or done == total:
                    self._emit(phase, f"evaluated {done}/{total}", done, total)
        return results

    # ── Elite selection ──
    def _select_elite(self, results: list[dict], pct: float = None) -> list[Genome]:
        pct = pct or self.cfg.elite_pct
        results.sort(key=lambda r: -r.get("score", 0))
        n = max(2, int(len(results) * pct))
        return [Genome.from_dict(r["genome"]) for r in results[:n]]

    # ── Purge ──
    def _purge(self, results: list[dict]):
        for r in results:
            if not r.get("ok"): continue
            passed, why = algory_purge_check(r["stats"], self.cfg.purge)
            if passed:
                r["purge_passed"] = True
                r["purge_reason"] = why
                self.vault.append(r)
            else:
                r["purge_passed"] = False
                r["purge_reason"] = why
                self.killed_genome_ids.add(r.get("id"))

    # ── Generation step: breed next from current ──
    def _breed(self, current: list[Genome], target_size: int, gen: int) -> list[Genome]:
        if len(current) < 2: return [Genome.random(gen) for _ in range(target_size)]
        next_pop = []
        elite_n = max(1, int(len(current) * 0.10))
        next_pop.extend(current[:elite_n])     # elite carry-over
        while len(next_pop) < target_size:
            a, b = random.sample(current, 2)
            child = Genome.crossover(a, b, gen)
            if random.random() < self.cfg.mutation_rate:
                child = child.mutate(self.cfg.mutation_rate, gen)
            next_pop.append(child)
        return next_pop[:target_size]

    # ── Top-level phases ──
    def proving_grounds(self) -> list[Genome]:
        # Elite carry-forward: seed PG with top genomes from Hall of Fame
        # so the GA continues from where prior cycles left off instead of
        # restarting from random every time
        seed_pop = self._load_elite_seeds(self.cfg.symbol)
        n_seeds = len(seed_pop)
        n_random = max(1, self.cfg.pg_candidates - n_seeds)

        self._emit("PG", f"Generating {n_random} random + {n_seeds} elite-carry genomes",
                   0, 1)
        pop = seed_pop + [Genome.random(gen=0) for _ in range(n_random)]
        self._emit("PG", f"Evaluating {len(pop)} candidates with {self.cfg.n_workers} workers", 0, len(pop))
        results = self._evaluate_population(pop, "PG")
        self._purge(results)
        elite = self._select_elite(results)
        self.elites = results[:50]
        self._emit("PG", f"Done. Survivors: {len(elite)}  Vault: {len(self.vault)}", 1, 1)
        return elite

    def _load_elite_seeds(self, symbol: str, n: int = 30) -> list:
        """Pull top genomes from Hall of Fame to seed this GA cycle.
        This is what makes the system actually accumulate wisdom across
        cycles instead of starting from scratch each time."""
        try:
            from r_native.hall_of_fame import get_elites
            elites = get_elites(symbol, n=n, include_pinned=True)
        except Exception:
            return []

        seeds = []
        for e in elites:
            params = e.get("all_params") or {}
            if not params:
                continue
            try:
                # Try Genome.from_dict (handles full genome dicts)
                g = Genome.from_dict(params)
                seeds.append(g)
            except Exception:
                continue
        return seeds

    def run_tribe(self, tribe_name: str, n_gens: int, seed: list[Genome]) -> list[Genome]:
        current = seed
        for gen in range(1, n_gens + 1):
            new_pop = self._breed(current, target_size=max(200, len(current) * 4), gen=gen)
            self._emit(tribe_name, f"Gen {gen}/{n_gens} — evolving {len(new_pop)} genomes", gen, n_gens)
            results = self._evaluate_population(new_pop, tribe_name)
            self._purge(results)
            current = self._select_elite(results)
            best = results[0] if results else {}
            self._emit(tribe_name, f"Gen {gen}/{n_gens} top score={best.get('score',0)} survivors={len(current)}",
                       gen, n_gens)
        return current

    def war(self, n_gens: int, tribe_a: list[Genome], tribe_b: list[Genome]) -> list[Genome]:
        current = tribe_a + tribe_b
        for gen in range(1, n_gens + 1):
            new_pop = self._breed(current, target_size=max(200, len(current) * 2), gen=gen)
            self._emit("WAR", f"Gen {gen}/{n_gens}", gen, n_gens)
            results = self._evaluate_population(new_pop, "WAR")
            self._purge(results)
            current = self._select_elite(results)
        return current

    def revival(self, n_gens: int, base: list[Genome]) -> list[Genome]:
        """Mutated revivals of historical bests."""
        revived = []
        for g in self.elites[:30]:
            revived.append(Genome.from_dict(g["genome"]).mutate(0.25, gen=999))
        if not revived: return base
        pop = base + revived
        return self.run_tribe("REVIVAL", n_gens, pop)

    def run_full_campaign(self) -> dict:
        t0 = time.time()
        CAMPAIGN_DIR.mkdir(parents=True, exist_ok=True)
        camp_name = f"{self.cfg.symbol}_{self.cfg.timeframe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        camp_path = CAMPAIGN_DIR / camp_name
        camp_path.mkdir(exist_ok=True)

        # Save config
        (camp_path / "config.json").write_text(json.dumps({
            "symbol":  self.cfg.symbol, "timeframe": self.cfg.timeframe,
            "bars": self.cfg.bars, "pg_candidates": self.cfg.pg_candidates,
            "tribe_a_gens": self.cfg.tribe_a_gens, "tribe_b_gens": self.cfg.tribe_b_gens,
            "war_gens": self.cfg.war_gens, "revival_gens": self.cfg.revival_gens,
            "retrain_gens": self.cfg.retrain_gens, "n_workers": self.cfg.n_workers,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2), encoding="utf-8")

        self._emit("CAMPAIGN", f"Starting {camp_name} — {self.cfg.n_workers} workers", 0, 1)

        # 1) PG
        survivors = self.proving_grounds()
        # 2) Tribe A
        tribe_a = self.run_tribe("TRIBE_A", self.cfg.tribe_a_gens, survivors[:50])
        # 3) Tribe B (different seed for diversity)
        random.seed(int(time.time() * 1000) % 2**31)
        tribe_b_seed = [Genome.random(gen=0) for _ in range(50)]
        results = self._evaluate_population(tribe_b_seed, "TRIBE_B_SEED")
        self._purge(results)
        tribe_b_seed = self._select_elite(results)
        tribe_b = self.run_tribe("TRIBE_B", self.cfg.tribe_b_gens, tribe_b_seed)
        # 4) War
        war_survivors = self.war(self.cfg.war_gens, tribe_a, tribe_b)
        # 5) Revival
        revival_survivors = self.revival(self.cfg.revival_gens, war_survivors)
        # 6) Final retrain
        final = self.run_tribe("RETRAIN", self.cfg.retrain_gens, revival_survivors)

        elapsed = time.time() - t0
        # Save vault
        self.vault.sort(key=lambda r: -r.get("score", 0))
        (camp_path / "vault.json").write_text(json.dumps(self.vault, ensure_ascii=False, indent=2),
                                               encoding="utf-8")

        summary = {
            "campaign":          camp_name,
            "symbol":            self.cfg.symbol,
            "timeframe":         self.cfg.timeframe,
            "elapsed_seconds":   round(elapsed, 1),
            "vault_size":        len(self.vault),
            "killed_count":      len(self.killed_genome_ids),
            "elite_genomes":     [r["genome"]["id"] for r in self.vault[:20]],
            "top_score":         self.vault[0]["score"] if self.vault else 0,
            "top_genome":        self.vault[0] if self.vault else None,
            "finished_at":       datetime.now(timezone.utc).isoformat(),
        }
        (camp_path / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
        self._emit("DONE", f"Campaign complete in {elapsed:.0f}s — vault {len(self.vault)} strats",
                   1, 1)
        return summary


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDm"
    tf  = sys.argv[2] if len(sys.argv) > 2 else "M5"
    # Quick test campaign (small PG)
    cfg = CampaignConfig(
        symbol=sym, timeframe=tf, bars=2000,
        pg_candidates=200, tribe_a_gens=3, tribe_b_gens=3,
        war_gens=3, revival_gens=2, retrain_gens=2,
    )
    def cb(phase, msg, done, total):
        print(f"  [{phase}] {msg}")
    engine = GeneticEngine(cfg, progress_cb=cb)
    out = engine.run_full_campaign()
    print(); print("="*60)
    print(f"  vault: {out['vault_size']} strategies passed purge")
    print(f"  top score: {out['top_score']}")
    print(f"  elapsed: {out['elapsed_seconds']}s")
    if out['top_genome']:
        g = out['top_genome']
        print(f"  best id: {g['genome']['id']}  stats: PF={g['stats'].get('profit_factor')} WR={g['stats'].get('win_rate')}% trades={g['stats'].get('trades')}")

