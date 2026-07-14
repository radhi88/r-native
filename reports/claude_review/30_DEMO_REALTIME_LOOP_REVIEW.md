# Review 30 — Demo Realtime Loop Review
**Reviewer:** Claude (Supervisor)  
**Date:** 2026-05-14  
**Scope:** Requirements 1–5: Demo account, continuous loop, HOLD behavior, XAUUSDm M1 scan, log file.

---

## Summary Verdict: PARTIAL PASS — 3/5 requirements fully proven, 2 require fix

---

## REQUIREMENT 1: Demo/Trial account only

**Status:** ✅ PASS — Evidence confirmed

**Proof in logs:**
- `logs/qader_audit.jsonl` → `login=260749517, server="Exness-MT5Trial15"`
- `logs/auto_trades.jsonl` → `"demo_detected": true` on every trade entry
- `config/real_controlled_mode.yaml` — no hardcoded live server credentials

**Risk:** LOW — Account is demonstrably a trial account on Exness-MT5Trial15.

---

## REQUIREMENT 2: Realtime loop runs continuously

**Status:** ⚠️ CODE VERIFIED BUT NO LOG PROOF

**What the code does:**
- `src/qader_app/services/real_time_loop_service.py:196` — `while not self._stop_event.is_set():` runs indefinitely.
- `time.sleep(interval)` — default 1 second from `loop_interval_seconds` in config.
- Loop only terminates on: kill switch, `max_data_failures_reached`, `no_symbols_selected`, or explicit stop.

**Problem:**
- `logs/qader_realtime_loop.jsonl` does **NOT EXIST**.
- This file is only written when `_write_loop_log()` is called at the end of each `_scan_symbol_cycle()`.
- Absence of this file means the `RealTimeLoopService` has either never been started via the GUI, or crashed before writing any cycle.

**Circumstantial evidence the loop ran at some point:**
- `logs/arbitration_decisions.jsonl` contains XAUUSDm M1 entries at `2026-05-14T00:57:35` — the arbiter was called (the arbiter is only called inside `_scan_symbol_cycle()`).
- However, the loop log file was never created, suggesting the loop crashed or the log path was not resolved correctly.

**Priority:** HIGH  
**File:** `src/qader_app/services/real_time_loop_service.py`  
**Issue:** `qader_realtime_loop.jsonl` never created.  
**Risk:** Cannot prove loop is running. No cycle counter audit trail.  
**Recommendation for Codex:** Add a startup log entry immediately when the loop thread begins (before the `while` loop), using `_write_loop_log()`. Also add exception logging at the outermost level of `_run_loop()` to capture crash reason to file. Verify `logs_dir()` resolves correctly at runtime.  
**Safe to apply now:** YES

---

## REQUIREMENT 3: Does not stop on HOLD

**Status:** ✅ PASS — Code verified

**Proof:**
```python
# real_time_loop_service.py:183
continue_after_hold = bool(cfg.get("continue_after_hold", True))
```
Default is `True`. `real_controlled_mode.yaml` does not set this key, so default applies.

On HOLD, the scan result is written, last_signal is updated, and the loop sleeps then continues. No `_stop_event.set()` call on HOLD when `continue_after_hold=True`.

---

## REQUIREMENT 4: Scans XAUUSDm M1 repeatedly

**Status:** ✅ PASS — Config and log confirmed

**Proof:**
- `config/real_controlled_mode.yaml:symbols.active: [XAUUSDm]` and `symbols.timeframes: [M1]`
- `logs/arbitration_decisions.jsonl` — last 5 entries all: `symbol=XAUUSDm, timeframe=M1`
- Loop iterates `for symbol in selected_symbols: for timeframe in selected_timeframes:` on every cycle.

---

## REQUIREMENT 5: Logs written to logs/qader_realtime_loop.jsonl

**Status:** ❌ CRITICAL FAIL — File does not exist

**Evidence:**
```
C:/Users/Radhi/MT5/logs/ — qader_realtime_loop.jsonl NOT FOUND
Only qader_audit.jsonl exists.
```

**Root cause analysis:**
1. The file path is correctly defined at `real_time_loop_service.py:46`:  
   `self._log_path = logs_dir() / "qader_realtime_loop.jsonl"`
2. `_write_loop_log()` calls `self._log_path.parent.mkdir(parents=True, exist_ok=True)` before writing.
3. But if `_scan_symbol_cycle()` is never completed (loop crashed in `_run_loop()` before the scan), nothing is written.
4. The existing arbitration log entries suggest the loop reached `_scan_symbol_cycle()` at least once — but then no jsonl entry was written.

**Possible secondary cause:** The `_scan_symbol_cycle()` code at line 241 calls `self._write_loop_log(scan_result)` — this is correct. If the loop ran and produced scan results, the file should exist. The file's absence is unexplained and requires active debugging.

**Priority:** CRITICAL  
**File:** `src/qader_app/services/real_time_loop_service.py`  
**Issue:** `logs/qader_realtime_loop.jsonl` is missing. Loop is unproven to be running and logging.  
**Risk:** No audit trail for the continuous loop. Regulators and system owners cannot verify system was operating.  
**Recommendation for Codex:**  
1. Add `_write_loop_log({"event": "loop_start", ...})` immediately in `_run_loop()` before the while loop.  
2. Add `_write_loop_log({"event": "loop_end", "reason": ...})` in the `finally:` block.  
3. Add `_write_loop_log({"event": "loop_exception", "error": str(exc)})` in the `except Exception` handler.  
4. Run the loop manually with `python -c "from qader_app.services.real_time_loop_service import RealTimeLoopService; svc = RealTimeLoopService(); svc.start(final_confirmation=True)"` and verify the file is created within 5 seconds.  
**Safe to apply now:** YES
