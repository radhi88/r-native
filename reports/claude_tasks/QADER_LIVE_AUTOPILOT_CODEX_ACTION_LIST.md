# QADER LIVE AUTOPILOT — Codex Implementation Action List

**Author:** Claude (supervisor/reviewer)  
**Date:** 2026-05-14  
**Source reports:** claude_review/20–24  
**Purpose:** Actionable tasks for Codex in priority order  
**Target:** `QADER_LIVE_AUTOPILOT` — real autonomous live trading mode for the Qader desktop app

---

## CRITICAL

---

### LA-CRIT-1: Wire REAL_CONTROLLED_MODE into execute() routing

**Priority:** CRITICAL  
**File:** `src/mt5_ai/core/execution_manager.py` — `execute()` method (lines 261–319)

**Issue:** `execute()` does not route REAL_CONTROLLED_MODE to `_execute_real_controlled_market()`. It would return `"live_trading_not_allowed_in_config"` for any order in REAL_CONTROLLED_MODE because `is_live_allowed()` only checks mode == "LIVE".

**Risk:** Real orders are impossible. The entire execution gate (`_execute_real_controlled_market()` with 30+ checks) is unreachable through the normal pipeline.

**Recommended fix:**
```python
def execute(self, req: ExecutionRequest) -> ExecutionResult:
    if is_kill_switch():
        ...
    ok, msg = req.is_valid()
    if not ok:
        ...
    try:
        validate_request(req.magic, req.comment)
    except ValueError as e:
        ...
    if is_dry_run():
        ...  # simulate only — unchanged
    # ADD THIS BLOCK before the is_live_allowed() check:
    if is_real_controlled_mode():
        return self._execute_real_controlled_market(req)
    if not is_live_allowed():
        ...
    # MT5Gateway path — blocked — unchanged
```

**Safe to apply now:** YES — adds a new branch, does not affect DRY_RUN or any existing path.

---

### LA-CRIT-2: Add REAL_CONTROLLED_MODE keys to trading_runtime.yaml

**Priority:** CRITICAL  
**File:** `config/trading_runtime.yaml`

**Issue:** `validate_real_controlled_request()` checks 8 keys that are missing from the YAML. Without them every check fails as `None != False`.

**Risk:** Every real order attempt fails the execution gate with 8 simultaneous gate failures even after the routing fix (LA-CRIT-1).

**Recommended fix — append to `config/trading_runtime.yaml`:**
```yaml
execution:
  ...existing keys...
  pending_orders_enabled: false
  averaging_enabled: false
  martingale_enabled: false
  grid_enabled: false
  pyramiding_enabled: false
  reentry_loop_enabled: false
  comment: "QADER_RC"

runtime:
  ...existing keys...
  max_runtime_minutes: 480
```

**Safe to apply now:** YES — adds keys only; does not change existing DRY_RUN behavior.

---

### LA-CRIT-3: Update execution gate lot check for dynamic sizing

**Priority:** CRITICAL  
**File:** `src/mt5_ai/core/execution_manager.py` — `validate_real_controlled_request()` lines 140–141

**Issue:** Current gate:
```python
self._gate(gates, "lot_fixed", abs(float(req.lot) - fixed_lot) < 1e-9, ...)
```
Checks that lot equals `risk.fixed_lot` exactly. When equity-based lot sizing is implemented (LA-HIGH-1), every dynamically computed lot will fail this gate because computed lots will differ from the fixed config value.

**Risk:** All real orders blocked after risk governor is implemented.

**Recommended fix:** Replace exact-match with range check:
```python
min_lot = float(risk.get("min_lot", 0.01) or 0.01)
max_lot_cfg = float(risk.get("max_lot", 0.10) or 0.10)
self._gate(
    gates, "lot_within_valid_range",
    min_lot <= float(req.lot) <= max_lot_cfg,
    f"lot={req.lot},min={min_lot},max={max_lot_cfg}"
)
```
Also add `min_lot: 0.01` to `config/trading_runtime.yaml` under `risk:`.

**Safe to apply now:** YES — gate becomes more permissive (range instead of exact), not less.

---

### LA-CRIT-4: Build LiveUnlockWizard GUI (6-step dialog)

**Priority:** CRITICAL  
**File:** New — `src/qader_app/gui/live_unlock_wizard.py`; update `src/qader_app/gui/main_window.py`

