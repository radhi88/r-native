# Report 11 — Qader Safety Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Scope:** Live trading gates, order_send paths, kill_switch, voice-triggered actions, hidden persistence

---

## 1. Trading Safety Gates — Current State

| Gate | Status | Evidence |
|---|---|---|
| `trading_runtime.yaml` mode | `DRY_RUN` ✅ | Line 6 |
| `allow_live_trading` | `false` ✅ | Line 7 |
| `kill_switch` | `true` (SAFE DEFAULT) ✅ | Line 8 |
| ExecutionManager DRY_RUN guard | Active ✅ | `execution_manager.py` |
| MT5Gateway demo method guards | Active ✅ | Fixed in HIGH-2 |
| magic number registry | All validated ✅ | Fixed in CRIT-1 |
| Voice layer → MT5 order_send | **NONE** ✅ | `mt5_tools.py` is read-only |

**The core trading pipeline is safe.** No path from Qader UI → voice → MT5 `order_send` exists in the current state.

---

## 2. Safety Findings

---

### S-CRIT-1: Stack restart can engage trading loop without confirmation
**Priority:** CRITICAL  
**File:** `mark_xxxix/friday_plugin.py` lines 573–603

`_friday_stack_control({"action": "start"})` launches:
```python
subprocess.Popen([
    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", str(FRIDAY_ROOT / "restart_friday.ps1"),
], cwd=str(FRIDAY_ROOT), shell=False)
```

This PowerShell script starts the FRIDAY trading stack, which includes `main_loop.py`. If the runtime config is not DRY_RUN, this would start placing real trades. The action is available via natural language in Gemini ("start FRIDAY", "restart the stack", "شغل فرايدي") — no confirmation dialog, no PIN, no key.

**Risk:** A misheard voice command or an ambiguous text command could restart the trading process. If `trading_runtime.yaml` is ever changed to DEMO or LIVE mode and the stack is restarted via voice, real orders would be placed.

**Fix:** Add an explicit `require_confirmation=True` flag to `friday_stack_control` for `start`/`restart` actions. In the UI, show a confirmation dialog before any stack start action. Alternatively, rate-limit to text-only (not voice).

**Safe to apply now:** YES.

---

### S-HIGH-1: `-ExecutionPolicy Bypass` in stack control
**Priority:** HIGH  
**File:** `mark_xxxix/friday_plugin.py` line 595

```python
subprocess.Popen([
    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
])
```

