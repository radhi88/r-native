# 00 — Active Runtime Classification
Generated: 2026-05-13

## Classification Key
- **ACTIVE** — runs in production via orchestrator, touches live trading
- **EXPERIMENT** — was tested but not in current orchestrator
- **TOOL** — utility / one-shot script
- **DASHBOARD** — UI only, no execution authority
- **ARCHIVE_CANDIDATE** — inactive, duplicated, or superseded
- **DO_NOT_TOUCH** — third-party library or irreplaceable infrastructure

---

## Root-level files

| File | Class | Notes |
|------|-------|-------|
| `algory_chart_dashboard.py` | DASHBOARD | Chart visualiser, port 8855, no execution |
| `algory_retrain.py` | TOOL | One-shot genome retraining trigger |
| `clean_reset_feature_learning.py` | TOOL | Resets feature-learning state files |
| `export_friday_status.py` | TOOL | Exports system status snapshot |
| `fix_live_brain_htmlresponse.py` | TOOL | One-shot patch, applied |
| `fractal_features.py` | ARCHIVE_CANDIDATE | Superseded by `fractal_structure_engine.py` |
| `fractal_gene_memory.py` | ARCHIVE_CANDIDATE | Old fractal memory system |
| `fractal_projection_backtester.py` | TOOL | Walk-forward calibration for fractal engine |
| `fractal_smc_engine.py` | ARCHIVE_CANDIDATE | Older SMC engine, superseded by `src/mt5_ai/` |
| `fractal_strategy.py` | ARCHIVE_CANDIDATE | Early fractal strategy, not in orchestrator |
| `friday_agents_browser.py` | DASHBOARD | Agent status browser, port 8833 |
| `friday_autopilot_supervisor.py` | ACTIVE | Supervises services, Tier 5 |
| `friday_brain.py` | ARCHIVE_CANDIDATE | Early brain, superseded by `friday_live_brain_state.py` |
| `friday_build_risk_memory_rules.py` | TOOL | One-shot risk-memory builder |
| `friday_capital_brain.py` | ACTIVE | Capital risk monitor (reads FRIDAY_MAGICS positions) |
| `friday_chat_app.py` | DASHBOARD | Chat UI, port 8811 |
| `friday_control_center.py` | DASHBOARD | Control panel UI |
| `friday_demo_position_governor.py` | **EXPERIMENT** ⚠️ | Direct order_send — closes/reverses positions. NOT in orchestrator |
| `friday_demo_position_governor_v2.py` | **EXPERIMENT** ⚠️ | Direct order_send — SLTP modify, REMOVE pending. NOT in orchestrator |
| `friday_entry_gate.py` | ACTIVE | Entry signal gate/filter |
| `friday_evolution_memory.py` | ACTIVE | Genome evolution memory |
| `friday_feature_outcome_learner.py` | ACTIVE | Feature learning loop, Tier 2 |
| `friday_gene_performance_report.py` | TOOL | Gene performance reporter |
| `friday_genome_status_export.py` | TOOL | Genome status exporter |
| `friday_health_monitor.py` | ACTIVE | Health watchdog, Tier 6 |
| `friday_indicator_feature_engine.py` | ACTIVE | Indicator engine, Tier 1 |
| `friday_jarvis_bridge.py` | ACTIVE | Bridge between FRIDAY and Jarvis |
| `friday_jarvis_voice.py` | EXPERIMENT | Voice command integration (no execution authority) |
| `friday_live_brain_state.py` | ACTIVE | Brain state loop, Tier 2 & 3 |
| `friday_local_gateway.py` | ACTIVE | API gateway, port 8799, Tier 3 |
| `friday_orchestrator.py` | ACTIVE | Master process supervisor |
| `friday_orderflow_feature_engine.py` | ACTIVE | Orderflow features, Tier 1 |
| `friday_project_map.py` | TOOL | Project structure documenter |
| `friday_realtime_scalper_brain.py` | ARCHIVE_CANDIDATE | Analysis only (no order_send), old runner |
| `friday_realtime_scalper_demo_executor.py` | **EXPERIMENT** ⚠️ | Direct order_send — DEMO executor. NOT in orchestrator |
| `friday_risk_close.py` | **EXPERIMENT** ⚠️ | Direct order_send — force closes positions. NOT in orchestrator |
| `friday_runtime_inventory.py` | TOOL | Runtime file scanner |
| `friday_scalper_live_dashboard.py` | DASHBOARD | Live dashboard, port 8822 |
| `friday_scalper_visual_explain.py` | TOOL | Visual explanation renderer |
| `friday_symbol_universe.py` | ACTIVE | Symbol configuration registry |
| `friday_system_mesh.py` | ACTIVE | System mesh monitor, Tier 3 |
| `friday_touch_demo_executor.py` | **EXPERIMENT** ⚠️ | Direct order_send — DEMO touch executor. NOT in orchestrator |
| `friday_trade_outcome_learner.py` | ACTIVE | Trade outcome learner, Tier 2 |
| `fractal_projection_backtester.py` | TOOL | Fractal calibration |
| `ict_sweep_trader.py` | **EXPERIMENT** ⚠️ | Direct order_send, magic=202605. NOT in orchestrator |
| `live_fractal_monitor.py` | ACTIVE | Fractal live monitor |
| `live_fractal_projection_monitor.py` | ACTIVE | Fractal projection monitor, Tier 4 |

