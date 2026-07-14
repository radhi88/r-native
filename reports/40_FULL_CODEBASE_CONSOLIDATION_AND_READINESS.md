# Report 40 - Full Codebase Consolidation and Readiness

Generated: 2026-05-14T02:22:35+03:00

## 1. Executive Summary

The active controlled runner is `src/mt5_ai/runtime/main_loop.py`. The active architecture is:

`Agents -> SignalArbiter -> DecisionRouter -> ConflictGuard -> RiskManager -> ExecutionManager`.

The codebase remains **DRY_RUN / simulate_only only**. Live trading was not enabled. No real MT5 orders were placed. Claude supervisor findings were read from `reports/claude_review/` and safe recommendations were integrated.

Final safety status: **SAFE_FOR_DRY_RUN_ONLY**.

## 2. Actual Elapsed Time Per Phase

| Phase | Start | End | Elapsed seconds | Result |
|---|---:|---:|---:|---|
| PHASE 1 - Repository Inventory | 2026-05-14T02:22:14+03:00 | 2026-05-14T02:22:29+03:00 | 15.308 | inventory complete: 88395 files, 1528 Python files, 33 active/support files, 1 parse warnings |
| PHASE 2 - Active Pipeline Mapping | 2026-05-14T02:22:29+03:00 | 2026-05-14T02:22:29+03:00 | 0.0 | mapped active Agents -> SignalArbiter -> DecisionRouter -> ConflictGuard -> RiskManager -> ExecutionManager |
| PHASE 3 - Legacy and Duplicate Detection | 2026-05-14T02:22:29+03:00 | 2026-05-14T02:22:29+03:00 | 0.036 | legacy scan complete: 8 clear archive candidates |
| PHASE 4 - Safe Cleanup Plan and Implementation | 2026-05-14T02:22:29+03:00 | 2026-05-14T02:22:29+03:00 | 0.002 | archived 8 disabled legacy stubs |
| PHASE 5 - Merge Status Report | 2026-05-14T02:22:29+03:00 | 2026-05-14T02:22:29+03:00 | 0.001 | merge status complete for 12 legacy components |
| PHASE 6 - Safety Verification | 2026-05-14T02:22:29+03:00 | 2026-05-14T02:22:29+03:00 | 0.182 | PASS: account clean, exit code 0 |
| PHASE 7 - Static Safety Scan | 2026-05-14T02:22:29+03:00 | 2026-05-14T02:22:30+03:00 | 0.567 | static scan complete: 8 guarded order_send calls, 0 unguarded active order_send calls, live-enabled configs=0 |
| PHASE 8 - Controlled Runtime Test | 2026-05-14T02:22:30+03:00 | 2026-05-14T02:22:33+03:00 | 3.425 | runtime dry-run complete; real_order_send_calls=0; errors=0 |
| PHASE 9 - Import and Test Validation | 2026-05-14T02:22:33+03:00 | 2026-05-14T02:22:35+03:00 | 1.879 | safe tests complete: 7/7 passed |

Total measured phase elapsed: `21.4` seconds.

## 3. Active Architecture Map

```text
MT5 read-only bars -> FractalAgent / SmcAgent / IctSweepAgent
  -> SignalArbiter
  -> DecisionRouter
  -> ConflictGuard
  -> RiskManager
  -> ExecutionManager
  -> DRY_RUN simulated execution in current config
```

Position management path:

```text
GovernorAgent / RiskCloseAgent -> PositionManager -> ExecutionManager -> DRY_RUN simulated close/modify in current config
```

## 4. Main Runner Confirmation

Main runner confirmed: `src/mt5_ai/runtime/main_loop.py`.

## 5. Active Files Table

