# 03 — Strategy Ownership
Generated: 2026-05-13

## Module Classification & Future Role

| Module | Current Type | Future Role |
|--------|-------------|-------------|
| `src/mt5_ai/algory_signal_engine.py` | Signal computation | **SignalProducer** |
| `src/mt5_ai/algory_integrator.py` | Signal integrator + fractal filter | **DecisionRouterContributor** |
| `src/mt5_ai/algory_runner.py` | Runner + executor | Split: analysis→SignalProducer, execution→ExecutionManager |
| `src/mt5_ai/fractal_structure_engine.py` | Fractal analysis | **SignalProducer** (FractalAgent) |
| `src/mt5_ai/market_projection_engine.py` | Projection engine | **SignalProducer** (FractalAgent) |
| `src/mt5_ai/mt5_gateway.py` | MT5 adapter | **MT5Gateway** |
| `src/mt5_ai/prop_firm_guard.py` | Prop firm rules | **RiskFilter** |
| `src/mt5_ai/algory_backtest.py` | Backtesting | **ToolOnly** |
| `src/mt5_ai/algory_campaign.py` | Genome campaign | **ToolOnly** |
| `src/mt5_ai/algory_dna.py` | Genome DNA | **SignalProducer** component |
| `friday_demo_position_governor.py` | Position management + execution | **PositionManagementContributor** (after exec removed) |
| `friday_demo_position_governor_v2.py` | Position management + execution | **PositionManagementContributor** (after exec removed) |
| `friday_realtime_scalper_demo_executor.py` | Scalper strategy + execution | **ArchiveCandidate** (superseded) |
| `friday_realtime_scalper_brain.py` | Scalper signal analysis | **SignalProducer** (ScalperAgent) |
| `friday_touch_demo_executor.py` | Touch strategy + execution | **ArchiveCandidate** (superseded) |
| `friday_risk_close.py` | Emergency risk close | **PositionManagementContributor** (emergency action) |
| `scripts/mt5_ollama_trader.py` | Ollama AI + execution | **SignalProducer** (OllamaAgent) after exec removed |
| `ict_sweep_trader.py` / `scripts/ict_sweep_trader.py` | ICT sweep + execution | **SignalProducer** (IctSweepAgent) after exec removed |
| `fractal_smc_engine.py` | SMC analysis | **ArchiveCandidate** (superseded by fractal_structure_engine) |
| `friday_capital_brain.py` | Capital risk monitor | **RiskFilter** |
| `friday_entry_gate.py` | Entry signal gate | **DecisionRouterContributor** |
| `friday_live_brain_state.py` | Brain state | **SignalProducer** (AiAgent) |
| `friday_jarvis_bridge.py` | Jarvis bridge | **DashboardOnly** — no execution |
| `friday_jarvis_voice.py` | Voice commands | **DashboardOnly** — request pipeline only |
| `mark_xxxix/` | AI personal assistant | **DashboardOnly** — no trading execution |
| `FRIDAY_Gold_EA.mq5` | MT5 EA | Separate execution boundary — document only |