**Issue:** No multi-step GUI exists for the QADER_LIVE_AUTOPILOT unlock sequence. The storage layer (`PermissionsStore.unlock_real_controlled_mode`) is ready but has no UI.

**Risk:** Live mode is permanently inaccessible to the user regardless of account state.

**Recommended fix:** Create `LiveUnlockWizard(QDialog)` with 6 pages using `QWizard` or custom `QStackedWidget`:

Page 1 — Account snapshot from `MT5Service.connect()` + `mt5.account_info()`:
```python
# Display: login, server, balance, equity, margin, leverage, open_positions, pending_orders
# Require user to click "This is my account — continue"
```

Page 2 — Lockdown verification (inline):
```python
# Run: positions = mt5.positions_get() or [], orders = mt5.orders_get() or []
# external = any(int(p.magic or -1) == 0 for p in positions + orders)
# clean = (len(positions) == 0 and len(orders) == 0 and not external)
# Show: green "ACCOUNT CLEAN" or red "FAILED — X positions exist"
# Block Next if not clean
```

Page 3 — Phrase confirmation:
```python
# QLineEdit, validate: text.strip() == "I ACCEPT REAL TRADING RISK"
# "Next" disabled until match; red border on mismatch
```

Page 4 — Risk profile selection:
```python
# QButtonGroup with 4 options; warn on Aggressive/Extreme
# Store selection in settings["risk_profile"]
```

Page 5 — Symbol + timeframe selection:
```python
# QListWidget multi-select from trading_runtime.yaml symbols
# Must select ≥ 1 symbol and ≥ 1 timeframe
```

Page 6 — Final confirmation:
```python
# Summary label; "UNLOCK LIVE AUTOPILOT" calls:
perm_store.unlock_real_controlled_mode(phrase, lockdown_summary)
settings_store.save({"mode": "REAL_CONTROLLED_MODE", "risk_profile": profile, ...})
# config_loader.use_config() switches to a real-controlled YAML that sets the mode
```

Wire "Unlock Live Autopilot" button in `MainWindow` to open this dialog.

**Safe to apply now:** YES — new file, dialog, button.

---

### LA-CRIT-5: Build LiveAutopilotService — autonomous trading loop

**Priority:** CRITICAL  
**File:** New — `src/qader_app/services/live_autopilot_service.py`

**Issue:** No autonomous live trading loop exists in `qader_app`. `RunnerService` only implements dry-run cycles.

**Risk:** Live mode is unlocked but never executes because there is no loop calling the pipeline for real orders.

**Recommended structure:**
```python
class LiveAutopilotService:
    def __init__(self):
        self.running = False
        self._session_start_equity: float | None = None
        self._real_orders_sent: int = 0
        self._execution_manager = get_execution_manager()
        ...
    
    def start(self, mt5, symbols, timeframes, risk_profile, settings) -> None:
        """Called after live unlock wizard completes."""
        perm = PermissionsGuard().check("can_place_live_orders", "live_autopilot_start")
        if not perm.allowed:
            raise PermissionError(perm.reason)
        account = mt5.account_info()
        self._session_start_equity = float(account.equity)
        self.running = True
        self._loop(mt5, symbols, timeframes, risk_profile, settings)
    
    def _loop(self, mt5, symbols, timeframes, risk_profile, settings) -> None:
        """Main trading loop. One symbol+timeframe pair per iteration."""
        arbiter = SignalArbiter()
        router = DecisionRouter()
        guard = ConflictGuard()
        risk_mgr = RiskManager()
        risk_gov = RiskGovernor(mt5)
        exec_mgr = self._execution_manager
        exec_mgr.reset_real_controlled_run()
        
        cycle = 0
        while self.running and not is_kill_switch():
            for symbol in symbols:
                for timeframe in timeframes:
                    if not self.running:
                        break
                    self._scan_and_execute(
                        mt5, symbol, timeframe, arbiter, router, guard,
                        risk_mgr, risk_gov, exec_mgr, risk_profile
                    )
                    time.sleep(settings.get("scan_interval_seconds", 30))
            cycle += 1
        
        PermissionsStore().lock_real_controlled_mode("session_ended")
    
    def _scan_and_execute(self, mt5, symbol, timeframe, ...):
        """One scan+execute cycle for one symbol/timeframe."""
        # 1. Session loss check
        # 2. Fetch bars + data quality check
        # 3. Run agents → SignalArbiter → ConflictGuard
        # 4. Compute opportunity score — block if below threshold
        # 5. RiskGovernor.compute_lot()
        # 6. Build ExecutionRequest with QADER_RC magic and comment
        # 7. ExecutionManager.execute() → routes to _execute_real_controlled_market()
        # 8. Record result in TradeJournal
        ...
    
    def emergency_stop(self) -> None:
        self.running = False
        activate("qader_live_emergency_stop")
        PermissionsStore().lock_real_controlled_mode("emergency_stop")
    
    def pause_entries(self) -> None:
        self._entries_paused = True
```

