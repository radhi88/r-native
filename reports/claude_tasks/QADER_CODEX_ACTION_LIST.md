# QADER CODEX ACTION LIST — Prioritized Implementation Checklist

**Author:** Claude (supervisor/reviewer)  
**Date:** 2026-05-14  
**Source reports:** claude_review/10–14  
**Purpose:** Actionable tasks for Codex in priority order

---

## CRITICAL

---

### Q-CRIT-1: Fix all hardcoded `C:\Users\Radhi` paths — portability blocker

**Priority:** CRITICAL  
**Files:** 17 active files (see Report 14 §2 for full list)  
**Key files:** `core/config_loader.py:6`, `runtime/main_loop.py:18`, `core/structured_logger.py:7-8`, `core/signal_arbiter.py:59`, `algory_runner.py:34-35`, `core/breeding_pool.py:31-36`, `core/genome_quality_gate.py:41-46`, `core/numeric_safety.py:43-44`, `algory_loader.py:27`, `algory_integrator.py:43`, `market_projection_engine.py:33`, `runtime/dry_run_simulation.py:13`, `runtime/demo_runner.py:16`, `runtime/dry_run_runner.py:6`, `friday_voice/jarvis_prebrain.py:11`, `config/trading_runtime.yaml:57`

**Issue:** Every file that contains `C:\Users\Radhi` will crash with `FileNotFoundError` on any other machine or user account. The EXE cannot run on another Windows device.

**Risk:** Complete failure to launch on a new machine. No fallback.

**Recommended fix:**  
Create a single `src/mt5_ai/core/project_root.py`:
```python
import os
from pathlib import Path

def get_project_root() -> Path:
    env = os.getenv("FRIDAY_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    candidate = Path(__file__).resolve()
    for _ in range(6):
        candidate = candidate.parent
        if (candidate / "config" / "trading_runtime.yaml").exists():
            return candidate
    raise RuntimeError("Cannot locate project root. Set FRIDAY_PROJECT_ROOT.")

PROJECT_ROOT = get_project_root()
```

Then replace all `Path(r"C:\Users\Radhi\MT5")` with `PROJECT_ROOT` imported from this module. For AppData paths, use `Path.home() / "AppData" / "Local" / "FRIDAY"`.

For `config/trading_runtime.yaml:57`: change `log_dir` to `"logs"` (relative).

**Safe to apply now:** YES — does not change behavior on Radhi's machine if `trading_runtime.yaml` exists at the expected path (auto-discovery will find it).

---

### Q-CRIT-2: Create PyInstaller `.spec` file for Qader EXE

**Priority:** CRITICAL  
**File:** `qader.spec` (new file at project root)

**Issue:** No EXE packaging configuration exists. The project cannot be built as a portable EXE without a `.spec` file that defines entry point, assets, hidden imports, and bundled data files.

**Risk:** EXE build is impossible. Portability goal cannot be achieved.

**Recommended fix:**  
Create `qader.spec`:
```python
# qader.spec
a = Analysis(
    ['mark_xxxix/main.py'],
    pathex=['mark_xxxix', 'src'],
    datas=[
        ('mark_xxxix/core/prompt.txt', 'core/'),
        ('mark_xxxix/core/runtime_control.py', 'core/'),
        ('config/trading_runtime.yaml', 'config/'),
        ('config/dry_run_simulation.yaml', 'config/'),
        ('models/voice/vosk-model-ar-mgb2-0.4', 'models/voice/vosk-model-ar-mgb2-0.4'),
    ],
    hiddenimports=[
        'sounddevice', 'MetaTrader5', 'faster_whisper',
        'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
        'google.genai', 'mt5_ai.core.config_loader',
    ],
    excludes=['api_keys.json'],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas,
          name='Qader', console=False, icon='assets/qader.ico')
```

**Note:** `mark_xxxix/config/api_keys.json` must NOT be bundled — it is generated at first boot.

**Safe to apply now:** YES — new file, no runtime impact.

---

### Q-CRIT-3: Block voice-triggered stack start/restart — require confirmation

**Priority:** CRITICAL  
**File:** `mark_xxxix/friday_plugin.py` lines 573–603

