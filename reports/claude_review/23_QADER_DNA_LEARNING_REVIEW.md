# Report 23 — Qader DNA / Strategy Learning Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Scope:** Genome structure, learning engine, mutation safety, population management, live-trade feedback loop

---

## 1. Current DNA Infrastructure — What Exists

### 1.1 GeneStore
**File:** `src/qader_app/genome/gene_store.py`

Manages five files in `data/qader/dna/`:
- `default_genome.json` — safe reference genome, never overwritten by mutations
- `active_genome.json` — currently running genome, mutated by MutationEngine
- `genome_history.jsonl` — every save_active call appended
- `performance_journal.jsonl` — per-decision performance records

Current active genome schema:
```json
{
  "genome_id": "qader_default_v1",
  "version": 1,
  "agent_weights": { "fractal_agent": 0.45, "smc_agent": 0.45, "session": 0.10, "ict_sweep_agent": 0.0 },
  "confidence_thresholds": { "arbiter_pass": 0.70, "decision_min": 0.45 },
  "risk": { "max_lot": 0.01, "max_spread_points": 30, "atr_sl_multiplier": 1.5, "atr_tp_multiplier": 2.0, "max_open_positions": 1 },
  "symbols": { "XAUUSDm": { "enabled": true, "timeframes": ["M1"], "max_spread_points": 80 } },
  "sessions": { "prefer_london_ny_overlap": true, "avoid_low_liquidity": true },
  "performance": { "minimum_sample_size": 30, "rollback_score_floor": -0.25 }
}
```

### 1.2 MutationEngine
**File:** `src/qader_app/genome/mutation_engine.py`

- `propose_threshold_adjustment(metric)` — adjusts `confidence_thresholds.arbiter_pass` by ±0.01-0.02 based on score
- `apply(proposal, approved=True)` — deep-merges changes, increments version, appends history
- `rollback_to_default(reason)` — restores default genome, increments version
- `auto_rollback_if_bad(score)` — triggers rollback if score < `rollback_score_floor` (-0.25)

**Safety:** All mutations require `can_modify_strategy_dna` permission. `apply(approved=False)` is a no-op.

### 1.3 EvaluationEngine
**File:** `src/qader_app/genome/evaluation_engine.py`

`score_decision(decision)` — scores a dry-run result by:
- `score = confidence` if action is BUY/SELL
- `score = 0.0` if blocked/HOLD
- `score -= 1.0` if error occurred

This is a **confidence proxy score, not a P/L score**. It has no knowledge of:
- Whether the trade was profitable or not
- What the actual P/L was in pips or USD
- How long the trade was held
- What exit reason was used
- Drawdown during the trade

---

## 2. What Is Missing for Live DNA Learning

### 2.1 Live Trade Result Recording

There is no mechanism to:
- Detect when a position opened by Qader closes (via MT5 history query)
- Record the closed trade's: P/L (USD), P/L (pips), hold time, exit reason, symbol, timeframe, direction, entry price, exit price, SL, TP, lot
- Map the closed trade back to the genome version and signal that triggered it

**Required:**
```python
class TradeJournal:
    """Records every real trade opened and closed by Qader."""
    
    def record_opened(self, order_result, execution_request, genome_version, opportunity_score):
        """Called immediately after order_send succeeds."""
        ...
    
    def record_closed(self, position_ticket, close_reason, close_price, pnl_usd, pnl_pips):
        """Called when a Qader position disappears from open positions."""
        ...
    
    def get_recent_trades(self, n: int = 100) -> list[dict]:
        """Returns most recent closed trades for DNA scoring."""
        ...
```

File: `data/qader/dna/live_performance_journal.jsonl`

### 2.2 Minimum Sample Size Enforcement

The genome has `performance.minimum_sample_size: 30`, but `MutationEngine.apply()` does not check this. Mutations should be blocked if fewer than 30 live trades have been recorded for the current genome version.

```python
def apply(self, proposal, approved=False):
    # Add: check minimum sample size
    journal = self.load_performance_journal()
    current_version = self.store.load_active().get("version", 1)
    version_trades = [t for t in journal if t.get("genome_version") == current_version]
    min_sample = self.store.load_active().get("performance", {}).get("minimum_sample_size", 30)
    if len(version_trades) < min_sample:
        return {"applied": False, "reason": f"insufficient_sample:{len(version_trades)}/{min_sample}"}
    ...
```

### 2.3 Strategy Population and Campaign Management

The genome tracks one active strategy. Missing:
- `strategy_population.jsonl` — pool of candidate genomes being evaluated
- `retired_strategies.jsonl` — strategies that failed performance thresholds
- `champion_strategy.json` — the best-performing strategy across all generations

**Required genome fields for population management:**
```json
{
  "generation": 3,
  "parent_genome_id": "qader_v2_20260512",
  "status": "active",          // active | candidate | retired | champion
  "evaluation_mode": "live",   // live | backtest
  "sample_trades": 47,
  "stats": {
    "win_rate": 0.62,
    "profit_factor": 1.45,
    "sharpe": 0.89,
    "max_drawdown_pct": 2.3,
    "total_pnl_usd": 147.50,
    "total_trades": 47,
    "avg_hold_minutes": 22,
    "biggest_win_usd": 18.50,
    "biggest_loss_usd": -9.20,
    "max_win_streak": 5,
    "max_loss_streak": 3
  }
}
```

### 2.4 Background Candidate Generation