**Safe to apply now:** YES — new file, does not affect any existing system.

---

## HIGH

---

### LA-HIGH-1: Build RiskGovernor — equity-based lot sizing

**Priority:** HIGH  
**File:** New — `src/mt5_ai/core/risk_governor.py`

**Issue:** `RiskManager.validate()` always returns `adjusted_lot = max_lot` from config (e.g. 0.10) regardless of account equity, SL distance, or risk profile.

**Risk:** Fixed lot sizing with no account balance awareness. 0.10 lot is catastrophic on a $1,000 account.

**Recommended structure:**
```python
class RiskGovernor:
    def compute_lot(self, symbol, entry_price, sl_price, equity, free_margin, risk_profile, mt5) -> dict:
        """Returns computed lot and all intermediate values for audit."""
        risk_pct = float(risk_profile["risk_per_trade_percent"]) / 100.0
        risk_amount = equity * risk_pct
        
        sym_info = mt5.symbol_info(symbol)
        tick_size  = float(sym_info.trade_tick_size)
        tick_value = float(sym_info.trade_tick_value)
        volume_min  = float(sym_info.volume_min)
        volume_max  = float(sym_info.volume_max)
        volume_step = float(sym_info.volume_step)
        
        sl_distance = abs(entry_price - sl_price)
        if sl_distance < tick_size:
            return {"approved": False, "reason": "sl_too_close", "lot": 0.0}
        
        sl_ticks = sl_distance / tick_size
        loss_per_lot = sl_ticks * tick_value
        if loss_per_lot <= 0:
            return {"approved": False, "reason": "loss_per_lot_invalid", "lot": 0.0}
        
        raw_lot = risk_amount / loss_per_lot
        
        profile_cap = float(risk_profile.get("max_lot_hard_cap", volume_max))
        clamped = min(max(raw_lot, volume_min), min(volume_max, profile_cap))
        
        # Round to volume_step
        steps = round(clamped / volume_step)
        final_lot = round(steps * volume_step, 8)
        
        # Margin check
        margin_req = mt5.order_calc_margin(
            mt5.ORDER_TYPE_BUY, symbol, final_lot, entry_price
        )
        margin_ok = (margin_req is not None and free_margin >= margin_req * 1.5)
        
        return {
            "lot": final_lot,
            "risk_amount_usd": round(risk_amount, 2),
            "loss_per_lot_usd": round(loss_per_lot, 2),
            "sl_distance_points": round(sl_ticks, 1),
            "raw_lot": round(raw_lot, 5),
            "clamped_to": f"min={volume_min},max={min(volume_max, profile_cap)}",
            "margin_ok": margin_ok,
            "margin_required": margin_req,
            "approved": margin_ok,
            "reason": "approved" if margin_ok else "insufficient_margin",
        }
    
    def check_session_limits(self, equity, balance, session_start_equity, risk_profile) -> dict:
        """Daily and session loss check. Call before every new entry."""
        ...
```

**Safe to apply now:** YES — new file, called by LiveAutopilotService.

---

### LA-HIGH-2: Add risk profiles to genome and settings

**Priority:** HIGH  
**Files:** `data/qader/dna/default_genome.json`, `data/qader/dna/active_genome.json`, `src/qader_app/genome/gene_store.py`

**Issue:** No risk profile exists in the genome or settings. Conservative/Balanced/Aggressive/Extreme are undefined.

