# Report 60 - Qader EXE App Implementation

Generated: 2026-05-14

## What Was Built

Implemented the first full Qader desktop application layer:

- PyQt6 app shell
- First-run onboarding wizard
- Permissions center
- Local profile/settings/permissions storage
- Assistant identity and bilingual introduction
- Voice STT/TTS boundary
- Market scanner service over existing agents and `SignalArbiter`
- Dry-run runner service over `main_loop.run_cycle`
- Strategy DNA/genome engine
- Learning journal and mutation proposal loop
- Audit log system
- Settings import/export
- PyInstaller packaging files
- Safe unit tests and GUI smoke test

## New Entry Points

Development GUI:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m qader_app.main
```

Bootstrap without GUI:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m qader_app.main --no-gui
```

EXE build command:

```powershell
.\packaging\build_qader.ps1 -Clean
```

If PyInstaller is missing:

```powershell
.\packaging\build_qader.ps1 -InstallPyInstaller -Clean
```

## Changed / New Files

Primary implementation:
- `src/qader_app/main.py`
- `src/qader_app/paths.py`
- `src/qader_app/gui/*.py`
- `src/qader_app/assistant/*.py`
- `src/qader_app/services/*.py`
- `src/qader_app/genome/*.py`
- `src/qader_app/storage/*.py`

Packaging:
- `packaging/qader.spec`
- `packaging/build_qader.ps1`
- `packaging/README_BUILD.md`

Tests:
- `tests/test_qader_app.py`

Runtime data created by bootstrap:
- `data/qader/settings.json`
- `data/qader/permissions.json`
- `data/qader/dna/default_genome.json`
- `data/qader/dna/active_genome.json`
- `data/qader/dna/genome_history.jsonl`
- `data/qader/dna/performance_journal.jsonl`

## Reused Existing Architecture

Qader wraps the existing safe pipeline instead of replacing it:

```text
FractalAgent / SmcAgent / IctSweepAgent
  -> SignalArbiter
  -> DecisionRouter
  -> ConflictGuard
  -> RiskManager
  -> ExecutionManager in DRY_RUN only
```

Voice review reused design lessons from:
- `mark_xxxix/main.py`
- `src/mt5_ai/voice_io.py`
- `src/mt5_ai/friday_voice/voice_input.py`
- `src/mt5_ai/friday_voice/voice_output.py`

No broad Mark-XXXIX computer-control tools were copied into Qader.

## Safety Status

Live trading remains disabled and locked. Qader cannot place live orders in this build. Dry-run runner monkey-patches `mt5.order_send` during fixed-cycle tests so any unexpected write path is counted and blocked.

