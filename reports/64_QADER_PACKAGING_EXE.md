# Report 64 - Qader Packaging EXE

Generated: 2026-05-14

## Packaging Layer

Created:

```text
packaging/qader.spec
packaging/build_qader.ps1
packaging/README_BUILD.md
```

Expected output when PyInstaller is available:

```text
dist/Qader/Qader.exe
```

## Build Command

```powershell
.\packaging\build_qader.ps1 -Clean
```

If PyInstaller is not installed:

```powershell
.\packaging\build_qader.ps1 -InstallPyInstaller -Clean
```

## Packaging Validation

- `qader.spec` syntax compile: PASS
- PyInstaller availability in current `.venv`: NOT INSTALLED
- Actual EXE build: NOT RUN in this pass

The build script does not permanently delete old build output. With `-Clean`, prior build folders are moved under `_archive/qader_build_cleanup_<timestamp>/`.

## Included

- `src/qader_app` through PyInstaller imports
- `src/mt5_ai` through PyInstaller imports
- `config/trading_runtime.yaml`
- `config/dry_run_simulation.yaml`
- `config/live_micro_disabled.yaml`
- Runtime creation of `data/qader`, `logs`, and `reports`

## Excluded / Not Bundled Intentionally

- `.env`
- old logs
- reports with account details
- broker passwords
- personal secrets
- unrestricted live-trading config

