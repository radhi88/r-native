# FRIDAY R Factory — Deployment Guide

How to ship FRIDAY R Factory to a second machine (or 100 of them).

## Quick build (on your dev machine)

```powershell
# One-time prerequisites
python -m pip install --upgrade pyinstaller
# (Optional, for single-file installer) install Inno Setup 6:
#   https://jrsoftware.org/isdl.php

# Build
.\packaging\build_installer.ps1
```

Outputs in `dist/`:

| File | Size | What |
|---|---|---|
| `dist/FRIDAY/` | ~250 MB | Portable folder, copy anywhere |
| `dist/FRIDAY/FRIDAY.exe` | ~12 MB | Entry-point launcher |
| `dist/FRIDAY/FRIDAY_UI.exe` | ~12 MB | Desktop window (no console) |
| `dist/FRIDAY_Setup_v1.0.0.exe` | ~120 MB | Single-file installer (if Inno present) |

## Deploy to a second machine

### Option A — single-file installer (recommended)
1. Send the user `FRIDAY_Setup_v1.0.0.exe`
2. They double-click → wizard installs to `C:\Program Files\FRIDAY\` → desktop shortcut → optional auto-start
3. They open MetaTrader 5 first
4. They run "FRIDAY R Factory" from desktop
5. **First-Run Wizard** appears automatically — 6 stages, ~30 seconds, shows market + agents
6. Done — system trading

### Option B — portable folder
1. ZIP the `dist/FRIDAY/` folder
2. Recipient extracts anywhere (no admin needed)
3. Double-clicks `FRIDAY.exe`
4. Same first-run wizard

## Update flow (today)

For now, updates are **manual**:
1. Rebuild on your dev machine: `.\packaging\build_installer.ps1`
2. Send new `FRIDAY_Setup_v1.0.1.exe` to user
3. They install over the old version (Inno Setup auto-uninstalls previous)

## Roadmap toward over-the-air updates

| Phase | Need | Effort |
|---|---|---|
| **Now** | Manual installer sharing | Done |
| **A** | License key check on startup (RSA-signed local file) | 2h |
| **B** | Update server (FastAPI on cheap VPS, serves version manifest) | 3h |
| **C** | Auto-update inside FRIDAY.exe (download patch, restart) | 3h |
| **D** | User auth + subscription tiers (Stripe webhooks → license issuance) | 6h |
| **E** | Cloud-managed brain (Pro tier — brain runs on AWS, executor stays local) | 12h |

## What the second machine needs

| Required | Why |
|---|---|
| Windows 10 / 11 (64-bit) | PySide6 + PyInstaller target |
| MetaTrader 5 terminal | The trading bridge |
| MT5 account (demo or live) | To execute orders |
| 4 GB RAM free | Brain + UI + 5 agents + daemons |
| ~500 MB disk | Installation + data |

**Not required:** Python (bundled), Anthropic API key (Ollama is local-only currently)

## Telemetry / privacy

This build is fully **local**:
- No code or trade data leaves the user's machine
- LLM strategist uses Ollama (local llama3.1:8b) — no API calls
- Future cloud features (auth, updates) are opt-in

## Troubleshooting

| Problem | Fix |
|---|---|
| "MT5 init failed" on startup | Open MetaTrader 5 first, then launch FRIDAY |
| Windows Defender blocks `FRIDAY.exe` | Right-click → Properties → Unblock; or add an exclusion |
| First-run wizard doesn't appear | Delete `data/r_native/.onboarding_done` and relaunch |
| No trades after 5 minutes | Open AI ADVISORS tab → check agent log for blocked-symbol reasons |

---

Built with: PyInstaller, PySide6, MetaTrader5, Flask, NumPy, Pandas, Ollama.
