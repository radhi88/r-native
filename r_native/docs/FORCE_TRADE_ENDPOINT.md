# FORCE TRADE Endpoint — `/api/r/force_trade`

This endpoint lives in **`brain_server.py`** (outside the `r_native/` repo).
Documented here for portability.

## Endpoint
**`POST http://127.0.0.1:5055/api/r/force_trade`**

Bypasses ALL gates and fires a paper-mode test trade via `mt5.order_send()`.
Auto-picks safe SL/TP based on the symbol's current spread × 5 (avoids the
broker's "invalid stops" rejection on wide-spread symbols like crypto).

## Request body (JSON)
```json
{
  "symbol":  "BTCUSDm",        // required
  "side":    "BUY",             // BUY or SELL (default BUY)
  "lot":     0.01,              // optional, default 0.01
  "sl_pts":  500,               // optional — server auto-picks safe min
  "tp_pts":  500,               // optional
  "comment": "R_TEST"           // optional, max 31 chars
}
```

## Response (JSON)
```json
{
  "ok":      true,
  "retcode": 10009,             // TRADE_RETCODE_DONE = filled
  "order":   1668936293,
  "deal":    1542041913,
  "price":   76724.28,
  "sl":      76647.28,
  "tp":      76801.28,
  "side":    "BUY",
  "symbol":  "BTCUSDm",
  "volume":  0.01,
  "request": {"lot": 0.01, "sl_pts": 7700, "tp_pts": 7700}
}
```

## R Native UI integration
`r_native/app.py:_action_force_trade()` calls this endpoint when the user
clicks the **🔫 FIRE TEST TRADE** button in the vault tab's action bar.

## Magic number
`20260605` — same as R Executor. Trades appear in:
- MT5 terminal positions tab
- R Native LIVE tab (live position table)
- R Native Hero strip (open_pl + pixel mascot reacts)
- Brain server `/api/account` attribution
- Telegram bot (if enabled) via trade-event watcher

## Safety
- ALWAYS PAPER (uses MT5 demo account)
- Auto SL/TP at 5× spread to avoid "invalid stops"
- Lot capped at broker's volume_min
- **No daily-cap check** — this bypasses ALL gates including DD limit
- Use ONLY for testing the pipeline end-to-end

## When to use
- Verify end-to-end pipeline works (Hero P/L updates, mascot reacts, sounds)
- Test SL/TP placement against current spread
- Generate live trade history for the dashboard
- Demo the system to others

## When NOT to use
- Production trading — use the R Executor with `deployed_genome` instead
- On a funded/live account — bypasses prop firm safety gates
