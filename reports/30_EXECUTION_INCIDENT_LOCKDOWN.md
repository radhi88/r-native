# Report 30 — Execution Incident Lockdown

**Generated:** 2026-05-13  
**Triggered by:** Observed MT5 history — legacy/uncontrolled execution confirmed  
**Investigator:** Claude Code (lockdown audit)

---

## 1. Incident Summary

MT5 trade history shows execution from multiple uncontrolled paths that bypassed the controlled
`DecisionRouter → ConflictGuard → RiskManager → ExecutionManager → MT5Gateway` pipeline.

### Observed Trades

| Comment | Magic | Lot | Symbol(s) | Source Identified |
|---|---|---|---|---|
| `FRIDAY_GOV_CLOSE` | 20260507 | 1.0 | XAUUSDm | `friday_demo_position_governor_v2.py` |
| `FRIDAY_TOUCH_pro` | 20260505 | 0.01 | XAUUSDm | `friday_touch_demo_executor.py` |
| *(no comment)* | 0 | 0.1, 1.0 | XAUUSDm, AUDUSDm | **UNKNOWN — likely MT5 native EA** |

---

## 2. Source Identification

### FRIDAY_GOV_CLOSE / magic 20260507

- **Script:** `friday_demo_position_governor_v2.py` (root directory)
- **Evidence:**
  - Archived file line 986: `parser.add_argument("--magic", type=int, default=20260507)`
  - Archived file line 551: `"comment": "FRIDAY_GOV_CLOSE"`
  - Governor v2 log files in `position_governor_logs/`:
    - `governor_v2_20260505_021929.jsonl` through `governor_v2_20260506_020356.jsonl`
  - `friday_trade_outcome_learner.log` records multiple trades at magic=20260507 on XAUUSDm
- **Lot size:** The governor closes at the original position volume — the 1.0 lot was the pre-existing position size, not the governor's own lot
- **Scope:** Script managed positions with magic_values `{20260504, 20260505, 20260506, 20260507}`
- **Stub applied:** 2026-05-13 03:28 — file is now a safe stub with `LEGACY_EXECUTOR_DISABLED = True`

### FRIDAY_TOUCH_pro / magic 20260505

- **Script:** `friday_touch_demo_executor.py` (root directory)
- **Evidence:**
  - Archived file line 1222: `magic = 20260505` (hardcoded)
  - Archived file line 1058: `"comment": f"FRIDAY_TOUCH_{plan.sl_mode}"` → sl_mode="pro" → `FRIDAY_TOUCH_pro`
  - `friday_trade_outcome_learner.log` lines 267–348: `unknown_execution:magic=20260505` on XAUUSDm — multiple LEARNED WIN/LOSS entries
  - Active timeframes: M1, M5, M15 (M1/M5 weighted highest by TF_WEIGHTS)
- **Stub applied:** 2026-05-13 03:28 — file is now a safe stub

### Magic = 0 trades (0.1 and 1.0 lot) — UNRESOLVED

- **Not from any Python script** — all Python execution paths set an explicit magic number
- **Most likely source:** A MetaTrader Expert Advisor (MQL5 EA) running natively in the MT5 terminal, OR manual trades placed through the MT5 terminal UI
- **Cannot be confirmed stopped** without inspecting the MT5 terminal's Expert Advisors tab
- **This is an open risk**

---

## 3. Running Python Processes

**Query time:** 2026-05-13 (this session)  
**Result:** `Get-Process python*` returned no output — **no Python processes running**

No FRIDAY components are currently active in Python.

---

## 4. Config Verification

**Config file:** `C:\Users\Radhi\MT5\config\trading_runtime.yaml`

| Field | Required | Actual | Status |
|---|---|---|---|
| `runtime.kill_switch` | `true` | `true` | ✅ PASS |
| `runtime.allow_live_trading` | `false` | `false` | ✅ PASS |
| `runtime.mode` | `DRY_RUN_LOCKED` | `DRY_RUN` | ⚠️ PARTIAL — `DRY_RUN_LOCKED` is not a defined mode; `DRY_RUN` + `kill_switch: true` is functionally equivalent |

**Additional protections verified:**
- `ExecutionManager.send_order()` calls `is_kill_switch()` before every MT5 order — returns blocked if true
- `ExecutionManager.cancel_pending_order()` also checks kill_switch
- `RiskManager` checks kill_switch before any approval
- `LIVE_TRADING_ENABLED = False` in `src/mt5_ai/config.py` (line 138)

**Config verdict:** The ExecutionManager pipeline is hardlocked. `kill_switch: true` blocks all orders through the controlled path.

---

## 5. Legacy Executor Stub Verification

All 8 legacy executor files patched on **2026-05-13 03:28** (by `disable_legacy_executors_hard.py`):