| file_path | purpose | connected_to_main_loop.py | reason |
|---|---|---|---|
| test_100_cycles.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| verify_mt5_lockdown.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| config/dry_run_simulation.yaml | active main_loop pipeline component or direct support | yes | connected to active runner |
| config/trading_runtime.yaml | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/ai_brain.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/algory_signal_engine.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/config.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/fractal_structure_engine.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/learning_journal.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/market_projection_engine.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/market_structure.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/mt5_gateway.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/pivot_engine.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/strategy_profiles.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/agents/fractal_agent.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/agents/governor_agent.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/agents/ict_sweep_agent.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/agents/risk_close_agent.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/agents/smc_agent.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/agents/__init__.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/config_loader.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/conflict_guard.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/decision_router.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/execution_manager.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/indicators.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/kill_switch.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/magic_registry.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/position_manager.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/risk_manager.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/signal_arbiter.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/signal_schema.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/core/structured_logger.py | active main_loop pipeline component or direct support | yes | connected to active runner |
| src/mt5_ai/runtime/main_loop.py | active main_loop pipeline component or direct support | yes | connected to active runner |

## 6. Legacy Files Table

Showing first 120 legacy/archive-classified files. Full inventory is in `reports/40_FILE_INVENTORY.csv`.

| file_path | purpose | safe_to_archive | reason |
|---|---|---|---|
| patch_dashboard_feature_forecast.py | legacy patch/reset/helper script | yes | not connected to main_loop.py and appears historical |
| patch_feature_engine_weights.py | legacy patch/reset/helper script | yes | not connected to main_loop.py and appears historical |
| patch_feature_learner_learn_after.py | legacy patch/reset/helper script | yes | not connected to main_loop.py and appears historical |
| patch_feature_outcome_original_side.py | legacy patch/reset/helper script | yes | not connected to main_loop.py and appears historical |
| patch_feature_result_alignment.py | legacy patch/reset/helper script | yes | not connected to main_loop.py and appears historical |
| patch_live_brain_council_pending.py | legacy patch/reset/helper script | yes | not connected to main_loop.py and appears historical |
| reset_feature_learning_from_now.py | legacy patch/reset/helper script | yes | not connected to main_loop.py and appears historical |
| reset_feature_outcome_state.py | legacy patch/reset/helper script | yes | not connected to main_loop.py and appears historical |
| reset_trade_outcome_rebuild.py | legacy patch/reset/helper script | yes | not connected to main_loop.py and appears historical |
| patch_backups/patch_50_20260503_043349_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260503_043501_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260503_043733_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260503_043913_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260503_044126_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260503_044309_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_041952_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042013_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042027_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042035_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042049_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042056_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042110_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042126_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042132_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042149_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042156_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042215_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042220_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042236_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042302_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042324_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042346_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042408_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042430_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042451_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042521_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042542_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042604_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042625_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042626_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042647_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042708_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042709_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042733_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042755_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042817_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042838_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042900_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042921_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_042950_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043012_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043034_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043055_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043117_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043138_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043139_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043203_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043224_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043246_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043307_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043329_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043350_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043415_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043436_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043458_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043519_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043541_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043602_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043626_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043627_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043648_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043709_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043710_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043731_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043753_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043814_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043839_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043901_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043922_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_043944_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044005_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044027_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044051_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044113_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044134_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044156_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044217_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044218_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044239_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044304_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044325_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044347_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044408_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044430_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044452_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044516_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044538_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044559_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044621_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044643_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044704_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044729_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044751_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044812_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044834_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044855_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044856_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044917_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_044941_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_045003_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_045024_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_045025_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_045046_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_045108_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_045129_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_045153_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_045215_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_045237_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_045258_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |
| patch_backups/patch_50_20260504_045320_friday_brain.py.bak | already archived or backup artifact | yes | already isolated from active code |

## 7. Archived Files Table

| file_path | archived_to | reason |
|---|---|---|
| friday_demo_position_governor.py | _archive/20260514_legacy_cleanup/friday_demo_position_governor.py | already archived in this cleanup folder |
| friday_demo_position_governor_v2.py | _archive/20260514_legacy_cleanup/friday_demo_position_governor_v2.py | already archived in this cleanup folder |
| friday_realtime_scalper_demo_executor.py | _archive/20260514_legacy_cleanup/friday_realtime_scalper_demo_executor.py | already archived in this cleanup folder |
| friday_touch_demo_executor.py | _archive/20260514_legacy_cleanup/friday_touch_demo_executor.py | already archived in this cleanup folder |
| friday_risk_close.py | _archive/20260514_legacy_cleanup/friday_risk_close.py | already archived in this cleanup folder |
| ict_sweep_trader.py | _archive/20260514_legacy_cleanup/ict_sweep_trader.py | already archived in this cleanup folder |
| scripts/ict_sweep_trader.py | _archive/20260514_legacy_cleanup/scripts/ict_sweep_trader.py | already archived in this cleanup folder |
| scripts/mt5_ollama_trader.py | _archive/20260514_legacy_cleanup/scripts/mt5_ollama_trader.py | already archived in this cleanup folder |

