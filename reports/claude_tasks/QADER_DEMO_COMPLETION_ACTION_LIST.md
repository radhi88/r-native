# QADER DEMO COMPLETION — ACTION LIST FOR CODEX
**Author:** Claude (Supervisor)  
**Date:** 2026-05-14  
**Based on Reviews:** 30, 31, 32, 33, 34

This list is sorted by priority. All items must be applied to Qader source files only (not FRIDAY/algory files). Do not modify active FRIDAY executors.

---

## CRITICAL — Must fix before any demo trade can happen

---

### A-32-01 — Fix `one_market_order_per_run` to allow multi-cycle trading

**Priority:** CRITICAL  
**File:** `src/mt5_ai/core/execution_manager.py`  
**Issue:** `_real_orders_sent_this_run` is never reset between cycles in the realtime loop. After the first order, all subsequent orders are blocked permanently.

**Exact change:**

In `ExecutionManager.validate_real_controlled_request()`, replace the gate:
```python
# CURRENT (line 99):
self._gate(gates, "one_market_order_per_run",
           self._real_orders_sent_this_run == 0,
           f"sent_this_run={self._real_orders_sent_this_run}")
```
With a per-cycle check using a cycle-level counter instead of a run-level counter. The run-level counter should remain for audit purposes but the gate should be driven by config:
```python
max_orders_per_run = int(cfg.get("execution", {}).get("max_market_orders_per_run", 1) or 1)
self._gate(gates, "max_orders_per_run_not_exceeded",
           self._real_orders_sent_this_run < max_orders_per_run,
           f"sent_this_run={self._real_orders_sent_this_run},max={max_orders_per_run}")
```

**Also in `real_time_loop_service.py`:** Add `exec_mgr.reset_real_controlled_run()` at the START of each scan cycle (not just at loop start):
```python
# In _scan_symbol_cycle(), before attempting execution:
exec_mgr.reset_real_controlled_run()
```

**Config change needed in `config/real_controlled_mode.yaml`:**
```yaml
execution:
  max_market_orders_per_run: 3  # was 1 — allow up to 3 demo trades
```

**Safe to apply now:** YES

---

### A-32-02 — Raise max_open_positions to 3 and fix the gate logic

**Priority:** CRITICAL  
**File:** `src/mt5_ai/core/execution_manager.py` + `config/real_controlled_mode.yaml`

**Fix 1 — Gate logic bug (`execution_manager.py:179`):**
```python
# CURRENT (wrong):
self._gate(gates, "open_positions_clean",
           len(positions) == 0 and len(positions) < max_open, ...)

# FIX:
self._gate(gates, "open_positions_clean",
           len(positions) < max_open,
           f"open_positions={len(positions)},max={max_open}")
```

**Fix 2 — Config:**
```yaml
# config/real_controlled_mode.yaml
risk:
  max_open_positions: 3  # was 1

execution:
  max_market_orders_per_run: 3  # was 1
```

**Safe to apply now:** YES

---

### A-32-03 — Remove premature `break` in `start_real_controlled_run()`

**Priority:** CRITICAL  
**File:** `src/qader_app/services/real_mode_service.py:291`

```python
# CURRENT (stops after first order):
if result.get("order") or (result.get("success") and not result.get("simulated")):
    break

# FIX: Allow multiple orders per run up to max_cycles
# Remove the break, or only break after N successful orders match config limit:
orders_placed = sum(1 for r in results if r.get("success") and not r.get("simulated"))
if orders_placed >= max_orders_per_run:
    break
```

**Safe to apply now:** YES

---

### A-30-01 — Add startup and crash logging to `_run_loop()`

**Priority:** CRITICAL  
**File:** `src/qader_app/services/real_time_loop_service.py`

**Issue:** `logs/qader_realtime_loop.jsonl` does not exist because the loop may be crashing before any write.

**Add before the `while` loop:**
```python
self._write_loop_log({
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "event": "loop_start",
    "symbols": selected_symbols,
    "timeframes": selected_timeframes,
    "interval_seconds": interval,
    "loop_state": self.state,
})
```

**Add in the `except Exception as exc:` handler:**
```python
self._write_loop_log({
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "event": "loop_exception",
    "error": str(exc),
    "loop_state": self.BLOCKED,
})
```

