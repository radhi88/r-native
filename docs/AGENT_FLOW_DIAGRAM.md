# Qader Agent Flow Diagram

This diagram shows the live Qader/FRIDAY agent path as implemented in the
REAL_CONTROLLED_MODE loop. Learning changes Strategy DNA only; Python source
modification stays disabled.

```mermaid
flowchart TD
    A[Qader Loop<br/>scripts/run_qader_headless.py] --> B[RealTimeLoopService]
    B --> C[MT5 demo/trial account gate]
    C --> D[Fetch bars and tick data]
    D --> E[FractalAgent]
    D --> F[SmcAgent]
    D --> G[IctSweepAgent]
    E --> H[SignalArbiter]
    F --> H
    G --> H
    I[active_genome.json<br/>arbiter_pass threshold] --> H
    J[arbiter_gene_weights.json<br/>Bayesian feedback] --> H
    H --> K[DecisionRouter]
    K --> L[ConflictGuard]
    L --> M[RiskManager]
    M --> N[ExecutionManager<br/>only order_send caller]
    N --> O[MT5 order]
    O --> P[EventBus<br/>trade_opened]
    O --> Q[live_performance_journal.jsonl]
    Q --> R[LearningService]
    R --> S[EvaluationEngine<br/>score decisions]
    S --> T[MutationEngine<br/>proposal]
    T --> U{auto_apply_proposals<br/>permission + samples + cooldown}
    U -->|approved| I
    U -->|guarded| V[dna_learning_proposal journal event]
    Q --> W[dna_live_feedback.py]
    W --> X[gene_store_backtest.json]
    X --> J
    B --> Y[qader_live_state.json]
    Y --> Z[Dashboards and voice state]
```

## Runtime Notes

- `RealTimeLoopService` records every cycle into `logs/qader_realtime_loop.jsonl`.
- Trade entries call the learning path through `_record_trade_learning()`.
- `LearningService` proposes threshold changes from recent scored decisions.
- `MutationEngine` applies proposals to `data/qader/dna/active_genome.json` only when `can_modify_strategy_dna` is granted.
- `SignalArbiter` reads `active_genome.json` as its base threshold and lets matching Bayesian gene weights override it for a specific market context.
- Dashboard state includes `learning_state` from the latest proposal/application attempt.