**Recommended genome addition:**
```json
{
  "risk_profile": "balanced",
  "risk_profiles": {
    "conservative": { "risk_per_trade_percent": 0.25, "max_daily_loss_percent": 1.0, "max_session_loss_percent": 0.5, "max_open_positions": 1, "max_lot_hard_cap": 0.05, "opportunity_score_threshold": 85 },
    "balanced":     { "risk_per_trade_percent": 0.50, "max_daily_loss_percent": 2.0, "max_session_loss_percent": 1.0, "max_open_positions": 1, "max_lot_hard_cap": 0.10, "opportunity_score_threshold": 78 },
    "aggressive":   { "risk_per_trade_percent": 1.00, "max_daily_loss_percent": 3.0, "max_session_loss_percent": 1.5, "max_open_positions": 2, "max_lot_hard_cap": 0.20, "opportunity_score_threshold": 70 },
    "extreme":      { "risk_per_trade_percent": 2.00, "max_daily_loss_percent": 5.0, "max_session_loss_percent": 2.5, "max_open_positions": 3, "max_lot_hard_cap": 0.50, "opportunity_score_threshold": 62 }
  }
}
```

**Safe to apply now:** YES — JSON only, does not affect any running system.

---

### LA-HIGH-3: Add signal/bias/filter/management toggle fields to genome

**Priority:** HIGH  
**Files:** `data/qader/dna/default_genome.json`, `data/qader/dna/active_genome.json`

**Issue:** Genome has no toggle fields for the 48+ signal/bias/filter/management/execution modules. Evolution cannot vary which modules are active.

**Recommended addition to genome JSON:**
```json
{
  "signals": {
    "use_sig_fractal": true, "use_sig_smc": true, "use_sig_ict_sweep": true,
    "use_sig_bb": false, "use_sig_breakout": false, "use_sig_cci": false,
    "use_sig_engulfing": false, "use_sig_fib": false, "use_sig_macd": false,
    "use_sig_pin_bar": false, "use_sig_rsi": false, "use_sig_stoch": false,
    "use_sig_three_soldiers": false, "use_sig_wick_rejection": false,
    "use_sig_williams": false, "use_sig_inside_break": false,
    "use_sig_mom_break": false, "use_sig_order_block": false,
    "use_sig_fair_value_gap": false
  },
  "bias": {
    "use_bias_ema": true, "use_bias_htf": true, "use_bias_market_struct": true,
    "use_bias_fractal_struct": true, "use_bias_smc_bias": true,
    "use_bias_adx": false, "use_bias_chandelier": false, "use_bias_daily_mid": false,
    "use_bias_donchian_mid": false, "use_bias_momentum": false,
    "use_bias_psar": false, "use_bias_rsi": false, "use_bias_sma": false,
    "use_bias_trailing": false
  },
  "filters": {
    "use_filter_spread": true, "use_filter_session": true, "use_filter_volatility": true,
    "use_filter_data_quality": true, "use_filter_adr_exhaust": false,
    "use_filter_adx_trend": false, "use_filter_bb": false, "use_filter_cci": false,
    "use_filter_consec": false, "use_filter_doji": false, "use_filter_keltner": false,
    "use_filter_receding": false, "use_filter_rsi": false, "use_filter_sma": false,
    "use_filter_news_risk": false
  },
  "management": {
    "use_breakeven": true, "use_eod_close": true, "use_session_exit": true,
    "use_partial_tp": false, "use_sl_lock": false, "use_sl_reduce": false,
    "use_trailing": false, "use_opposite_signal_exit": false
  },
  "execution": {
    "use_market": true, "use_limit": false, "use_stop": false,
    "use_limit1": false, "use_limit2": false
  }
}
```

**Safe to apply now:** YES — JSON only.

---

### LA-HIGH-4: Add opportunity score to MarketScanResult and ScannerService

**Priority:** HIGH  
**Files:** `src/qader_app/services/scanner_service.py`

**Issue:** `MarketScanResult` has no `opportunity_score` field. Scan results cannot be filtered by profile threshold.

**Recommended fix:**
```python
@dataclass(slots=True)
class MarketScanResult:
    ...  # existing fields
    opportunity_score: int = 0
    recommended_lot: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0

# In scan_symbol():
opp_score = self._compute_opportunity_score(arb, result, genome)
result.opportunity_score = opp_score
threshold = genome.get("risk_profiles", {}).get(risk_profile, {}).get("opportunity_score_threshold", 78)
if opp_score < threshold:
    result.final_action = "HOLD"
    result.reason = f"opportunity_score_{opp_score}_below_threshold_{threshold}"
```

**Safe to apply now:** YES — additive only.

---

### LA-HIGH-5: Add live trade result recording (TradeJournal)

**Priority:** HIGH  
**File:** New — `src/qader_app/genome/trade_journal.py`

