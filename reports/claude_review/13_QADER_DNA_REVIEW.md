# Report 13 — Qader DNA / Genome / Self-Improvement Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Scope:** Strategy DNA, genetic evolution, self-modification risk

---

## 1. Strategy DNA Engine

**File:** `src/mt5_ai/algory_dna.py`

Gene catalogue replicated from Algory factory:
- `EXEC_GENES` (4): entry type flags — market2, limit, limit2, stop
- `BIAS_GENES` (12): trend confirmation — ADX, EMA, HTF, RSI, etc.
- `SIGNAL_GENES` (14): entry triggers — BB, breakout, MACD, pin bar, etc.
- `FILTER_GENES` (11): trade qualification
- `EXIT_GENES` (5): position management

Genomes are JSON files stored on disk (not source code). Evolution modifies genome data, not `.py` files. **No source code modification occurs in the DNA/genome engine.** ✅

**Genome storage:** `C:\Users\Radhi\AppData\Local\FRIDAY\` — hardcoded path (portability issue — see Report 14).

---

## 2. Genetic Evolution

**Files:** `src/mt5_ai/genetic_evolver.py`, `src/mt5_ai/gene_fitness_db.py`, `src/mt5_ai/algory_runner.py`

Evolution operates on genome JSON files:
- Selection: fitness-weighted (Sharpe + linearity + persistence + return)
- Crossover/mutation: parameter values within gene bounds
- Purge: genomes below fitness threshold removed from pool
- Output: new genome JSON in the population directory

**Finding:** Evolution is data-only. No `.py` file is ever written by the genetic engine. The trading pipeline reads genome parameters but does not execute arbitrary code from genome files. ✅

---

## 3. Self-Improvement Mechanism

**File:** `mark_xxxix/memory/ollama_self_improvement.json`

Contains:
- `"lessons"`: 7 performance observations about model speed (text only)
- `"tool_stats"`: success/failure counts per tool (35 project_agent successes)
- `"turns"`: recent conversation history (7 entries)
- `"agents"`: architect (38 success), planner (36), coder (25) — all success rates

**The `ollama_self_improvement.json` does NOT modify source code directly.** It stores lessons as text strings that are injected into future prompts as context. Model behavior adapts based on these lessons, but no `.py` file is written by this mechanism alone.

---

## 4. CRITICAL FINDING — Project Agent Can Modify Source Files

**File:** `mark_xxxix/main.py` — `project_agent` tool  
**Priority:** HIGH

The `project_agent` tool (referenced 51 times in tool_stats with 100% success rate) is an AI-driven code editor embedded in Jarvis. It can:
- Read any file in `PROJECT_ROOT`
- Write/edit `.py`, `.yaml`, `.json` files
- Run shell commands (with `BLOCKED_COMMAND_WORDS` filter)
- Back up files to `.jarvis_backups/`

**Key settings (default = SAFE):**
```python
PROJECT_AGENT_AUTO_FIX   = False  # auto-apply fixes: OFF
PROJECT_AGENT_AUTO_WATCH = False  # auto-watch for errors: OFF
```

When `AUTO_FIX=False` and `AUTO_WATCH=False`, the project agent only runs when explicitly invoked by the user. It does not self-trigger. ✅

**However:** Once triggered by voice or text, it CAN modify `execution_manager.py`, `config_loader.py`, `trading_runtime.yaml`, or any other active runtime file. The `PROJECT_AGENT_SECRET_FILE_NAMES` set blocks `api_keys.json` but NOT `.yaml` config files. A user saying "fix the config" could result in the AI modifying `trading_runtime.yaml`.

**Risk:** If a voice command triggers `project_agent` and the AI decides to modify `trading_runtime.yaml` to enable live trading (e.g., interpreting "make trading work" as enabling DEMO mode), the safety gate would be bypassed.

**Fix:**
1. Add `trading_runtime.yaml`, `dry_run_simulation.yaml` to `PROJECT_AGENT_SECRET_FILE_NAMES`
2. Add `execution_manager.py`, `config_loader.py`, `kill_switch.py` to a blocked files list
3. Never allow voice-triggered `project_agent` to modify trading config or execution files

**Safe to apply now:** YES.

---

## 5. Self-Modification Summary

| Mechanism | Modifies Source .py | Risk |
|---|---|---|
| Genetic evolution | ❌ NO — JSON only | NONE |
| `ollama_self_improvement.json` | ❌ NO — prompt context only | NONE |
| `project_agent` tool (user-triggered) | ✅ YES — can write any file | HIGH if config files not blocked |
| `PROJECT_AGENT_AUTO_FIX=True` | ✅ YES — autonomous | CRITICAL — must remain False |
| `PROJECT_AGENT_AUTO_WATCH=True` | ✅ YES — autonomous | CRITICAL — must remain False |

**Conclusion:** Auto-modification is off by default. The risk is limited to user-triggered `project_agent` runs that could accidentally edit trading config or execution files. Block those files explicitly.
