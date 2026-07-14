# Qader EXE Build

Qader uses PyQt6 and PyInstaller for the Windows desktop build.

## Safe Build Command

```powershell
.\packaging\build_qader.ps1 -Clean
```

If PyInstaller is not installed in `.venv`, install it inside the project venv:

```powershell
.\packaging\build_qader.ps1 -InstallPyInstaller -Clean
```

Expected output:

```text
dist\Qader\Qader.exe
```

## Safety Notes

- The EXE includes app code and config templates, not old logs or secrets.
- The default runtime remains locked. `REAL_CONTROLLED_MODE` is bundled as a separate config and requires GUI unlock, typed confirmation, and a clean `verify_mt5_lockdown.py` result.
- Qader creates `data/qader/`, `logs/`, and `reports/` beside the EXE on first run.
- If MT5 is missing, Qader runs in assistant/offline mode.
- Live order placement is locked unless the user manually unlocks REAL CONTROLLED MODE in the Qader permissions screen.
