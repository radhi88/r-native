# Report 24 — Genome Quality Gate

**Date:** 2026-05-13  
**Module:** `src/mt5_ai/core/genome_quality_gate.py`

---

## Purpose

Every genome MUST pass the `GenomeQualityGate` before:
- Survivor selection / ranking
- Database storage
- Memory save
- Best-genome promotion
- Runtime loading
- Breeding

No genome ever bypasses this gate.

---

## Genome Status Ladder

| Status | Meaning | Trust Level |
|--------|---------|-------------|
| `REJECTED` | Hard rule violation — never use | 0 |
| `QUARANTINED` | Degenerate — archived, blocked everywhere | 0 |
| `CANDIDATE` | Passes hard rules and metric sanity | 1 |
| `WATCHLIST` | Passes hard rules, borderline metrics | 0.5 |
| `APPROVED_FOR_BREEDING` | Passes all quality gates including OOS | 2 |
| `APPROVED_FOR_DEMO` | Breeding-approved + dry-run validated | 3 |
| `ACTIVE_DISABLED` | Was active, now suspended | — |

---

## Hard Rejection Rules

A genome is **immediately rejected** if any of these fire:

| Rule | Condition | Reason |
|------|-----------|--------|
| R1 | `score > 10,000` | Impossible in valid Modern scoring |
| R2 | `abs(return_pct) > 100,000%` | Overflow / simulation error |
| R3 | Any metric is NaN or Inf | Corrupted computation |
| R4 | `OverflowError` (ERANGE) caught | Caller calls `reject_erange()` |
| R5 | `return_pct > 50,000% AND trades < 500` | Disproportionate return |
| R6 | `winrate > 95% AND trades < 300` | Statistical artefact |
| R7 | `drawdown ≤ 0.05% AND return > 1,000%` | Physically impossible |
| R8 | Near-zero denominator | `guard_denominator()` prevents /0 |
| RMIN | `trades < 100` | Too few to trust any metric |
| RDEP | `wins < 3` | Result depends on too few winners |
| RDOM | Single trade > 40% of total profit | Trade dominance |
| RJMP | Single equity step > 300% | Unrealistic equity jump |
| RCONS | WR × trades inconsistent with wins | Mathematical inconsistency |
| RPF | `profit_factor > 1e12` | Infinite profit factor |

---

## Candidate Rules

A genome becomes `CANDIDATE` if:
- All hard rejection rules pass
- `drawdown_pct` ≤ 35%
- `winrate` between 15% and 85%
- `profit_factor` between 1.05 and 5.0
- `trades` ≥ 150

A genome becomes `WATCHLIST` if it passes hard rules but has borderline metrics.

---

## Bounded Score (0–1000)

The raw `modern_score()` formula `(ret/dd) × linearity × persistence` can produce millions. The gate computes a **bounded robust score** capped at 1000:

| Component | Max Points | Formula |
|-----------|-----------|---------|
| Profitability | 250 | `log(1 + ret/100) / log(3)` — capped at 200% return |
| Drawdown control | 200 | `(35 - dd) / 35` — 0% DD = 200, 35%+ DD = 0 |
| Stability | 150 | Equity linearity R² |
| Consistency | 150 | Persistence across rolling windows |
| Trade count | 150 | Sigmoid to 500 trades |
| Profit factor bonus | 100 | PF 1.0→0, PF 3.0→100 |
| OOS multiplier | ×0.5–1.0 | Degrades if OOS underperforms IS |

**Maximum total: 1000. No degenerate genome can score above 0.**

---

## Quarantine System

All genomes that trigger R1–R7 are:
1. Rejected immediately
2. Written to `src/mt5_ai/archive/quarantined_genomes/` as a JSON snapshot
3. Logged to `logs/fitness_safety_log.jsonl` and `logs/genome_quality_log.jsonl`

Quarantine metadata includes: symbol, timeframe, generation, score, return_pct, drawdown_pct, winrate, trades, rejection reason, source, timestamp.

---

## Runtime Loader Protection

If `algory_loader` or any runtime loader attempts to load an invalid genome:
- Gate rejects it
- Rejection logged
- Loader continues to next genome (fallback to HOLD / no-trade if no valid genome available)
- No silent fallthrough with invalid genome

---

## Integration Points

| File | Gate Called At |
|------|---------------|
| `algory_campaign.py` | PG ranking, tribe generation ranking |
| `gene_fitness_db.py` | Before any record written to fitness DB |
| `algory_loader.py` | Before `integrator.registry.activate()` |
| `algory_retrain.py` | Before survivor is accepted into results |
| `algory_dna.py` | `modern_score()` returns 0 if non-finite |
| `algory_backtest.py` | Equity capped at 1000× balance, ERANGE caught |

---

## QUALITY_GATE_STATUS = IMPLEMENTED
