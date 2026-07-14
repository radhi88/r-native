# Report 25 — Breeding Pool System

**Date:** 2026-05-13  
**Module:** `src/mt5_ai/core/breeding_pool.py`

---

## Purpose

The `BreedingPool` is the gatekeeper between campaign output and active evolution. Only genomes with status `APPROVED_FOR_BREEDING` or higher may enter. The pool enforces:

1. **Size limit** — max 50 genomes
2. **Family dominance limit** — one parent lineage ≤ 30% of pool
3. **Correlation / diversity check** — no two members with gene correlation > 85%
4. **Quality replacement** — when pool is full, new genome must beat the weakest to enter
5. **Always quality-gated** — every `add()` call runs the full gate first

---

## Pool Entry Tracking

Each `PoolEntry` records:

| Field | Description |
|-------|-------------|
| `genome_id` | Unique identifier |
| `symbol` / `timeframe` | Asset this genome was trained on |
| `bounded_score` | Gate score (0–1000) |
| `quality_score` | Same as bounded_score |
| `robustness_score` | `√(linearity × persistence)` |
| `stability_score` | Equity linearity R² |
| `oos_score` | OOS/IS ratio (0–1) |
| `return_pct` | Net return on balance |
| `drawdown_pct` | Maximum drawdown |
| `winrate` | Win rate |
| `trades` | Trade count |
| `profit_factor` | Gross profit / gross loss |
| `status` | GenomeStatus at admission |
| `parent_ids` | Parent genome IDs for lineage tracking |
| `mutation_history` | List of mutation events |
| `binary_signature` | Gene vector for diversity check |
| `added_at` | Admission timestamp |

---

## Admission Rules (beyond gate approval)

A genome that passes `APPROVED_FOR_BREEDING` from the gate must additionally:

| Rule | Check |
|------|-------|
| Pool size | If pool full: new score must beat weakest member |
| Family dominance | Parent lineage ≤ 30% of pool |
| Correlation | Gene similarity ≤ 85% to any existing member |

If any pool admission rule fails, the genome becomes `WATCHLIST` (not rejected — it's still valid, just not needed in the pool right now).

---

## Parent Selection for Breeding

`select_parents(symbol, timeframe, n=2)` returns `n` diverse high-quality parents:
1. Always includes the highest-scoring member
2. Each subsequent parent must have gene correlation < 70% with all already-selected parents
3. Ensures offspring inherits from diverse gene sets, not clones of the same strategy

---

## Diversity Metric

Gene correlation is computed as **Jaccard similarity** on binary gene vectors:

```
similarity = matching_gene_count / total_gene_count
```

A score of 1.0 means identical gene sets. 0.0 means completely different.

Threshold for rejection from pool: **0.85**  
Threshold for breeding pair selection: **0.70** (stricter for evolution quality)

---

## Persistence

The pool is saved to `data/breeding_pool.json` after every admission. Format:

```json
{
  "saved_at": "2026-05-13T...",
  "count": 12,
  "pool": [ { "genome_id": "...", "bounded_score": 423.0, ... }, ... ]
}
```

---

## Logging

Every pool event is written to `logs/breeding_pool_log.jsonl`:

| Event | Trigger |
|-------|---------|
| `added_to_pool` | Genome successfully admitted |
| `rejected_from_pool` | Gate failed or pool admission rule failed |
| `evicted_from_pool` | Weakest genome removed to make room |

---

## Approved-for-Demo Pathway

A genome can only reach `APPROVED_FOR_DEMO` (highest status) if:
1. It is `APPROVED_FOR_BREEDING` first
2. Passes controlled dry-run execution (Report 13/15 conditions)
3. Passes recent market validation
4. Has no safety flags or quarantine history
5. RiskManager accepts it at runtime
6. `max_lot` remains 0.01, `max_open_positions` remains 1

This is a manual promotion — no code automatically sets `APPROVED_FOR_DEMO`.

---

## BREEDING_POOL_STATUS = IMPLEMENTED
