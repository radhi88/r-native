# Algory Feature Audit — What R Native Should Mirror

**Source**: `C:\Users\Radhi\AppData\Local\Algory\`
**Date**: 2026-05-24
**Method**: Filesystem inspection (config + learning + strategies) — no reverse engineering of binary.

---

## 1. What Algory Does (full capability map)

### A. Symbol Coverage — **18 assets** vs R Native's ~6
| Class | Algory | R Native |
|---|---|---|
| Forex majors | 6 (EUR/GBP/AUD/JPY/CAD/CHF USD) | 6 ✅ |
| Forex crosses | 4 (EURGBP, GBPJPY, EURJPY, GBPAUD) | 0 ❌ |
| Crypto | BTCUSD | BTCUSD ✅ |
| Metals | XAUUSD, **XAGUSD** | XAUUSD only |
| Indices | US30, USTEC, US500, DE30 | 0 ❌ |
| Energy | USOIL | 0 ❌ |

### B. Timeframes — Algory: **6** (incl. unique H2), R Native: 4
M5, M15, M30, H1, **H2**, H4

### C. Genome System — **49 genes in 5 categories**
| Category | Count | Examples |
|---|---|---|
| **Exec modes** | 5 | `exec_market2`, `exec_limit`, `exec_limit2`, `exec_stop`, `exec_swing` |
| **Bias** | 12 | `use_bias_adx`, `use_bias_chandelier`, `use_bias_daily_mid`, `use_bias_donchian_mid`, `use_bias_ema`, `use_bias_htf`, `use_bias_market_struct`, `use_bias_momentum`, `use_bias_psar`, `use_bias_rsi`, `use_bias_sma`, `use_bias_trailing` |
| **Signals** | 14 | `use_sig_bb`, `use_sig_breakout`, `use_sig_cci`, `use_sig_engulfing`, `use_sig_fib`, `use_sig_inside_break`, `use_sig_macd`, `use_sig_mom_break`, `use_sig_pin_bar`, `use_sig_rsi`, `use_sig_stoch`, `use_sig_three_soldiers`, `use_sig_wick_rejection`, `use_sig_williams` |
| **Filters** | 13 | `use_filt_adr_exhaust`, `use_filt_adx`, `use_filt_bb`, `use_filt_cci`, `use_filt_consec`, `use_filt_doji`, `use_filt_keltner`, `use_no_open_friday`, `use_filt_receding`, `use_filt_rsi`, `use_filt_sma`, `use_filt_volatility` |
| **Management** | 6 | `use_breakeven`, `use_eod_close`, `use_friday_close_profit`, `use_partial_tp`, `use_sl_lock`, `use_sl_reduce` |

R Native has **48 similar genes** in `r_native/genes.py` — close to parity ✅

### D. Prop Firm Compliance — **14 settings** (FTMO-ready)
| Setting | Default | R Native |
|---|---|---|
| `news_mode` | FTMO | ❌ missing |
| `news_mins` | 30 | ❌ |
| `use_no_open_news_day` | True | ❌ |
| `use_dd` (daily DD) | True | partial (in executor) |
| `dd_limit` | 4.0% | $10 hard cap |
| `use_friday` close | True | ❌ |
| `friday_hour` | 19 | ❌ |
| `use_symbol_lock` | True | partial |
| `use_max_agg_risk` | True | ❌ |
| `max_agg_risk_pct` | 5.0% | ❌ |
| `use_profit_target` | False | ❌ |
| `profit_target_pct` | 10.0% | ❌ |
| `use_m2_subbar_only` | True | ❌ |
| `use_stop_strict_offset` | True | ❌ |

**Impact**: Without prop firm gates, R Native can't be used for funded accounts (FTMO/MFF/etc.) — a HUGE missing market.

### E. Purge Filters — **9 thresholds** (strategy quality gate)
- `dd_gt_ret` (drawdown > return safety check)
- `min_trades: 40`
- `max_dd: 10.0%`
- `min_pf: 1.2`
- `min_ret: 6.0%`
- `min_linearity: 0.7`
- `min_win_rate: 0.0`
- `min_sharpe: 0.0`
- `min_persistence: 0.0`

R Native has partial purge in `r_native/genes.py:algory_purge_check` — needs UI exposure.

### F. Campaign Engine — **34 input parameters**
Beyond the basics R Native has:
- `pg` (4000) — Proving Grounds candidate count
- `tribe_a/b` (20/20) — Generations per tribe
- `rev` (10) — Revival generations
- `war` (20) — War phase generations
- `retrain_gens` (10) — Final retrain
- `oos` (Auto) + `split` (0.67) — In-Sample/Out-of-Sample
- `stagnation` (5) — Early-stop threshold
- `scoring_a/b` (Modern) — Dual scoring system!
- `sl_max/tp_max` (4.0x ATR) — Max multipliers
- `force_start/end` — Hour-of-day filter
- **Per-asset-class** slippage: major/cross/metal/index/crypto (10/25/30/300/600 pts)
- **Per-asset-class** spread: major/cross/metal/index/crypto (3/10/16/60/100 pips)
- **Per-asset-class** leverage: major/metal/index (100/30/50)

### G. Smart Modes
- `auto_bars: True` — Engine picks bar count automatically
- `auto_trades: True` — Auto-tune min trades
- `auto_oos: True` — Auto-pick OOS window
- `smart_mode: False` — Master switch
- `power_mode: Medium (50%)` — CPU throttle (Low/Medium/High)

### H. Learning System — **gene_fitness_v2.json** (this is the secret sauce)
Tracks performance of:
- **47 genes** globally + per-symbol+TF combos
- **598 gene combos** with wins/fails/avg_return (e.g. `bias_daily_mid+filt_consec+sig_inside_break+sig_pin_bar`)
- **4 exec_modes** comparative performance
- **Param distributions**: `start_hour` histogram, `rr_bucket` histogram
- **total_campaigns** counter (currently 7)

**Critical metric**: `mid_oos_pass` / `mid_oos_fail` — tracks how each gene survives out-of-sample validation. This is the **anti-overfit** mechanism.

Example global learning entry:
```json
{
  "use_bias_daily_mid": {
    "wins": 4, "fails": 61,
    "mid_oos_pass": 11, "mid_oos_fail": 89,
    "avg_return": 49.7, "avg_dd": 5.5,
    "best_return": 53.6, "appearances": 165,
    "last_seen": "2026-05-24"
  }
}
```

---

## 2. What R Native is Missing (gap analysis)

### 🚨 Critical Missing (mass-adoption blockers)
1. **Prop firm compliance suite** — FTMO/MFF accounts can't use R Native
2. **News filter** — no calendar integration
3. **Per-asset-class slippage/spread/leverage** — generic settings for all
4. **9 indices + 4 forex crosses + XAGUSD + USOIL** — half the assets missing
5. **H2 timeframe** — unique to Algory

### ⚠️ Important Missing (competitive disadvantages)
6. **Per-combo gene fitness learning** — Algory tracks 598 combos; R Native tracks nothing
7. **`mid_oos_pass/fail` tracking** — anti-overfit metric
8. **Force genes** — override management genes globally
9. **Smart modes (auto_bars/trades/oos)** — Algory tunes itself
10. **Dual scoring** (`scoring_a` + `scoring_b`) — A/B test scoring systems

### 💡 Nice-to-have Missing (UX polish)
11. **Power mode throttle** (Low/Medium/High) — CPU budget control
12. **Session lock pills** (TO/LO/NYO/Tokyo/London/NY) — preset time windows
13. **Strategy table filters** (MARKET/CAMPAIGN/BOT TYPE/PERFORMANCE dropdowns)
14. **All Strategies / Latest / Retrain / Portfolios** tab grouping
15. **Stagnation auto-stop** — engine quits if no improvement

---

## 3. Proposed R Native Phases (H.12 → H.18)

### Phase H.12 — Prop Firm Compliance Suite (URGENT)
- News filter calendar (`forexfactory` JSON)
- Per-symbol daily DD enforcement
- Friday close hour gate
- Max aggregate risk %
- Profit target (optional)
- Sub-bar exec mode for market2 strategies
- **Estimate**: 4-6 hours
- **Impact**: Opens R Native to funded-account traders (~10× market)

### Phase H.13 — Asset Class Expansion
- Add 12 missing symbols (crosses, indices, metals, oil)
- Per-class slippage/spread/leverage table
- Symbol-quality classifier (MARGINAL/GOOD/EXCELLENT)
- **Estimate**: 3 hours
- **Impact**: Multi-asset trading parity with Algory

### Phase H.14 — Per-Combo Learning (the SECRET SAUCE)
- Track gene combos in `gene_combo_fitness.json`
- Per-combo wins/fails/avg_return
- `mid_oos_pass/fail` for each gene
- Inspector displays "this combo has been seen X times, wins Y%"
- Engine biases mutation toward winning combos
- **Estimate**: 4 hours
- **Impact**: Self-improving strategy generation (the Algory edge)

### Phase H.15 — H2 Timeframe + Force Genes
- Add M30, H2 support throughout
- "Force ON" toggle per management gene
- **Estimate**: 1 hour
- **Impact**: Strategy diversity

### Phase H.16 — Smart Modes
- `auto_bars` — engine picks bar count from symbol activity
- `auto_trades` — purge `min_trades` adapts to TF
- `auto_oos` — OOS window adapts to data length
- `power_mode` — CPU throttle (uses N% of cores)
- **Estimate**: 2 hours
- **Impact**: Hands-off campaign launch

### Phase H.17 — Vault Table Filters
- MARKET / CAMPAIGN / BOT TYPE / PERFORMANCE dropdowns
- All / Latest / Retrain / Portfolios tabs
- **Estimate**: 1.5 hours
- **Impact**: Better strategy discovery in 2000+ vault

### Phase H.18 — Session Lock + Time Pills
- Quick session presets: TO/LO/NYO/Tokyo/London/NY
- Hour range input
- Per-strategy session override
- **Estimate**: 1 hour
- **Impact**: Session-aware strategy selection

---

## 4. Recommendation: Build Order

**Most impactful first:**
1. **H.14 — Per-combo learning** (1 day) → R Native gets self-improvement
2. **H.12 — Prop firm suite** (1 day) → Opens funded-account market
3. **H.13 — Asset expansion** (½ day) → Trade more markets
4. **H.16 — Smart modes** (½ day) → Hands-off operation
5. **H.17 / H.18 / H.15** (small UX wins) — 2-3 hours total

**Total to full Algory parity**: ~3-4 focused days of dev work.

## 5. What R Native ALREADY does better than Algory
- ✅ **Live executor** with MT5 IPC (Algory generates strategies, R Native trades them)
- ✅ **Modern UI** (Inter font, slate palette, Linear-style)
- ✅ **Heartbeat + launcher architecture** (Algory is monolithic)
- ✅ **Backtest replay** with instant 30-day result
- ✅ **In-app trade gate** (`/api/r/trade_gate`)
- ✅ **R Native genome → trade_gate integration** (H.7 phase — deployed genome drives live decisions)
- ✅ **Brain server REST API** (Algory has no API)
- ✅ **Open architecture** — extensible by user

R Native is ALREADY ahead on execution + integration. It just lacks Algory's depth in strategy generation/learning.
