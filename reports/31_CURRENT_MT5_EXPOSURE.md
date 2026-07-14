# Report 31 — Current MT5 Exposure

**Generated:** 2026-05-13  
**Context:** Post-incident lockdown audit  
**Method:** Static analysis — no live MT5 connection available

---

## 1. Python-Side Execution — Confirmed Offline

| Component | Last Active | Last Known State |
|---|---|---|
| algory_runner.py | 2026-05-13 00:44 UTC | 0 open positions, paper=True, offline now |
| friday_orchestrator.py | Not running | Offline |
| friday_demo_position_governor_v2.py | 2026-05-06 02:03 (last log) | NOW STUB — cannot run |
| friday_touch_demo_executor.py | 2026-05-05 (trade learner records) | NOW STUB — cannot run |
| friday_realtime_scalper_demo_executor.py | Unknown | NOW STUB — cannot run |
| friday_health_monitor.py | Unknown | Offline |
| All other friday_*.py | Unknown | Offline |

**Active Python processes at audit time:** 0

---

## 2. Known Historical Open Exposure (Pre-Lockdown)

### From `friday_trade_outcome_learner.log`

Trades with magic=20260505 on **XAUUSDm** (FRIDAY_TOUCH_pro executor):
- Multiple LEARNED WIN/LOSS entries from 2026-05-05 02:36 UTC
- These are **closed historical trades** — the learner only records closed P&L

### From governor_v2 logs (position_governor_logs/)

The governor v2 ran on:
- 2026-05-05 02:19 through 2026-05-06 02:03 (6 sessions)
- It managed positions with magic_values `{20260504, 20260505, 20260506, 20260507}`
- It placed `FRIDAY_GOV_CLOSE` orders to close and optionally reverse positions

**All governor-managed positions were action=CLOSE or CLOSE_AND_REVERSE** — the governor was designed to exit, not to hold. Positions it managed are likely closed.

### From algory_runner heartbeat

Last recorded: `2026-05-13 00:44 — 0 open positions`  
Mode: `paper=True` — no real positions were ever opened by Algory in this session.

---

## 3. Current Open Positions — CANNOT VERIFY

**Live MT5 query not possible:** No Python process is running and no MT5 connection is available
in this audit session.

**What is unknown:**
- Whether any positions opened by legacy executors (magic 20260504-20260507) remain open
- Whether any positions were opened by the magic=0 source (MT5 native EA or manual)
- Current account balance and equity

**What is known:**
- Algory had 0 open at 00:44 on 2026-05-13 and is now offline
- The governor's last run was 2026-05-06 — if it closed all positions then, they have been closed for ~7 days
- Touch executor's last recorded trades were 2026-05-05 — similarly, ~8 days ago

**Risk assessment:** Residual open positions from Python legacy executors are unlikely but cannot be ruled out. The magic=0 source is fully unknown.

---

## 4. Pending Orders — CANNOT VERIFY

Same limitation: no live MT5 connection. The algory_runner does cancel its own pending orders
on shutdown, but it was running in paper mode so no real pending orders were placed by it.

---

## 5. Magic=0 Trade Source — UNRESOLVED

| Attribute | Detail |
|---|---|
| Magic number | 0 (no magic set) |
| Lots observed | 0.1 and 1.0 |
| Symbols | XAUUSDm, AUDUSDm |
| Origin | NOT Python — Python always sets magic ≥ 20260504 |
| Likely source | MT5 terminal EA (MQL5 Expert Advisor) OR manual terminal trades |
| Confirmed stopped | ❌ UNKNOWN |

**To verify:** Open MT5 terminal → Tools → Expert Advisors (or Experts panel) — look for any active EA on XAUUSDm or AUDUSDm charts.

---

## 6. Account Risk — Estimated

Because no live connection exists, this is a worst-case estimate based on historical data:

| Scenario | Estimated Exposure |
|---|---|
| Best case (all positions closed by governors) | $0.00 open |
| Worst case (old touch/governor positions still open) | Unknown — trades were 0.01–0.05 lot range |
| Magic=0 source still active | Unknown — lots were 0.1 and 1.0 (significant for XAUUSDm) |

**XAUUSDm at 1.0 lot:** Each 100-point move = ~$100 USD exposure (significant on demo or small live account).

---

## 7. Actions Required to Establish Ground Truth

```
PRIORITY 1 (Immediate):
  → Open MT5 terminal
  → Check "Trade" tab for any open positions
  → Check "Orders" tab for any pending orders
  → Disable/remove all Expert Advisors from XAUUSDm and AUDUSDm charts

PRIORITY 2 (Before any restart):
  → Close all open positions if any exist
  → Confirm account equity = account balance (no floating P&L)
  → Run: python -c "import MetaTrader5 as mt5; mt5.initialize(); print(mt5.positions_get())"
    (as a one-off terminal command — not a FRIDAY service)

PRIORITY 3 (Documentation):
  → Record: what positions were open, what EA was running, manual close confirmation
```

---

## 8. Config Lock State at Time of Report

```yaml
# trading_runtime.yaml — verified this session
runtime:
  mode: DRY_RUN           # blocks new orders through ExecutionManager
  allow_live_trading: false
  kill_switch: true        # blocks ALL orders through ExecutionManager

# src/mt5_ai/config.py
LIVE_TRADING_ENABLED = False  # line 138 — verified this session
```

All Python execution paths are blocked. Risk remains only from the MT5 terminal itself.

---

## Final Exposure Status

```
INCIDENT_STATUS = ACTIVE_RISK_REMAINS

Reason:
  1. Magic=0 trade source (0.1–1.0 lot, XAUUSDm/AUDUSDm) NOT identified, NOT confirmed stopped.
  2. Current MT5 open positions CANNOT be verified without live connection.
  3. MT5 terminal EA audit required before LOCKED_DOWN can be declared.

Python-side is LOCKED DOWN.
MT5 terminal-side is UNVERIFIED.
```