The `genetic_evolver.py` (in `src/mt5_ai/`) already implements genetic crossover and mutation on genome JSON files. It is not yet wired to `qader_app/genome/`. A background thread should:
- Generate candidate genomes by mutating the current champion
- Run candidates against historical data (backtest mode) with minimum bars threshold
- Promote candidates that pass backtest thresholds to "candidate" status
- Allow user to "Apply DNA Proposal" via UI (never auto-apply to live without user approval)

### 2.5 Promotion Conditions

Before a candidate genome can be promoted to "active":
- Minimum sample size met (e.g., 30 forward-test trades OR 200 backtest trades)
- Max drawdown < threshold (profile-based)
- Profit factor ≥ 1.3
- Win rate ≥ 40% (even low win rate is acceptable with high RR)
- Sharpe ratio ≥ 0.5
- Recovery factor ≥ 1.0
- Forward test passed: backtest promoter must show results on out-of-sample data

### 2.6 Signal / Bias / Filter Gene Fields Missing From Genome

The current genome has no toggles for the 19 signal modules, 14 bias modules, or 15 filter modules mentioned in the product spec. These need to be gene fields:

```json
{
  "signals": {
    "use_sig_fractal": true,
    "use_sig_smc": true,
    "use_sig_ict_sweep": true,
    "use_sig_bb": false,
    "use_sig_breakout": false,
    "use_sig_macd": false,
    ...
  },
  "bias": {
    "use_bias_ema": true,
    "use_bias_htf": true,
    "use_bias_adx": false,
    ...
  },
  "filters": {
    "use_filter_spread": true,
    "use_filter_session": true,
    "use_filter_volatility": true,
    "use_filter_adr_exhaust": false,
    ...
  },
  "management": {
    "use_breakeven": true,
    "use_trailing": false,
    "use_partial_tp": false,
    "use_eod_close": true,
    "use_sl_lock": false,
    "use_sl_reduce": false,
    "use_opposite_signal_exit": false,
    "use_session_exit": true,
  },
  "execution": {
    "use_market": true,
    "use_limit": false,
    "use_stop": false,
  }
}
```

These fields allow genetic evolution to vary which modules are active, not just numerical thresholds.

---

## 3. Genome Safety Invariants

The following must never be modified by the mutation engine:

| Field | Reason |
|---|---|
| `trading_runtime.yaml` | Trading safety config — write-protected by PROJECT_AGENT_SECRET_FILE_NAMES |
| `execution_manager.py` | Order execution gate — not a genome parameter |
| `kill_switch.py` | Safety control — not a genome parameter |
| `magic_number` | Must remain `QADER_REAL_CONTROLLED_MAGIC` for live orders |
| `comment` prefix | Required for audit trail integrity |

**Confirmed:** MutationEngine modifies only `active_genome.json` via GeneStore. It does not write Python source files or YAML config files. ✅

---

## 4. DNA Files to Create

The following files are referenced in the product spec but do not yet exist:

| File | Location | Purpose |
|---|---|---|
| `live_performance_journal.jsonl` | `data/qader/dna/` | Real trade results (not simulation) |
| `strategy_population.jsonl` | `data/qader/dna/` | Candidate genome pool |
| `retired_strategies.jsonl` | `data/qader/dna/` | Genomes that failed promotion |
| `champion_strategy.json` | `data/qader/dna/` | Best genome ever recorded |

`genome_history.jsonl` and `performance_journal.jsonl` already exist via GeneStore. ✅

---

## 5. Data Quality Check

If MT5 returns insufficient historical bars (e.g., fewer than 200 bars for M1), backtesting and genetic evolution will produce unreliable results. Required:

```python
def check_data_quality(df, symbol, timeframe, min_bars=200) -> dict:
    n = len(df) if df is not None else 0
    limited = n < min_bars
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "bars_returned": n,
        "min_bars_required": min_bars,
        "limited_resolution": limited,
        "warning": (
            "LIMITED RESOLUTION DATA — increase MetaTrader5 chart history: "
            "Tools > Options > Charts > Max bars in chart: Unlimited. "
            "Restart MT5, wait 2-3 minutes."
        ) if limited else None,
    }
```

---

## 6. Learning Engine Summary

| Component | Status | Gap |
|---|---|---|
| GeneStore (5 files) | ✅ EXISTS | Missing 4 new DNA files |
| MutationEngine | ✅ EXISTS | Missing minimum sample check |
| EvaluationEngine | ✅ EXISTS (basic) | Scores confidence, not P/L |
| Performance journal | ✅ EXISTS | Records simulation scores only |
| Live trade result recording | ❌ MISSING | TradeJournal not implemented |
| Strategy population management | ❌ MISSING | Single active genome only |
| Background candidate generation | ❌ MISSING | genetic_evolver not wired |
| DNA promotion conditions | ❌ MISSING | No threshold enforcement |
| Signal/Bias/Filter gene fields | ❌ MISSING | Genome schema too minimal |
| Management module genes | ❌ MISSING | No toggle fields in genome |
| Data quality check | ❌ MISSING | No bar count validation |
| Champion/Retired tracking | ❌ MISSING | No population lifecycle |

---

## 7. Safe Implementation Order for DNA

1. Extend genome schema with signal/bias/filter/management toggle fields (no behavior change — just store them)
2. Create `live_performance_journal.jsonl` and `TradeJournal` class
3. Wire trade open recording in LiveAutopilotService (when order succeeds)
4. Wire trade close detection in position management loop (poll MT5 history)
5. Add P/L scoring to EvaluationEngine (replaces confidence proxy)
6. Add minimum sample check to MutationEngine.apply()
7. Create strategy population files and population lifecycle logic
8. Wire background candidate generation (genetic_evolver → qader_app genome)
9. Add data quality check to scanner and runner
10. Add Apply DNA Proposal / Rollback DNA UI buttons
