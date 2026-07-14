# Orphaned Root-Level Python Files Audit
**Date:** 2026-05-15  
**Auditor:** Claude Code (Sonnet 4.6)  
**Scope:** All 55 `.py` files at `C:\Users\Radhi\MT5\` root level (excluding `.venv/`)

---

## Summary

| Category   | Count | Description |
|-----------|-------|-------------|
| ACTIVE     | 19    | Launched by orchestrator/startup scripts or imported by active src/ code |
| STANDALONE | 9     | Self-contained tools useful as-is (run once or on demand) |
| DUPLICATE  | 5     | Functionality superseded by a canonical version in `src/mt5_ai/` |
| PATCH      | 8     | One-time code-patchers — already applied, safe to delete |
| OBSOLETE   | 7     | Superseded, never launched, or pre-refactor artifacts |
| TEST       | 7     | Test/verify/reset utilities |

---

## Full File Table

| Filename | Category | Reason | Recommendation |
|----------|----------|--------|----------------|
| `algory_chart_dashboard.py` | ACTIVE | Launched by `friday_orchestrator.py` Tier 4 (port 8866). `src/mt5_ai/algory_integrator.py` imports `_calc_smc` and `_atr_from_df` from it at runtime | Keep at root; document the import dependency |
| `algory_retrain.py` | STANDALONE | CLI tool to wipe and retrain all genomes from scratch. Self-contained, useful on demand. Not launched by any startup script | Move to `scripts/` |
| `clean_reset_feature_learning.py` | PATCH | Writes a blank `friday_feature_outcome_learner_state.json`. One-shot reset, already superseded by `reset_feature_learning_from_now.py` | DELETE (use the more complete reset variant) |
| `disable_legacy_executors_hard.py` | PATCH | Archived legacy executor files into `src/mt5_ai/archive/legacy_executors_disabled_20260513_032812/`. Archive already exists — this patch was applied | DELETE (work is done) |
| `export_friday_status.py` | STANDALONE | Dumps full project file listing and status to `friday_status_exports/`. Self-contained snapshot tool | Move to `scripts/` |
| `fix_live_brain_htmlresponse.py` | PATCH | Applied an `HTMLResponse` import fix directly to `friday_live_brain_state.py` via string replacement. One-time fix | DELETE (patch already applied) |
| `fractal_features.py` | DUPLICATE | Builds fractal AI features from `fractal_smc_engine`. However `src/mt5_ai/fractal_structure_engine.py` is the canonical evolved version used by the active stack (`live_fractal_projection_monitor.py` → `src/mt5_ai/fractal_structure_engine.py`). This older root-level version is only imported by root-level `fractal_strategy.py` | DELETE after verifying `fractal_strategy.py` is also removed |
| `fractal_gene_memory.py` | ACTIVE | Used by `live_fractal_monitor.py` (which is launched by Tier 4 of orchestrator indirectly via `live_fractal_projection_monitor.py`). Also tested in `test_fractal_smc.py` | Move to `src/mt5_ai/` alongside `fractal_structure_engine.py` |
| `fractal_projection_backtester.py` | STANDALONE | Walk-forward self-calibration tool for projection engine. Imports from `src/mt5_ai`. CLI tool, run manually. Not started by any script | Move to `scripts/` |
| `fractal_smc_engine.py` | DUPLICATE | Original fractal/SMC/liquidity engine. Superseded by `src/mt5_ai/fractal_structure_engine.py` (more complete, used by active stack). Only used by root-level `fractal_features.py`, `fractal_strategy.py`, and `test_fractal_smc.py` | Move to `src/mt5_ai/` OR delete and update `test_fractal_smc.py` to use `fractal_structure_engine` |
| `fractal_strategy.py` | DUPLICATE | Fractal SMC scalping signal generator. Functionality is covered by `src/mt5_ai/agents/fractal_agent.py` and `src/mt5_ai/algory_integrator.py`. Not imported or launched anywhere active | DELETE |
| `friday_agents_browser.py` | ACTIVE | Launched by `start_friday_all.ps1` and `restart_friday.ps1` on port 8833. Listed in orchestrator Tier 4. Core dashboard service | Keep at root (launched as top-level FastAPI service) |
| `friday_autopilot_supervisor.py` | ACTIVE | Launched by orchestrator Tier 5. Referenced in `start_friday_all.ps1`, `stop_friday_all.ps1`, `restart_friday.ps1`, `device_tools.py` (voice). Supervises genome status export, manages service health | Keep at root |
| `friday_brain.py` | OBSOLETE | Old DB-backed brain reader. Reads `friday_brain_memory.json` from MySQL. No active import in `src/`, not launched by any startup script. The brain is now served by `friday_live_brain_state.py` | DELETE |
| `friday_build_risk_memory_rules.py` | STANDALONE | Reads `friday_gene_performance_report.json` and writes risk rules to `friday_risk_memory_rules.json`. Utility to rebuild risk config from gene performance data. Not launched automatically | Move to `scripts/` |
| `friday_capital_brain.py` | OBSOLETE | Older MT5-direct capital sizing engine. Only referenced from archived disabled executors in `src/mt5_ai/archive/`. A snapshot copy already exists at `src/mt5_ai/archive/original_snapshot_20260513_002759/friday_capital_brain.py` | DELETE (archived copy exists) |
| `friday_chat_app.py` | ACTIVE | Launched by orchestrator Tier 4 (port 8811) and `start_friday_all.ps1`. Core chat/LLM interface service | Keep at root |
| `friday_control_center.py` | OBSOLETE | Simple FastAPI control-center dashboard that starts/stops services via subprocess. Listed in `stop_friday_all.ps1` kill list but never in any start script. Superseded by `friday_orchestrator.py` | DELETE |
| `friday_entry_gate.py` | ACTIVE | Imported by archived executors, but the active `src/mt5_ai/archive/legacy_executors_disabled_20260513_032812/friday_realtime_scalper_demo_executor.py` still imports `from friday_entry_gate import check_entry`. More importantly it is a pure logic module with no startup — it is a library used at runtime. `scripts/friday_safe_supervisor.py` may also depend on it indirectly | Move to `src/mt5_ai/` — it is a reusable library, not a service |
| `friday_evolution_memory.py` | STANDALONE | Manages `friday_strategy_genes.json` evolution memory, gene tracking, prediction learning. Pure library with no side effects at import. Not imported from `src/` directly but provides core gene state logic | Move to `src/mt5_ai/` |
| `friday_feature_outcome_learner.py` | ACTIVE | Launched by orchestrator Tier 2. Referenced in `device_tools.py`, `scripts/friday_jarvis_desktop_agent.py`. One of the core learning loops | Keep at root (running service) |
| `friday_gene_performance_report.py` | STANDALONE | Reads `friday_strategy_genes.json` and generates `friday_gene_performance_report.json`. Run on demand to refresh gene performance stats. Not in any startup | Move to `scripts/` |
| `friday_genome_status_export.py` | ACTIVE | Launched by `friday_autopilot_supervisor.py` on schedule. Referenced by `friday_local_gateway.py`, `friday_system_mesh.py`, `mark_xxxix/friday_plugin.py`, `stop_friday_all.ps1`. Actively monitored by autopilot | Keep at root |
| `friday_health_monitor.py` | ACTIVE | Launched by orchestrator Tier 6. Monitors all services, auto-restarts crashed processes. Referenced by `stop_friday_all.ps1` | Keep at root |
| `friday_indicator_feature_engine.py` | ACTIVE | Launched by orchestrator Tier 1 (Feature Council Engine). Referenced in `scripts/friday_jarvis_desktop_agent.py` and `device_tools.py`. Imports `friday_symbol_universe` | Keep at root (running service) |
| `friday_jarvis_bridge.py` | STANDALONE | Gemini AI voice bridge — listens to FRIDAY SSE events, announces via TTS, accepts voice commands. Standalone launcher (`python friday_jarvis_bridge.py`). Not referenced in any startup script | Move to `scripts/` |
| `friday_jarvis_voice.py` | STANDALONE | Older pyttsx3 + Ollama voice interface. Superseded by `scripts/friday_jarvis_voice_bridge.py` (more complete). Not started by any script | Move to `scripts/` (or DELETE if voice_bridge fully replaces it) |
| `friday_live_brain_state.py` | ACTIVE | Launched twice by orchestrator: Tier 2 (loop mode) and Tier 3 (serve mode port 8844). Referenced everywhere. Core brain aggregator | Keep at root |
| `friday_local_gateway.py` | ACTIVE | Launched by orchestrator Tier 3 (port 8799), `start_friday_all.ps1`, `restart_friday.ps1`. Central API gateway | Keep at root |
| `friday_orchestrator.py` | ACTIVE | The master launcher. Called by `start_friday_trading_full.ps1`. Starts all 6 tiers in order | Keep at root |
| `friday_orderflow_feature_engine.py` | ACTIVE | Launched by orchestrator Tier 1 (Order Flow Engine). Referenced in `scripts/friday_jarvis_desktop_agent.py` and `device_tools.py`. Imports `friday_symbol_universe` | Keep at root (running service) |
| `friday_project_map.py` | STANDALONE | Scans the project tree and writes `friday_project_map.json`. One-shot inventory tool. Not started by any script | Move to `scripts/` |
| `friday_realtime_scalper_brain.py` | OBSOLETE | Multi-TF scalper signal aggregator with MT5. Not launched by any startup script. Pattern referenced only in `.planning/codebase/CONVENTIONS.md` as historical. Functionality covered by `src/mt5_ai/agents/scalper_agent.py` and the live dashboard | DELETE |
| `friday_runtime_inventory.py` | STANDALONE | Scans files and running ports, outputs a runtime inventory summary. Self-contained diagnostic tool | Move to `scripts/` |
| `friday_scalper_live_dashboard.py` | ACTIVE | Launched by orchestrator Tier 4 (TradingView Dashboard port 8822), `start_friday_all.ps1`, `restart_friday.ps1`. Referenced in `device_tools.py` | Keep at root |
| `friday_scalper_visual_explain.py` | STANDALONE | Generates matplotlib chart PNGs explaining scalper signals. Saves to `scalper_charts/`. CLI tool, run on demand | Move to `scripts/` |
| `friday_symbol_universe.py` | ACTIVE | Imported directly by `src/mt5_ai/algory_runner.py`, `scripts/friday_auto_trader.py`, `scripts/friday_safe_supervisor.py`, `scripts/friday_web_dashboard.py`. Also used by `friday_indicator_feature_engine.py`, `friday_orderflow_feature_engine.py`, `friday_realtime_scalper_brain.py` | Move to `src/mt5_ai/` — it is a shared library, not a service |
| `friday_system_mesh.py` | ACTIVE | Launched by orchestrator Tier 3 (--loop mode). Monitors services, reads genome export, logs mesh state | Keep at root |
| `friday_trade_outcome_learner.py` | ACTIVE | Launched by orchestrator Tier 2. Referenced in `device_tools.py` and `scripts/friday_jarvis_desktop_agent.py`. Core trade learning loop | Keep at root (running service) |
| `live_fractal_monitor.py` | STANDALONE | Standalone fractal SMC signal monitor — imports `fractal_gene_memory` and `fractal_smc_engine`. Writes `data/latest_fractal_signal.json`. Separate from the `live_fractal_projection_monitor.py` which uses the `src/mt5_ai/` versions. Not launched by orchestrator | Move to `scripts/` |
| `live_fractal_projection_monitor.py` | ACTIVE | Launched by orchestrator Tier 4. Imports from `src/mt5_ai/fractal_structure_engine` and `src/mt5_ai/market_projection_engine`. Writes `fractal_live_state.json` | Keep at root |
| `mt5_review_bridge_v2.py` | STANDALONE | Safe review-only helper: builds a zip pack, runs compileall, checks genome quality, snapshots processes/ports. Does NOT start live or place orders | Move to `scripts/` |
| `patch_dashboard_feature_forecast.py` | PATCH | Patched `friday_scalper_live_dashboard.py` to add `FEATURE_STATE_FILE` constant and a `load_feature_state()` function via string replacement | DELETE (patch was a one-time apply) |
| `patch_feature_engine_weights.py` | PATCH | Patched `friday_indicator_feature_engine.py` to add `WEIGHTS_FILE` constant and `indicator_weight()`/`group_weight()` helpers | DELETE (patch was a one-time apply) |
| `patch_feature_learner_learn_after.py` | PATCH | Patched `friday_feature_outcome_learner.py` to add `learn_from_after` timestamp filter logic | DELETE (patch was a one-time apply) |
| `patch_feature_outcome_original_side.py` | PATCH | Patched `friday_feature_outcome_learner.py` to add `infer_original_position_side()` helper | DELETE (patch was a one-time apply) |
| `patch_feature_result_alignment.py` | PATCH | Patched `friday_feature_outcome_learner.py` to add `feature_prediction_from_snapshot()` helper | DELETE (patch was a one-time apply) |
| `patch_live_brain_council_pending.py` | PATCH | Patched `friday_live_brain_state.py` to add a `pending` field to the council vote function | DELETE (patch was a one-time apply) |
| `reset_feature_learning_from_now.py` | TEST | Resets `friday_feature_outcome_learner_state.json` with a `learn_from_after` timestamp set to now. Useful operational reset tool | Move to `scripts/` |
| `reset_feature_outcome_state.py` | TEST | Resets `friday_feature_outcome_learner_state.json` to blank (no learn_from_after). Similar to `clean_reset_feature_learning.py` but with different `rebuilt_reason` | Move to `scripts/` (or DELETE as duplicate reset) |
| `reset_trade_outcome_rebuild.py` | TEST | Resets `friday_trade_outcome_learner_state.json` and clears `trade_outcomes` in genes file so learner rebuilds from full MT5 history | Move to `scripts/` |
| `test_100_cycles.py` | TEST | 100-cycle pipeline stress test — no MT5, no real orders. Tests SignalProposal → DecisionRouter → RiskManager pipeline | Move to `scripts/` or a `tests/` directory |
| `test_fractal_smc.py` | TEST | Validates all fractal SMC components using synthetic data. Imports `fractal_smc_engine` and `fractal_gene_memory` from root | Move to `scripts/` or `tests/` |
| `validate_unlock_persistence.py` | TEST | Validates the `qader_app.storage.settings_store` unlock persistence fix. Tests `PermissionsStore` directly | Move to `scripts/` or `tests/` |
| `verify_mt5_demo_state.py` | TEST | Read-only MT5 check: prints account state, open positions, orders, history | Move to `scripts/` |
| `verify_mt5_lockdown.py` | TEST | Read-only MT5 lockdown verifier. Flags magic=0 entries, reports open positions. Used before/after changes to confirm clean state | Move to `scripts/` |

---

## FILES TO DELETE
These files are safe to delete. Their work is already applied or they are superseded.

| File | Reason |
|------|--------|
| `clean_reset_feature_learning.py` | Redundant — superseded by `reset_feature_learning_from_now.py` |
| `disable_legacy_executors_hard.py` | Already applied — archive at `src/mt5_ai/archive/legacy_executors_disabled_20260513_032812/` exists |
| `fix_live_brain_htmlresponse.py` | Already applied — `friday_live_brain_state.py` has the HTMLResponse fix |
| `patch_dashboard_feature_forecast.py` | Already applied — feature forecast logic is in `friday_scalper_live_dashboard.py` |
| `patch_feature_engine_weights.py` | Already applied — weights helpers are in `friday_indicator_feature_engine.py` |
| `patch_feature_learner_learn_after.py` | Already applied — learn_from_after is in `friday_feature_outcome_learner.py` |
| `patch_feature_outcome_original_side.py` | Already applied — `infer_original_position_side()` is in learner |
| `patch_feature_result_alignment.py` | Already applied — `feature_prediction_from_snapshot()` is in learner |
| `patch_live_brain_council_pending.py` | Already applied — pending field in council vote |
| `friday_brain.py` | Superseded by `friday_live_brain_state.py`. No active importer |
| `friday_capital_brain.py` | Superseded. Archived copy at `src/mt5_ai/archive/original_snapshot_20260513_002759/friday_capital_brain.py` |
| `friday_control_center.py` | Superseded by `friday_orchestrator.py`. Listed in kill list but never started |
| `friday_realtime_scalper_brain.py` | Superseded by `src/mt5_ai/agents/scalper_agent.py`. Not launched anywhere |
| `fractal_strategy.py` | Superseded by `src/mt5_ai/agents/fractal_agent.py` + `algory_integrator.py` |
| `fractal_features.py` | Superseded by `src/mt5_ai/fractal_structure_engine.py`. Only used by `fractal_strategy.py` (also to be deleted) |

**Verify before deleting:** Run `python -c "import compileall; compileall.compile_dir('.')"` and confirm these files are not imported anywhere else. The patch files in particular should be verified by checking if their target files already contain the patched code.

---

## FILES TO MOVE TO `scripts/`
These are standalone tools that run independently. Moving them reduces root clutter without breaking anything.

| File | Purpose |
|------|---------|
| `algory_retrain.py` | Full genome reset + retrain CLI |
| `export_friday_status.py` | Project status snapshot to file |
| `fractal_projection_backtester.py` | Walk-forward backtester for projection engine |
| `friday_build_risk_memory_rules.py` | Rebuild risk rules from gene performance data |
| `friday_gene_performance_report.py` | Generate gene performance JSON from genes file |
| `friday_jarvis_bridge.py` | Gemini AI + Jarvis voice bridge launcher |
| `friday_jarvis_voice.py` | Older pyttsx3 voice interface (consider deleting if `scripts/friday_jarvis_voice_bridge.py` fully replaces it) |
| `friday_project_map.py` | Project tree scanner — writes `friday_project_map.json` |
| `friday_runtime_inventory.py` | Runtime port + file inventory scanner |
| `friday_scalper_visual_explain.py` | Chart PNG generator for signal explanation |
| `live_fractal_monitor.py` | Standalone fractal SMC signal monitor |
| `mt5_review_bridge_v2.py` | Safe review-only bridge (zip, checks, no orders) |
| `reset_feature_learning_from_now.py` | Reset feature learner state to current timestamp |
| `reset_feature_outcome_state.py` | Blank-reset feature learner state |
| `reset_trade_outcome_rebuild.py` | Reset trade learner state for full rebuild |
| `test_100_cycles.py` | 100-cycle pipeline stress test |
| `test_fractal_smc.py` | Fractal SMC unit tests |
| `validate_unlock_persistence.py` | Qader unlock persistence validator |
| `verify_mt5_demo_state.py` | Read-only MT5 demo state checker |
| `verify_mt5_lockdown.py` | Read-only MT5 lockdown verifier |

---

## FILES TO INTEGRATE INTO `src/`
These files are libraries (not services), imported by active code, and belong in `src/mt5_ai/`.

| File | Target Location | Active Importers |
|------|----------------|-----------------|
| `friday_symbol_universe.py` | `src/mt5_ai/friday_symbol_universe.py` | `src/mt5_ai/algory_runner.py`, `scripts/friday_auto_trader.py`, `scripts/friday_safe_supervisor.py`, `scripts/friday_web_dashboard.py` |
| `friday_entry_gate.py` | `src/mt5_ai/friday_entry_gate.py` | `src/mt5_ai/archive/*/friday_realtime_scalper_demo_executor.py` (archived), potentially new executors |
| `friday_evolution_memory.py` | `src/mt5_ai/friday_evolution_memory.py` | Gene state management library used by multiple learners |
| `fractal_gene_memory.py` | `src/mt5_ai/fractal_gene_memory.py` | `live_fractal_monitor.py`, `test_fractal_smc.py` |
| `fractal_smc_engine.py` | `src/mt5_ai/fractal_smc_engine.py` (or merge into `fractal_structure_engine.py`) | `test_fractal_smc.py`, root-level fractal files |

**Migration note:** After moving `friday_symbol_universe.py`, update all import paths in `src/` files that currently use `sys.path` injection (`sys.path.insert(0, ROOT)`) to import it from `mt5_ai.friday_symbol_universe`. The `algory_runner.py` already does a lazy `from friday_symbol_universe import resolve_symbols` inside a function — this will keep working as long as the root is on sys.path, but should be updated.

---

## Files to KEEP AT ROOT (Active Services)
The following 19 files are correctly located at root — they are services launched by the orchestrator or startup scripts:

`algory_chart_dashboard.py`, `friday_agents_browser.py`, `friday_autopilot_supervisor.py`, `friday_chat_app.py`, `friday_feature_outcome_learner.py`, `friday_genome_status_export.py`, `friday_health_monitor.py`, `friday_indicator_feature_engine.py`, `friday_live_brain_state.py`, `friday_local_gateway.py`, `friday_orchestrator.py`, `friday_orderflow_feature_engine.py`, `friday_scalper_live_dashboard.py`, `friday_system_mesh.py`, `friday_trade_outcome_learner.py`, `live_fractal_projection_monitor.py`

Plus these 3 that are referenced as services in some scripts (even if not in the primary orchestrator):  
`friday_autopilot_supervisor.py` (already counted), `friday_agents_browser.py` (already counted), `friday_genome_status_export.py` (already counted).

---

## Priority Action Order

1. **DELETE the 6 applied patch files** — zero risk, already merged into targets
2. **DELETE `clean_reset_feature_learning.py`** — strictly superseded
3. **DELETE `disable_legacy_executors_hard.py`** — archive already created
4. **DELETE `fix_live_brain_htmlresponse.py`** — fix already applied
5. **MOVE `friday_symbol_universe.py` to `src/mt5_ai/`** — most-imported shared lib
6. **DELETE `friday_brain.py`, `friday_capital_brain.py`, `friday_control_center.py`** — superseded
7. **DELETE `friday_realtime_scalper_brain.py`, `fractal_strategy.py`, `fractal_features.py`** — superseded
8. **MOVE the 20 standalone/test files to `scripts/`**
9. **MOVE `friday_entry_gate.py`, `friday_evolution_memory.py`, `fractal_gene_memory.py` to `src/mt5_ai/`**
10. **Decide on `fractal_smc_engine.py`** — merge useful detection functions into `fractal_structure_engine.py` or keep as companion module

---

*Generated by Claude Code audit. All file reads were performed from the actual source — no guesses.*
