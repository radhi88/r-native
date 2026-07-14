# Report 52 - Qader Learning Design

Generated: 2026-05-14

## Learning Scope

Qader learning is deliberately config-only. It can learn from dry-run decisions, blocked trades, arbiter outcomes, user feedback, and performance metrics. It cannot rewrite production Python source code while running.

## Inputs

- Scanner decisions from `ScannerService`
- Dry-run result summaries from `RunnerService`
- SignalArbiter confidence and reason codes
- Risk blocks and ConflictGuard blocks
- User feedback and saved preferences

## Outputs

- Decision scores in `data/qader/dna/performance_journal.jsonl`
- Mutation proposals in memory/report output
- Approved genome updates in `active_genome.json`
- Rollback events in `genome_history.jsonl`

## Minimal Loop

```text
collect decisions
  -> EvaluationEngine.score_decision()
  -> append performance journal
  -> summarize score
  -> MutationEngine.propose_threshold_adjustment()
  -> require can_modify_strategy_dna + explicit approval
  -> apply config-only genome mutation or reject
  -> rollback if performance floor is breached
```

## Safety Rules

- Mutations affect JSON genome/config only.
- Source code is never self-modified.
- `can_modify_strategy_dna` is required for applying changes.
- Approval is required before any mutation is applied.
- Bad performance can rollback to the default genome.
- Every scoring, proposal, apply, reject, and rollback event is logged.