## src/mt5_ai/ files

| File | Class | Notes |
|------|-------|-------|
| `algory_backtest.py` | ACTIVE | Genome backtesting engine |
| `algory_campaign.py` | ACTIVE | Campaign runner |
| `algory_dna.py` | ACTIVE | Genome DNA structure |
| `algory_integrator.py` | ACTIVE | Signal integrator with fractal filter |
| `algory_runner.py` | **ACTIVE** ⚠️ | **ONLY ACTIVE EXECUTOR** — 3 direct order_send calls |
| `algory_signal_engine.py` | ACTIVE | Signal computation (no execution) |
| `config.py` | ACTIVE | Central config (DEFAULT_MAGIC=260426) |
| `fractal_structure_engine.py` | ACTIVE | Fractal analysis engine |
| `market_projection_engine.py` | ACTIVE | Market projection engine |
| `mt5_gateway.py` | ACTIVE | **INTENDED low-level adapter** (6 order_send calls) |
| `prop_firm_guard.py` | ACTIVE | Prop firm rule checker |
| `gene_fitness_db.py` | ACTIVE | Gene fitness database |

## scripts/ directory

| File | Class | Notes |
|------|-------|-------|
| `ict_sweep_trader.py` | **EXPERIMENT** ⚠️ | Duplicate of root, magic=20260506 |
| `mt5_ollama_trader.py` | **EXPERIMENT** ⚠️ | Ollama AI → direct order_send, magic=88888 |
| `trading_trace_scanner.py` | TOOL | Scans for execution traces |
| `_run_monitor.py` | TOOL | Monitor launcher |

## Other directories

| Directory | Class | Notes |
|-----------|-------|-------|
| `OpenJarvis/` | DO_NOT_TOUCH | Third-party framework library |
| `mark_xxxix/` | DO_NOT_TOUCH | Personal AI assistant (Jarvis), no trading execution |
| `scripts/friday_web_dashboard.py` | DASHBOARD | AI dashboard, port 8790 |
| `selected_code/` | ARCHIVE_CANDIDATE | Snapshot of old code versions |
| `patch_backups/` | ARCHIVE_CANDIDATE | Applied patches archive |
| `FRIDAY_Gold_EA.mq5` | EXPERIMENT | Separate MT5 EA (separate execution path) |

---

## Summary

| Class | Count |
|-------|-------|
| ACTIVE | 22 |
| EXPERIMENT ⚠️ | 9 |
| DASHBOARD | 7 |
| TOOL | 12 |
| ARCHIVE_CANDIDATE | 8 |
| DO_NOT_TOUCH | 2 directories |
