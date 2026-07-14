# Report 22 — Qader Dynamic Risk Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Scope:** Lot sizing, risk profiles, daily/session loss limits, exposure control, opportunity score thresholds

---

## 1. Current Risk Manager State

**File:** `src/mt5_ai/core/risk_manager.py`

`RiskManager.validate()` currently:
- Checks kill_switch ✅
- Checks spread ≤ max_spread_points (from config per-symbol) ✅
- Checks open_positions < max_open_positions ✅
- Checks daily_loss_pct < max_daily_loss_percent ✅
- Checks decision.confidence ≥ min_decision_confidence ✅
- Returns `adjusted_lot = max_lot = get("risk.max_lot")` — fixed from config (0.10)

**Critical gap: Lot size is always the config max_lot. It is NOT computed from equity, SL distance, or risk profile. A 10,000 USD account and a 1,000,000 USD account would get the same lot size.**

This is unacceptable for live trading.

---

## 2. Required: Dynamic Lot Sizing Formula

The correct formula for position sizing based on risk:

```
# Step 1: Determine risk amount
risk_percent = risk_profile.risk_per_trade_percent   # e.g. 0.50 for Balanced
risk_amount = equity × (risk_percent / 100.0)        # e.g. 1000 × 0.005 = 5.00 USD

# Step 2: Determine loss per 1 lot at stop-loss distance
sl_distance_price = abs(entry_price - sl_price)      # e.g. 0.00050 for EUR/USD
sl_distance_points = sl_distance_price / tick_size   # e.g. 0.00050 / 0.00001 = 50 points
loss_per_lot = sl_distance_points × tick_value       # e.g. 50 × 1.00 = 50.00 USD

# Step 3: Calculate lot
raw_lot = risk_amount / loss_per_lot                 # e.g. 5.00 / 50.00 = 0.10

# Step 4: Clamp
lot = clamp(raw_lot, 
            broker_min_lot,                          # from mt5.symbol_info.volume_min
            min(broker_max_lot, profile_max_lot))    # from profile and broker
lot = round_to_step(lot, broker_lot_step)            # from mt5.symbol_info.volume_step
```

**Required MT5 symbol info fields:**
- `symbol_info.trade_tick_size` — minimum price movement (e.g. 0.00001 for EUR/USD)
- `symbol_info.trade_tick_value` — USD value per tick per 1 lot
- `symbol_info.volume_min` — broker minimum lot
- `symbol_info.volume_max` — broker maximum lot
- `symbol_info.volume_step` — lot size precision step

**Required account info:**
- `account_info.equity` — current equity (not balance — equity reflects open P/L)
- `account_info.free_margin` — available margin check
- `account_info.balance` — for daily loss calculation baseline

---

## 3. Required: Risk Profiles

Four profiles must be defined and stored:

```python
RISK_PROFILES = {
    "conservative": {
        "risk_per_trade_percent": 0.25,
        "max_daily_loss_percent": 1.0,
        "max_session_loss_percent": 0.5,
        "max_open_positions": 1,
        "max_lot_hard_cap": 0.05,
        "opportunity_score_threshold": 85,
    },
    "balanced": {
        "risk_per_trade_percent": 0.50,
        "max_daily_loss_percent": 2.0,
        "max_session_loss_percent": 1.0,
        "max_open_positions": 1,
        "max_lot_hard_cap": 0.10,
        "opportunity_score_threshold": 78,
    },
    "aggressive": {
        "risk_per_trade_percent": 1.00,
        "max_daily_loss_percent": 3.0,
        "max_session_loss_percent": 1.5,
        "max_open_positions": 2,
        "max_lot_hard_cap": 0.20,
        "opportunity_score_threshold": 70,
    },
    "extreme": {
        "risk_per_trade_percent": 2.00,
        "max_daily_loss_percent": 5.0,
        "max_session_loss_percent": 2.5,
        "max_open_positions": 3,
        "max_lot_hard_cap": 0.50,
        "opportunity_score_threshold": 62,
    },
}
```

The selected risk profile must be:
1. Chosen during the live unlock wizard
2. Stored in `data/qader/settings.json` as `risk_profile`
3. Loaded by the RiskGovernor at every cycle
4. Reflected in the genome's `risk` section

