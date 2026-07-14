# Report 14 — Qader EXE Packaging Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Scope:** EXE build strategy, portability, bundling gaps, hardcoded paths

---

## 1. Current Packaging State

**Verdict: No EXE packaging exists. The project cannot currently be built as a portable EXE.**

| Item | Status |
|---|---|
| PyInstaller `.spec` file | ❌ MISSING |
| cx_Freeze configuration | ❌ MISSING |
| Nuitka configuration | ❌ MISSING |
| `setup.py` in mark_xxxix/ | Only runs `pip install` + `playwright install` — not an EXE builder |
| Frozen-aware path in `ui.py` | ✅ Present — `_base_dir()` checks `sys.frozen` |
| Frozen-aware path in `main.py` | ✅ Present — `get_base_dir()` checks `sys.frozen` |

The two frozen-aware functions in `ui.py` and `main.py` are the only EXE-ready code. Everything else assumes a development directory layout.

---

## 2. Hardcoded Path Catalog — Active Files Only

17 hardcoded `C:\Users\Radhi` paths in non-archive source files that **must be fixed before any EXE can run on another machine:**

| File | Hardcoded Path | Breaks What |
|---|---|---|
| `core/config_loader.py:6` | `C:\Users\Radhi\MT5\config\trading_runtime.yaml` | Entire pipeline init |
| `runtime/main_loop.py:18` | `C:\Users\Radhi\MT5` | Main trading loop |
| `runtime/dry_run_simulation.py:13` | `C:\Users\Radhi\MT5` | Simulation test |
| `runtime/demo_runner.py:16` | `C:\Users\Radhi\MT5` | Demo mode runner |
| `runtime/dry_run_runner.py:6` | `C:\Users\Radhi\MT5` | Dry run runner |
| `core/signal_arbiter.py:59` | `C:\Users\Radhi\MT5\logs\...` | Arbitration logging |
| `core/structured_logger.py:7-8` | `C:\Users\Radhi\MT5\logs` + AppData | All JSONL logs |
| `core/breeding_pool.py:31-32,36` | `C:\Users\Radhi\MT5\logs` + AppData | Genome breeding |
| `core/genome_quality_gate.py:41-42,46` | `C:\Users\Radhi\...` | Genome validation |
| `core/numeric_safety.py:43-44` | `C:\Users\Radhi\MT5\logs` + AppData | Numeric safety logs |
| `algory_runner.py:34-35` | `C:/Users/Radhi/AppData/Local/FRIDAY/...` | Runner log + state |
| `algory_loader.py:27` | `C:\Users\Radhi\AppData\Local\Algory\...` | Strategy vault |
| `algory_integrator.py:43` | `C:/Users/Radhi/AppData/Local/FRIDAY/...` | Active genomes registry |
| `gene_fitness_db.py:459` | `C:\Users\Radhi\AppData\Local\Algory\...` | Gene fitness source |
| `market_projection_engine.py:33` | `C:/Users/Radhi/AppData/Local/FRIDAY` | Market projections |
| `friday_voice/jarvis_prebrain.py:11` | `C:\Users\Radhi\MT5` | Voice pre-brain |
| `config/trading_runtime.yaml:57` | `C:/Users/Radhi/AppData/Local/FRIDAY/logs` | YAML log_dir |

**Recommended fix pattern** (apply to every file above):
```python
# Replace hardcoded ROOT = Path(r"C:\Users\Radhi\MT5") with:
import os
from pathlib import Path

def _resolve_project_root() -> Path:
    env = os.getenv("FRIDAY_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    # Walk up from __file__ to find config/trading_runtime.yaml
    candidate = Path(__file__).resolve()
    for _ in range(6):
        candidate = candidate.parent
        if (candidate / "config" / "trading_runtime.yaml").exists():
            return candidate
    raise RuntimeError("Cannot locate FRIDAY project root. Set FRIDAY_PROJECT_ROOT env var.")

ROOT = _resolve_project_root()
```

For `config/trading_runtime.yaml:57` — replace hardcoded `log_dir` with a relative path:
```yaml
logging:
  log_dir: "logs"  # relative to project root
```

---

## 3. Asset Bundling Requirements

For a portable EXE the following assets must be included:

| Asset | Size | Location | Status |
|---|---|---|---|
| Vosk Arabic model | ~50MB | `models/voice/vosk-model-ar-mgb2-0.4/` | Present locally |
| Whisper model (small) | ~460MB | Downloaded by faster-whisper on first run | NOT bundled |
| Neural network weights | Variable | `models/` or AppData | NOT inventoried |
| Genome population files | Variable | `AppData/Local/FRIDAY/` | Hardcoded path |
| Trading config YAML | Small | `config/trading_runtime.yaml` | Present |
| mark_xxxix `core/prompt.txt` | Small | `mark_xxxix/core/prompt.txt` | Must be included |
| `api_keys.json` | Tiny | `mark_xxxix/config/` | Must NOT be bundled — generated at first boot |

**Key issue:** Whisper model is downloaded at runtime by faster-whisper. On a machine with no internet connection, this fails silently. The model must be pre-bundled or downloaded during setup.

---

## 4. Platform Dependencies

| Dependency | Windows | Portable |
|---|---|---|
| MetaTrader5 Python package | Windows only (MT5 DLL) | ❌ NOT portable to other OS |
| PyQt6 | Windows/Mac/Linux | ✅ |
| sounddevice | Windows/Mac/Linux | ✅ |
| faster-whisper | Windows/Mac/Linux | ✅ |
| Gemini API | Cloud — requires internet | Requires internet |
| Ollama | Requires local install | NOT bundleable as EXE |
| Playwright | Requires browser install | Requires setup step |
| tensorflow / keras | Windows/Linux/Mac | ✅ but large (~600MB) |

**Conclusion:** MetaTrader5 is Windows-only. The EXE is Windows-only. This is acceptable for the stated use case but must be documented.

**Ollama cannot be bundled** — it is a separate server process. The EXE must handle "Ollama not available" gracefully (currently it does — falls back to Gemini).

---

## 5. Recommended Packaging Approach

**Tool:** PyInstaller (best compatibility with PyQt6 + sounddevice + numpy)

**Minimum spec requirements:**
```python
# qader.spec (skeleton)
a = Analysis(
    ['mark_xxxix/main.py'],
    pathex=['mark_xxxix', 'src'],
    datas=[
        ('mark_xxxix/core/prompt.txt', 'core/'),
        ('config/trading_runtime.yaml', 'config/'),
        ('config/dry_run_simulation.yaml', 'config/'),
        ('models/voice/vosk-model-ar-mgb2-0.4', 'models/voice/vosk-model-ar-mgb2-0.4'),
        ('mark_xxxix/ui.py', '.'),  # if not auto-discovered
    ],
    hiddenimports=['sounddevice', 'MetaTrader5', 'faster_whisper', ...],
)
```

**Critical:** `api_keys.json` must be excluded from the bundle. `mark_xxxix/config/api_keys.json` is generated at first boot via `SetupOverlay` — this pattern is correct and must be preserved.

---

## 6. Packaging Summary

| Issue | Priority | Blocking EXE |
|---|---|---|
| No `.spec` file exists | CRITICAL | YES |
| 17+ hardcoded paths | CRITICAL | YES |
| Whisper model not bundled | HIGH | YES (offline use) |
| Ollama not bundleable | MEDIUM | NO — fallback exists |
| Playwright not bundled | MEDIUM | Partial — some actions break |
| `api_keys.json` in bundle risk | MEDIUM | NO — but must stay out |
| MetaTrader5 Windows-only | LOW | Documented limitation |