## 8. Files Left As UNKNOWN

Unknown count: `80371`. Showing first 120. Full inventory is in `reports/40_FILE_INVENTORY.csv`.

| file_path | purpose | reason |
|---|---|---|
| .friday_jarvis_runtime.ps1 | miscellaneous project artifact | left untouched |
| .friday_loop_state.json | miscellaneous project artifact | left untouched |
| .friday_voice_runtime.ps1 | miscellaneous project artifact | left untouched |
| .gitignore | miscellaneous project artifact | left untouched |
| algory_chart_dashboard.py | miscellaneous project artifact | left untouched |
| algory_retrain.py | miscellaneous project artifact | left untouched |
| audit_input.zip | miscellaneous project artifact | left untouched |
| build_full_audit_pack.ps1 | miscellaneous project artifact | left untouched |
| clean_reset_feature_learning.py | miscellaneous project artifact | left untouched |
| demo_execute_command_fix.zip | miscellaneous project artifact | left untouched |
| disable_legacy_executors_hard.py | miscellaneous project artifact | left untouched |
| export_friday_status.py | miscellaneous project artifact | left untouched |
| fix_live_brain_htmlresponse.py | miscellaneous project artifact | left untouched |
| fractal_features.py | miscellaneous project artifact | left untouched |
| fractal_gene_memory.py | miscellaneous project artifact | left untouched |
| fractal_projection_backtester.py | miscellaneous project artifact | left untouched |
| fractal_smc_engine.py | miscellaneous project artifact | left untouched |
| fractal_strategy.py | miscellaneous project artifact | left untouched |
| friday_agents_browser.py | miscellaneous project artifact | left untouched |
| friday_autopilot_state.json | miscellaneous project artifact | left untouched |
| friday_autopilot_supervisor.py | miscellaneous project artifact | left untouched |
| friday_brain.py | miscellaneous project artifact | left untouched |
| friday_brain_memory.json | miscellaneous project artifact | left untouched |
| friday_build_risk_memory_rules.py | miscellaneous project artifact | left untouched |
| friday_capital_brain.py | miscellaneous project artifact | left untouched |
| friday_capital_brain_memory.json | miscellaneous project artifact | left untouched |
| friday_capital_brain_memory.lock | miscellaneous project artifact | left untouched |
| friday_chat_app.py | miscellaneous project artifact | left untouched |
| friday_chat_memory.json | miscellaneous project artifact | left untouched |
| friday_control_center.py | miscellaneous project artifact | left untouched |
| friday_entry_gate.py | miscellaneous project artifact | left untouched |
| friday_entry_gate_state.json | miscellaneous project artifact | left untouched |
| friday_evolution_memory.py | miscellaneous project artifact | left untouched |
| friday_feature_council_state.json | miscellaneous project artifact | left untouched |
| friday_feature_outcome_learner.py | miscellaneous project artifact | left untouched |
| friday_feature_outcome_learner_state.json | miscellaneous project artifact | left untouched |
| friday_fvg_state.json | miscellaneous project artifact | left untouched |
| friday_genome_status_export.py | miscellaneous project artifact | left untouched |
| FRIDAY_Gold_EA.mq5 | miscellaneous project artifact | left untouched |
| friday_health_monitor.py | miscellaneous project artifact | left untouched |
| friday_indicator_feature_engine.py | miscellaneous project artifact | left untouched |
| friday_indicator_weights.json | miscellaneous project artifact | left untouched |
| friday_jarvis_bridge.py | miscellaneous project artifact | left untouched |
| friday_jarvis_memory.json | miscellaneous project artifact | left untouched |
| friday_jarvis_voice.py | miscellaneous project artifact | left untouched |
| friday_live_brain_state.json | miscellaneous project artifact | left untouched |
| friday_live_brain_state.py | miscellaneous project artifact | left untouched |
| friday_local_gateway.py | miscellaneous project artifact | left untouched |
| friday_orchestrator.py | miscellaneous project artifact | left untouched |
| friday_orderflow_events.json | miscellaneous project artifact | left untouched |
| friday_orderflow_feature_engine.py | miscellaneous project artifact | left untouched |
| friday_orderflow_state.json | miscellaneous project artifact | left untouched |
| friday_position_trailing_state.json | miscellaneous project artifact | left untouched |
| friday_project_map.json | miscellaneous project artifact | left untouched |
| friday_project_map.py | miscellaneous project artifact | left untouched |
| friday_realtime_scalper_brain.py | miscellaneous project artifact | left untouched |
| FRIDAY_REALTIME_VOICE.md | miscellaneous project artifact | left untouched |
| friday_risk_memory_rules.json | miscellaneous project artifact | left untouched |
| friday_runtime_inventory.json | miscellaneous project artifact | left untouched |
| friday_runtime_inventory.py | miscellaneous project artifact | left untouched |
| friday_scalper_live_dashboard.py | miscellaneous project artifact | left untouched |
| friday_scalper_visual_explain.py | miscellaneous project artifact | left untouched |
| friday_strategy_genes.json | miscellaneous project artifact | left untouched |
| FRIDAY_Summary.txt | miscellaneous project artifact | left untouched |
| friday_symbol_sl_settings.json | miscellaneous project artifact | left untouched |
| friday_symbol_universe.py | miscellaneous project artifact | left untouched |
| friday_system_mesh.py | miscellaneous project artifact | left untouched |
| friday_touch_level_memory.json | miscellaneous project artifact | left untouched |
| friday_touch_runtime_state.json | miscellaneous project artifact | left untouched |
| friday_trade_outcome_learner.py | miscellaneous project artifact | left untouched |
| friday_trade_outcome_learner_state.json | miscellaneous project artifact | left untouched |
| jarvis_session_brief.md | miscellaneous project artifact | left untouched |
| live_fractal_monitor.py | miscellaneous project artifact | left untouched |
| live_fractal_projection_monitor.py | miscellaneous project artifact | left untouched |
| obey_demo_scalping_patch.zip | miscellaneous project artifact | left untouched |
| README.md | miscellaneous project artifact | left untouched |
| README_AGGRESSIVE_SCALPING.txt | miscellaneous project artifact | left untouched |
| README_DEMO_EXECUTE_FIX.txt | miscellaneous project artifact | left untouched |
| README_OBEY_DEMO_SCALPING.txt | miscellaneous project artifact | left untouched |
| requirements-voice.txt | miscellaneous project artifact | left untouched |
| restart_friday.ps1 | miscellaneous project artifact | left untouched |
| run_backtest.bat | miscellaneous project artifact | left untouched |
| selected_code.zip | miscellaneous project artifact | left untouched |
| start_friday_all.ps1 | miscellaneous project artifact | left untouched |
| start_friday_trading_full.ps1 | miscellaneous project artifact | left untouched |
| start_friday_voice.ps1 | miscellaneous project artifact | left untouched |
| stop_friday_all.ps1 | miscellaneous project artifact | left untouched |
| trading_decision_trace.json | miscellaneous project artifact | left untouched |
| uv.lock | miscellaneous project artifact | left untouched |
| verify_mt5_demo_state.py | miscellaneous project artifact | left untouched |
| .claude/gsd-file-manifest.json | miscellaneous project artifact | left untouched |
| .claude/package.json | miscellaneous project artifact | left untouched |
| .claude/scheduled_tasks.lock | miscellaneous project artifact | left untouched |
| .claude/settings.json | miscellaneous project artifact | left untouched |
| .claude/settings.local.json | miscellaneous project artifact | left untouched |
| .jarvis_agents/friday_awareness.json | miscellaneous project artifact | left untouched |
| .jarvis_agents/friday_genome_development_status.json | miscellaneous project artifact | left untouched |
| .jarvis_agents/friday_system_mesh.json | miscellaneous project artifact | left untouched |
| .jarvis_agents/task_history.json | miscellaneous project artifact | left untouched |
| .jarvis_agents/watch_state.json | miscellaneous project artifact | left untouched |
| .planning/MILESTONES.md | miscellaneous project artifact | left untouched |
| .planning/PROJECT.md | miscellaneous project artifact | left untouched |
| .planning/REQUIREMENTS.md | miscellaneous project artifact | left untouched |
| .planning/ROADMAP.md | miscellaneous project artifact | left untouched |
| .planning/STATE.md | miscellaneous project artifact | left untouched |
| .ruff_cache/.gitignore | miscellaneous project artifact | left untouched |
| .ruff_cache/CACHEDIR.TAG | miscellaneous project artifact | left untouched |
| .venv/.gitignore | vendor/tool/model/runtime asset | outside trading pipeline |
| .venv/.lock | vendor/tool/model/runtime asset | outside trading pipeline |
| .vscode/settings.json | miscellaneous project artifact | left untouched |
| capital_brain_backups/friday_capital_brain_memory_20260512_163000.json | miscellaneous project artifact | left untouched |
| data/agent_thresholds.json | miscellaneous project artifact | left untouched |
| data/auto_symbol_memory.json | miscellaneous project artifact | left untouched |
| data/brain_insights.json | miscellaneous project artifact | left untouched |
| data/confidence_scores.json | miscellaneous project artifact | left untouched |
| data/gene_fitness_v2.json | miscellaneous project artifact | left untouched |
| data/indicator_memory.json | miscellaneous project artifact | left untouched |
| data/indicator_snapshots.csv | miscellaneous project artifact | left untouched |
| data/latest_fractal_signal.json | miscellaneous project artifact | left untouched |
| data/liquidity_state_AAPLm.json | miscellaneous project artifact | left untouched |

