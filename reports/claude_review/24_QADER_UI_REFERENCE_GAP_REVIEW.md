# Report 24 — Qader UI Reference Gap Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Scope:** Current GUI state vs. required QADER_LIVE_AUTOPILOT UI specification

---

## 1. Current GUI State

**Entry point:** `src/qader_app/main.py` → `MainWindow` (PyQt6, 1200×760)

**Tabs:**
| Tab | Current Content |
|---|---|
| Dashboard | 4 labels (status, MT5, mode, safety) + Emergency Stop button |
| Market scanner | ScannerView — basic scan trigger |
| Qader assistant | AssistantView — text input + voice toggle |
| Symbols | SymbolSelectorView |
| Permissions | PermissionsView |
| Logs | LogsView |
| Settings | SettingsView |

**DashboardView current:**
```
status_label: "Qader status: ready"
mt5_label:    "MT5: not checked"
mode_label:   "Mode: observe_only"
safety_label: "Safety: DRY_RUN_ONLY"
emergency_button: "Emergency Stop"
```

This is a minimal placeholder. The dashboard has no live data, no account panel, no status badge, no risk meter, no scanner results table, no strategy panel.

---

## 2. Required UI Panels (Gap Analysis)

### 2.1 Live Autopilot Status Badge — MISSING

Priority: CRITICAL  
The user must always know at a glance whether Qader is trading live or locked.

Required widget: A large, high-contrast status indicator:
```
┌─────────────────────────────────────┐
│  ⚡ LIVE AUTOPILOT ENABLED           │  ← background: dark red, text: bright red
│     EURUSDm M5 | Balanced            │
└─────────────────────────────────────┘
```
or:
```
┌─────────────────────────────────────┐
│  🔒 LIVE LOCKED — DRY RUN ONLY      │  ← background: dark green, text: green
└─────────────────────────────────────┘
```

This badge must update live without requiring tab navigation.

---

### 2.2 Live Unlock Wizard — MISSING

Priority: CRITICAL  
The multi-step unlock sequence for QADER_LIVE_AUTOPILOT does not exist as a UI flow.

Required: A modal dialog or dedicated panel with 6 steps:

**Step 1 — Real Account Information**
- Connect to MT5 and display:
  - Login number, Server name
  - Balance (USD), Equity (USD), Margin (USD), Leverage (e.g. 1:100)
  - Open positions count, Pending orders count
- User confirms this is the correct account before proceeding
- Reject if MT5 not connected

**Step 2 — Lockdown Verification**
- Run `verify_mt5_lockdown.py` logic inline (same as the script)
- Show: "Account is CLEAN (0 positions, 0 pending orders)" in green
- Show: "FAILED — external positions exist" in red with details
- Proceed only if exit_code == 0

**Step 3 — Risk Acceptance Phrase**
- Large text field:
  ```
  Type exactly: I ACCEPT REAL TRADING RISK
  ```
- Disabled "Next" button until phrase matches exactly
- Red border on mismatch

**Step 4 — Risk Profile Selection**
- Radio group:
  - ○ Conservative (0.25% per trade, max 1% daily loss, 1 position)
  - ○ Balanced (0.50% per trade, max 2% daily loss, 1 position)  ← recommended
  - ○ Aggressive (1.00% per trade, max 3% daily loss, 2 positions)
  - ○ Extreme (2.00% per trade, max 5% daily loss, 3 positions)
- Warning panel for Aggressive/Extreme: "Higher risk levels can result in significant account losses."

**Step 5 — Symbol and Timeframe Selection**
- Multi-select checkboxes from symbols in `trading_runtime.yaml`
- Timeframe checkboxes
- Must select at least one symbol and one timeframe

**Step 6 — Final Confirmation**
- Summary of all selected parameters
- Max daily loss and session loss values displayed
- "UNLOCK LIVE AUTOPILOT" button — calls `PermissionsStore.unlock_real_controlled_mode()`

---

### 2.3 Real Account Panel — MISSING

Priority: HIGH  
Required on Dashboard or in a persistent sidebar:

```
╔══════════════════════════════════════╗
║  ACCOUNT                             ║
║  Login:   12345678                   ║
║  Server:  ExnessReal-MT5-3           ║
║  Balance: $10,250.00                 ║
║  Equity:  $10,185.50   ↓ -0.63%     ║
║  Margin:  $125.00                    ║
║  Free:    $10,060.50                 ║
║  Leverage: 1:500                     ║
║  Open:    1 position                 ║
╚══════════════════════════════════════╝
```

This updates on every cycle. Shows equity change % vs. session start equity.

---

### 2.4 Live Risk Meter — MISSING

Priority: HIGH  
A visual progress bar showing current daily loss % vs. limit:

```
Daily Risk:  ████░░░░░░░░░░░░  1.2% / 2.0% limit
Session:     ██░░░░░░░░░░░░░░  0.4% / 1.0% limit
```

Color: green → yellow (≥ 50% of limit) → red (≥ 80% of limit)

Auto-stop triggers at 100% (daily loss limit reached).

---

### 2.5 Market Scanner Table — MINIMAL (needs expansion)

Current scanner returns `MarketScanResult` with basic fields. Required scanner table columns:

| Symbol | TF | Bias | Signal | Filter | Arbiter | Conf | Opp Score | Risk | Action | SL | TP | Lot | Reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

Current `MarketScanResult` has: symbol, timeframe, fractal_result, smc_result, ict_result, arbiter_result, confidence, reason, risk_status, spread, atr, final_action.

Missing from current result: opportunity_score, recommended_lot, sl_price, tp_price, management_plan, bias_result (separate from signal).

---

### 2.6 Signal / Bias / Filter / Management Module Toggles — MISSING

Priority: HIGH  
Currently no toggle panels exist in the UI. Required panels (inspired by reference UI, no copying):

**Signal Modules Panel** (enable/disable which signals Qader uses):
```
[✓] Fractal    [✓] SMC       [✓] ICT Sweep  [ ] BB
[ ] Breakout   [ ] CCI       [ ] Engulfing   [ ] Fib
[ ] MACD       [ ] Pin Bar   [ ] RSI         [ ] Stoch
[ ] Williams   [ ] Wick Rej  [ ] 3 Soldiers
```

**Bias Modules Panel:**
```
[✓] EMA        [✓] HTF D1   [✓] Market Struct  [ ] ADX Dir
[ ] PSAR       [ ] RSI Bias  [ ] Momentum        [ ] Chandelier
[ ] Daily Mid  [ ] SMC Bias  [ ] Fractal Struct  [ ] Donchian
```

**Filter Modules Panel:**
```
[✓] Spread    [✓] Session   [✓] Volatility  [ ] ADR Exhaust
[ ] ADX Trend [ ] BB Filter  [ ] CCI Filter   [ ] Consecutive
[ ] Doji      [ ] Keltner    [ ] Receding     [ ] RSI Filter
[ ] SMA Filter [ ] Data Quality
```

**Execution Module Toggles:**
```
[✓] Market    [ ] Limit     [ ] Stop      [ ] Limit1    [ ] Limit2
```
(Only Market enabled by default for first live version — pending orders blocked)

**Management Module Toggles:**
```
[✓] Breakeven      [✓] EOD Close      [ ] Partial TP
[ ] SL Lock        [ ] SL Reduce      [ ] Trailing Stop
[ ] Opp Signal Exit [✓] Session Exit
```

These toggle states must be stored in the active genome under the `signals`, `bias`, `filters`, `management`, `execution` JSON keys.

---

### 2.7 Strategy DNA Panel — MISSING

Priority: MEDIUM  
A panel showing the current active genome at a glance:

```
╔══════════════════════════════════════╗
║  ACTIVE STRATEGY DNA                 ║
║  ID:         qader_v3_balanced       ║
║  Version:    12                      ║
║  Generation: 3                       ║
║  Status:     ● ACTIVE                ║
║                                      ║
║  Confidence: arbiter 0.72 | min 0.48 ║
║  ATR mult:   SL×1.5  TP×2.0          ║
║  Weights:    Fractal 0.45 SMC 0.45   ║
║                                      ║
║  Trades:     47  WR: 62%  PF: 1.45   ║
║  Score:      0.74                    ║
╚══════════════════════════════════════╝
[Apply DNA Proposal]  [Rollback DNA]
```

---

### 2.8 Campaign / Backtest Results Panel — MISSING

Priority: MEDIUM  
A panel for strategy population management:

```
Portfolio (Active Strategies)
┌─────────────────────────────────────────────────────────┐
│ ID            Gen  Status     WR    PF    DD%   Score   │
│ qader_v3_bal   3   ● ACTIVE  62%  1.45  2.3%  0.74    │
│ qader_v4_agg   4   ○ CAND.   54%  1.21  3.1%  0.51    │
│ qader_v2_con   2   × RETRD   38%  0.95  4.5%  -0.12   │
└─────────────────────────────────────────────────────────┘
[Run Campaign]  [Promote Candidate]  [Retire Strategy]
```

---

### 2.9 Limited Resolution Data Warning — MISSING

Priority: MEDIUM  
When MT5 returns fewer bars than required for reliable analysis or backtesting:

```
╔═══════════════════════════════════════════════════════╗
║  ⚠️  LIMITED RESOLUTION DATA — EURUSDm M1              ║
║  Only 152 bars returned (minimum: 200)                ║
║                                                       ║
║  To fix:                                              ║
║  1. Open MetaTrader 5                                 ║
║  2. Tools > Options > Charts                          ║
║  3. Set "Max bars in chart" to Unlimited              ║
║  4. Restart MT5 and wait 2–3 minutes                  ║
║  5. Re-run campaign or scanner                        ║
╚═══════════════════════════════════════════════════════╝
```

---

### 2.10 Control Buttons — PARTIALLY EXISTS

The following control buttons must exist in the live autopilot UI:

| Button | Status | Notes |
|---|---|---|
| Emergency Stop | ✅ EXISTS | Connected to kill_switch via RunnerService |
| Unlock Live Autopilot | ❌ MISSING | Triggers LiveUnlockWizard |
| Lock Live Autopilot | ❌ MISSING | Calls PermissionsStore.lock_real_controlled_mode() |
| Pause Scanner | ❌ MISSING | Pauses scan loop without locking |
| Pause New Entries | ❌ MISSING | Continue managing positions, no new entries |
| Manage Open Positions | ❌ MISSING | Show position management panel |
| Close All Qader Positions | ❌ MISSING | Close all positions with QADER_RC magic |
| Export Audit Log | ❌ MISSING | Export logs/qader_audit.jsonl |
| Run Campaign | ❌ MISSING | Trigger genetic optimizer |
| Apply DNA Proposal | ❌ MISSING | Approve pending mutation |
| Rollback DNA | ❌ MISSING | Trigger rollback_to_default() |

---

### 2.11 Voice Integration Into qader_app — MISSING

The `qader_app` has `QaderVoice` and `QaderBrain` referenced in `main_window.py`, but these are lightweight wrappers (not the full Gemini Live voice system from `mark_xxxix/`). Voice commands in `qader_app` should support:

- "Scan the market" → triggers `ScannerService.scan_symbols()`
- "What is the current risk?" → returns RiskGovernor status
- "Emergency stop" → triggers `MainWindow.emergency_stop()`
- "Pause entries" → sets pause flag in LiveAutopilotService
- "What is the strategy score?" → returns EvaluationEngine.summarize()
- "قادر، أوقف التداول" (Arabic) → emergency stop

Voice MUST NOT be able to:
- Unlock live autopilot
- Change risk profile
- Apply DNA mutations
- Close positions directly

---

## 3. UI Style Guide (for Codex)

The dashboard must use a dark cyber terminal aesthetic:
- Background: `#000d12` (very dark teal-black)
- Primary accent: `#00ffd5` or `#00e5ff` (cyan/teal)
- Live autopilot active: `#ff3355` (red alert)
- Locked/safe: `#00c853` (green)
- Warning: `#ff9800` (orange)
- Text: `#8ffcff`
- Font: `Courier New` or `JetBrains Mono` for terminal feel
- No rounded corners on table cells (sharp cyber grid)
- All critical numbers displayed in monospace

Do NOT copy any specific UI from third-party software. Use these colors and conventions as independent design choices.

---

## 4. Gap Summary Table

| UI Component | Status | Priority |
|---|---|---|
| Live status badge (LIVE/LOCKED) | ❌ MISSING | CRITICAL |
| Live unlock wizard (6 steps) | ❌ MISSING | CRITICAL |
| Real account panel | ❌ MISSING | HIGH |
| Live risk meter | ❌ MISSING | HIGH |
| Signal module toggles (19) | ❌ MISSING | HIGH |
| Bias module toggles (14) | ❌ MISSING | HIGH |
| Filter module toggles (15) | ❌ MISSING | HIGH |
| Execution module toggles (5) | ❌ MISSING | HIGH |
| Management module toggles (8) | ❌ MISSING | HIGH |
| Scanner results table (expanded) | ⚠️ PARTIAL | HIGH |
| Strategy DNA panel | ❌ MISSING | MEDIUM |
| Campaign / population panel | ❌ MISSING | MEDIUM |
| Limited resolution warning | ❌ MISSING | MEDIUM |
| Emergency stop button | ✅ EXISTS | — |
| Unlock live autopilot button | ❌ MISSING | CRITICAL |
| Lock/pause controls | ❌ MISSING | HIGH |
| Export audit log | ❌ MISSING | MEDIUM |
| DNA apply / rollback buttons | ❌ MISSING | MEDIUM |
| Voice integration | ⚠️ PARTIAL | MEDIUM |
| Tab: Dashboard (content) | ⚠️ PLACEHOLDER | CRITICAL |
| Tab: Scanner (expanded) | ⚠️ PARTIAL | HIGH |
| Window title "Qader - قادر" | ✅ EXISTS | — |
