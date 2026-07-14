# Architecture

## The Infinite Geometric Loop

```
                         ┌──────────────────────────────────────────┐
                         │            orchestrator.loop               │
                         └──────────────────────────────────────────┘
                                          │ per symbol, per cycle
     ┌───────────────┬────────────────────┼────────────────────┬─────────────────┐
     ▼               ▼                     ▼                    ▼                 ▼
MarketDataAgent  HRExamAgent          AnalysisAgent          RiskAgent      ExecutionAgent
 fetch OHLC      walk-forward exam    SMC + Gann/Sq9 +       Kelly + ATR    demo-guarded
 + symbol meta   (sweep params,       fractals + VP +        survival       order_send
                 score 0–100)         regime + ML →          sizing +       (mandatory SL,
                                      confluence matrix      session gate   no martingale)
                                          │                                      │
                                          ▼                                      ▼
                                     ChartAgent (PNG)                   data/markets/*.db
                                                                       (ticks · journal · exams)
```

Each cycle: data → exam → analysis → risk → (chart + journal) → execution.
Execution fires only when the deploy gate is open.

## Modules

| Package | Responsibility |
|---|---|
| `config` | Safety flags, per-market `MarketProfile`s, symbol routing, JSON overrides |
| `core/micro_equity` | Modified Kelly, ATR stop, fractional sizing, **$10 survival rule** |
| `core/gann` | Square of 9, Gann-angle fans (1×1 / 1×2 / 2×1) |
| `core/fractals` | Williams fractals (right-confirmed, causal) |
| `core/smc` | BOS / CHoCH / OB / FVG / liquidity sweep |
| `core/indicators` | EMA, Wilder ATR/RSI, VWAP |
| `core/volume_profile` | POC / VAH / VAL |
| `core/regime` | trend/range/volatile classifier |
| `core/ml_signal` | Logistic next-bar vote (honest, ~coin-flip) |
| `core/confluence` | The trade-or-pass matrix |
| `core/charts` | Annotated geometric chart artist |
| `data/db` | Per-market SQLite (enterprise schema + audit BLOB + exam log) |
| `markets/*` | Per-asset-class strategy declarations |
| `agents/broker` | MT5 IO + demo guard + guarded `order_send` |
| `agents/desk_agents` | The five pipeline agents + HR exam agent |
| `agents/hr_manager` | Autonomous R&D + exam grading loop |
| `exam/backtest` | Walk-forward, net-of-spread, no-lookahead, 0–100 score |
| `rl/*` | Linear Q-learning scaffold over the feature space |
| `reports/report` | Final transparency report (Gann/Sq9 + model arch + PF) |
| `dashboard/desk_dashboard` | Read-only live console |
| `scripts/watchdog` | Singleton + auto-respawn supervisor |

## The deploy gate (the spine)

A trade reaches the broker only when **all** hold:

1. `REQUIRE_EXAM_PASS` is `False` (forward-test) **or** the symbol's exam
   scored ≥ 95 with PF ≥ 2.5;
2. the confluence matrix proposes a trade (≥ `MIN_CONFLUENCES` aligned and ML
   confidence ≥ `ML_CONFIDENCE_GATE`);
3. survival sizing accepts (min-lot risk ≤ 15% of equity, margin ≤ 90% free);
4. the market session is open and the daily-loss halt is clear;
5. the account is a **demo** and no position is already open in the symbol.

## Honesty contract

This project's own out-of-sample research found SMC, fractals, and ML
direction to be NO_EDGE net of cost; the durable edge is discipline + sizing.
The desk is built so the risk engine is load-bearing and the geometry must earn
its way past an adversarial exam before it can risk the account. See
`README.md` and the project memory for the full record.