## 9. Merge Status Table

| old_file | new_replacement | merge_status | evidence | recommendation |
|---|---|---|---|---|
| friday_demo_position_governor.py | src/mt5_ai/agents/governor_agent.py + core/position_manager.py | PARTIAL | GovernorAgent emits PositionManagementRequest; direct executor stub archived; advanced reverse/TP expansion parity not proven. | keep archived reference; validate DRY_RUN behavior |
| friday_demo_position_governor_v2.py | src/mt5_ai/agents/governor_agent.py + core/position_manager.py | PARTIAL | Position management path exists and magic=0 issue was fixed; full v2 feature parity not confirmed. | keep archived reference; integrate missing management rules later |
| friday_risk_close.py | src/mt5_ai/agents/risk_close_agent.py + core/position_manager.py | MERGED | RiskCloseAgent implements emergency no-SL/profit threshold close requests; direct executor stub archived. | remove from active path; retain archived reference |
| ict_sweep_trader.py | src/mt5_ai/agents/ict_sweep_agent.py | PARTIAL | ICT sweep signal logic exists as SignalProposal producer; direct execution removed. | keep active agent; optionally improve arbiter weighting later |
| scripts/ict_sweep_trader.py | src/mt5_ai/agents/ict_sweep_agent.py | PARTIAL | Signal-only agent replaces direct order_send script for active pipeline. | keep archived reference only |
| scripts/mt5_ollama_trader.py | src/mt5_ai/agents/ai_agent.py | PARTIAL | AiAgent exists but is imported/not called by main_loop run_cycle; old direct trader stub archived. | integrate later through SignalArbiter only if dry-run tests pass |
| friday_realtime_scalper_demo_executor.py | src/mt5_ai/agents/scalper_agent.py / scalping_agent.py | NOT MERGED | ScalperAgent is exported/imported but not called by main_loop; old executor stub archived. | keep as archived reference; integrate later only as SignalProposal producer |
| friday_touch_demo_executor.py | src/mt5_ai/agents/touch_agent.py | NOT MERGED | TouchAgent exists but is not called by main_loop; old executor stub archived. | keep as archived reference; integrate later through SignalArbiter/ConflictGuard |
| src/mt5_ai/execution.py | src/mt5_ai/core/execution_manager.py | PARTIAL | Core ExecutionManager is active; legacy Paper/Demo executors remain for other surfaces but direct demo trading default was disabled. | keep for non-main surfaces until callers are migrated |
| src/risk.py | src/mt5_ai/core/risk_manager.py | NOT MERGED | Old grid ExecutionEngine skeleton is outside active main_loop path. | archive later after confirming no legacy tests need it |
| fractal_smc_engine.py / fractal_strategy.py | src/mt5_ai/agents/fractal_agent.py + smc_agent.py + market_structure.py | PARTIAL | Active agents use structured SignalProposal pipeline; root fractal scripts are standalone research/backtest artifacts. | keep as reference until strategy parity review |
| src/mt5_ai/algory_runner.py | src/mt5_ai/runtime/main_loop.py | PARTIAL | Algory runner is a separate genome runtime using ExecutionManager raw-order path; not the current main_loop path. | do not archive yet; keep isolated and dry-run gated |