**Issue:** `friday_stack_control(action="start"/"restart")` launches `restart_friday.ps1` via PowerShell with no confirmation. A misheard or ambiguous voice command can start the trading loop. If config is ever changed to DEMO/LIVE, real orders would be placed.

**Risk:** Unintended trading session started by voice. No undo.

**Recommended fix:**
```python
def _friday_stack_control(args: dict) -> str:
    action = str(args.get("action", "status") or "status").strip().lower()
    if action in {"start", "restart", "stop"}:
        return (
            f"⚠️ Stack {action.upper()} requires manual confirmation. "
            f"Use the FRIDAY control panel or type the command directly in the terminal. "
            f"Voice-triggered stack control is disabled for safety."
        )
    # status/health/check fall through to read-only probe
    return _friday_services({"detail": True})
```

Stack start/stop should only be possible via a physical button click in the UI, not via voice or text.

**Safe to apply now:** YES.

---

## HIGH

---

### Q-HIGH-1: Remove `-ExecutionPolicy Bypass` from stack control subprocess

**Priority:** HIGH  
**File:** `mark_xxxix/friday_plugin.py` line 595

**Issue:** `subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass", "-File", script])` disables PowerShell script signing. Any `.ps1` file in FRIDAY_ROOT can be executed without restriction.

**Risk:** If FRIDAY_ROOT is compromised, arbitrary PowerShell code executes.

**Fix:** Remove `-ExecutionPolicy Bypass`. Use `-ExecutionPolicy RemoteSigned` or `Unrestricted` only if scripts are not signed. Validate `script` path against a fixed whitelist before calling Popen.

**Safe to apply now:** YES.

---

### Q-HIGH-2: Block trading config files from project_agent writes

**Priority:** HIGH  
**File:** `mark_xxxix/main.py` — `PROJECT_AGENT_SECRET_FILE_NAMES` set (line ~154)

**Issue:** The `project_agent` AI tool can write any `.py` or `.yaml` file in PROJECT_ROOT. This includes `trading_runtime.yaml`, `execution_manager.py`, `kill_switch.py`. A voice-triggered project_agent invocation could modify trading safety gates.

**Risk:** AI-driven modification of trading config or execution pipeline, bypassing DRY_RUN or kill_switch.

**Fix:** Add to `PROJECT_AGENT_SECRET_FILE_NAMES`:
```python
PROJECT_AGENT_SECRET_FILE_NAMES = {
    ".env", "api_keys.json", "secrets.json", "credentials.json",
    "token.json", "tokens.json", "service_account.json",
    # Trading safety files — must never be AI-edited:
    "trading_runtime.yaml", "dry_run_simulation.yaml",
    "execution_manager.py", "kill_switch.py", "config_loader.py",
}
```

**Safe to apply now:** YES.

---

### Q-HIGH-3: Fix `config_loader.py` default config path (part of Q-CRIT-1)

**Priority:** HIGH (also covered in Q-CRIT-1 but warrants explicit tracking)  
**File:** `src/mt5_ai/core/config_loader.py:6`

**Issue:** `_DEFAULT_CONFIG = Path(r"C:\Users\Radhi\MT5\config\trading_runtime.yaml")` — the first line executed by the entire trading pipeline uses a hardcoded absolute path.

**Risk:** `is_dry_run()`, `is_kill_switch()`, and `is_live_allowed()` all raise `FileNotFoundError` on a new machine. The safety defaults (DRY_RUN, kill_switch=True) cannot be read.

**Fix:**
```python
_DEFAULT_CONFIG = (
    Path(os.getenv("FRIDAY_PROJECT_ROOT", ""))
    / "config" / "trading_runtime.yaml"
    if os.getenv("FRIDAY_PROJECT_ROOT")
    else Path(__file__).resolve().parents[4] / "config" / "trading_runtime.yaml"
)
```

**Safe to apply now:** YES.

---

### Q-HIGH-4: Bundle Whisper model or add download-on-first-run with progress UI

**Priority:** HIGH  
**File:** `mark_xxxix/main.py` — Whisper initialization

