# Review 33 — Professional UI Review
**Reviewer:** Claude (Supervisor)  
**Date:** 2026-05-14  
**Scope:** Requirements 11, 12 — Professional interactive panels; HTML/JS dashboard if PyQt6 insufficient.

---

## Summary Verdict: ❌ INCOMPLETE — UI exists but is not professional. No Qader-specific HTML dashboard.

---

## Current UI Inventory

### Application entry point
`src/qader_app/main.py` — launches PyQt6 `MainWindow`

### Tab structure (8 tabs)
| Tab | Widget | Assessment |
|-----|---------|------------|
| Dashboard | `DashboardView` | ❌ Basic — 4 labels + 1 button |
| Market scanner | `ScannerView` | ⚠️ Functional but static table |
| Qader assistant | `AssistantView` | Not reviewed in this pass |
| Symbols | `SymbolSelectorView` | Not reviewed in this pass |
| Permissions | `PermissionsView` | Not reviewed in this pass |
| REAL CONTROLLED MODE | `RealControlledModeView` | ✅ Most complete — multi-button form |
| Logs | `LogsView` | ❌ Raw text dump only |
| Settings | `SettingsView` | Not reviewed in this pass |

---

## Detailed Panel Reviews

### DashboardView — `src/qader_app/gui/dashboard.py`

**Code:**
```python
self.status_label = QLabel("Qader status: ready")
self.mt5_label = QLabel("MT5: not checked")
self.mode_label = QLabel("Mode: observe_only")
self.safety_label = QLabel("Safety: DRY_RUN_ONLY")
self.emergency_button = QPushButton("Emergency Stop")
```

**Missing:**
- Live cycle counter (shows how many loops have run)
- Last signal display (BUY/SELL/HOLD with direction color)
- Open positions table (symbol, side, PnL, SL distance)
- Account equity / balance line
- Auto-refresh timer (currently no QTimer anywhere in dashboard)
- Spread live display
- ATR live display

**Verdict:** ❌ Not professional. This is a skeleton/placeholder.

---

### ScannerView — `src/qader_app/gui/scanner_view.py`

**Code:**
```python
self.scan_button = QPushButton("Scan selected symbols")
self.table = QTableWidget(0, len(self.HEADERS))
```

**What it shows when scanned:** 11 columns: symbol, timeframe, fractal_result, smc_result, arbiter_result, confidence, risk_status, spread, atr, final_action, reason.

**Missing:**
- Auto-refresh (requires user to click button each time)
- Color coding (BUY=green, SELL=red, HOLD=gray)
- Confidence bar/progress indicator
- No timestamp on last scan
- No integration with `RealTimeLoopService` — loop results don't appear here automatically

**Verdict:** ⚠️ Functional for manual single-scan. Not a live professional scanner.

---

### RealControlledModeView — `src/qader_app/gui/real_controlled.py`

**Code summary:**
- Account info form with 7 fields (login, server, balance, equity, margin, open_positions, pending_orders)
- Typed unlock phrase field
- Auto-start toggle
- 7 buttons: Refresh, Lockdown check, Unlock, Validation only, Arm+Start, Lock, Emergency
- Live execution log via `QPlainTextEdit`

**Verdict:** ✅ Functional professional panel. Sufficient for its purpose.

**Missing:**
- No auto-refresh of account info
- No loop status display (cycle count, state, last signal) from `RealTimeLoopService`
- No visual indicator that loop is running vs stopped

---

### LogsView — `src/qader_app/gui/logs_view.py`

**Code:**
```python
self.refresh_button = QPushButton("Refresh audit log")
self.output = QPlainTextEdit()  # reads last 200 audit entries
```

**Missing:**
- No filtering by action type
- No color highlighting
- No `qader_realtime_loop.jsonl` display (only audit log)
- No arbitration decisions log display
- No execution log display
- Manual refresh only

**Verdict:** ❌ Not professional. This is a debug dump.

---

## REQUIREMENT 11: Professional Interactive Panels

**Status:** ❌ HIGH FAIL

**Deficiency list:**

| # | Missing Feature | Severity |
|---|---|---|
| 1 | Live cycle counter updating automatically | HIGH |
| 2 | Color-coded signal direction (BUY=green/SELL=red) | HIGH |
| 3 | Open positions table with live PnL | HIGH |
| 4 | Auto-refresh QTimer on dashboard (every 2-5 seconds) | HIGH |
| 5 | Loop state indicator (RUNNING/STOPPED/BLOCKED in bold color) | HIGH |
| 6 | Last signal timestamp with direction | MEDIUM |
| 7 | Spread and ATR live display | MEDIUM |
| 8 | Equity curve chart (pyqtgraph or simple QProgressBar) | MEDIUM |
| 9 | ScannerView auto-refresh toggle | MEDIUM |
| 10 | Log view filtering and color coding | LOW |

**Priority:** HIGH  
**File:** `src/qader_app/gui/dashboard.py`, `src/qader_app/gui/scanner_view.py`, `src/qader_app/gui/logs_view.py`  
**Issue:** Dashboard has no live data, no auto-refresh, no visual state.  
**Risk:** System appears inert. No operator can monitor the loop from the UI.  
**Recommendation for Codex:**

**Minimum changes to reach "professional" bar:**

1. Add `QTimer` to `DashboardView` that fires every 3 seconds and calls `refresh_status()`.
2. Update `refresh_status()` to pull `RealTimeLoopService.status()` and display: state (colored label), cycle_count, last_cycle_time, last_signal, last_decision, last_block_reason.
3. Add color styling: RUNNING=green, BLOCKED=red, STOPPED=gray on the state label.
4. Add a `QTableWidget` to `DashboardView` showing open MT5 positions (symbol, side, PnL).
5. Add signal direction badge: BUY badge in green, SELL in red, HOLD in gray.

**Safe to apply now:** YES

---

## REQUIREMENT 12: HTML/JS Dashboard if PyQt6 Insufficient

**Status:** ❌ NOT IMPLEMENTED FOR QADER

**What exists:**
```
web/jarvis/index.html    — FRIDAY's Jarvis assistant UI
web/jarvis/app.js
web/live_insight/index.html — FRIDAY's live insight (fractal monitor UI)
web/live_insight/app.js
```

**None of these connect to `RealTimeLoopService`**, `qader_realtime_loop.jsonl`, or any Qader component. They are FRIDAY's old web UIs.

**No web server is started** that would serve Qader loop data. No `aiohttp` or `flask` server for Qader.

**Priority:** MEDIUM  
**File:** N/A (needs new file)  
**Issue:** If live charts (candlestick, equity curve) cannot be achieved in PyQt6 without major dependency, a `web/qader/` HTML dashboard connected to a lightweight local HTTP server would be appropriate.  
**Risk:** Without this, the system lacks any way to show professional charts.  
**Recommendation for Codex:**  
Option A (PyQt6 only): Add `pyqtgraph` charts to `DashboardView` for price history and equity curve.  
Option B (HTML): Create `web/qader/index.html` with a simple aiohttp server that reads `logs/qader_realtime_loop.jsonl` and serves JSON to a websocket/poll endpoint. Update `src/qader_app/main.py` to start this server as a background thread.  
**Safe to apply now:** YES (start with Option A minimum viable charts)