Full CSV: `reports/40_MERGE_STATUS.csv`.

## 10. Safety Scan Results

- Static scan matching lines: `1764`
- Guarded active `order_send` call sites: `8`
- Unguarded active `order_send` call sites: `0`
- Non-active/report/archive `order_send` mentions: `601`
- Live-enabled configs: `[]`
- Summary: No active config enables live trading; no unguarded active order_send call was found. Active write calls are confined to ExecutionManager and MT5Gateway methods guarded by kill_switch/DRY_RUN/live flags, with demo gateway writes additionally blocked by DEMO_TRADING_ENABLED=false.

Guarded active `order_send` lines:

```text
src\mt5_ai\mt5_gateway.py:458:        result = self.mt5.order_send(request)
src\mt5_ai\mt5_gateway.py:461:            result = self.mt5.order_send(request)
src\mt5_ai\mt5_gateway.py:539:        result = self.mt5.order_send(request)
src\mt5_ai\mt5_gateway.py:542:            result = self.mt5.order_send(request)
src\mt5_ai\mt5_gateway.py:638:        result = self.mt5.order_send(request)
src\mt5_ai\mt5_gateway.py:641:            result = self.mt5.order_send(request)
src\mt5_ai\core\execution_manager.py:111:            result = mt5.order_send(req)
src\mt5_ai\core\execution_manager.py:150:            result = mt5.order_send(req)
```