**Issue:** `faster-whisper` downloads the model on first use. On a new machine without internet, this silently fails. The voice assistant starts but STT fails with no user feedback.

**Risk:** Voice system appears broken on first launch. No error message shown to user.

**Fix:** Either pre-bundle the `small` Whisper model in the EXE assets, or add a first-launch download progress bar before the main window opens. Show a clear error if download fails.

**Safe to apply now:** YES — new file/UI addition.

---

## MEDIUM

---

### Q-MED-1: Apply Qader identity — rename UI from Ghder/MARK XXXIX to قادر

**Priority:** MEDIUM  
**File:** `mark_xxxix/ui.py`

**Issues:**
- Line 1029: `setWindowTitle("Ghder — MARK XXXIX")` → `"قادر — Qader"`
- Line 1181: title label text `"Ghder"` → `"قادر"`
- Line 461: HUD fallback text `"Ghder"` → `"قادر"`
- Line 1442: footer `"FatihMakes Industries · MARK XXXIX · CLASSIFIED"` → project name
- Line 1444: footer `"© FATIHMAKES"` → owner name
- Line 1186: tagline `"Just A Rather Very Intelligent System"` → optional Qader tagline

**Risk:** No functional impact. But branding is inconsistent for any demo or release.

**Safe to apply now:** YES.

---

### Q-MED-2: Add trading safety context to onboarding screen

**Priority:** MEDIUM  
**File:** `mark_xxxix/ui.py` — `SetupOverlay` class (line 888)

**Issue:** First-boot screen only asks for Gemini API key and OS. No mention of: trading mode (DRY_RUN), live trading status, audio privacy (Gemini receives voice), or what Qader can/cannot do.

**Fix:** Add a brief info panel to `SetupOverlay`:
- "Trading mode: DRY_RUN — no real orders will be placed"
- "Voice is processed by Google Gemini (requires internet)"
- "No broker credentials are stored by this application"

**Safe to apply now:** YES.

---

### Q-MED-3: Validate Gemini API key format at onboarding

**Priority:** MEDIUM  
**File:** `mark_xxxix/ui.py` — `SetupOverlay._submit()` (line 1011)

**Issue:** Any non-empty string is accepted as a valid API key. A typo is discovered only when Gemini fails at runtime, with no user-friendly message.

**Fix:** Add format check: Gemini API keys start with `"AIza"` and are 39 characters. Reject keys that don't match before saving.

**Safe to apply now:** YES.

---

### Q-MED-4: Store Gemini API key in Windows Credential Manager

**Priority:** MEDIUM  
**File:** `mark_xxxix/config/api_keys.json`

**Issue:** API key stored as plaintext JSON in project directory. Risk of accidental exposure via cloud sync, version control, or EXE bundle.

**Fix:** Use Python `keyring` library:
```python
import keyring
keyring.set_password("Qader", "gemini_api_key", key)
key = keyring.get_password("Qader", "gemini_api_key")
```

**Safe to apply now:** YES — `keyring` is cross-platform and works on Windows without additional dependencies.

---

### Q-MED-5: Pick one voice system — consolidate or explicitly deprecate friday_voice/

**Priority:** MEDIUM  
**Files:** `src/mt5_ai/friday_voice/` (entire subsystem)

**Issue:** Two independent voice stacks exist. `friday_voice/` is not called by `mark_xxxix/main.py`. It is dead code for Qader but still in the Python package path.

**Fix:** Either integrate `friday_voice/` as a local STT/TTS backend for mark_xxxix, or move it to `archive/`. Document the decision.

**Safe to apply now:** YES — moving to archive does not affect mark_xxxix voice.

---

### Q-MED-6: Keep `PROJECT_AGENT_AUTO_FIX=False` and `AUTO_WATCH=False` enforced

**Priority:** MEDIUM  
**File:** `mark_xxxix/main.py` lines 138–139

**Issue:** These are currently `False` by default (safe). But they are env-var overridable. If a user or script sets `JARVIS_PROJECT_AGENT_AUTO_FIX=1`, the AI will silently apply code fixes autonomously.