**Issue:** There is no mechanism to record real trade outcomes (P/L after close) for DNA learning.

**Recommended structure:**
```python
class TradeJournal:
    def __init__(self):
        self._path = dna_dir() / "live_performance_journal.jsonl"
        self._open_trades: dict[int, dict] = {}  # ticket → metadata
    
    def record_opened(self, ticket, symbol, direction, lot, entry_price, sl, tp, genome_version, opportunity_score, timestamp) -> None:
        self._open_trades[ticket] = {
            "ticket": ticket, "symbol": symbol, "direction": direction,
            "lot": lot, "entry_price": entry_price, "sl": sl, "tp": tp,
            "genome_version": genome_version, "opportunity_score": opportunity_score,
            "opened_at": timestamp, "status": "open"
        }
    
    def check_and_record_closed(self, mt5, magic: int) -> list[dict]:
        """Compare current open positions against known open trades. Record any that closed."""
        current_tickets = {int(p.ticket) for p in (mt5.positions_get() or []) if int(p.magic) == magic}
        closed = []
        for ticket, trade in list(self._open_trades.items()):
            if ticket not in current_tickets:
                # Position closed — fetch from MT5 history
                history = mt5.history_deals_get(position=ticket)
                closed_deal = self._find_close_deal(history)
                pnl_usd = float(getattr(closed_deal, "profit", 0.0) if closed_deal else 0.0)
                record = {**trade, "status": "closed", "pnl_usd": pnl_usd,
                         "closed_at": datetime.now(timezone.utc).isoformat()}
                self._write(record)
                del self._open_trades[ticket]
                closed.append(record)
        return closed
```

**Safe to apply now:** YES — new file.

---

### LA-HIGH-6: Expand DashboardView — live status badge and account panel

**Priority:** HIGH  
**File:** `src/qader_app/gui/dashboard.py`

**Issue:** Current DashboardView is 4 labels + 1 button. Missing: live autopilot status badge, real account panel, risk meter, scanner table, action buttons.

**Recommended structure:**
```python
class DashboardView(QWidget):
    def __init__(self):
        # Status badge (large, colored)
        self.live_badge = QLabel("🔒 LIVE LOCKED — DRY RUN ONLY")
        # Account panel
        self.account_panel = AccountPanel()      # login, balance, equity, margin
        # Risk meter
        self.risk_meter = RiskMeterWidget()      # daily/session progress bars
        # Control buttons row
        self.unlock_btn  = QPushButton("Unlock Live Autopilot")
        self.lock_btn    = QPushButton("Lock Live Autopilot")
        self.pause_btn   = QPushButton("Pause New Entries")
        self.emergency_button = QPushButton("⛔ EMERGENCY STOP")  # existing
        self.close_all_btn = QPushButton("Close All Qader Positions")
        # Scanner summary (last scan results)
        self.scanner_table = ScannerTableWidget()
```

Style the live badge as a colored QLabel that changes background color with stylesheet:
- Locked: dark green background, green text
- Live: dark red background, bright red text, bold

**Safe to apply now:** YES — rewrite of placeholder.

---

### LA-HIGH-7: kill_switch.deactivate() must require confirmation

**Priority:** HIGH  
**File:** `src/mt5_ai/core/kill_switch.py`

**Issue:** `deactivate()` writes `kill_switch: false` to config with no confirmation gate. Any code that imports kill_switch can re-enable trading.

**Risk:** A bug, exception handler, or future careless call could deactivate the kill switch without going through the unlock wizard.

**Recommended fix:**
```python
def deactivate(reason: str = "manual", confirm_phrase: str = "") -> bool:
    """Deactivate kill switch. Requires confirmation phrase from caller."""
    _CONFIRM = "QADER_DEACTIVATE_CONFIRMED"
    if confirm_phrase != _CONFIRM:
        import logging
        logging.getLogger("kill_switch").error(
            "deactivate() called without confirmation phrase — BLOCKED. reason=%s", reason
        )
        return False
    # proceed with yaml write
    ...
```

The unlock wizard would call `deactivate(reason="live_unlock", confirm_phrase="QADER_DEACTIVATE_CONFIRMED")`. All other callers get False.

**Safe to apply now:** YES — adds a guard; existing emergency_stop behavior uses `activate()` not `deactivate()`.

---

### LA-HIGH-8: Add auto-relock on session end and emergency stop

