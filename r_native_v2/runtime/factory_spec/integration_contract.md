# LIVE Genome Contract + Radhi Acceptance Filter

Source of truth: `C:\Users\Radhi\MT5\r_native_v2\runtime\unified_trader.py`
(functions `_load_genome_for` L128, `evaluate_genome` L336, order placement L584-593,
trend/structure gates L853-896, risk sizing `_risk_lot` L538).
Example genome: `C:\Users\Radhi\MT5\r_native_v2\data\live_genome__XAUUSDm.json`.

---

## Part 1 — Genome Param Contract (what `unified_trader` actually honors)

A genome file is `{ "name", "symbol", "params": {...}, "source", "ts" }`.
`_load_genome_for(sym)` loads `live_genome__<sym>.json` if present (using its
`params`); otherwise falls back to the shared champion's `params`. Only the
`params` keys below are read. `pt` = symbol price-unit scale (XAUUSDm=1.0,
EURUSDm=0.0001, etc.) — gold-tuned point thresholds are multiplied by `pt`.

### Signal gates — consumed in `evaluate_genome` (L336)
Evaluated strictly in this order; first failing gate returns `(None, 0, reason)`.

| Param | Type / values | Default | Precise semantics |
|---|---|---|---|
| `session_filter` | list ⊂ {`NY_OVERLAP`,`LONDON`,`NY_LATE`,`ASIAN`} | `[]` | If non-empty, block unless `snap.session ∈ session_filter`. Empty list = trade all sessions (24/7). |
| `regime_filter` | list of regime tags | `[]` | If non-empty, block unless `snap.regime ∈ regime_filter`. Empty = any regime. |
| `min_mtf_agreement` | int | `2` | Count MTF biases: `up_count`/`dn_count`. If `up_count ≥ min` → direction BUY; elif `dn_count ≥ min` → SELL; else block "MTF mixed". |
| `side_bias` | `BUY_ONLY` / `SELL_ONLY` / `null` | `null` | `BUY_ONLY` blocks any non-BUY direction; `SELL_ONLY` blocks any non-SELL; `null`/absent = both sides allowed. |
| `rsi_max` | number (0-100) | `60` | RSI taken from `snap.rsi.m1` (default 50). BUY blocked if `rsi ≥ rsi_max`. SELL blocked if `rsi ≤ (100 - rsi_max)`. (e.g. `rsi_max=50` → SELL needs rsi>50, BUY needs rsi<50.) |
| `min_pressure_abs` | gold-points | `3` | Scaled `×pt`. MOMENTUM entry (pressure confirms side): block if `abs(pressure) < min_pressure_abs`. PULLBACK entry (pressure contra) allowed only if `trend_n ≥ 3` and `abs(pressure) ≤ PULLBACK_MAX_CONTRA×pt`. |

Confidence is computed from MTF strength + pressure, then gated by module-level
`MIN_CONFIDENCE = 0.5` (L843) — below that → `LOW_CONF`, no trade.

### Post-signal gates — consumed in the order path (L853-896)
| Param | Type | Default | Precise semantics |
|---|---|---|---|
| `trend_align` | bool | `true` | If true, run `counter_trend_veto(snap, side, trend_align_min)`; veto kills counter-HTF-trend entries (`TREND_VETO`). |
| `trend_align_min` | number | `0.45` | Threshold passed to `counter_trend_veto` (read only when `trend_align` true). |
| `struct_min` | number | `0.10` | From `structure_decision`: block if `side_vetoes` (`STRUCT_VETO`); block if `opp_score - side_score ≥ 0.30` (`STRUCT_OPP`); block if `side_score < struct_min` (`STRUCT_WEAK`). Structure agreement can only RAISE confidence. |

### Execution / sizing params — consumed at order build (L584-593)
| Param | Type | Default | Precise semantics |
|---|---|---|---|
| `sl_pts` | gold-points | `4.0` | Stop distance; `sl_px = sl_pts × pt`. |
| `tp_pts` | gold-points | `12.0` | Take-profit distance; floored to `max(tp_pts, 20.0)` then `tp_px = tp_pts × pt` (trail ladder handles real exit). |
| `lot` | float | `0.02` | Flat lot used when `risk_pct = 0`. |
| `risk_pct` | float % | `0.0` | If `> 0`, `_risk_lot` sizes lot so hitting SL risks `risk_pct%` of equity (overrides flat `lot`); `0` = use flat `lot`. |

### Inert in `unified_trader`
| Param | Status |
|---|---|
| `use_footprint` | NOT read by `unified_trader.py`. Honored only by other traders (`claude_genome_trader.py`, `r_native_brain_link.py`) where it gates footprint supply/demand-zone vetoes. In the unified path it is a passthrough/no-op field. |

`name` / `symbol` are metadata; `name` is used for change-logging only.

---

## Part 2 — Radhi Acceptance Filter

Derived from `C:\Users\Radhi\MT5\r_native_v2\data\radhi_dna.json` (432 manual
trades): SELL = 98.4% WR / +$765; BUY = −$967; Asian/night(21-08) = −$671;
NY_overlap(13-17) = +$329. A candidate genome is ACCEPTED only if ALL hold:

1. **Permits SELL** — `params.side_bias != "BUY_ONLY"` (i.e. `SELL_ONLY` or `null`).
2. **Trades NY** — `params.session_filter` includes `NY_OVERLAP` (the 13-17 UTC
   overlap bucket), OR is empty `[]` (empty = all sessions, which includes NY).
3. **Linearity (OOS)** — `algory_stats.linearity_oos >= 0.3`.
4. **Sample (OOS)** — `algory_stats.trades_oos >= 40`.
5. **Profitability** — `algory_stats.profit_factor > 1.1`.

Reject if any condition fails. (`algory_stats` is the candidate's out-of-sample
evaluation block, expected alongside `params`.)

### Reference Python predicate
```python
def radhi_accepts(genome: dict) -> tuple[bool, str]:
    p = genome.get("params", {})
    a = genome.get("algory_stats", {})
    if p.get("side_bias") == "BUY_ONLY":
        return False, "rejects SELL (side_bias BUY_ONLY)"
    sf = p.get("session_filter") or []
    if sf and "NY_OVERLAP" not in sf:
        return False, f"no NY session ({sf})"
    if (a.get("linearity_oos", 0) or 0) < 0.3:
        return False, f"linearity_oos {a.get('linearity_oos')} < 0.3"
    if (a.get("trades_oos", 0) or 0) < 40:
        return False, f"trades_oos {a.get('trades_oos')} < 40"
    if (a.get("profit_factor", 0) or 0) <= 1.1:
        return False, f"profit_factor {a.get('profit_factor')} <= 1.1"
    return True, "accepted"
```

### Worked check — `RADHI-CLONE-G1` (`live_genome__XAUUSDm.json`)
`side_bias=SELL_ONLY` ✓ (permits SELL) · `session_filter=[NY_OVERLAP]` ✓ (NY) ·
`algory_stats` absent → fails linearity/trades/PF gates → would be REJECTED until
an OOS `algory_stats` block is attached.