---

## 4. New Module: RiskGovernor

**Proposed file:** `src/mt5_ai/core/risk_governor.py`

```python
class RiskGovernor:
    """
    Computes equity-based lot size and enforces all live-trading risk limits.
    
    Called AFTER RiskManager.validate() — adds live account context that the
    stateless RiskManager cannot provide.
    """
    
    def __init__(self, mt5_module=None):
        self.mt5 = mt5_module
    
    def compute_lot(
        self,
        symbol: str,
        entry_price: float,
        sl_price: float,
        equity: float,
        risk_profile: dict,
    ) -> dict:
        """
        Returns:
            {
                "lot": float,
                "risk_amount_usd": float,
                "loss_per_lot_usd": float,
                "sl_distance_points": float,
                "clamp_reason": str | None,
                "approved": bool,
                "reason": str,
            }
        """
        ...
    
    def check_limits(
        self,
        equity: float,
        balance: float,
        session_start_equity: float,
        risk_profile: dict,
        open_exposure_lots: float,
    ) -> dict:
        """
        Returns daily/session loss check result.
        Must be called before any new entry.
        """
        daily_loss_pct = (balance - equity) / balance * 100 if balance > 0 else 0
        session_loss_pct = (session_start_equity - equity) / session_start_equity * 100 if session_start_equity > 0 else 0
        
        daily_ok = daily_loss_pct < risk_profile["max_daily_loss_percent"]
        session_ok = session_loss_pct < risk_profile["max_session_loss_percent"]
        
        return {
            "daily_loss_pct": daily_loss_pct,
            "session_loss_pct": session_loss_pct,
            "daily_limit_ok": daily_ok,
            "session_limit_ok": session_ok,
            "approved": daily_ok and session_ok,
            "reason": "approved" if (daily_ok and session_ok) else
                      f"daily_loss_{daily_loss_pct:.2f}%>={risk_profile['max_daily_loss_percent']}%" if not daily_ok else
                      f"session_loss_{session_loss_pct:.2f}%>={risk_profile['max_session_loss_percent']}%",
        }
```

---

## 5. Session Loss Tracking

Currently `RiskManager.validate()` receives `daily_loss_pct` as a parameter (computed externally in `main_loop.py`). But:

- `daily_loss_pct` is computed from current equity vs balance — this is a floating value that moves with open positions
- There is no **session loss** tracking (loss since the session/unlock started)
- Session start equity must be recorded at the moment QADER_LIVE_AUTOPILOT is unlocked

**Required implementation:**
```python
# In LiveAutopilotService.__init__():
self._session_start_equity: float | None = None

# At session unlock:
account_info = mt5.account_info()
self._session_start_equity = float(account_info.equity)

# Before each new entry:
current_equity = float(mt5.account_info().equity)
session_loss = (self._session_start_equity - current_equity) / self._session_start_equity * 100
if session_loss >= risk_profile["max_session_loss_percent"]:
    log.warning("Session loss limit reached — pausing new entries")
    return  # no new entries, but existing positions are still managed
```

---

## 6. Exposure Limits

Current `RiskManager.validate()` checks `open_positions < max_open_positions`.

Missing:
- **Total open lot exposure** — if a Conservative profile has 1 position open at 0.05 lot, a second entry (even if position count allows it) would double exposure. Total lot exposure should be checked.
- **Symbol-specific exposure** — no two positions on the same symbol (avoid accidental pyramiding on the same instrument).
- **Correlated pair exposure** — e.g., EUR/USD and GBP/USD both long is higher correlation risk than EUR/USD long + USD/JPY short.

For the first implementation, total open positions check is sufficient. Correlated pair exposure can be added later.

---

## 7. Opportunity Score

**File:** `src/qader_app/services/scanner_service.py` — `MarketScanResult`

Currently `MarketScanResult` has `confidence` (0.0–1.0 from SignalArbiter) but no `opportunity_score` (0–100).

**Required: Opportunity Score calculation:**

