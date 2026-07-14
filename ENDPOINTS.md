# R-Native — API Endpoints

`brain_server.py` @ `localhost:5055` — 110 routes (56 under `/api/r/`).


| Endpoint | Methods | Purpose |
|---|---|---|
| `/api/r/agents/list` | [GET] | List all registered agents + their status. |
| `/api/r/agents` | [GET] | List all registered agents + their status. |
| `/api/r/agents/<name>/run` | ["POST"] | Path-style alias for dashboard: POST /api/r/agents/<name>/run |
| `/api/r/agents/toggle` | ["POST"] | Toggle a specific agent on/off. |
| `/api/r/agents/run_now` | ["POST"] | Manually trigger one tick of an agent. |
| `/api/r/agents/strategist_autonomous` | ["GET", "POST"] | Get or set the LLM Strategist's autonomous mode flag. |
| `/api/r/breed` | ["POST"] | Manually breed two HoF genomes into a child + admit to HoF. |
| `/api/r/agents/insights` | [GET] | Recent insights from the unified stream. |
| `/api/r/hof/summary` | [GET] | Hall of Fame stats — total genomes, by-symbol ranks, pinned count. |
| `/api/r/hof/symbol/<symbol>` | [GET] | Ranked list of all genomes ever produced for this symbol. |
| `/api/r/hof/pin` | ["POST"] | Pin/unpin a genome (pinned = immortal, can't be killed). |
| `/api/r/hof/deploy` | ["POST"] | Manually deploy a Hall-of-Fame genome to live. |
| `/api/r/auto_evo/status` | [GET] | Return continuous-evolution loop status. |
| `/api/r/auto_evo/toggle` | ["POST"] | Toggle the continuous-evolution loop on/off. |
| `/api/r/auto_evo/run_now` | ["POST"] | Fire one evolution cycle immediately (non-blocking). |
| `/api/r/auto_evo/config` | ["GET", "POST"] | Read or update continuous-evolution settings. |
| `/api/r/force_trade` | ["POST"] | Bypass ALL gates and fire a test trade. |
| `/api/r/memory` | [GET] | R's accumulated learning memory — LIGHT version for the UI. |
| `/api/r/executor` | [GET] | R executor state — mode, armed, today_pl, freeze status. |
| `/api/r/trades` | [GET] | Recent R trades from CSV. |
| `/api/r/trade_why/<ticket>` | [GET] | WHY a specific trade opened — full reasoning snapshot from the |
| `/api/r/indicator_matrix` | [GET] | Full 21-indicator × multi-timeframe confluence matrix for a symbol. |
| `/api/r/symbols` | [GET] | Ranked list of tradeable symbols + blacklist/whitelist. |
| `/api/r/training` | [GET] | Training session — when market closed, R simulates today and learns. |
| `/api/r/levels` | [GET] | Chart-read levels: PDH/PDL, VWAP+bands, swings, FVGs, round numbers. |
| `/api/r/sparkline` | [GET] | Lightweight closes series for per-symbol sparklines in scanner UI. |
| `/api/r/candles` | [GET] | OHLC candles for Lightweight-Charts on /r/, plus R's live entry/SL/TP |
| `/api/r/learning` | [GET] | R's adaptive learning state: per-archetype stats, recent trades, |
| `/api/r/similar` | [GET] | Pattern matcher: given a proposed setup, find historically similar |
| `/api/r/equity_curve` | [GET] |  |
| `/api/r/full` | [GET] | Single rich snapshot for the R Factory UI — combines account, executor, |
| `/api/r/proof_gate` | [GET] | HONEST PROOF-GATE for the R executor (magic 20260605). |
| `/api/r/hour_symbol_heatmap` | [GET] | Hour-of-day × symbol P/L heatmap for R trades (magic 20260605). |
| `/api/r/trade_gate` | [GET] | R's exact decision on whether to enter a trade RIGHT NOW. |
| `/api/r/multi_tf_strategies` | [GET] | For each TF (M5/M15/H1/H4), produce strategy guidance based on Algory wisdom. |
| `/api/r/gate_vs_algory` | [GET] | Side-by-side cross-validation: R's live gate verdict vs Algory's |
| `/api/r/genome/<gid>/info` | [GET] |  |
| `/api/r/genome/<gid>/decisions` | [GET] |  |
| `/api/r/genome/<gid>/bars` | [GET] |  |
| `/api/r/contenders` | [GET] | Return the current contender pipeline — genomes validated in shadow, |
| `/api/r/contenders/<child_id>/accept` | ["POST"] |  |
| `/api/r/contenders/<child_id>/reject` | ["POST"] |  |
| `/api/r/exposure` | [GET] | Per-symbol exposure snapshot: opens today, net P/L, DD-pause status. |
| `/api/r/monsters` | [GET] | List qualified monster genomes (sorted by monster_score). |
| `/api/r/genomes/active` | [GET] | List every deployed genome (and ensemble members) across all symbols, |
| `/api/r/indicators` | [GET] | Live indicator panel for a symbol/timeframe (Feature 2). |
| `/api/r/performance` | [GET] | Live performance summary from MT5 deal history (Feature 2). |
| `/api/r/strategy/polish` | ["POST"] | Claude Call A — natural language -> structured Strategy (Feature 1). |
| `/api/r/strategy/list` | [GET] |  |
| `/api/r/strategy/create` | ["POST"] |  |
| `/api/r/strategy/<sid>/status` | ["POST"] |  |
| `/api/r/strategy/<sid>/delete` | ["POST"] |  |
| `/api/r/chart_analysis` | [GET] | Claude Call B — analyze a chart, optionally draw on MT5 (Feature 3). |
| `/api/r/strategy/decisions` | [GET] | Live decision-log feed for the monitor (Feature 4). |
| `/api/r/strategy/<sid>/evaluate` | ["POST"] | Run one evaluation pass for a strategy now (Feature 4). |
| `/api/r/live` | [GET] | Aggregate the whole live signal system: per-symbol signal + breakdown, |