**Add in the `finally:` block:**
```python
self._write_loop_log({
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "event": "loop_end",
    "cycle_count": self.cycle_count,
    "final_state": self.state,
    "reason": self.state_reason,
})
```

**Safe to apply now:** YES

---

## HIGH — Required for professional operation

---

### A-33-01 — Add auto-refresh QTimer to DashboardView

**Priority:** HIGH  
**File:** `src/qader_app/gui/dashboard.py`

**Issue:** Dashboard shows static labels. No live data from the running loop.

**Add to `DashboardView.__init__()`:**
```python
from PyQt6.QtCore import QTimer
from qader_app.services.real_time_loop_service import RealTimeLoopService

self._loop_svc: RealTimeLoopService | None = None  # set from MainWindow

# Add cycle counter and loop status labels:
self.cycle_label = QLabel("Cycles: —")
self.loop_state_label = QLabel("Loop: STOPPED")
self.last_signal_label = QLabel("Last signal: —")
self.positions_label = QLabel("Open positions: —")

# Add to layout

self._refresh_timer = QTimer(self)
self._refresh_timer.setInterval(3000)  # every 3 seconds
self._refresh_timer.timeout.connect(self._auto_refresh)
self._refresh_timer.start()
```

**Add `_auto_refresh()` method:**
```python
def _auto_refresh(self) -> None:
    if self._loop_svc is None:
        return
    status = self._loop_svc.status()
    state = status.get("state", "UNKNOWN")
    color_map = {
        "RUNNING": "#059669", "ARMING": "#d97706",
        "PAUSED": "#6b7280", "BLOCKED": "#dc2626",
        "EMERGENCY_STOP": "#111827", "STOPPED": "#374151",
    }
    color = color_map.get(state, "#374151")
    self.loop_state_label.setText(f"Loop: {state}")
    self.loop_state_label.setStyleSheet(f"color:{color};font-weight:700;")
    self.cycle_label.setText(f"Cycles: {status.get('cycle_count', 0)}")
    self.last_signal_label.setText(f"Signal: {status.get('last_signal','—')} → {status.get('last_decision','—')}")
```

**In `MainWindow.__init__()`:**
```python
from qader_app.services.real_time_loop_service import RealTimeLoopService
self.realtime_loop = RealTimeLoopService()
self.dashboard._loop_svc = self.realtime_loop
```

**Safe to apply now:** YES

---

### A-33-02 — Add color coding and live confidence to ScannerView

**Priority:** HIGH  
**File:** `src/qader_app/gui/scanner_view.py`

**Add color coding to `set_rows()`:**
```python
from PyQt6.QtGui import QColor, QBrush

def set_rows(self, rows: list[dict]) -> None:
    self.table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, key in enumerate(self.HEADERS):
            item = QTableWidgetItem(str(row.get(key, "")))
            if key == "arbiter_result":
                val = str(row.get(key, ""))
                if val == "BUY":
                    item.setBackground(QBrush(QColor("#d1fae5")))
                elif val == "SELL":
                    item.setBackground(QBrush(QColor("#fee2e2")))
            if key == "final_action" and str(row.get(key,"")) in ("BUY","SELL"):
                item.setBackground(QBrush(QColor("#fef3c7")))
            self.table.setItem(r, c, item)
    self.table.resizeColumnsToContents()
```

**Add auto-refresh toggle:**
```python
self.auto_refresh_toggle = QCheckBox("Auto-refresh every 5s")
self._auto_timer = QTimer(self)
self._auto_timer.setInterval(5000)
self._auto_timer.timeout.connect(self.scan_now)
self.auto_refresh_toggle.stateChanged.connect(
    lambda s: self._auto_timer.start() if s else self._auto_timer.stop()
)
```

**Safe to apply now:** YES

---

### A-33-03 — Add open positions table to DashboardView

**Priority:** HIGH  
**File:** `src/qader_app/gui/dashboard.py`

Add a `QTableWidget` with columns: Symbol, Side, Lot, Open Price, Current PnL, SL, Magic.
Populate it via `mt5.positions_get()` in the `_auto_refresh()` method.

**Safe to apply now:** YES

---

### A-33-04 — Upgrade LogsView to show realtime loop log

**Priority:** HIGH  
**File:** `src/qader_app/gui/logs_view.py`

