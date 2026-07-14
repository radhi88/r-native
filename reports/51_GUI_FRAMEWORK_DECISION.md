# Report 51 - GUI Framework Decision

Generated: 2026-05-14

## Decision

Selected framework: **PyQt6**

## Reasoning

| Criteria | PyQt6 | PySide6 | CustomTkinter | Electron/Tauri |
|---|---:|---:|---:|---:|
| Already installed in `.venv` | yes | no | no | no |
| Native Windows desktop | yes | yes | yes | via web shell |
| Background workers | strong | strong | basic | strong |
| Tables/log dashboards | strong | strong | moderate | strong |
| Voice controls integration | good | good | good | requires bridge |
| EXE packaging | PyInstaller-supported | PyInstaller-supported | PyInstaller-supported | separate stack |
| Fit with Python MT5 codebase | strong | strong | strong | weaker |

PyQt6 is the pragmatic choice because it is already available in the project environment and avoids adding a second runtime. It supports the app shell, tabs, tables, logs, settings dialogs, and future worker-thread scanner updates.

## Implementation

GUI entry point:

```text
src/qader_app/main.py
```

Main window:

```text
src/qader_app/gui/main_window.py
```

First-run onboarding:

```text
src/qader_app/gui/onboarding.py
```

## Packaging Note

PyInstaller is not currently installed in `.venv`. Packaging files were created and syntax-validated. Build script supports installing PyInstaller into the project venv when explicitly run with `-InstallPyInstaller`.