`-ExecutionPolicy Bypass` disables PowerShell script signing requirements. Any `.ps1` file in `FRIDAY_ROOT` can be run without restriction. If `FRIDAY_ROOT` is user-writable (it is — it's `C:\Users\Radhi\MT5`), a compromised file in that directory could be executed.

**Risk:** If the FRIDAY_ROOT directory is accessible by malware or a compromised dependency, arbitrary PowerShell code could be executed. Scope: local machine only, not remote.

**Fix:** Remove `-ExecutionPolicy Bypass` and sign scripts, or use `Unrestricted` as the minimum needed. Validate the script path against a whitelist before execution.

**Safe to apply now:** YES.

---

### S-HIGH-2: `BLOCKED_COMMAND_WORDS` does not cover internal plugin calls
**Priority:** HIGH  
**File:** `mark_xxxix/core/runtime_control.py` and `mark_xxxix/friday_plugin.py`

`runtime_control.is_command_allowed()` blocks `powershell` and `powershell.exe`. But `friday_plugin._friday_stack_control()` calls `subprocess.Popen(["powershell", ...])` directly — as a trusted plugin function, not through `is_command_allowed()`. The filter is bypassed.

**Risk:** The intent of the security layer (block PowerShell access) is silently violated by the plugin. Future plugins could follow the same pattern and bypass all command guards.

**Fix:** Route all subprocess calls through `is_command_allowed()`, or document that `friday_stack_control` is an explicitly permitted exception and gate it with its own confirmation requirement.

**Safe to apply now:** YES.

---

### S-HIGH-3: Hardcoded `C:\Users\Radhi\MT5` in `config_loader.py`
**Priority:** HIGH  
**File:** `src/mt5_ai/core/config_loader.py` line 6

```python
_DEFAULT_CONFIG = Path(r"C:\Users\Radhi\MT5\config\trading_runtime.yaml")
```

This is the fallback path used when `use_config()` is not called. On any other machine (or any other Windows user account), this path does not exist. `config_loader.load()` will raise `FileNotFoundError`. The entire pipeline (ExecutionManager, RiskManager, ConflictGuard, kill_switch) all fail to initialize.

**Risk:** On a new machine, `is_dry_run()` raises instead of returning True. `is_kill_switch()` raises instead of returning True (safe default). Both would propagate as unhandled exceptions.

**Impact on EXE portability:** The EXE cannot run on another Windows device at all.

**Fix:**
```python
_DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config" / "trading_runtime.yaml"
```
Or better: derive from a runtime-resolved project root, or from an environment variable:
```python
_DEFAULT_CONFIG = Path(os.getenv("FRIDAY_CONFIG", str(
    Path(__file__).resolve().parents[4] / "config" / "trading_runtime.yaml"
)))
```

**Safe to apply now:** YES — does not affect any running session if `use_config()` is called first.

---

### S-HIGH-4: 17+ additional hardcoded `C:\Users\Radhi` paths in active source
**Priority:** HIGH  
**Files:** Multiple (see full list below)

Grep result confirmed hardcoded paths in the following active (non-archive) files:

| File | Hardcoded Path |
|---|---|
| `core/config_loader.py:6` | `C:\Users\Radhi\MT5\config\trading_runtime.yaml` |
| `algory_runner.py:34-35` | `C:/Users/Radhi/AppData/Local/FRIDAY/...` |
| `core/breeding_pool.py:31-32,36` | `C:\Users\Radhi\MT5\logs`, AppData, pool file |
| `algory_loader.py:27` | `C:\Users\Radhi\AppData\Local\Algory\Generated_Strategies` |
| `core/genome_quality_gate.py:41-42,46` | log dirs + quarantine dir |
| `algory_integrator.py:43` | `C:/Users/Radhi/AppData/Local/FRIDAY/active_genomes.json` |
| `gene_fitness_db.py:459` | `C:\Users\Radhi\AppData\Local\Algory\gene_fitness_v2.json` |
| `market_projection_engine.py:33` | `C:/Users/Radhi/AppData/Local/FRIDAY` |
| `core/numeric_safety.py:43-44` | log dirs |
| `runtime/demo_runner.py:16` | `C:\Users\Radhi\MT5` |
| `runtime/dry_run_runner.py:6` | `C:\Users\Radhi\MT5` |
| `core/signal_arbiter.py:59` | `C:\Users\Radhi\MT5\logs\arbitration_decisions.jsonl` |
| `core/structured_logger.py:7-8` | project logs + AppData logs |
| `runtime/main_loop.py:18` | `C:\Users\Radhi\MT5` |
| `runtime/dry_run_simulation.py:13` | `C:\Users\Radhi\MT5` |
| `friday_voice/jarvis_prebrain.py:11` | `C:\Users\Radhi\MT5` |
| `config/trading_runtime.yaml:57` | `C:/Users/Radhi/AppData/Local/FRIDAY/logs` |

**Risk:** Any of these modules will crash on a different machine or user account. The EXE cannot be ported.

**Fix:** Replace all hardcoded paths with a runtime-resolved `PROJECT_ROOT` derived from `Path(__file__)` or an environment variable. See recommended pattern in S-HIGH-3 fix above.

**Safe to apply now:** YES — each file can be fixed independently.

---

### S-MED-1: Gemini API key stored in plaintext JSON
**Priority:** MEDIUM  
**File:** `mark_xxxix/config/api_keys.json`

The API key is stored as:
```json
{"gemini_api_key": "AIza...", "os_system": "windows"}
```

This file is in the project directory, unencrypted. If the project directory is shared, synced to cloud storage, or included in an EXE bundle, the key is exposed.

**Risk:** API key exposure. Cost impact (Gemini API billing). Not a trading safety risk.

**Fix:** Store in Windows Credential Manager or `keyring` library. At minimum, document that `config/api_keys.json` must not be committed to version control or bundled in the EXE.

**Safe to apply now:** YES.

---

### S-MED-2: No log directory creation guard in trading_runtime.yaml
**Priority:** MEDIUM  
**File:** `config/trading_runtime.yaml` line 57

```yaml
logging:
  log_dir: "C:/Users/Radhi/AppData/Local/FRIDAY/logs"
```

On another machine, this directory does not exist. `structured_logger.py` would fail to write logs. Depending on error handling, this could silently suppress all structured logging (JSONL logs that the decision pipeline relies on).

**Fix:** Either derive `log_dir` from a relative path (e.g., `"./logs"` relative to the config file), or ensure all logging code creates the directory if it doesn't exist.

**Safe to apply now:** YES.

---

### S-LOW-1: No hidden startup persistence
**Priority:** CONFIRMED SAFE  
No Windows registry startup entries, no scheduled tasks, no startup folder shortcuts were added by the application code. The app starts via explicit user action only. ✅

---

### S-LOW-2: No broker secrets or passwords stored
**Priority:** CONFIRMED SAFE  
No MT5 password, broker login, or account credentials are stored anywhere in the Python codebase. MT5 connection is via the platform's own session. ✅

---

### S-LOW-3: No hidden actions in SSE listener
**Priority:** CONFIRMED SAFE  
The SSE listener (`friday_plugin._sse_thread`) reads events and calls `jarvis.speak()` and `ui.write_log()`. It does not call any trading function, does not modify config, does not run subprocesses. ✅

---

## 3. Safety Summary

| Gate | Status |
|---|---|
| Live trading disabled by default | ✅ CONFIRMED |
| order_send unreachable from voice | ✅ CONFIRMED |
| Kill switch active | ✅ CONFIRMED |
| Stack restart requires no confirmation | ❌ S-CRIT-1 |
| ExecutionPolicy Bypass in subprocess | ❌ S-HIGH-1 |
| Hardcoded paths break portability | ❌ S-HIGH-3/4 |
| API key stored in plaintext | ⚠️ S-MED-1 |
| No hidden persistence | ✅ CONFIRMED |
| No stored broker credentials | ✅ CONFIRMED |