Unguarded active `order_send` lines:

```text
(none)
```

## 11. verify_mt5_lockdown Result

- Command: `C:\Users\Radhi\MT5\.venv\Scripts\python.exe verify_mt5_lockdown.py`
- Exit code: `0`
- Account info readable: `yes`
- Open positions: `0`
- Pending orders: `0`
- magic=0 external exposure: `none`

Output tail:

```text

════════════════════════════════════════════════════════════════════
  FRIDAY — MT5 LOCKDOWN VERIFICATION  (read-only)
════════════════════════════════════════════════════════════════════
════════════════════════════════════════════════════════════════════
  ACCOUNT
════════════════════════════════════════════════════════════════════
  Login      : 260749517
  Server     : Exness-MT5Trial15
  Name       : Standard
  Company    : Exness Technologies Ltd
  Currency   : USD
  Balance    : 160.81 USD
  Equity     : 160.81 USD
  Margin     : 0.00 USD
  Free margin: 160.81 USD
  Leverage   : 1:2000000000
  Trade mode : 0  (DEMO/TRIAL)

════════════════════════════════════════════════════════════════════
  OPEN POSITIONS  (0)
════════════════════════════════════════════════════════════════════
  (none)

════════════════════════════════════════════════════════════════════
  PENDING ORDERS  (0)
════════════════════════════════════════════════════════════════════
  (none)

════════════════════════════════════════════════════════════════════
  LOCKDOWN VERDICT
════════════════════════════════════════════════════════════════════
  Open positions  : 0
  Pending orders  : 0

  ✓  ACCOUNT IS CLEAN — no open positions, no pending orders
     Exit code: 0
════════════════════════════════════════════════════════════════════


```

## 12. Runtime Dry-Run Results

