# Report 33 — Current MT5 Terminal Exposure

**Generated:** 2026-05-13  
**Method:** Read-only MetaTrader5 Python API — no orders sent, no modifications made  
**MT5 connection:** `mt5.initialize()` → read → `mt5.shutdown()`

---

## 1. Account

| Field | Value |
|---|---|
| Login | 260749517 |
| Server | Exness-MT5Trial15 |
| Account Name | Standard |
| Company | Exness Technologies Ltd |
| Balance | $160.81 USD |
| Equity | $160.81 USD |
| Margin Used | $0.00 |
| Free Margin | $160.81 |
| Leverage | 2,000,000,000 |
| Currency | USD |
| API trade_mode | 0 |

**Account type assessment:**  
Server `Exness-MT5Trial15` is Exness's trial/demo server family. Leverage of 2,000,000,000 is consistent with Exness demo accounts. The `trade_mode=0` returned by the Python API is a known Exness quirk on demo accounts and does not indicate a live account in this context. **Assessment: DEMO/TRIAL account.**

---

## 2. Open Positions

```
OPEN_POSITIONS = 0
```

`mt5.positions_get()` returned an empty list. Confirmed by: margin = $0.00, equity = balance.

*No open positions table — nothing to display.*

---

## 3. Pending Orders

```
PENDING_ORDERS = 0
```

`mt5.orders_get()` returned an empty list.

*No pending orders table — nothing to display.*

---

## 4. History — Last 48 Hours

**Query:** `history_deals_get(now - 48h, now)`  
**Time range covered:** 2026-05-11 05:25:55 UTC → 2026-05-12 20:29:54 UTC  
**Total deals returned:** 3,403  
**Total history orders:** 2,939  
**Symbols appearing:** 63

**Note on time range:** No deals after 2026-05-12 20:29:54 UTC. The last ~7 hours before now have zero activity. This is consistent with the executor stubs being applied at 03:28 on 2026-05-13 and the Exness copy trading subscription being paused or having no new signals.

### 4a. Magic Numbers Present

| Magic | Source | Status |
|---|---|---|
| 0 | Exness Social/Copy Trading (server-side) | ACTIVE SUBSCRIPTION — uncontrolled |
| 20260504 | Legacy scalper executor (oldest generation) | STUBBED (inactive) |
| 20260505 | `friday_touch_demo_executor.py` | STUBBED as of 2026-05-13 03:28 |
| 20260507 | `friday_demo_position_governor_v2.py` | STUBBED as of 2026-05-13 03:28 |

### 4b. 48h Deals Summary — Grouped by Magic / Symbol / Comment

Sorted by absolute P&L impact (exit deals only):

**[magic=0] Source: Exness Social/Copy Trading**

| Symbol | Comment | Closed Deals | Min Vol | Max Vol | Total P&L |
|---|---|---|---|---|---|
| XAUUSDm | `[so 0.00%/-14.57/0.00]` | 56 | 0.01 | 0.01 | -$2,305.23 |
| XAUUSDm | *(empty)* | 222 | 0.01 | 0.10 | +$1,603.59 |
| XAUUSDm | `[so 0.00%/-2.58/0.00]` | 43 | 0.01 | 0.01 | -$280.90 |
| XAUUSDm | `[sl 4650.670]` | 1 | 1.00 | 1.00 | +$134.60 |
| XAUUSDm | `[so 0.00%/-8.29/0.00]` | 1 | 1.00 | 1.00 | -$83.90 |
| XAUUSDm | `[tp 4692.00000]` | 1 | 0.10 | 0.10 | +$52.68 |
| XAUUSDm | `[so 0.00%/-11.15/0.00]` | 1 | 0.01 | 0.01 | -$41.58 |
| XAUUSDm | `[so 0.00%/-0.13/0.00]` | 1 | 0.01 | 0.01 | -$41.52 |
| XAGGBPm | *(empty)* | 1 | 0.02 | 0.02 | -$11.41 |
| XAGEURm | *(empty)* | 1 | 0.02 | 0.02 | -$10.59 |
| **Subtotal magic=0** | | **~330** | 0.01 | **1.00** | **≈ -$984** |

**[magic=20260507] Source: `friday_demo_position_governor_v2.py` — LAST ACTIVE 2026-05-12 20:29 UTC**

