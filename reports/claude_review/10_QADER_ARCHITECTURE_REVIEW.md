# Report 10 — Qader Architecture Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Scope:** App architecture, GUI framework, identity, onboarding, integration

---

## 1. Current Architecture Overview

```
mark_xxxix/
├── main.py            — JarvisLive: Gemini Live audio loop, tool dispatch, Ollama fallback
├── ui.py              — JarvisUI / MainWindow (PyQt6)
├── friday_plugin.py   — FRIDAY trading tools (read-only state + stack control)
├── core/
│   └── runtime_control.py  — Permission profiles, path guards, command filter
├── memory/
│   ├── memory_manager.py   — JSON long-term memory (long_term.json)
│   └── ollama_self_improvement.json — Tool stats, AI lessons, conversation history
└── actions/           — File, browser, screen, weather, reminder, dev-agent tools
```

```
src/mt5_ai/
├── agents/            — 28 trading agents
├── core/              — Execution pipeline (arbiter, router, guard, risk, exec)
├── friday_voice/      — Local voice subsystem (separate from mark_xxxix)
├── runtime/           — main_loop.py, dry_run_simulation.py
└── [55 modules]       — DNA, genome, market analysis, neural network
```

**Integration:** `mark_xxxix/friday_plugin.py` connects Jarvis to FRIDAY via HTTP (127.0.0.1 ports 8790–8844) and SSE event stream. No shared Python imports — pure REST/SSE boundary.

---

## 2. GUI Framework

**Framework:** PyQt6 ✅  
**Entry point:** `mark_xxxix/main.py` → `JarvisLive` class → `JarvisUI(face_path)` → `MainWindow`

**UI components confirmed:**
- `HudCanvas` — animated face with rings, particles, speaking/muted states
- `MetricBar` — CPU/MEM/NET/GPU/TMP system meters
- `LogWidget` — typewriter-style activity log
- `FileDropZone` — drag-and-drop file upload
- `SetupOverlay` — first-boot config (API key + OS selection)

**Issue:** `_base_dir()` uses `sys.executable.parent` when frozen — correct EXE-aware pattern. ✅  
**Issue:** `MainWindow.setWindowTitle("Ghder — MARK XXXIX")` — title still has old identity (see §3).

---

## 3. Assistant Identity and Branding

| Location | Current Text | Expected |
|---|---|---|
| `ui.py:1029` — window title | `"Ghder — MARK XXXIX"` | `"قادر — Qader"` |
| `ui.py:1181` — header title label | `"Ghder"` | `"قادر"` |
| `ui.py:1444` — footer copyright | `"© FATIHMAKES"` | — |
| `ui.py:1442` — footer brand | `"FatihMakes Industries · MARK XXXIX · CLASSIFIED"` | — |
| `ui.py:461` — HUD fallback text | `"Ghder"` | `"قادر"` |
| `ui.py:1186` — tagline | `"Just A Rather Very Intelligent System"` | — |
| `friday_plugin.py` — all logs | `"JARVIS"` / `"FRIDAY"` | `"قادر"` |
| `memory/ollama_self_improvement.json` | `"Alternative Name": "Qader"` | Preferences only |

**Finding:** The project already has "Qader" registered as an alternative name in memory (confirmed in `ollama_self_improvement.json`). But the UI, window title, and all UI labels still display "Ghder" or "MARK XXXIX". No coherent Qader branding has been applied yet.

**Priority:** MEDIUM — cosmetic, no functional impact, but required before any demo or release.

---

## 4. Onboarding and First-Boot

`SetupOverlay` (ui.py:888) shows on first boot if `mark_xxxix/config/api_keys.json` is missing or has no `gemini_api_key`.

**What it captures:** Gemini API key (password field) + OS selection (Windows/macOS/Linux).  
**What it saves:** `{"gemini_api_key": key, "os_system": os_name}` to `api_keys.json`.

**Gaps:**
1. No key format validation — any non-empty string passes. A typo is only discovered when Gemini fails at runtime.
2. No trading mode explanation — user is not told whether trading is enabled, what DRY_RUN means, or that live trading is disabled.
3. No MT5 connection check during onboarding — user might expect it to connect to MT5 immediately.
4. No privacy notice — the app collects voice audio and sends it to Google Gemini.

**Priority:** MEDIUM — onboarding works but gives false confidence and no safety context.

---

## 5. Permissions System

`mark_xxxix/core/runtime_control.py` implements a layered permissions model:

**Profiles (set via `JARVIS_PERMISSION_PROFILE` env var, default: `"guarded"`):**
- `guarded` — safe roots = project dir + user home folders (Desktop, Downloads, etc.)
- `developer` — same as guarded
- `full` / `autonomous` — safe roots include `Path.home()` (full home directory)

**Guards:**
- Secret files blocked by default (`api_keys.json`, `.env`, `credentials.json`, etc.)
- System roots blocked (Windows, Program Files, AppData)
- Destructive ops (delete/move/rename) blocked unless `JARVIS_ALLOW_DESTRUCTIVE=1`
- Command word filter blocks `rm`, `del`, `powershell`, `curl`, `wget`, etc.

**Finding:** `powershell` and `powershell.exe` are in `BLOCKED_COMMAND_WORDS` in `runtime_control.py`. But `friday_plugin.py:_friday_stack_control()` calls `subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script])` directly — this bypasses the command word filter entirely because `is_command_allowed()` is only checked for user-specified shell commands, not for internal plugin tool calls.

**Priority:** HIGH — safety bypass via trusted plugin path (see Safety Review for details).

---

## 6. Architecture Gaps

| # | Area | Gap |
|---|---|---|
| A1 | Trading integration | FRIDAY trading engine (src/mt5_ai) has no documented activation/deactivation API from Qader UI. Stack is started via PowerShell, not controlled from within the Python app. |
| A2 | Two voice systems | `mark_xxxix/` uses Gemini Live + Whisper. `src/mt5_ai/friday_voice/` is a separate voice stack. No integration between them. Final Qader app needs one voice system. |
| A3 | Identity incomplete | No Python module named `qader` exists. The app is entirely built on `mark_xxxix` + `src/mt5_ai`. Rename/rebranding is purely cosmetic at this stage. |
| A4 | Market scanner | Market scanner exists in multiple files (`live_fractal_monitor.py`, `fractal_structure_engine.py`) but no dedicated Qader UI panel for it. |
| A5 | Logging divergence | Two log directories: `C:\Users\Radhi\MT5\logs\` and `C:\Users\Radhi\AppData\Local\FRIDAY\logs\`. No unified log view in Qader UI. |
| A6 | No EXE packaging | No `.spec` file, no cx_Freeze config, no Nuitka config. `setup.py` only installs pip packages. EXE build cannot proceed without a packaging spec. |