```json
{
  "skipped": false,
  "symbol": "XAUUSDm",
  "timeframe": "M1",
  "cycles_completed": 50,
  "agent_signal_counts": {
    "fractal_agent:BUY": 50,
    "smc_agent:NO_CONFIRMATION": 50
  },
  "smc_counts": {
    "NO_CONFIRMATION": 50
  },
  "fractal_counts": {
    "BUY": 50
  },
  "ict_counts": {
    "NONE": 50
  },
  "arbiter_counts": {
    "HOLD": 50
  },
  "result_counts": {
    "ARBITER_HOLD": 50
  },
  "conflict_guard_blocks": 0,
  "risk_blocks": 0,
  "execution_manager_reached_count": 0,
  "simulated_executions": 0,
  "real_order_send_calls": 0,
  "errors": 0,
  "error_details": [],
  "config_mode": "DRY_RUN",
  "is_dry_run": true,
  "is_live_allowed": false
}
```

## 13. Real order_send Calls Count

`0`

## 14. Errors And Warnings

Runtime errors: `0`

Test failures: `0`

Warnings:

(none)

Errors:

(none)

## 15. What Was Fixed

- `main_loop.py` now passes real spread, open-position count, daily-loss percent, and open-position side map into guards.
- `mt5_gateway.py` now has explicit blocked `send_order`, `close_position`, and `modify_position` adapters.
- Direct gateway demo write paths now block during DRY_RUN/kill_switch and `DEMO_TRADING_ENABLED` defaults to false.
- `DEFAULT_MAGIC` now matches registered `ALGORY_MAGIC` value `20260600`.
- `validate_request()` now rejects disabled legacy magic numbers for new execution requests.
- `PositionManager` no longer emits magic=0 execution requests.
- `ExecutionRequest.is_valid()` now validates entry, close, reduce, and trail actions by action type.
- `execution.simulate_only=true` now contributes to `is_dry_run()`.
- `dry_run_simulation.yaml` no longer advertises `micro_live_mode: true`.
- `dry_run_simulation.py` now routes synthetic signals through `SignalArbiter` and no longer forces BUY after a HOLD.
- `algory_runner.py` paper mode now calls `PaperExecutor.execute()` instead of a missing `open_trade()` method.
- `kill_switch.py` now writes the active config path exposed by `config_loader.active_config_path()`.
- `main_loop.py` now reuses one `SignalArbiter`, logs heartbeat progress, and activates kill_switch after five consecutive cycle errors.
- `main_loop.py` now uses shared `core/indicators.py::atr()` for ATR-based SL/TP.
- `DecisionRouter` now has explicit `signal_arbiter` source weighting.

## 16. What Was Not Touched

- No live trading flags were enabled.
- No real MT5 orders were placed.
- No tests/reports/configs were archived.
- No active runner/core files were archived.
- Broad unknown source modules outside `main_loop.py` were left in place.
- Existing logs and historical reports were left in place.

## 17. Remaining Risks

- `IctSweepAgent` is collected but currently treated as a confirmer by `SignalArbiter`; it is not weighted as a primary signal.
- `AiAgent`, `ScalperAgent`, and `TouchAgent` are not connected to `run_cycle()`.
- `algory_runner.py` is a separate runtime and remains outside the main-loop architecture, though its execution path is still DRY_RUN-gated by config.
- `src/mt5_ai/archive/` remains under the importable source tree; moving it needs a dedicated import-path cleanup.
- Some duplicate ATR implementations remain in older strategy/research surfaces outside the active main_loop path.
- Some source files remain `UNKNOWN` because they may serve dashboards, voice, research, or legacy workflows outside the active runner.

## 18. Next Recommended Implementation Phases

1. Add focused unit tests for `PositionManager -> ExecutionManager` dry-run close/trail requests.
2. Add a unit test proving gateway demo methods return blocked under DRY_RUN and with `DEMO_TRADING_ENABLED=False`.
3. Decide whether `IctSweepAgent` should stay confirmer-only or receive a bounded arbiter weight.
4. Decide whether Ai/Scalper/Touch agents should be integrated, archived, or retained as inactive references.
5. Move archive/reference code out of the importable source tree after dependency checks.
6. Continue consolidating UNKNOWN modules in small batches, with no direct execution paths allowed.

## 19. Final Safety Status

**SAFE_FOR_DRY_RUN_ONLY**

Real `order_send` calls observed: `0`.

Live trading enabled: `false`.

DRY_RUN/simulate_only preserved: `true`.