**Priority:** HIGH  
**Files:** `src/qader_app/services/live_autopilot_service.py` (new)

**Issue:** Permissions are not automatically revoked when the live session ends. If Qader crashes or is closed, `can_place_live_orders` remains True until the next explicit lock.

**Recommended fix:**
```python
# In LiveAutopilotService.stop() (normal stop):
PermissionsStore().lock_real_controlled_mode("session_ended_normally")
log_action("live_session_ended", None, True, "auto_relocked", "live_autopilot_service")

# In LiveAutopilotService.emergency_stop():
activate("qader_emergency_stop")
PermissionsStore().lock_real_controlled_mode("emergency_stop")

# In qader_app/main.py — app close event:
def closeEvent(self, event):
    self.live_service.stop()  # triggers auto-relock
    event.accept()
```

**Safe to apply now:** YES — new logic in new service file.

---

## MEDIUM

---

### LA-MED-1: Create live_performance_journal.jsonl and strategy_population files

**Priority:** MEDIUM  
**Files:** `data/qader/dna/`, `src/qader_app/genome/gene_store.py`

Add 4 new DNA files to `GeneStore.ensure_defaults()`:
```python
def ensure_defaults(self) -> None:
    ...
    for fname in ("live_performance_journal.jsonl", "strategy_population.jsonl",
                  "retired_strategies.jsonl"):
        (dna_dir() / fname).touch(exist_ok=True)
    champion = dna_dir() / "champion_strategy.json"
    if not champion.exists():
        champion.write_text(json.dumps({"champion": None, "updated_at": now}), encoding="utf-8")
```

**Safe to apply now:** YES.

---

### LA-MED-2: Add minimum sample check to MutationEngine.apply()

**Priority:** MEDIUM  
**File:** `src/qader_app/genome/mutation_engine.py`

**Issue:** Mutations can be applied with 0 trade samples. Threshold adjustments based on 0 trades are meaningless.

**Recommended fix:**
```python
def apply(self, proposal, approved=False):
    if not approved:
        return {"applied": False, "reason": "approval_required"}
    perm = self.guard.check("can_modify_strategy_dna", ...)
    if not perm.allowed:
        return {"applied": False, "reason": perm.reason}
    active = self.store.load_active()
    min_sample = int(active.get("performance", {}).get("minimum_sample_size", 30))
    journal = self.load_live_performance_journal()
    version = int(active.get("version", 1))
    version_records = [r for r in journal if r.get("genome_version") == version and r.get("status") == "closed"]
    if len(version_records) < min_sample:
        return {"applied": False, "reason": f"insufficient_sample:{len(version_records)}/{min_sample}",
                "proposal": proposal.proposal_id}
    ...
```

**Safe to apply now:** YES.

---

### LA-MED-3: Add P/L scoring to EvaluationEngine

**Priority:** MEDIUM  
**File:** `src/qader_app/genome/evaluation_engine.py`

**Issue:** `score_decision()` uses signal confidence as a proxy for trade quality. Real P/L from `TradeJournal` is not used.

**Recommended addition:**
```python
def score_trade_result(self, trade: dict) -> dict:
    """Score a closed live trade from TradeJournal."""
    pnl = float(trade.get("pnl_usd", 0.0))
    lot = float(trade.get("lot", 0.01) or 0.01)
    pnl_per_lot = pnl / lot
    score = pnl_per_lot / 100.0   # normalize: $100 profit/lot = score 1.0
    score = max(-2.0, min(2.0, score))
    record = {"pnl_usd": pnl, "pnl_per_lot": pnl_per_lot, "score": round(score, 4),
              "symbol": trade.get("symbol"), "genome_version": trade.get("genome_version"),
              "type": "live_trade"}
    self.store.append_performance(record)
    return record
```

**Safe to apply now:** YES — additive to existing EvaluationEngine.

---

### LA-MED-4: Add data quality check to scanner and runner

**Priority:** MEDIUM  
**Files:** `src/qader_app/services/scanner_service.py`, `src/qader_app/services/runner_service.py`

**Issue:** No bar count validation. Scans on 50 bars produce unreliable results.

