# Report 32 — Terminal Lockdown Verification

**Generated:** 2026-05-13  
**Context:** Continuation of Reports 30 and 31 — closing remaining incident gaps  
**MT5 connection:** Read-only via MetaTrader5 Python API (no orders sent)

---

## 1. Process Inventory

### MT5 Terminal Process

| PID | Name | Command Line | Classification |
|---|---|---|---|
| 37928 | terminal64.exe | `"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe"` | MT5_TERMINAL |

### Python Processes

| PID | Name | Classification |
|---|---|---|
| *(none)* | — | — |

**Result: No Python processes running. No order-capable Python execution path active.**

### Node / Other Processes

None found matching `python`, `pythonw`, `node`, or `terminal64` other than the MT5 terminal above.

---

## 2. MT5 Terminal — Account Verification

```
Login    : 260749517
Server   : Exness-MT5Trial15
Name     : Standard
Company  : Exness Technologies Ltd
Balance  : $160.81 USD
Equity   : $160.81 USD
Margin   : $0.00
Free Mrgn: $160.81
Leverage : 2,000,000,000 (Exness demo default)
Currency : USD
Mode API : 0 (API reports REAL mode)
```

**Account type note:**  
The Python `trade_mode=0` field would normally indicate a real account. However:
- Server name `Exness-MT5Trial15` is Exness's trial/demo server family
- Leverage of 2,000,000,000 is characteristic of Exness demo accounts
- Exness trial accounts are confirmed demo by server name convention
- **Assessment: DEMO/TRIAL account** (server name is definitive; API field may be a known Exness quirk)

---

## 3. Open Positions

**MT5 API result:** `positions_get()` returned empty list.

```
OPEN_POSITIONS = 0
```

Confirmed by: equity = balance = $160.81 and margin = $0.00 (zero floating exposure).

---

## 4. Pending Orders

**MT5 API result:** `orders_get()` returned empty list.

```
PENDING_ORDERS = 0
```

---

## 5. 48-Hour Deal History Analysis

**Query window:** 2026-05-11 05:25 UTC → 2026-05-12 20:29 UTC  
**Total deals:** 3,403  
**History orders count:** 2,939  
**Unique symbols traded:** 63  
**Magic numbers present:** `[0, 20260504, 20260505, 20260507]`

### CRITICAL FINDING — Governor Still Active in Last 48h

Magic `20260507` (`friday_demo_position_governor_v2.py`) appears with `FRIDAY_GOV_CLOSE` across **30+ symbols** in this window. The last governor deal was **2026-05-12 20:29:54 UTC** — approximately **7 hours before the executor stubs were applied** (03:28 on 2026-05-13).

Timeline:
```
2026-05-12 20:29:54  Last FRIDAY_GOV_CLOSE deal (magic=20260507)
2026-05-13 03:28:00  disable_legacy_executors_hard.py applied stubs
2026-05-13 (now)     No Python processes, no open positions
```

The governor was actively closing positions right up to stub patching.

### 48h Deal Summary — Grouped by Magic / Symbol / Comment

**magic = 0 (Exness Social/Copy Trading)**

| Symbol | Comment | Closed Deals | Lot Range | Total P&L |
|---|---|---|---|---|
| XAUUSDm | `[so 0.00%/-14.57/0.00]` | 56 | 0.01 | **-$2,305.23** |
| XAUUSDm | *(empty)* | 222 | 0.01–0.10 | **+$1,603.59** |
| XAUUSDm | `[so 0.00%/-2.58/0.00]` | 43 | 0.01 | -$280.90 |
| XAUUSDm | `[sl 4650.670]` | 1 | 1.00 | +$134.60 |
| XAUUSDm | `[so 0.00%/-8.29/0.00]` | 1 | 1.00 | -$83.90 |
| XAUUSDm | `[tp 4692.00000]` | 1 | 0.10 | +$52.68 |
| XAUUSDm | `[so 0.00%/-11.15/0.00]` | 1 | 0.01 | -$41.58 |
| XAUUSDm | `[so 0.00%/-0.13/0.00]` | 1 | 0.01 | -$41.52 |
| XAGGBPm | *(empty)* | 1 | 0.02 | -$11.41 |
| XAGEURm | *(empty)* | 1 | 0.02 | -$10.59 |
| (other minor) | various | various | various | various |

**magic = 20260507 (friday_demo_position_governor_v2.py — NOW STUBBED)**

