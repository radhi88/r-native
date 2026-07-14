# Report 21 — Numeric Safety Patch

**Date:** 2026-05-13  
**Trigger:** Degenerate Retrain Incident (Report 20)  
**Status:** PATCH_COMPLETE

---

## New Module

**`src/mt5_ai/core/numeric_safety.py`** — created

8 rejection rules applied at every validation call:

| Rule | Condition | Threshold |
|------|-----------|-----------|
| R1 | `score > SCORE_MAX` | 10,000 |
| R2 | `abs(return_pct) > RETURN_MAX` | ±100,000% |
| R3 | `isnan(v) or isinf(v)` | any metric |
| R4 | ERANGE `OverflowError` caught | caller calls `reject_erange()` |
| R5 | `return_pct > 50,000 and trades < 500` | disproportionate return |
| R6 | `winrate > 0.95 and trades < 300` | statistical artefact |
| R7 | `drawdown <= 0.05% and return_pct > 1,000%` | physically impossible |
| R8 | `abs(denominator) < 1e-10` | `guard_denominator()` helper |

All rejections write to `logs/fitness_safety_log.jsonl` (both project-level and AppData).

---

## Files Patched

### 1. `src/mt5_ai/algory_dna.py` — `modern_score()`

Added `guard_denominator(dd, fallback=1.0)` before dividing by drawdown.  
Added `math.isfinite()` check on `ret` and `dd` before scoring.  
Added `math.isfinite(score)` guard on result — returns 0.0 if not finite.

### 2. `src/mt5_ai/algory_backtest.py` — `_simulate()` + `_worker()`

- Added `EQUITY_CAP = balance × 1000` (caps at 100M from 100K start) — prevents float overflow in compounding PnL.
- Applied `equity = min(equity, EQUITY_CAP)` after each trade exit.
- Added `except OverflowError` in `_worker()` — calls `reject_erange()` and returns error result.

### 3. `src/mt5_ai/algory_campaign.py` — `run_proving_grounds()` + `run_tribe()`

- Added `from .core.numeric_safety import validate_genome` import.
- In `run_proving_grounds()`: filters all candidates through `validate_genome()` before sort.
- In `run_tribe()`: filters all genomes through `validate_genome()` at each generation ranking before `pop.sort()`. Population never emptied (fallback to full pop if all rejected).

### 4. `src/mt5_ai/gene_fitness_db.py` — `record_genome_result()`

Added `validate_genome()` check at entry. Degenerate genomes are blocked before any record is written to the fitness DB.

### 5. `src/mt5_ai/algory_loader.py` — `bootstrap_from_algory_vault()`

Added `validate_genome()` check before `integrator.registry.activate()`. Degenerate loaded genomes are blocked and logged.

### 6. `algory_retrain.py` — `run_campaigns()`

Added `validate_genome()` check after `integrator.run_campaign_and_activate()` returns a genome. Degenerate results are rejected, logged, and `results[key]` set to `None` instead.

---

## Coverage Map

| Stage | Guard | Rule(s) |
|-------|-------|---------|
| PG fitness evaluation | `_worker()` OverflowError catch | R4 |
| PG simulation equity | `EQUITY_CAP` in `_simulate()` | R4/R2 |
| PG genome scoring | `modern_score()` finite guard | R3/R8 |
| PG survivor ranking | `validate_genome()` in `run_proving_grounds()` | R1–R7 |
| Tribe generation ranking | `validate_genome()` in `run_tribe()` | R1–R7 |
| Fitness DB recording | `validate_genome()` in `record_genome_result()` | R1–R7 |
| Runtime loader | `validate_genome()` in `bootstrap_from_algory_vault()` | R1–R7 |
| Retrain acceptance | `validate_genome()` in `run_campaigns()` | R1–R7 |

---

## Degenerate Genome Would Have Been Caught At

Applying the patch to the actual incident:

| Check | Rule | Would Catch? |
|-------|------|-------------|
| Gen 1 PG ranking | R1: score=23,764,414 > 10,000 | ✅ YES |
| Gen 2 tribe ranking | R1: score=26,806,002 > 10,000 | ✅ YES |
| Gen 2 tribe ranking | R2: return=4,337,520,470% > 100,000% | ✅ YES |
| Equity overflow | R4: OverflowError caught, returns error result | ✅ YES |

**The degenerate genome would have been rejected at PG ranking (before Gen 1 was even declared champion).**

---

## PATCH_STATUS = COMPLETE