**Recommended fix:**
```python
MIN_BARS_REQUIRED = {"M1": 200, "M5": 200, "M15": 150, "H1": 100, "H4": 80}

def scan_symbol(self, symbol, timeframe):
    ...
    df = self.mt5_service.fetch_bars(symbol, timeframe, n=300)
    min_bars = MIN_BARS_REQUIRED.get(timeframe, 200)
    if df is None or len(df) < 50:
        return MarketScanResult(symbol, timeframe, error="offline_or_insufficient_mt5_data")
    if len(df) < min_bars:
        return MarketScanResult(
            symbol, timeframe,
            error=f"limited_resolution:{len(df)}_bars_returned_{min_bars}_required",
            reason="limited_resolution_data"
        )
    ...
```

**Safe to apply now:** YES.

---

### LA-MED-5: Update packaging/qader.spec with correct assets

**Priority:** MEDIUM  
**File:** `packaging/qader.spec`

**Issues:**
- References `config/live_micro_disabled.yaml` which does not exist
- Missing Vosk model directory
- Missing `google.genai`, `faster_whisper` hidden imports
- Missing `sounddevice` hidden import

**Recommended fix:**
```python
datas = [
    (str(ROOT / "config" / "trading_runtime.yaml"), "config"),
    (str(ROOT / "config" / "dry_run_simulation.yaml"), "config"),
    # Remove live_micro_disabled.yaml (does not exist)
    # Add Vosk model (if present):
    (str(ROOT / "models" / "voice" / "vosk-model-ar-mgb2-0.4"), 
     "models/voice/vosk-model-ar-mgb2-0.4"),
]
hiddenimports=[
    ...,
    "sounddevice", "faster_whisper", "google.genai",
    "mt5_ai.core.project_root", "mt5_ai.core.risk_governor",
    "qader_app.services.live_autopilot_service",
]
```

Also delete the `qader.spec` created at the root (`C:\Users\Radhi\MT5\qader.spec`) — it incorrectly points to `mark_xxxix/main.py`. The canonical spec is `packaging/qader.spec`.

**Safe to apply now:** YES.

---

### LA-MED-6: Add signal/bias/filter toggle UI panels to scanner tab

**Priority:** MEDIUM  
**File:** `src/qader_app/gui/scanner_view.py`

**Issue:** No toggle panels for modules. Scanner always uses all available agents regardless of genome settings.

**Recommended:** Add toggle checkboxes to ScannerView that write directly to the active genome via GeneStore. Scanner reads genome before each scan to determine which modules are enabled.

**Safe to apply now:** YES — additive UI.

---

### LA-MED-7: Wire scanner results into DashboardView table

**Priority:** MEDIUM  
**File:** `src/qader_app/gui/dashboard.py`

**Issue:** DashboardView has no scanner results. User must switch tabs to see scan output.

**Recommended:** Add `QTableWidget` to Dashboard that shows the last N scan results with columns: Symbol, TF, Action, Confidence, Opp Score, Spread, Status.

**Safe to apply now:** YES — additive UI.

---

## LOW

---

### LA-LOW-1: Delete root-level qader.spec (wrong entry point)

**Priority:** LOW  
**File:** `C:\Users\Radhi\MT5\qader.spec` (created in prior session)

This spec points to `mark_xxxix/main.py` — the JarvisLive voice assistant, not the Qader desktop app. The canonical spec is `packaging/qader.spec` which correctly points to `src/qader_app/main.py`.

Either delete `qader.spec` or update it to match `packaging/qader.spec`.

**Safe to apply now:** YES.

---

### LA-LOW-2: Add voice rules to QaderBrain for live autopilot

**Priority:** LOW  
**File:** `src/qader_app/assistant/qader_brain.py`

Ensure voice command routing in `qader_app` enforces:
- "Scan market" → ScannerService.scan_symbols() ✓
- "Emergency stop" → RunnerService.emergency_stop() ✓
- "Pause entries" → LiveAutopilotService.pause_entries()
- "What is the risk?" → RiskGovernor status
- "Unlock live" → BLOCKED ("Live trading unlock requires GUI confirmation.")
- "Change risk profile" → BLOCKED ("Risk profile changes require GUI confirmation.")
- "Apply DNA" → BLOCKED ("DNA changes require GUI approval.")

**Safe to apply now:** YES.

---

### LA-LOW-3: Add export audit log button to Permissions/Logs tab

**Priority:** LOW  
**File:** `src/qader_app/gui/logs_view.py`

Add a "Export Audit Log" button that copies `logs/qader_audit.jsonl` to a user-selected location via `QFileDialog.getSaveFileName()`.