**Fix:** Add a startup warning if either flag is True:
```python
if PROJECT_AGENT_AUTO_FIX:
    log.warning("PROJECT_AGENT_AUTO_FIX is enabled — AI will autonomously modify source files")
if PROJECT_AGENT_AUTO_WATCH:
    log.warning("PROJECT_AGENT_AUTO_WATCH is enabled — AI will autonomously monitor and fix errors")
```

Consider making these hard-disabled for the Qader EXE build (not overridable via env var).

**Safe to apply now:** YES.

---

## LOW

---

### Q-LOW-1: Add `two-voice-system` notice to mark_xxxix README

**Priority:** LOW  
Note that `friday_voice/` is a standalone subsystem not used by Qader. Prevents future confusion.

---

### Q-LOW-2: Add mute-stops-capture behavior to UI tooltip

**Priority:** LOW  
**File:** `mark_xxxix/ui.py` — mute button  
Current mute stops processing but not microphone capture. Add tooltip: "Mutes responses — audio capture continues in background."

---

### Q-LOW-3: Add `FRIDAY_PROJECT_ROOT` to `.env.example`

**Priority:** LOW  
Create `mark_xxxix/.env.example` documenting all configurable env vars:
```
FRIDAY_PROJECT_ROOT=C:\Users\YourName\MT5
JARVIS_PERMISSION_PROFILE=guarded
JARVIS_PROJECT_AGENT_ENABLED=1
JARVIS_PROJECT_AGENT_AUTO_FIX=0
JARVIS_PROJECT_AGENT_AUTO_WATCH=0
```

---

## Summary Table

| ID | Priority | File | Issue | Safe Now |
|---|---|---|---|---|
| Q-CRIT-1 | CRITICAL | 17 files | Hardcoded `C:\Users\Radhi` paths — portability blocker | YES |
| Q-CRIT-2 | CRITICAL | `qader.spec` (new) | No EXE packaging spec exists | YES |
| Q-CRIT-3 | CRITICAL | `friday_plugin.py` | Stack start/restart via voice — no confirmation | YES |
| Q-HIGH-1 | HIGH | `friday_plugin.py` | `-ExecutionPolicy Bypass` in subprocess | YES |
| Q-HIGH-2 | HIGH | `main.py` | Trading config files not blocked from project_agent | YES |
| Q-HIGH-3 | HIGH | `config_loader.py` | Hardcoded default config path (subset of Q-CRIT-1) | YES |
| Q-HIGH-4 | HIGH | `main.py` | Whisper model not bundled — fails offline | YES |
| Q-MED-1 | MEDIUM | `ui.py` | Identity still shows Ghder/MARK XXXIX | YES |
| Q-MED-2 | MEDIUM | `ui.py` | No trading safety context in onboarding | YES |
| Q-MED-3 | MEDIUM | `ui.py` | API key not validated at setup | YES |
| Q-MED-4 | MEDIUM | `api_keys.json` | API key in plaintext JSON | YES |
| Q-MED-5 | MEDIUM | `friday_voice/` | Two voice stacks — consolidate or archive | YES |
| Q-MED-6 | MEDIUM | `main.py` | AUTO_FIX/AUTO_WATCH startup warning missing | YES |
| Q-LOW-1 | LOW | README | Document two-voice-system architecture | YES |
| Q-LOW-2 | LOW | `ui.py` | Mute button tooltip misleading | YES |
| Q-LOW-3 | LOW | `.env.example` (new) | No documented env var reference | YES |

**Total: 3 CRITICAL, 4 HIGH, 6 MEDIUM, 3 LOW**

---

## Safety Invariants (must not be violated by any fix)

- `trading_runtime.yaml` mode must remain `DRY_RUN` by default
- `allow_live_trading` must remain `false` by default
- `kill_switch` must remain `true` by default
- `order_send` must never be callable from voice or UI without explicit user confirmation + mode change
- `SignalArbiter` and `ConflictGuard` must never be bypassed
- `PROJECT_AGENT_AUTO_FIX` must remain `False` in the Qader EXE build
- `api_keys.json` must never be bundled inside the EXE
