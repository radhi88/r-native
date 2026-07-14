# Algory Generated-Strategy Gene Schema

Source: `C:\Users\Radhi\AppData\Local\Algory\Generated_Strategies` (+ `.recycle\`).
Sampled **152 strategy JSON files** (single-line JSON). `schema_version` observed: **3 and 4** (v4 adds the
`*_cross`, `stop_strict_*`, `profit_target`/`fcp`, `scale_in`, `sweep` and `no_open_*` families plus the
top-level `archetype` / `symbol_quality` / `win_mechanism` / `session_profile` labels — present in 72 files).
Ranges below are the **observed min..max across all samples**; they reflect the GA search space, not hard bounds.

## Top-level keys
`id`, `symbol`, `timeframe`, `created_at`, `schema_version`, `stats`, `genome`, `optimizable`,
`trained_risk_pct`, `time_shift`, `spread_points_avg`, `settings_snapshot`, `limit_signals`,
`limit_diagnostics`, `trades`, `equity_curve`.
v4 adds: `archetype`, `symbol_quality`, `win_mechanism`, `session_profile`.

---

## `genome`

### Core scalars
| key | type | observed range |
|---|---|---|
| start_hour | int | 2 .. 19 |
| end_hour | int | 11 .. 23 |
| friday_close | int | 16 .. 19 |
| sl_mult | float | 0.4 .. 4.0 |
| tp_mult | float | 0.35 .. 9.9 |
| tribe_origin | str | `Tribe A`, `Tribe B`, `Wild`, `REVOLUTION`, `FINAL WAR` |

### String enums
| key | values |
|---|---|
| exec_mode | `stop`, `limit`, `limit2`, `market2` |
| engulfing_type | `SIMPLE_SAME`, `SIMPLE_DIFF` |
| breakout_type | `PEAK`, `SIMPLE` |
| _pg_source | `random` |

### Bias toggles (`use_bias_*`, bool)
`use_bias_sma`, `use_bias_ema`, `use_bias_rsi`, `use_bias_adx`, `use_bias_psar`,
`use_bias_momentum`, `use_bias_trailing`, `use_bias_chandelier`, `use_bias_donchian_mid`,
`use_bias_daily_mid`, `use_bias_market_struct` (always False in samples), `use_bias_htf`.

### Signal toggles (`use_sig_*`, bool)
`use_sig_macd`, `use_sig_cci`, `use_sig_rsi`, `use_sig_bb`, `use_sig_stoch`, `use_sig_williams`,
`use_sig_sweep`, `use_sig_mom_break`, `use_sig_engulfing`, `use_sig_inside_break`,
`use_sig_wick_rejection`, `use_sig_pin_bar`, `use_sig_fib`, `use_sig_breakout`, `use_sig_three_soldiers`.

### Filter toggles (`use_filt_*`, bool)
`use_filt_sma`, `use_filt_rsi`, `use_filt_bb`, `use_filt_cci`, `use_filt_adx`, `use_filt_keltner`,
`use_filt_receding`, `use_filt_doji`, `use_filt_volatility`, `use_filt_consec`, `use_filt_adr_exhaust`.

### Trade-management toggles (bool)
`use_breakeven`, `use_sl_reduce`, `use_sl_lock`, `use_partial_tp`, `use_eod_close`, `use_scale_in`.
v4: `use_profit_target`, `use_friday_close_profit`, `use_no_open_friday`, `use_no_open_news_day`,
`stop_strict_offset`, `market2_sub_bar_only`.

### Risk / safety toggles (bool — effectively constant in samples)
`use_news_filter`(T), `use_daily_dd`(T), `use_friday_close`(T), `use_slippage`(T), `use_symbol_lock`(T),
`use_max_agg_risk`, `news_all_high_impact`(F).

### Numeric indicator / management params (observed min..max)
sma_fast_period 20..99 · sma_slow_period 107..287 · ema_period 7..200 · htf_sma_period 20..200 ·
rsi_period 8..24 · cci_period 8..24 · cci_limit 80..150 · bb_period 10..34 · bb_std 1.5..3.0 ·
adx_period 10..32 · adx_threshold 15..40 · atr_ma_period 10..31 ·
stoch_k_period 5..20 · stoch_d_period 3..7 · stoch_slowing 3..5 ·
williams_period 8..28 · williams_ob -30..-10 · williams_os -90..-70 ·
psar_step 0.005..0.03 · psar_max 0.05..0.35 · chand_mult 1.0..4.0 · trailing_period 10..50 ·
keltner_period 10..30 · keltner_mult 1.0..3.0 · momentum_period 4..20 · mom_break_atr 0.1..0.6 ·
sweep_period 7..55 · sweep_lookback_candles 1..8 · consec_count 2..7 ·
adr_period 5..20 · adr_exhaust_pct 0.6..0.95 · wick_ratio 1.0..4.0 · pin_bar_body_pct 0.33 (const) ·
fib_level 0.236..0.786 · fib_lookback 12..192 · breakout_lookback 10..60 · soldiers_min_body_atr 0.2..0.8 ·
scale_max_trades 2..5.

### Execution / order-placement params
market2_window_bars 3..60 · market2_pullback_atr 0.03..0.5 · limit_offset_atr 0.05..0.7 ·
limit2_offset_atr 0.005..0.12 · limit_expiry_bars 2..58 · stop_offset_atr 0.05..1.0 ·
stop_expiry_bars 3..16 · swing_expiry_bars 3..20.

### Breakeven / partial-TP / profit-target trigger params
be_trigger_pct 15..80 · pt_trigger_pct 15..80 · pt_close_pct 20..75 · fcp_trigger_pct 25..100 (v4) ·
profit_target_pct 10.0 const (v4).

### Risk-management constants (fixed across samples)
news_mins_before 30 · daily_dd_limit 4.0 · max_agg_risk_pct 5.0 ·
max_spread_major 3.0 / metal 16.0 / index 60.0 / crypto 100.0 / cross 10.0 (v4) ·
max_slip_major 10 / metal 30 / index 300 / crypto 600 / cross 25 (v4).

### Internal GA bookkeeping (prefixed `_` or meta)
`_cached_return` (14.6..355.4), `_cached_dd` (1.2..14.9), `_family_penalty` (0.42..1.0),
`_family_reward` (1.0..1.4), `_oos_validated` (bool), `_oos_failed_count` (1, when present),
`survived_full_tribe` (bool).

---

## `stats`

| key | type | observed range / values |
|---|---|---|
| return_pct | float | 17.87 .. 649.91 |
| drawdown_pct | float | 1.31 .. 15.04 |
| trades | int | 85 .. 852 |
| win_rate | float | 32.81 .. 96.32 |
| profit_factor | float | 1.19 .. 13.14 |
| sharpe | float | 1.32 .. 18.78 |
| linearity | float | 0.68 .. 0.996 |
| linearity_is | float | 0.69 .. 0.997 |
| linearity_oos | float | 0.09 .. 0.984 |
| trades_is | int | 51 .. 566 |
| trades_oos | int | 28 .. 286 |
| return_is | float | 16.98 .. 353.53 |
| return_oos | float | 0.20 .. 79.49 |
| longs | int | 51 .. 411 |
| shorts | int | 6 .. 441 |
| max_cons_wins | int | 4 .. 95 |
| max_cons_losses | int | 1 .. 10 |
| exit_reasons | dict[str,int] | keys: `TP`, `SL`, `TRAIL`, `EOD`, `FRIDAY`, `END`, `BUSTED` |
| exit_reasons_wins | dict[str,int] | subset of the same exit-reason keys |
| m2_natural_fills | int | 0 .. 852 |
| m2_fallback_fills | int | 0 .. 124 |
| m2_fallback_ratio | float | 0.0 .. 1.0 |
| stop_clamps | int | 0 (v4) |
| stop_clamp_ratio | float | 0.0 (v4) |
| stop_strict_skips | int | 0 (v4) |

**exit_reasons value set:** `TP`, `SL`, `TRAIL`, `EOD`, `FRIDAY`, `END`, `BUSTED`.