**Safe to apply now:** YES.

---

## Summary Table

| ID | Priority | File | Issue | Safe Now |
|---|---|---|---|---|
| LA-CRIT-1 | CRITICAL | `execution_manager.py` | execute() doesn't route REAL_CONTROLLED_MODE | YES |
| LA-CRIT-2 | CRITICAL | `trading_runtime.yaml` | Missing 8 REAL_CONTROLLED_MODE config keys | YES |
| LA-CRIT-3 | CRITICAL | `execution_manager.py` | Fixed-lot gate blocks dynamic sizing | YES |
| LA-CRIT-4 | CRITICAL | new `live_unlock_wizard.py` | No 6-step live unlock GUI exists | YES |
| LA-CRIT-5 | CRITICAL | new `live_autopilot_service.py` | No autonomous live trading loop | YES |
| LA-HIGH-1 | HIGH | new `risk_governor.py` | No equity-based lot sizing | YES |
| LA-HIGH-2 | HIGH | genome JSON files | No risk profiles | YES |
| LA-HIGH-3 | HIGH | genome JSON files | No signal/bias/filter/management genes | YES |
| LA-HIGH-4 | HIGH | `scanner_service.py` | No opportunity score | YES |
| LA-HIGH-5 | HIGH | new `trade_journal.py` | No live trade result recording | YES |
| LA-HIGH-6 | HIGH | `dashboard.py` | Dashboard is placeholder | YES |
| LA-HIGH-7 | HIGH | `kill_switch.py` | deactivate() has no confirmation gate | YES |
| LA-HIGH-8 | HIGH | `live_autopilot_service.py` | No auto-relock on session end | YES |
| LA-MED-1 | MEDIUM | `gene_store.py` + DNA files | 4 missing DNA files | YES |
| LA-MED-2 | MEDIUM | `mutation_engine.py` | No minimum sample check | YES |
| LA-MED-3 | MEDIUM | `evaluation_engine.py` | Scores confidence, not P/L | YES |
| LA-MED-4 | MEDIUM | `scanner_service.py` | No data quality bar count check | YES |
| LA-MED-5 | MEDIUM | `packaging/qader.spec` | Missing assets + wrong references | YES |
| LA-MED-6 | MEDIUM | `scanner_view.py` | No module toggle UI | YES |
| LA-MED-7 | MEDIUM | `dashboard.py` | No scanner results table | YES |
| LA-LOW-1 | LOW | `qader.spec` (root) | Wrong entry point spec | YES |
| LA-LOW-2 | LOW | `qader_brain.py` | Voice rules for live mode | YES |
| LA-LOW-3 | LOW | `logs_view.py` | No export audit log button | YES |

**Total: 5 CRITICAL, 8 HIGH, 7 MEDIUM, 3 LOW**

---

## Safety Invariants (must not be violated by any fix)

- `trading_runtime.yaml` mode must remain `DRY_RUN` as default; only set to `REAL_CONTROLLED_MODE` when the live unlock wizard explicitly writes it
- `allow_live_trading: false` is the config default; the unlock wizard sets it to `true` for REAL_CONTROLLED_MODE only
- `kill_switch: true` is the config default; `deactivate()` requires confirmation phrase (LA-HIGH-7)
- Every real `mt5.order_send` must pass all 30+ gates in `_execute_real_controlled_market()`
- Voice commands cannot unlock live trading or apply DNA mutations
- `can_place_live_orders` in permissions is forced to False unless all three unlock conditions are simultaneously true
- `api_keys.json` must never be bundled inside the EXE
- `PROJECT_AGENT_AUTO_FIX` must remain `False` — AI must never modify source files during live trading
- DNA mutation never modifies Python source files — genome JSON only
- SignalArbiter cannot be bypassed — arbiter result must be BUY/SELL (not HOLD) for any real order
- ConflictGuard cannot be bypassed — must return allow=True before execution request is built
- RiskManager cannot be bypassed — must return approved=True before execution request is built
- RiskGovernor must compute lot before every real order — no fixed-lot fallback in live mode
- Every real order must have magic=QADER_REAL_CONTROLLED_MAGIC (20260514), SL > 0, TP > 0
- Session and daily loss limits must cause automatic pause (not emergency stop — managed positions still active)
- Daily loss limit breach must cause auto-relock of live mode
- No martingale, grid, averaging, pyramiding, re-entry loops — enforced by execution gate config
