# Python → MT5 Chart Drawing Bridge

> The Python brain writes structured drawing instructions into `brain.json`.
> An MT5 EA (`FRIDAY_Brain_Executor.mq5`) polls the file (~1 Hz) and renders
> the `drawings[]` array onto the chart using MQL5 graphics objects.
>
> **Guarantees**: idempotent updates (deterministic IDs), per-symbol filtering,
> staleness pruning, zero-flicker re-renders.

---

## 1. JSON Schema for `drawings[]`

### Common envelope

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Deterministic — see ID strategy below |
| `type` | enum | yes | `rectangle`, `hline`, `trendline`, `arrow`, `label`, `fib_levels` |
| `symbol` | string | yes | EA renders only if `symbol == _Symbol` |
| `tf` | string | optional | `m1`, `m5`, `h1`, etc. (informational) |
| `created_at` | int (epoch UTC) | yes | For TTL pruning |
| `ttl_sec` | int | optional | Default `86400` (24 h) |
| `style` | object | optional | `{color, width, line_style, fill, transparent, zorder}` |
| `meta` | object | optional | Free-form: confidence, pattern subtype, status |

### ID strategy

```
{type_prefix}_{md5_8(logical_key)}
```

Prefixes: `r_` rect, `h_` hline, `t_` trendline, `a_` arrow, `lbl_` label,
`fib_` fib. The EA prepends `FRIDAY_` to every MT5 object name to avoid
colliding with manually drawn objects.

Deterministic IDs (MD5 of the logical key) make updates idempotent —
republishing the same OB on the next tick reuses the same MQL5 object name,
so it updates in place rather than flicker-recreating.

### Type-by-type

**`rectangle`** (Order Block, FVG) — needs `ts_start, ts_end, price_high, price_low`.

**`hline`** (liquidity, SL, TP, IDM) — needs `price`, optional `label`.

**`trendline`** (BOS, CHoCH) — needs `ts1, price1, ts2, price2`, optional `label`.

**`arrow`** (entry, sweep) — needs `ts, price, arrow_code` (Wingdings: 233 up,
234 down, 251 X, 159 dot), optional `anchor`.

**`label`** (narrative text) — needs `ts, price, text` (UTF-8, Arabic supported
via `meta.font = "Tahoma"` and `meta.rtl = true`).

**`fib_levels`** — needs `ts1, price1, ts2, price2, levels: [floats]`.

### Default styling

| Pattern | Color | Width | Style | Fill |
|---|---|---|---|---|
| Bullish OB | `#26A69A` | 1 | solid | yes, transparent 70 |
| Bearish OB | `#EF5350` | 1 | solid | yes, transparent 70 |
| Mitigated zone | (same) | 1 | solid | yes, transparent 90 (faded) |
| Bullish FVG | `#42A5F5` | 0 | — | yes, transparent 80 |
| Bearish FVG | `#FF7043` | 0 | — | yes, transparent 80 |
| BOS bull | `#66BB6A` | 2 | solid | — |
| BOS bear | `#EF5350` | 2 | solid | — |
| CHoCH | `#FFCA28` | 3 | dash | — |
| Liquidity sweep | `#FFA726` | 2 | — | — |
| IDM | `#BA68C8` | 1 | dot | — |
| Entry (long) | `#00E676` | 3 | — | — |
| Entry (short) | `#FF1744` | 3 | — | — |
| SL | `#FF1744` | 2 | solid | — |
| TP | `#00E676` | 2 | solid | — |

---

## 2. MQL5 Include — `DrawingRenderer.mqh`

The EA includes this file. Public functions:

- `DrawingRenderer_Init(string chart_symbol)` — bind to one symbol.
- `DrawingRenderer_Render(string json_drawings)` — parse + create/update objects.
- `DrawingRenderer_PruneRemoved()` — delete objects not in latest payload.
- `DrawingRenderer_ClearAll()` — cleanup on EA shutdown.

Implementation notes:

- Uses **JAson.mqh** (`CJAVal`) — widely-used MQL5 JSON parser.
- Color parser converts `#RRGGBB` hex to MQL5 `color`.
- Time conversion: `(TimeTradeServer() - TimeGMT())` cached once at init.
- `OBJPROP_SELECTABLE=false`, `OBJPROP_HIDDEN=true` so manual edits don't disturb.
- `OBJPROP_BACK=true` for rectangles so price candles stay on top.
- Each render call refreshes the `g_alive_ids[]` array; `PruneRemoved` deletes
  any `FRIDAY_*` object whose ID isn't in that array.

