# Report 62 - Qader DNA Engine

Generated: 2026-05-14

## Files

```text
src/qader_app/genome/gene_store.py
src/qader_app/genome/strategy_dna.py
src/qader_app/genome/mutation_engine.py
src/qader_app/genome/evaluation_engine.py
```

Runtime DNA files:

```text
data/qader/dna/default_genome.json
data/qader/dna/active_genome.json
data/qader/dna/genome_history.jsonl
data/qader/dna/performance_journal.jsonl
```

## Genome Contents

The default genome stores:
- agent weights
- confidence thresholds
- ATR SL/TP multipliers
- spread limits
- max lot
- symbol/timeframe preferences
- session behavior
- rollback performance floor

## Mutation Rules

- Mutations are JSON config changes only.
- Source code mutation is not allowed.
- `can_modify_strategy_dna` is required.
- Explicit approval is required.
- Rejections are logged.
- Rollback restores the default genome if performance falls below the configured floor.

## Current Default Safety

`max_lot` is `0.01`. Live trading remains locked outside the DNA layer and cannot be enabled by genome mutation.