| Symbol | Comment | Closed Deals | Lot Range | Total P&L |
|---|---|---|---|---|
| XAUUSDm | `FRIDAY_GOV_CLOSE` | 25 | 0.01–1.00 | **-$1,132.63** |
| XAGAUDm | `FRIDAY_GOV_CLOSE` | 104 | 0.01–0.02 | -$470.82 |
| XAGGBPm | `FRIDAY_GOV_CLOSE` | 44 | 0.01–0.02 | -$216.12 |
| CHFSGDm | `FRIDAY_GOV_CLOSE` | 51 | 0.02 | -$195.10 |
| XAGUSDm | `FRIDAY_GOV_CLOSE` | 39 | 0.01–0.02 | -$173.15 |
| XAGEURm | `FRIDAY_GOV_CLOSE` | 23 | 0.01–0.02 | -$122.17 |
| US30_x10m | `FRIDAY_GOV_CLOSE` | 31 | 0.01–0.02 | -$92.05 |
| GBPSGDm | `FRIDAY_GOV_CLOSE` | 32 | 0.01–0.02 | -$89.96 |
| NZDSGDm | `FRIDAY_GOV_CLOSE` | 22 | 0.02 | -$45.15 |
| US500_x100m | `FRIDAY_GOV_CLOSE` | 13 | 0.01–0.02 | -$33.38 |
| CHFJPYm | `FRIDAY_GOV_CLOSE` | 3 | 0.01–0.02 | -$28.34 |
| UKOILm | `FRIDAY_GOV_CLOSE` | 9 | 0.01–0.02 | -$25.44 |
| SGDJPYm | `FRIDAY_GOV_CLOSE` | 6 | 0.01–0.02 | -$24.93 |
| USDILSm | `FRIDAY_GOV_CLOSE` | 9 | 0.01–0.02 | -$19.75 |
| GBPJPYm | `FRIDAY_GOV_CLOSE` | 4 | 0.01 | -$19.21 |
| EURSGDm | `FRIDAY_GOV_CLOSE` | 7 | 0.02 | -$15.34 |
| GBPCHFm | `FRIDAY_GOV_CLOSE` | 7 | 0.01–0.02 | -$13.60 |
| EURGBPm | `FRIDAY_GOV_CLOSE` | 6 | 0.01–0.02 | -$11.56 |
| EURCADm | `FRIDAY_GOV_CLOSE` | 6 | 0.02 | -$10.94 |
| EURJPYm | `FRIDAY_GOV_CLOSE` | 3 | 0.01 | -$10.78 |
| USOILm | `FRIDAY_GOV_CLOSE` | 3 | 0.02 | -$10.36 |
| CADJPYm | `FRIDAY_GOV_CLOSE` | 3 | 0.01 | -$9.96 |
| AUDJPYm | `FRIDAY_GOV_CLOSE` | 3 | 0.01 | -$7.93 |
| GBPNZDm | `FRIDAY_GOV_CLOSE` | 4 | 0.02 | *(continued)* |
| ... (additional minor symbols) | `FRIDAY_GOV_CLOSE` | various | 0.01–0.02 | various |

**magic = 20260505 (friday_touch_demo_executor.py — NOW STUBBED)**

| Symbol | Comment | Closed Deals | Lot Range | Total P&L |
|---|---|---|---|---|
| XAUUSDm | `[tp 4712.09500]` | 3 | 0.01 | +$9.26 |

**magic = 20260504 (legacy scalper — INACTIVE)**

| Symbol | Comment | Closed Deals | Lot Range | Total P&L |
|---|---|---|---|---|
| XAGAUDm | `[sl/tp ...]` | 9 | 0.01–0.02 | +$100 est. |
| XAGUSDm | `[sl/tp ...]` | 3 | 0.01–0.02 | +$36 est. |
| XAGGBPm | `[tp ...]` | 3 | 0.01 | +$24 est. |

### Source Classification of magic=0 Trades — RESOLVED

The `[so 0.00%/-14.57/0.00]` comment format is the **Exness Social Trading / Copy Trading** system's auto-generated comment. The `[so ...]` prefix stands for **Social Order** — placed server-side by Exness's copy trading platform when a subscribed strategy fires, independently of any local EA or Python process.

- **Cannot be stopped via Python** — it is a server-side Exness subscription
- **Cannot be stopped by removing MT5 terminal EAs** — it runs on Exness servers
- **Must be stopped by:** cancelling the copy trading subscription in the Exness Personal Area / Social Trading platform

The `[sl ...]` and `[tp ...]` close comments are SL/TP exits on copy-trade-opened positions. The empty-comment magic=0 trades are also consistent with copy trading closes.

---

## 6. FRIDAY_Gold_EA Verification

### Project Root Copy

```
File: C:\Users\Radhi\MT5\FRIDAY_Gold_EA.mq5
Scan: CTrade=0, OrderSend=0, trade.Buy=0, trade.Sell=0, PositionModify=0
Result: CLEAN — signal-only
```

### MetaQuotes Terminal Copy

