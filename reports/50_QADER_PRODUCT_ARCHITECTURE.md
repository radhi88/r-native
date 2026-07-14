# Report 50 - Qader Product Architecture

Generated: 2026-05-14

## Executive Summary

Qader is implemented as a Windows desktop wrapper around the existing MT5 dry-run intelligence pipeline. The trading core remains in `src/mt5_ai/`; the new application layer lives in `src/qader_app/` and calls the core through guarded services.

Live trading remains locked. Qader can observe, scan, explain, learn from dry-run outcomes, and propose strategy DNA changes without modifying production source code while running.

## Active Safety Baseline Read

Reviewed:
- `reports/34_100_CYCLE_PIPELINE_TEST.md`
- `reports/35_CONTROLLED_DRY_RUN.md`
- `reports/36_SIGNAL_ARBITRATION_TEST.md`
- `reports/37_SMC_NEUTRAL_SIGNAL_FIX.md`
- `reports/claude_review/01_ARCHITECTURE_REVIEW.md` through `05_VERIFICATION.md`
- `reports/claude_tasks/CODEX_ACTION_LIST.md`

Baseline retained:
- `src/mt5_ai/runtime/main_loop.py` remains the main runner.
- `SignalArbiter` remains active.
- `ConflictGuard` remains active.
- `ExecutionManager` remains the only active MT5 execution boundary.
- All Qader execution services default to DRY_RUN or observe-only behavior.

## Module Architecture

| Module | Implementation | Purpose | Safety Boundary |
|---|---|---|---|
| App shell / GUI | `src/qader_app/gui/main_window.py` | PyQt6 desktop shell with tabs | No trading action without service checks |
| Voice assistant | `src/qader_app/assistant/qader_voice.py` | STT/TTS wrapper | Requires microphone/speaker permissions |
| Onboarding wizard | `src/qader_app/gui/onboarding.py` | First-run profile and permissions setup | Live trading checkbox locked |
| User memory | `src/qader_app/assistant/memory.py` | Preferences and local memory | Strips sensitive keys |
| Permissions center | `src/qader_app/gui/permissions.py` | User-facing permission toggles | `can_place_live_orders=false` locked |
| MT5 connection | `src/qader_app/services/mt5_service.py` | Read-only MT5 connection and bars | Requires `can_read_mt5` |
| Symbol selection | `src/qader_app/gui/symbol_selector.py` | Symbols/timeframes storage | Scans selected symbols only |
| Market scanner | `src/qader_app/services/scanner_service.py` | Agents -> Arbiter -> Router -> Guard -> Risk view | No execution call |
| Pipeline controller | `src/qader_app/services/runner_service.py` | Fixed-cycle dry-run wrapper | Monkey-patches `order_send` during dry-run |
| Arbiter dashboard | `ScannerView` table | Shows final arbiter output | Explainable reason strings |
| Risk dashboard | Scanner risk column | Shows approved/blocked/not reached | Uses `RiskManager` only |
| Dry-run monitor | `RunnerService` | Fixed dry-run cycles | Requires `can_run_dry_run` |
| Strategy DNA | `src/qader_app/genome/` | Config/genome learning layer | No source-code mutation |
| Learning journal | `performance_journal.jsonl` | Decision scoring records | Config-only learning |
| Logs/reports viewer | `src/qader_app/gui/logs_view.py` | Audit log viewer | Read-only |
| Settings import/export | `src/qader_app/services/config_service.py` | Portable settings bundles | No secrets expected |
| EXE packaging | `packaging/qader.spec`, `build_qader.ps1` | PyInstaller onedir build | Excludes logs/secrets/archive outputs |

## Runtime Flow

```text
Qader GUI
  -> PermissionsGuard
  -> MT5Service read-only bars
  -> FractalAgent / SmcAgent / IctSweepAgent
  -> SignalArbiter
  -> DecisionRouter
  -> ConflictGuard
  -> RiskManager
  -> Scanner table / learning journal
```

Dry-run runner flow:

```text
Qader RunnerService
  -> can_run_dry_run permission
  -> config/dry_run_simulation.yaml
  -> monkey-patched mt5.order_send counter/blocker
  -> main_loop.run_cycle(... fixed cycles ...)
  -> DRY_RUN simulated result
```

## Data Layout

```text
data/qader/profile.json        created after onboarding
data/qader/settings.json       safe app settings
data/qader/permissions.json    user permissions with live trading locked
data/qader/memory.json         local assistant memory
data/qader/dna/default_genome.json
data/qader/dna/active_genome.json
data/qader/dna/genome_history.jsonl
data/qader/dna/performance_journal.jsonl
logs/qader_audit.jsonl
```

## Another Device Behavior

`qader_app.paths` resolves paths relative to the EXE folder when frozen and relative to the repo root during development. On another Windows device, Qader creates `data/qader`, `logs`, and `reports`, then launches onboarding if no profile exists. If MT5 is unavailable, Qader remains usable in assistant/offline mode.