| File | Stub Applied | Proof |
|---|---|---|
| `friday_demo_position_governor.py` | ✅ | `LEGACY_EXECUTOR_DISABLED = True`; raises `SystemExit` on run |
| `friday_demo_position_governor_v2.py` | ✅ | `LEGACY_EXECUTOR_DISABLED = True`; raises `SystemExit` on run |
| `friday_realtime_scalper_demo_executor.py` | ✅ | `LEGACY_EXECUTOR_DISABLED = True`; raises `SystemExit` on run |
| `friday_touch_demo_executor.py` | ✅ | `LEGACY_EXECUTOR_DISABLED = True`; raises `SystemExit` on run |
| `friday_risk_close.py` | ✅ | `LEGACY_EXECUTOR_DISABLED = True`; raises `SystemExit` on run |
| `scripts/ict_sweep_trader.py` | ✅ | `LEGACY_EXECUTOR_DISABLED = True`; raises `SystemExit` on run |
| `scripts/mt5_ollama_trader.py` | ✅ | `LEGACY_EXECUTOR_DISABLED = True`; raises `SystemExit` on run |

**Originals archived to:**
`src/mt5_ai/archive/legacy_executors_disabled_20260513_032812/`

No stub contains any MT5 order-send logic. Running any stub raises `SystemExit` immediately.

---

## 6. Log Search Results

Search terms: `FRIDAY_GOV_CLOSE`, `FRIDAY_TOUCH_pro`, `20260507`, `20260505`, `XAUUSDm`, `AUDUSDm`

### FRIDAY log directory (`AppData/Local/FRIDAY/`)

| Term | Found | Location |
|---|---|---|
| `FRIDAY_GOV_CLOSE` | NOT in FRIDAY logs | Only in archived Python source code |
| `FRIDAY_TOUCH_pro` | NOT in FRIDAY logs | Only in archived Python source code |
| `20260507` | Only in `magic_registry.py` LEGACY_MAGICS set | Registered as inactive legacy magic |
| `20260505` | Only in `magic_registry.py` LEGACY_MAGICS set | Registered as inactive legacy magic |
| `XAUUSDm` | `active_genomes.json`, `algory_runner.log` | Expected — Algory genome, paper mode |
| `AUDUSDm` | `active_genomes.json`, `active_genomes.bak.*.json` | Expected — Algory genome coverage |

### Project-wide search (non-.venv, non-archive)

`20260505` and `20260507` found in:
- `friday_trade_outcome_learner.log` — historical learning records (read-only learning data)
- `friday_capital_brain.py`, `friday_feature_outcome_learner.py` — learner filtering logic
- `src/mt5_ai/core/magic_registry.py` — LEGACY_MAGICS set (for learner filtering only)
- `friday_gene_performance_report.json`, `friday_risk_memory_rules.json` — historical performance records
- `.jarvis_agents/friday_genome_development_status.json` — historical genome status

None of these are execution paths. All references to legacy magic numbers are in learner/reporting code that reads trade history — not in code that places orders.

---

## 7. Algory Runner — Last Known State

```
Last log entry: 2026-05-13 00:44:10
Mode at startup: paper=True
Open positions: 0 (heartbeat: "0 open")
Genomes active: 40
Trading hours: M1/M5 07:00-20:00 UTC, M15 06:00-20:00 UTC, H1/H4 04:00-20:00/23:00 UTC
```

The algory_runner was last running in **paper mode** (no real MT5 orders). It is now offline (no Python processes). Last real activity: 2026-05-13 00:44 UTC.

---

## 8. Outstanding Risks

| Risk | Severity | Status |
|---|---|---|
| Legacy Python executors re-running | HIGH | ✅ MITIGATED — stubs block execution |
| Algory runner sending real orders | HIGH | ✅ MITIGATED — paper=True + kill_switch=true |
| LIVE_TRADING_ENABLED re-enabled | HIGH | ✅ MITIGATED — currently False |
| Magic=0 trades from unknown MT5 EA | HIGH | ❌ UNRESOLVED — source not identified |
| Current open positions unknown | MEDIUM | ❌ UNRESOLVED — no MT5 connection available |
| Mode not `DRY_RUN_LOCKED` (undefined enum) | LOW | ⚠️ PARTIAL — functionally blocked by kill_switch |

---

## 9. Required Actions Before Any Restart

1. **Identify and disable the MT5 native EA** responsible for magic=0 trades (inspect MT5 terminal → Expert Advisors tab → disable all EAs)
2. **Verify current open positions** via MT5 terminal or Python script before unlocking
3. **Close all open positions** if any remain from legacy execution paths
4. **Upgrade `DRY_RUN` to `DRY_RUN_LOCKED`** as a mode once defined in config_loader.py (or document that `DRY_RUN` + `kill_switch: true` is the equivalent)
5. **Never run `friday_orchestrator.py` or `start_friday_trading_full.ps1`** without explicit per-session authorization

---

## Final Status

```
INCIDENT_STATUS = ACTIVE_RISK_REMAINS
```

**Reason:** The source of magic=0 trades (0.1 and 1.0 lot, symbols XAUUSDm and AUDUSDm) is unidentified
and cannot be confirmed stopped. Current MT5 open positions cannot be verified without a live MT5
connection. The Python-side is locked down, but the MT5 terminal itself is not audited.
