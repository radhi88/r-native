# Report 20 — Degenerate Retrain Incident

**Date:** 2026-05-13  
**Severity:** HIGH — numerical safety incident  
**Status:** CONTAINED — processes terminated, no persistent storage contaminated

---

## Incident Summary

During a scheduled full retrain cycle (`python algory_retrain.py --clear-fitness --symbols EURUSDm GBPUSDm USDJPYm AUDUSDm`), the EURUSDm H1 campaign produced a degenerate genome with physically impossible fitness scores.

---

## Degenerate Genome Signature

| Metric | Value | Normal Range | Status |
|--------|-------|--------------|--------|
| Score (modern) | 26,806,002.13 | 0–50 | **DEGENERATE** |
| Return % | 4,337,520,470.7% | 0–200% realistic | **OVERFLOW** |
| Win Rate | 17.9% | — | — |
| Drawdown | 30.2% | — | — |
| Trades | 95 | min 40 | Low |

---

## Root Cause

The backtest simulation uses compounding equity:

```
pnl = (price_diff) × (equity × risk_pct / |entry_px - sl_px|)
```

When H1 bar data produces many winning trades in sequence on a compounding account (starting equity = 100,000), the equity can grow unconstrained. Once equity exceeds ~10M, floating-point multiplication in subsequent PnL calculations triggers **OverflowError (errno 34, ERANGE)** or produces values exceeding float64 range. The `modern_score()` formula `(ret/dd) × linearity × persistence` then produces a number in the billions.

**Why H1 specifically:** H1 bars represent full hours of price movement. Genomes that trigger on major H1 structures see fewer but larger individual candle moves, and when these align in a single direction the simulation compounds violently. M15 produced the same ERANGE error 13 minutes earlier (at 00:59:02) but the process was still running.

**Evolution stagnation:** Gen 2 and Gen 3 selected the identical degenerate genome, confirming that once an overflow genome enters the population it dominates and blocks evolution progress.

---

## Timeline

| Time (UTC) | Event |
|------------|-------|
| 2026-05-13 00:47 | EURUSDm M15 campaign terminated — ERANGE error |
| 2026-05-13 02:03 | EURUSDm H1 PG complete — 400/4000 survived |
| 2026-05-13 02:03 | Tribe A Gen 1: Score 23,764,414 first appears |
| 2026-05-13 02:06 | Tribe A Gen 2: Score 26,806,002 — degenerate genome propagated |
| 2026-05-13 02:10 | Tribe A Gen 3: Same genome selected — evolution stagnated |
| 2026-05-13 02:10 | User reported incident |
| 2026-05-13 02:10 | PIDs 23368 and 29016 terminated (SIGTERM) |

---

## Contamination Assessment

| Storage Location | Contaminated? | Evidence |
|-----------------|---------------|---------|
| `active_genomes.json` | **NO** | EURUSDm\|H1 entry has total_pnl=123766.5 (pre-existing clean genome) |
| `data/campaigns/20260513_0059/vault.json` | **NO** | Directory empty — vault.json only written at end of purge phase |
| `gene_fitness_db` / `gene_fitness.json` | **NO** | File = `{}` (2 bytes, empty) |
| `friday_strategy_genes.json` | **NO** | Not part of Algory pipeline |
| `friday_evolution_events.jsonl` | **NO** | Not part of Algory pipeline |

**Conclusion: Zero persistent contamination.** The degenerate genome existed only in process memory at the time of termination.

---

## Quarantine

No files require quarantine. The EURUSDm H1 campaign directory `data/campaigns/20260513_0059/` is empty (no vault.json was written before termination).

---

## INCIDENT_STATUS = CONTAINED_NO_STORAGE_CONTAMINATION