Add tab selector for: Audit Log / Realtime Loop / Execution Log / Arbitration Decisions.
Each tab reads from the corresponding JSONL file (last 100 lines, most recent first).
Add color code: `order_send_called=true` → green, `blocked` → red.

**Safe to apply now:** YES

---

## MEDIUM — Required for production completeness

---

### A-34-01 — Wire LearningService to RealTimeLoopService

**Priority:** MEDIUM  
**File:** `src/qader_app/services/real_time_loop_service.py`

See full code sample in Review 34. Batch-collect cycle decisions every 10 cycles and call `learning_svc.collect_and_propose()`. Log the proposal to the loop log. Do NOT auto-apply — keep `requires_approval=True`.

**Safe to apply now:** YES

---

### A-31-01 — Add `continue_after_hold: true` to real_controlled_mode.yaml explicitly

**Priority:** MEDIUM  
**File:** `config/real_controlled_mode.yaml`

Current behavior relies on Python default. Make it explicit:
```yaml
realtime_loop_enabled: true
loop_interval_seconds: 1
continue_after_hold: true
continue_after_blocked_cycle: true
continue_after_order_send: true
manage_open_positions: true
heartbeat_interval_seconds: 5
max_data_failures_before_block: 60
```

**Safe to apply now:** YES

---

### A-33-05 — Create Qader web dashboard for live charts

**Priority:** MEDIUM  
**File:** New file `web/qader/index.html` + server in `src/qader_app/services/web_server_service.py`

Minimum viable: lightweight aiohttp server (or Flask) serving `qader_realtime_loop.jsonl` as JSON endpoint. HTML page polls every 2 seconds and renders:
- Cycle count
- Loop state badge
- Last 20 signals in a scrollable table (color coded)
- Account equity in a number block

**Safe to apply now:** YES (low risk, new files only)

---

## LOW — Polish items

---

### A-30-02 — Add `heartbeat_interval_seconds` to real_controlled_mode.yaml explicitly

**Priority:** LOW  
**File:** `config/real_controlled_mode.yaml`

```yaml
heartbeat_interval_seconds: 5
```

Currently relies on Python default of 5. Make explicit.

**Safe to apply now:** YES

---

## Completion Proof Requirements

When Codex marks this list complete, the following artifacts MUST exist and be provided:

| # | Artifact | Minimum Acceptable |
|---|---|---|
| 1 | `logs/qader_realtime_loop.jsonl` | File exists, ≥ 10 cycle entries, ≥ 1 `"event":"loop_start"` |
| 2 | 3 successful demo trades | `logs/execution_log.jsonl` has ≥ 3 entries with `magic=20260514, success=true, retcode=10009` |
| 3 | Position management proof | At least 1 close entry in `logs/execution_log.jsonl` with `action=CLOSE, magic=20260514` |
| 4 | UI screenshot or description | Dashboard shows: state label (colored), cycle count, last signal, positions table |
| 5 | DNA learning journal | `dna/performance_journal.jsonl` has entries from loop cycles |
| 6 | No source code modified by DNA | Confirm `dna/active_genome.json` changed, no `.py` files changed |

---

## Summary Table

| ID | Description | Priority | Safe Now |
|----|-------------|----------|----------|
| A-32-01 | Fix `one_market_order_per_run` gate + reset between cycles | CRITICAL | YES |
| A-32-02 | Fix `open_positions_clean` gate logic + raise max to 3 | CRITICAL | YES |
| A-32-03 | Remove premature `break` in `start_real_controlled_run()` | CRITICAL | YES |
| A-30-01 | Add startup/crash logging to `_run_loop()` | CRITICAL | YES |
| A-33-01 | Add auto-refresh QTimer to DashboardView | HIGH | YES |
| A-33-02 | Add color coding + auto-refresh to ScannerView | HIGH | YES |
| A-33-03 | Add open positions table to Dashboard | HIGH | YES |
| A-33-04 | Upgrade LogsView to show multiple log sources | HIGH | YES |
| A-34-01 | Wire LearningService to RealTimeLoopService | MEDIUM | YES |
| A-31-01 | Add explicit loop config keys to real_controlled_mode.yaml | MEDIUM | YES |
| A-33-05 | Create Qader web dashboard | MEDIUM | YES |
| A-30-02 | Add heartbeat_interval_seconds to config explicitly | LOW | YES |