The full include file is generated in Phase 2 implementation. See agent output
or `_full_mql5_listing` in this doc's appendix (TBD).

---

## 3. Python helper — `chart_drawings.py`

Pure Python module that builds drawing dicts. Functions:

```python
draw_order_block(symbol, tf, ts_start, ts_end, price_high, price_low, side, status="active") -> dict
draw_fvg(symbol, tf, ts_start, ts_end, gap_high, gap_low, side, status="open") -> dict
draw_bos(symbol, tf, ts_break, level, side) -> dict
draw_choch(symbol, tf, ts_break, level, side) -> dict
draw_liquidity_sweep(symbol, tf, ts, level, direction) -> dict
draw_idm(symbol, tf, ts_taken, level) -> dict
draw_entry_marker(symbol, ts, price, side, reason_short) -> dict
draw_sl_tp_zone(symbol, entry, sl, tp, side) -> list[dict]  # [entry, sl, tp]
draw_narrative_label(symbol, ts, price, text_ar) -> dict
draw_fib(symbol, tf, ts1, price1, ts2, price2, levels) -> dict
```

Each returns a dict matching the JSON schema. IDs built from
`md5("smc_ob:XAGUSDm:h1:20260524T1400Z:bull")[:8]` so the same logical pattern
always produces the same ID across ticks.

---

## 4. `brain.json` integration in `r_executor._write_brain_json`

Replace `drawings: []` stub with composed list, filtered per symbol,
TTL-pruned, capped at `MAX_DRAWINGS_PER_SYMBOL=50`:

```python
def _collect_drawings(self, symbol: str) -> list[dict]:
    now = int(time.time())
    out: list[dict] = []
    for ob in self.smc_state.order_blocks.get(symbol, []):
        out.append(cd.draw_order_block(...))
    # ... fvgs, bos, choch, sweeps, idm
    if trade := self.active_trades.get(symbol):
        out.extend(cd.draw_sl_tp_zone(...))
        out.append(cd.draw_entry_marker(...))
        if trade.narrative_ar:
            out.append(cd.draw_narrative_label(...))
    out = [d for d in out
           if (now - d["created_at"]) < d.get("ttl_sec", STALE_AFTER_SEC)]
    out.sort(key=lambda d: d["created_at"], reverse=True)
    return out[:MAX_DRAWINGS_PER_SYMBOL]
```

Atomic write (`.tmp` + `os.replace`) prevents the EA from reading a half-written
file. The EA tolerates JSON parse failures by skipping that tick.

---

## 5. Per-chart EA hook

```mql5
[[include]] <DrawingRenderer.mqh>
[[include]] <JAson.mqh>

int OnInit() {
   DrawingRenderer_Init(_Symbol);
   EventSetTimer(1);
   return INIT_SUCCEEDED;
}
void OnDeinit(const int r) {
   EventKillTimer();
   DrawingRenderer_ClearAll();
}
void OnTimer() {
   string json = ReadBrainJsonFile();
   if(json == "") return;
   CJAVal root;
   if(!root.Deserialize(json)) return;
   DrawingRenderer_Render(root["drawings"].Serialize());
}
```

Each chart runs its own EA instance; the symbol filter inside
`DrawingRenderer_Render` ensures XAGUSDm objects never appear on a XAUUSDm chart
even though both EAs read the same `brain.json`.

---

## Guarantees summary

- **Idempotent** — deterministic MD5-hashed IDs → in-place property updates.
- **Per-symbol** — EA renders only drawings where `drawing.symbol == _Symbol`.
- **Self-pruning** — anything missing from current payload is deleted.
- **TTL-bounded** — drawings older than 6 h dropped Python-side; capped at 50.
- **Atomic file swap** — writer uses `.tmp` + `os.replace`; reader tolerates parse errors.
- **Time-safe** — epoch UTC in JSON, converted via cached broker-vs-GMT offset.
- **Arabic labels** — UTF-8 JSON + `Tahoma` font + `rtl: true` meta flag.