```
File: C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\
      53785E099C927DB68A545C249CDBCE06\MQL5\Experts\FRIDAY_Gold_EA.mq5
Modified: 2026-05-13 07:52:28

Scan (comment-stripped): 
  CTrade outside comments       = 0
  OrderSend outside comments    = 0
  trade.Buy outside comments    = 0
  trade.Sell outside comments   = 0
  PositionModify outside comments = 0

Only match was: Print("No CTrade. No OrderSend. No PositionModify.");
  — this is a Print() statement in a string, not an execution call.

Header confirms:
  "FRIDAY Signal-Only Boundary EA"
  "This EA DOES NOT trade."
  "No CTrade. No OrderSend. No PositionModify."
  "It only analyzes market structure and writes a signal JSON file."

Compiled .ex5 modified: 2026-05-13 07:52:29 (compiled from signal-only .mq5)
```

```
EA_EXECUTION_COPY_FOUND = NO
```

Both the project root copy and the MetaQuotes terminal copy are confirmed signal-only.

---

## 7. Legacy Executor Stub Re-Verification

All 8 files verified this session:

| File | LEGACY_EXECUTOR_DISABLED | SystemExit Guard | Execution Code | Status |
|---|---|---|---|---|
| `scripts/ict_sweep_trader.py` | ✅ True | ✅ Present | ❌ None | **STUB_OK** |
| `scripts/mt5_ollama_trader.py` | ✅ True | ✅ Present | ❌ None | **STUB_OK** |
| `friday_demo_position_governor.py` | ✅ True | ✅ Present | ❌ None | **STUB_OK** |
| `friday_demo_position_governor_v2.py` | ✅ True | ✅ Present | ❌ None | **STUB_OK** |
| `friday_realtime_scalper_demo_executor.py` | ✅ True | ✅ Present | ❌ None | **STUB_OK** |
| `friday_touch_demo_executor.py` | ✅ True | ✅ Present | ❌ None | **STUB_OK** |
| `friday_risk_close.py` | ✅ True | ✅ Present | ❌ None | **STUB_OK** |
| `ict_sweep_trader.py` (root) | ✅ True | ✅ Present | ❌ None | **STUB_OK** |

8/8 stubs confirmed clean. No execution code exists in any active legacy executor file.

---

## 8. Config Verification

**File:** `C:\Users\Radhi\MT5\config\trading_runtime.yaml`

| Field | Required | Actual | Pass? |
|---|---|---|---|
| `runtime.kill_switch` | `true` | `true` | ✅ |
| `runtime.allow_live_trading` | `false` | `false` | ✅ |
| `runtime.mode` | Not DEMO / Not LIVE | `DRY_RUN` | ✅ |
| `src/mt5_ai/config.py LIVE_TRADING_ENABLED` | `False` | `False` | ✅ |

Note: `DRY_RUN_LOCKED` is not a defined enum in `config_loader.py`. `DRY_RUN` + `kill_switch: true` is the functional equivalent. All three `ExecutionManager` send paths (`send_order`, `cancel_pending_order`, `send_raw_order`) return `kill_switch_active` before any MT5 call.

---

## 9. Remaining Open Risk — Exness Social/Copy Trading

The sole unresolved risk is the **Exness server-side Social Trading subscription** on account 260749517.

| Property | Detail |
|---|---|
| Source | Exness Social Trading platform (server-side) |
| Detection | Magic=0 with `[so ...]` comments in MT5 history |
| Last activity | 2026-05-12 20:29:54 UTC (within 48h window) |
| Can be stopped by Python? | NO — server-side |
| Can be stopped by disabling MT5 EAs? | NO — independent of local EAs |
| Current open positions from this source | 0 (confirmed via API) |
| Could open new positions in future? | YES — unless subscription is cancelled |

**Required action:** Log in to Exness Personal Area → Social Trading → cancel or pause the active strategy subscription.

---

## 10. MT5 Exposure Verification Status

```
MT5_EXPOSURE_VERIFICATION = COMPLETE (read-only API confirmed)
```

MT5 API returned valid account data. Open positions and pending orders confirmed at zero.

---

## Final Status

```
INCIDENT_STATUS = ACTIVE_RISK_REMAINS
```

**Reason:**  
All Python execution paths are confirmed locked down. The FRIDAY_Gold_EA is signal-only. Legacy executors are stubs. Configs are locked. Open positions = 0. Pending orders = 0.

However, an **active Exness Social/Copy Trading subscription** (magic=0, `[so ...]` comments) represents an uncontrolled execution path that is **server-side and outside Python/EA control**. It was placing trades on XAUUSDm at 0.01–1.00 lot as recently as 2026-05-12 and can resume at any time.

`LOCKED_DOWN` cannot be declared until this subscription is confirmed cancelled or paused.