```python
def compute_opportunity_score(
    arb_confidence: float,         # 0.0-1.0 from SignalArbiter
    agent_agreement: int,          # number of agents that agree (0-3)
    spread_points: float,          # current spread
    max_spread_points: float,      # from risk config for this symbol
    atr: float,                    # current ATR (volatility)
    min_atr: float,                # minimum acceptable ATR
    max_atr: float,                # maximum acceptable ATR (avoid high-vol blowups)
    session_quality: float,        # 0.0-1.0 from session filter
    htf_aligned: bool,             # HTF D1 bias matches signal
    recent_dna_score: float,       # strategy DNA score (0.0-1.0)
) -> int:  # 0-100
    score = 0.0
    score += arb_confidence * 40         # confidence accounts for 40 points
    score += (agent_agreement / 3) * 20  # agent agreement: 20 points
    spread_ok_pct = max(0, 1 - spread_points / max_spread_points)
    score += spread_ok_pct * 10          # spread quality: 10 points
    atr_in_range = min_atr <= atr <= max_atr
    score += 10 if atr_in_range else 0   # ATR in range: 10 points
    score += session_quality * 10        # session quality: 10 points
    score += 5 if htf_aligned else 0     # HTF alignment: 5 points
    score += recent_dna_score * 5        # DNA score: 5 points
    return min(100, int(score))
```

**Opportunity score thresholds per profile:**
- Conservative: 85+
- Balanced: 78+
- Aggressive: 70+
- Extreme: 62+

These thresholds act as a final gate before submitting the execution request. Even if all pipeline stages (Arbiter, ConflictGuard, RiskGovernor) pass, an opportunity score below the profile threshold should result in HOLD.

---

## 8. ATR and Spread Filters

### ATR Filter
Current `main_loop.py` computes ATR for SL/TP sizing. For live trading, ATR-based filters should also block entry if:
- ATR is too low (market is dead — very tight range, spreads likely dominate)
- ATR is too high (extreme volatility — SL could be hit by noise)

Suggested thresholds (symbol-specific, tunable in genome):
- `min_atr_pips`: 3 (block if market too quiet)
- `max_atr_pips`: 50 (block if abnormally volatile)

### Spread Filter
Already in `RiskManager.validate()` via `max_spread_points`. Must also be in RiskGovernor for explicit block before lot computation.

---

## 9. Margin Check

`RiskManager.validate()` currently sets `margin_ok=True` unconditionally. For live trading:

```python
# Required margin check:
import MetaTrader5 as mt5
order_margin_req = mt5.order_calc_margin(
    mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL,
    symbol, lot, price
)
free_margin = float(mt5.account_info().margin_free)
margin_ok = order_margin_req is not None and free_margin >= order_margin_req * 1.5  # 50% safety buffer
```

Without this check, orders can fail at the broker level with REQUOTE or MARGIN_ERROR — the order send returns success=False but a position may have been partially entered.

---

## 10. Risk Integration Into Execution Gate

When `RiskGovernor.compute_lot()` is implemented, the `ExecutionManager.validate_real_controlled_request()` must be updated:

Current gate: `lot_fixed: abs(req.lot - fixed_lot) < 1e-9` (exact match)

Required: `lot_within_dynamic_range: min_lot <= req.lot <= max_lot_for_profile`

The exact-lot-match gate must be replaced with a range check, otherwise equity-based sizing will fail the gate on every order.

---

## 11. Risk Review Summary

| Item | Status | Required Action |
|---|---|---|
| Spread filter | ✅ EXISTS | Already in RiskManager |
| Max open positions | ✅ EXISTS | Already in RiskManager |
| Daily loss % check | ✅ EXISTS | Already in RiskManager |
| Kill switch | ✅ EXISTS | Already in RiskManager |
| Equity-based lot sizing | ❌ MISSING | Build RiskGovernor |
| Risk profiles (4 modes) | ❌ MISSING | Add to genome + config + UI |
| Session loss tracking | ❌ MISSING | Add to LiveAutopilotService |
| Opportunity score | ❌ MISSING | Add to MarketScanResult |
| ATR range filter | ❌ MISSING | Add to RiskGovernor |
| Margin check | ❌ MISSING | Add to RiskGovernor |
| Dynamic lot gate in ExecutionManager | ❌ INCOMPATIBLE | Update fixed_lot gate |
| Exposure limit (total lot) | ⚠️ PARTIAL | Position count ok; lot sum missing |