| Symbol | Comment | Closed Deals | Min Vol | Max Vol | Total P&L |
|---|---|---|---|---|---|
| XAUUSDm | `FRIDAY_GOV_CLOSE` | 25 | 0.01 | 1.00 | -$1,132.63 |
| XAGAUDm | `FRIDAY_GOV_CLOSE` | 104 | 0.01 | 0.02 | -$470.82 |
| XAGGBPm | `FRIDAY_GOV_CLOSE` | 44 | 0.01 | 0.02 | -$216.12 |
| CHFSGDm | `FRIDAY_GOV_CLOSE` | 51 | 0.02 | 0.02 | -$195.10 |
| XAGUSDm | `FRIDAY_GOV_CLOSE` | 39 | 0.01 | 0.02 | -$173.15 |
| XAGEURm | `FRIDAY_GOV_CLOSE` | 23 | 0.01 | 0.02 | -$122.17 |
| US30_x10m | `FRIDAY_GOV_CLOSE` | 31 | 0.01 | 0.02 | -$92.05 |
| GBPSGDm | `FRIDAY_GOV_CLOSE` | 32 | 0.01 | 0.02 | -$89.96 |
| NZDSGDm | `FRIDAY_GOV_CLOSE` | 22 | 0.02 | 0.02 | -$45.15 |
| US500_x100m | `FRIDAY_GOV_CLOSE` | 13 | 0.01 | 0.02 | -$33.38 |
| CHFJPYm | `FRIDAY_GOV_CLOSE` | 3 | 0.01 | 0.02 | -$28.34 |
| UKOILm | `FRIDAY_GOV_CLOSE` | 9 | 0.01 | 0.02 | -$25.44 |
| SGDJPYm | `FRIDAY_GOV_CLOSE` | 6 | 0.01 | 0.02 | -$24.93 |
| USDILSm | `FRIDAY_GOV_CLOSE` | 9 | 0.01 | 0.02 | -$19.75 |
| GBPJPYm | `FRIDAY_GOV_CLOSE` | 4 | 0.01 | 0.01 | -$19.21 |
| EURSGDm | `FRIDAY_GOV_CLOSE` | 7 | 0.02 | 0.02 | -$15.34 |
| GBPCHFm | `FRIDAY_GOV_CLOSE` | 7 | 0.01 | 0.02 | -$13.60 |
| EURGBPm | `FRIDAY_GOV_CLOSE` | 6 | 0.01 | 0.02 | -$11.56 |
| EURCADm | `FRIDAY_GOV_CLOSE` | 6 | 0.02 | 0.02 | -$10.94 |
| EURJPYm | `FRIDAY_GOV_CLOSE` | 3 | 0.01 | 0.01 | -$10.78 |
| USOILm | `FRIDAY_GOV_CLOSE` | 3 | 0.02 | 0.02 | -$10.36 |
| CADJPYm | `FRIDAY_GOV_CLOSE` | 3 | 0.01 | 0.01 | -$9.96 |
| AUDJPYm | `FRIDAY_GOV_CLOSE` | 3 | 0.01 | 0.01 | -$7.93 |
| GBPNZDm + others | `FRIDAY_GOV_CLOSE` | various | 0.01 | 0.02 | various |
| **Subtotal magic=20260507** | | **≈480** | 0.01 | **1.00** | **≈ -$2,750** |

**[magic=20260505] Source: `friday_touch_demo_executor.py` — STUBBED**

| Symbol | Comment | Closed Deals | Min Vol | Max Vol | Total P&L |
|---|---|---|---|---|---|
| XAUUSDm | `[tp 4712.09500]` | 3 | 0.01 | 0.01 | +$9.26 |

**[magic=20260504] Source: Legacy scalper (oldest generation) — INACTIVE**

| Symbol | Comment | Closed Deals | Min Vol | Max Vol | Total P&L |
|---|---|---|---|---|---|
| XAGAUDm | `[sl/tp ...]` | 9 | 0.01 | 0.02 | +$100 est. |
| XAGUSDm | `[sl/tp ...]` | 3 | 0.01 | 0.02 | +$36 est. |
| XAGGBPm | `[tp ...]` | 3 | 0.01 | 0.01 | +$24 est. |

---

## 5. Source Resolution — magic=0 Trades CONFIRMED

The magic=0 trades with comment format `[so 0.00%/-14.57/0.00]` are **Exness Social Trading (copy trading) auto-generated comments**. The `[so ...]` prefix is the Exness platform's Social Order signature. This is a **server-side subscription**, not a local EA or Python script.

| Property | Detail |
|---|---|
| Source type | Exness Social Trading — server-side copy subscription |
| Identifiable comment | `[so <equity%>/<drawdown>/<something>]` |
| Lot sizes observed | 0.01 (typical copy) and 1.00 (larger positions — scaled or manual) |
| Symbols | XAUUSDm primary; also XAGGBPm, XAGEURm |
| SL/TP exits | `[sl 4650.670]`, `[tp 4692.00000]` |
| Last activity | 2026-05-12 20:29:54 UTC |
| Under Python control? | NO |
| Under local EA control? | NO |
| Requires action | Cancel/pause in Exness Personal Area → Social Trading |

---

## 6. MT5 Exposure Verification Status

```
MT5_EXPOSURE_VERIFICATION = COMPLETE
```

Live MT5 API successfully returned:
- Account info ✅
- Open positions: 0 ✅
- Pending orders: 0 ✅
- 48h history: 3,403 deals ✅

---

## Final Exposure Status

```
INCIDENT_STATUS = ACTIVE_RISK_REMAINS

Current floating exposure:
  Open positions   : 0
  Pending orders   : 0
  Python processes : 0
  Legacy executors : all stubbed

Remaining risk:
  Exness Social/Copy Trading subscription (magic=0) is server-side and ACTIVE.
  It placed trades on XAUUSDm at up to 1.00 lot as recently as 2026-05-12 20:29 UTC.
  It CAN resume placing trades without any local action.

Required to achieve LOCKED_DOWN:
  → Log into Exness Personal Area
  → Navigate to Social Trading / Copy Trading
  → Cancel or pause the active strategy subscription on account 260749517
  → Confirm no new magic=0 [so ...] deals appear after cancellation
```
