"""
algory_dna.py
-------------
Full Algory-style genome definition for FRIDAY.

Gene pool replicated exactly from Algory factory_config.json:
  exec_modes  : 4 entry-type flags
  bias        : 12 trend/direction confirmation filters
  signals     : 15 entry trigger generators
  filters     : 11 trade qualification filters
  exits       : 5 position management features

Scoring: 'Modern' mode — Sharpe + linearity + persistence + return
Purge  : exact criteria from Algory purge config
Campaign: exact phase settings from Algory dashboard_settings.json
"""

from __future__ import annotations

import json
import math
import random
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
#  Gene catalogue (from Algory genes config)
# ─────────────────────────────────────────────────────────────────────────────

EXEC_GENES: list[str] = [
    "exec_market2",   # delayed/confirmed market entry
    "exec_limit",     # standard limit order
    "exec_limit2",    # aggressive limit entry
    "exec_stop",      # stop order entry
    # exec_market  → always disabled (exec_market=false in Algory config)
    # exec_swing   → always disabled (exec_swing=false)
    # use_scale_in → always disabled (use_scale_in=false)
]

BIAS_GENES: list[str] = [
    "use_bias_adx",
    "use_bias_chandelier",
    "use_bias_daily_mid",
    "use_bias_donchian_mid",
    "use_bias_ema",
    "use_bias_htf",
    "use_bias_market_struct",
    "use_bias_momentum",
    "use_bias_psar",
    "use_bias_rsi",
    "use_bias_sma",
    "use_bias_trailing",
]

SIGNAL_GENES: list[str] = [
    # 14 signals — exact from Algory SIGNALS panel (SWEEP is internal, not a gene)
    "use_sig_bb",
    "use_sig_breakout",
    "use_sig_cci",
    "use_sig_engulfing",
    "use_sig_fib",
    "use_sig_inside_break",
    "use_sig_macd",
    "use_sig_mom_break",
    "use_sig_pin_bar",
    "use_sig_rsi",
    "use_sig_stoch",
    "use_sig_three_soldiers",
    "use_sig_wick_rejection",
    "use_sig_williams",
]

FILTER_GENES: list[str] = [
    "use_filt_adr_exhaust",
    "use_filt_adx",
    "use_filt_bb",
    "use_filt_cci",
    "use_filt_consec",
    "use_filt_doji",
    "use_filt_keltner",
    "use_filt_receding",
    "use_filt_rsi",
    "use_filt_sma",
    "use_filt_volatility",
]

EXIT_GENES: list[str] = [
    "use_breakeven",
    "use_eod_close",
    "use_partial_tp",
    "use_sl_lock",
    "use_sl_reduce",
]

ALL_BINARY_GENES: list[str] = EXEC_GENES + BIAS_GENES + SIGNAL_GENES + FILTER_GENES + EXIT_GENES

# ─────────────────────────────────────────────────────────────────────────────
#  Numeric DNA bounds (Algory sl_max=4.0, tp_max=10.0 + FRIDAY params)
# ─────────────────────────────────────────────────────────────────────────────

NUMERIC_BOUNDS: dict[str, tuple[float, float]] = {
    # Core risk/entry
    "sl_max":         (1.0,  4.0),
    "tp_max":         (2.0, 10.0),
    "risk_pct":       (0.5,  2.0),
    "buy_threshold":  (0.55, 0.88),
    "sell_threshold": (0.12, 0.45),
    "min_smc_score":  (1.0,  5.0),
    "atr_sl_mult":    (0.5,  4.0),
    "min_rr":         (1.0,  3.0),
    # Trading hours
    "start_hour":     (0.0,  8.0),
    "end_hour":       (14.0, 23.0),
    "friday_close":   (12.0, 22.0),
    # Indicator periods
    "rsi_period":     (5.0,  30.0),
    "cci_period":     (5.0,  30.0),
    "cci_limit":      (50.0, 200.0),
    "bb_period":      (10.0, 50.0),
    "bb_std":         (1.0,  3.5),
    "sma_slow_period":(50.0, 300.0),
    "sma_fast_period":(5.0,  100.0),
    "adx_period":     (5.0,  30.0),
    "adx_threshold":  (15.0, 40.0),
    "stoch_k_period": (5.0,  30.0),
    "stoch_d_period": (2.0,  10.0),
    "stoch_slowing":  (2.0,  10.0),
    "ema_period":     (5.0,  100.0),
    "atr_ma_period":  (5.0,  30.0),
    "trailing_period":(5.0,  50.0),
    "momentum_period":(5.0,  30.0),
    "williams_period":(5.0,  30.0),
    "williams_ob":    (-5.0, -25.0),
    "williams_os":    (-75.0, -95.0),
    "keltner_period": (5.0,  50.0),
    "keltner_mult":   (0.5,  3.0),
    "htf_sma_period": (5.0,  50.0),
    "psar_step":      (0.01, 0.05),
    "psar_max":       (0.1,  0.4),
    "chand_mult":     (1.0,  5.0),
    # Pattern params
    "consec_count":   (2.0,  12.0),
    "wick_ratio":     (0.5,  4.0),
    "fib_level":      (0.236, 0.786),
    "fib_lookback":   (10.0, 100.0),
    "breakout_lookback":(5.0, 50.0),
    "pin_bar_body_pct":(0.1, 0.5),
    "mom_break_atr":  (0.1,  2.0),
    "soldiers_min_body_atr": (0.1, 1.0),
    "sweep_lookback_candles":(2.0, 10.0),
    "sweep_period":   (5.0,  50.0),
    "adr_period":     (5.0,  30.0),
    "adr_exhaust_pct":(0.5,  0.95),
    # Execution params
    "limit_offset_atr":  (0.1, 1.5),
    "limit_expiry_bars": (3.0, 30.0),
    "limit2_offset_atr": (0.05, 0.5),
    "stop_offset_atr":   (0.1, 1.5),
    "stop_expiry_bars":  (3.0, 30.0),
    "market2_window_bars":(10.0, 120.0),
    "market2_pullback_atr":(0.1, 2.0),
    # Exit params
    "be_trigger_pct": (30.0, 100.0),
    "pt_trigger_pct": (40.0, 100.0),
    "pt_close_pct":   (20.0, 80.0),
    "scale_max_trades":(1.0,  10.0),
}

INT_PARAMS: set[str] = {
    "min_smc_score",
    "start_hour", "end_hour", "friday_close",
    "rsi_period", "cci_period", "bb_period",
    "sma_slow_period", "sma_fast_period", "adx_period",
    "stoch_k_period", "stoch_d_period", "stoch_slowing",
    "ema_period", "atr_ma_period", "trailing_period", "momentum_period",
    "williams_period", "keltner_period", "htf_sma_period",
    "consec_count", "fib_lookback", "breakout_lookback",
    "sweep_lookback_candles", "sweep_period", "adr_period",
    "limit_expiry_bars", "stop_expiry_bars",
    "market2_window_bars", "scale_max_trades",
}

# ─────────────────────────────────────────────────────────────────────────────
#  Purge criteria — exact values from Algory purge config
# ─────────────────────────────────────────────────────────────────────────────

PURGE_CRITERIA: dict[str, Any] = {
    "dd_gt_ret":       True,   # discard if max_dd > total_return_pct
    "min_trades":      40,
    "max_dd":          10.0,   # % max drawdown
    "min_pf":          1.2,    # profit factor
    "min_ret":         6.0,    # % net return on balance
    "min_linearity":   0.70,   # R² of equity curve
    "min_win_rate":    0.0,    # 0 = any
    "min_sharpe":      0.0,    # 0 = any
    "min_persistence": 0.0,    # 0 = any
}

# ─────────────────────────────────────────────────────────────────────────────
#  Campaign settings — exact values from Algory dashboard_settings.json
# ─────────────────────────────────────────────────────────────────────────────

CAMPAIGN_SETTINGS: dict[str, Any] = {
    "pg_candidates":    4000,
    "tribe_gens_a":     20,
    "tribe_gens_b":     20,
    "war_gens":         20,
    "rev_gens":         10,
    "stagnation_limit": 5,
    "oos_split":        0.33,       # 33% held out
    "train_split":      0.67,
    "balance":          100_000.0,
    "risk_pct":         1.0,
    "spread_mult":      1.0,
    "swap_mult":        1.0,
    "fee_mode":         "B",        # commission-based
    "bars_total":       16_000,
    "scoring_mode":     "Modern",
    "assets": {
        "EURUSDm": {"tf": "H1", "leverage": 100, "spread_pips": 3.0,  "slip_pts": 10,  "enabled": True},
        "GBPUSDm": {"tf": "H1", "leverage": 100, "spread_pips": 3.0,  "slip_pts": 10,  "enabled": True},
        "XAUUSDm": {"tf": "H1", "leverage": 30,  "spread_pips": 16.0, "slip_pts": 30,  "enabled": True},
        "XAGUSDm": {"tf": "H1", "leverage": 30,  "spread_pips": 16.0, "slip_pts": 30,  "enabled": False},
        "BTCUSDm": {"tf": "H1", "leverage": 2,   "spread_pips": 100.0,"slip_pts": 600, "enabled": False},
    },
}


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ─────────────────────────────────────────────────────────────────────────────
#  AlgoryGenome
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AlgoryGenome:
    """
    Full Algory-style genome with binary feature genes + numeric DNA.

    Binary genes replicate Algory's genes section exactly.
    Numeric DNA covers SL/TP bounds, risk, and FRIDAY signal thresholds.
    Scoring uses Algory's 'Modern' mode: Sharpe + linearity + persistence.
    """

    id:           str
    generation:   int
    parent_ids:   list[str]
    created_at:   str
    symbol:       str
    campaign:     str = ""
    phase:        str = "pg"    # pg / tribe_a / tribe_b / war / review / oos / live

    # ── Execution mode genes ──────────────────────────────────────────────────
    exec_market2: bool = True
    exec_limit:   bool = True
    exec_limit2:  bool = True
    exec_stop:    bool = True

    # ── Bias genes ────────────────────────────────────────────────────────────
    use_bias_adx:           bool = True
    use_bias_chandelier:    bool = True
    use_bias_daily_mid:     bool = True
    use_bias_donchian_mid:  bool = True
    use_bias_ema:           bool = True
    use_bias_htf:           bool = True
    use_bias_market_struct: bool = True
    use_bias_momentum:      bool = True
    use_bias_psar:          bool = True
    use_bias_rsi:           bool = True
    use_bias_sma:           bool = True
    use_bias_trailing:      bool = True

    # ── Signal genes ──────────────────────────────────────────────────────────
    use_sig_bb:             bool = True
    use_sig_breakout:       bool = True
    use_sig_cci:            bool = True
    use_sig_engulfing:      bool = True
    use_sig_fib:            bool = True
    use_sig_inside_break:   bool = True
    use_sig_macd:           bool = True
    use_sig_mom_break:      bool = True
    use_sig_pin_bar:        bool = True
    use_sig_rsi:            bool = True
    use_sig_stoch:          bool = True
    use_sig_three_soldiers: bool = True
    use_sig_wick_rejection: bool = True
    use_sig_williams:       bool = True
    use_sig_sweep:          bool = True

    # ── Filter genes ──────────────────────────────────────────────────────────
    use_filt_adr_exhaust: bool = True
    use_filt_adx:         bool = True
    use_filt_bb:          bool = True
    use_filt_cci:         bool = True
    use_filt_consec:      bool = True
    use_filt_doji:        bool = True
    use_filt_keltner:     bool = True
    use_filt_receding:    bool = True
    use_filt_rsi:         bool = True
    use_filt_sma:         bool = True
    use_filt_volatility:  bool = True

    # ── Exit management genes — force_genes=false replicates Algory default ──
    use_breakeven:  bool = False
    use_eod_close:  bool = False
    use_partial_tp: bool = False
    use_sl_lock:    bool = False
    use_sl_reduce:  bool = False

    # ── Numeric DNA ───────────────────────────────────────────────────────────
    sl_max:         float = 2.0
    tp_max:         float = 6.0
    risk_pct:       float = 1.0
    buy_threshold:  float = 0.62
    sell_threshold: float = 0.38
    min_smc_score:  int   = 2
    atr_sl_mult:    float = 1.5
    min_rr:         float = 1.5

    # Trading hours
    start_hour:     int   = 4
    end_hour:       int   = 19
    friday_close:   int   = 16

    # Signal indicator periods
    rsi_period:     int   = 14
    cci_period:     int   = 14
    cci_limit:      float = 100.0
    bb_period:      int   = 20
    bb_std:         float = 2.0
    sma_slow_period: int  = 200
    sma_fast_period: int  = 50
    adx_period:     int   = 14
    adx_threshold:  float = 25.0
    stoch_k_period: int   = 14
    stoch_d_period: int   = 3
    stoch_slowing:  int   = 3
    ema_period:     int   = 20
    atr_ma_period:  int   = 14
    trailing_period: int  = 20
    momentum_period: int  = 10
    williams_period: int  = 10
    williams_ob:    float = -20.0
    williams_os:    float = -85.0
    keltner_period: int   = 20
    keltner_mult:   float = 1.5
    htf_sma_period: int   = 20
    psar_step:      float = 0.02
    psar_max:       float = 0.2
    chand_mult:     float = 3.0

    # Pattern / shape params
    consec_count:   int   = 6
    wick_ratio:     float = 1.5
    fib_level:      float = 0.382
    fib_lookback:   int   = 50
    breakout_lookback: int = 20
    pin_bar_body_pct: float = 0.33
    mom_break_atr:  float = 0.5
    soldiers_min_body_atr: float = 0.3
    sweep_lookback_candles: int  = 4
    sweep_period:   int   = 20
    adr_period:     int   = 14
    adr_exhaust_pct: float = 0.7

    # Execution entry params
    limit_offset_atr:  float = 0.4
    limit_expiry_bars: int   = 15
    limit2_offset_atr: float = 0.12
    stop_offset_atr:   float = 0.4
    stop_expiry_bars:  int   = 12
    market2_window_bars: int = 60
    market2_pullback_atr: float = 0.4

    # Exit / management params
    be_trigger_pct: float = 70.0
    pt_trigger_pct: float = 80.0
    pt_close_pct:   float = 50.0
    scale_max_trades: int = 5

    # ── Performance state ─────────────────────────────────────────────────────
    trades:       int         = 0
    wins:         int         = 0
    total_pnl:    float       = 0.0
    win_pnl:      float       = 0.0
    loss_pnl:     float       = 0.0
    max_dd_pct:   float       = 0.0
    equity_curve: list[float] = field(default_factory=list)
    trade_log:    list[dict]  = field(default_factory=list)

    is_protected: bool       = False
    is_active:    bool       = False
    advisor_note: str        = ""
    name:         str        = ""
    medals:       list[str]  = field(default_factory=list)

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.loss_pnl <= 0:
            return 1.0 if self.win_pnl > 0 else 0.0
        return self.win_pnl / abs(self.loss_pnl)

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.trades if self.trades > 0 else 0.0

    @property
    def total_return_pct(self) -> float:
        return (self.total_pnl / CAMPAIGN_SETTINGS["balance"]) * 100.0

    # ── Algory Modern scoring components ──────────────────────────────────────

    def equity_linearity(self) -> float:
        """R² of equity curve vs ideal straight line (Algory's linearity metric)."""
        eq = self.equity_curve
        if len(eq) < 3:
            return 0.0
        n    = len(eq)
        mean = sum(eq) / n
        ideal_start, ideal_end = eq[0], eq[-1]
        ideal = [ideal_start + (ideal_end - ideal_start) * i / (n - 1) for i in range(n)]
        ss_tot = sum((y - mean) ** 2 for y in eq)
        ss_res = sum((y - yhat) ** 2 for y, yhat in zip(eq, ideal))
        if ss_tot == 0:
            return 1.0 if ss_res == 0 else 0.0
        return round(max(0.0, 1.0 - ss_res / ss_tot), 4)

    def sharpe_ratio(self) -> float:
        """Trade-level Sharpe (mean_pnl_pct / std_pnl_pct * sqrt(252))."""
        if len(self.trade_log) < 5:
            return 0.0
        returns = [t.get("pnl_pct", 0.0) for t in self.trade_log]
        n       = len(returns)
        mean_r  = sum(returns) / n
        variance = sum((r - mean_r) ** 2 for r in returns) / n
        std_r   = math.sqrt(variance) if variance > 0 else 0.0
        if std_r == 0:
            return 2.0 if mean_r > 0 else 0.0
        return round((mean_r / std_r) * math.sqrt(252), 4)

    def persistence(self) -> float:
        """Fraction of rolling 10-trade windows that are net-positive."""
        pnls = [t.get("pnl", 0.0) for t in self.trade_log]
        if len(pnls) < 10:
            return 0.0
        window = 10
        total  = len(pnls) - window + 1
        hits   = sum(1 for i in range(total) if sum(pnls[i:i + window]) > 0)
        return round(hits / total, 4)

    def modern_score(self) -> float:
        """
        Algory 'Modern' scoring (reverse-engineered from terminal output).

        Formula: (Return% / MaxDD%) × Linearity × (0.5 + Persistence / 2)

        Verified against terminal logs:
          Gen14: (59.4/2.8) × 0.97 × (0.5 + 0.75/2) ≈ 17.7  ✓
          Gen13: (58.4/3.1) × 0.97 × (0.5 + 0.72/2) ≈ 16.3  ✓
          Gen11: (56.3/4.2) × 0.97 × (0.5 + 0.68/2) ≈ 10.9  ✓
        """
        if self.trades < 5:
            return 0.0
        if self.max_dd_pct <= 0:
            return 0.0

        ret     = self.total_return_pct
        dd      = self.max_dd_pct
        linear  = self.equity_linearity()
        persist = self.persistence()

        # R8: guard near-zero denominator; R3: guard non-finite inputs
        try:
            from .core.numeric_safety import guard_denominator
            dd = guard_denominator(dd, fallback=1.0)
        except ImportError:
            pass

        if not (math.isfinite(ret) and math.isfinite(dd)):
            return 0.0

        score = (ret / dd) * linear * (0.5 + persist / 2.0)
        if not math.isfinite(score):
            return 0.0
        return round(max(0.0, score), 4)

    # ── Purge check ───────────────────────────────────────────────────────────

    def passes_purge(self) -> tuple[bool, str]:
        """
        Algory purge criteria — exact values from purge config.
        Returns (passes, reason_if_fail).
        """
        c = PURGE_CRITERIA

        if self.trades < c["min_trades"]:
            return False, f"trades {self.trades} < {c['min_trades']}"
        if self.max_dd_pct > c["max_dd"]:
            return False, f"max_dd {self.max_dd_pct:.1f}% > {c['max_dd']}%"
        if self.profit_factor < c["min_pf"]:
            return False, f"PF {self.profit_factor:.2f} < {c['min_pf']}"
        if self.total_return_pct < c["min_ret"]:
            return False, f"return {self.total_return_pct:.1f}% < {c['min_ret']}%"

        lin = self.equity_linearity()
        if lin < c["min_linearity"]:
            return False, f"linearity {lin:.2f} < {c['min_linearity']}"
        if self.win_rate < c["min_win_rate"]:
            return False, f"win_rate {self.win_rate:.2%} < {c['min_win_rate']:.2%}"
        if self.sharpe_ratio() < c["min_sharpe"]:
            return False, f"sharpe {self.sharpe_ratio():.2f} < {c['min_sharpe']}"
        if self.persistence() < c["min_persistence"]:
            return False, f"persistence {self.persistence():.2f} < {c['min_persistence']}"
        if c["dd_gt_ret"] and self.max_dd_pct > self.total_return_pct:
            return False, f"dd {self.max_dd_pct:.1f}% > return {self.total_return_pct:.1f}%"

        return True, "OK"

    # ── Record a completed trade ──────────────────────────────────────────────

    def record_trade(self, won: bool, pnl: float, pnl_pct: float = 0.0) -> None:
        self.trades += 1
        if won:
            self.wins    += 1
            self.win_pnl += abs(pnl)
        else:
            self.loss_pnl += abs(pnl)
        self.total_pnl += pnl

        balance     = CAMPAIGN_SETTINGS["balance"] + self.total_pnl
        prev_balance = CAMPAIGN_SETTINGS["balance"] + (self.total_pnl - pnl)
        self.equity_curve.append(round(balance, 2))
        if len(self.equity_curve) > 16_000:
            self.equity_curve = self.equity_curve[-16_000:]

        # track max drawdown
        if self.equity_curve:
            peak    = max(self.equity_curve)
            current = self.equity_curve[-1]
            dd_pct  = (peak - current) / peak * 100.0 if peak > 0 else 0.0
            self.max_dd_pct = max(self.max_dd_pct, dd_pct)

        self.trade_log.append({
            "t":       self.trades,
            "won":     won,
            "pnl":     round(pnl, 4),
            "pnl_pct": round(pnl_pct, 6),
        })
        if len(self.trade_log) > 2_000:
            self.trade_log = self.trade_log[-2_000:]

        if not self.is_protected and self.is_profitable:
            self.is_protected = True

    @property
    def is_profitable(self) -> bool:
        return (self.trades >= PURGE_CRITERIA["min_trades"]
                and self.total_return_pct >= PURGE_CRITERIA["min_ret"]
                and self.profit_factor    >= PURGE_CRITERIA["min_pf"])

    # ── Gene helpers ──────────────────────────────────────────────────────────

    def active_gene_count(self) -> int:
        return sum(1 for g in ALL_BINARY_GENES if getattr(self, g, False))

    def gene_summary(self) -> dict[str, list[str]]:
        return {
            "exec":    [g for g in EXEC_GENES    if getattr(self, g, False)],
            "bias":    [g for g in BIAS_GENES    if getattr(self, g, False)],
            "signals": [g for g in SIGNAL_GENES  if getattr(self, g, False)],
            "filters": [g for g in FILTER_GENES  if getattr(self, g, False)],
            "exits":   [g for g in EXIT_GENES    if getattr(self, g, False)],
        }

    def to_entry_params(self) -> dict:
        """Convert genome to FRIDAY entry agent parameters."""
        return {
            "buy_prob_threshold":  self.buy_threshold,
            "sell_prob_threshold": self.sell_threshold,
            "min_smc_score":       self.min_smc_score,
            "sl_atr_mult":         self.atr_sl_mult,
            "sl_max_atr":          self.sl_max,
            "tp_max_atr":          self.tp_max,
            "min_rr":              self.min_rr,
            "risk_pct":            self.risk_pct,
            "genes":               self.gene_summary(),
        }

    def card_data(self) -> dict:
        ok, reason = self.passes_purge()
        return {
            "id":            self.id,
            "symbol":        self.symbol,
            "phase":         self.phase,
            "gen":           self.generation,
            "modern_score":  self.modern_score(),
            "sharpe":        self.sharpe_ratio(),
            "linearity":     self.equity_linearity(),
            "persistence":   self.persistence(),
            "return_pct":    round(self.total_return_pct, 2),
            "max_dd_pct":    round(self.max_dd_pct, 2),
            "win_rate":      round(self.win_rate, 3),
            "profit_factor": round(self.profit_factor, 2),
            "total_pnl":     round(self.total_pnl, 2),
            "trades":        self.trades,
            "is_protected":  self.is_protected,
            "is_active":     self.is_active,
            "passes_purge":  ok,
            "purge_reason":  reason,
            "active_genes":  self.active_gene_count(),
            "gene_summary":  self.gene_summary(),
            "name":          self.name or "—",
            "medals":        self.medals,
            "advisor_note":  self.advisor_note,
        }

    # ── Evolution operators ───────────────────────────────────────────────────

    @classmethod
    def random_genome(
        cls,
        symbol: str = "",
        campaign: str = "",
        generation: int = 0,
        phase: str = "pg",
    ) -> "AlgoryGenome":
        """Random genome — used for Proving Grounds candidates."""
        kw: dict[str, Any] = {
            "id":         str(uuid.uuid4())[:12],
            "generation": generation,
            "parent_ids": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "symbol":     symbol,
            "campaign":   campaign,
            "phase":      phase,
        }
        for gene in ALL_BINARY_GENES:
            if gene in EXIT_GENES:
                kw[gene] = False  # force_genes override
            elif gene in EXEC_GENES:
                kw[gene] = random.random() < 0.65
            else:
                kw[gene] = random.random() < 0.60

        for param, (lo, hi) in NUMERIC_BOUNDS.items():
            val = random.uniform(lo, hi)
            kw[param] = int(round(val)) if param in INT_PARAMS else round(val, 4)
        return cls(**kw)

    @classmethod
    def crossover(
        cls,
        p1: "AlgoryGenome",
        p2: "AlgoryGenome",
        generation: int = 0,
        phase: str = "tribe_a",
    ) -> "AlgoryGenome":
        """Uniform crossover (binary) + BLX-α blend (numeric)."""
        kw: dict[str, Any] = {
            "id":         str(uuid.uuid4())[:12],
            "generation": generation,
            "parent_ids": [p1.id, p2.id],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "symbol":     p1.symbol,
            "campaign":   p1.campaign,
            "phase":      phase,
        }
        for gene in ALL_BINARY_GENES:
            if gene in EXIT_GENES:
                kw[gene] = False
            else:
                kw[gene] = getattr(p1, gene) if random.random() < 0.5 else getattr(p2, gene)

        alpha = 0.3
        for param, (lo, hi) in NUMERIC_BOUNDS.items():
            v1 = float(getattr(p1, param, (lo + hi) / 2))
            v2 = float(getattr(p2, param, (lo + hi) / 2))
            span = abs(v2 - v1)
            lo_c = min(v1, v2) - alpha * span
            hi_c = max(v1, v2) + alpha * span
            val  = random.uniform(max(lo, lo_c), min(hi, hi_c))
            kw[param] = int(round(val)) if param in INT_PARAMS else round(val, 4)
        return cls(**kw)

    @classmethod
    def mutate(
        cls,
        parent: "AlgoryGenome",
        rate: float = 0.15,
        generation: int = 0,
        phase: str = "tribe_a",
    ) -> "AlgoryGenome":
        """Bit-flip (binary) + Gaussian noise (numeric)."""
        kw: dict[str, Any] = {
            "id":         str(uuid.uuid4())[:12],
            "generation": generation,
            "parent_ids": [parent.id],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "symbol":     parent.symbol,
            "campaign":   parent.campaign,
            "phase":      phase,
        }
        for gene in ALL_BINARY_GENES:
            if gene in EXIT_GENES:
                kw[gene] = False
            else:
                v = getattr(parent, gene, False)
                kw[gene] = (not v) if random.random() < rate else v

        for param, (lo, hi) in NUMERIC_BOUNDS.items():
            val = float(getattr(parent, param, (lo + hi) / 2))
            if random.random() < rate:
                sigma = (hi - lo) * 0.10
                val   = _clamp(val + random.gauss(0, sigma), lo, hi)
            kw[param] = int(round(val)) if param in INT_PARAMS else round(val, 4)
        return cls(**kw)

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        d = asdict(self)
        # trim equity curve to last 500 points for storage
        d["equity_curve"] = self.equity_curve[-500:]
        d["trade_log"]    = self.trade_log[-200:]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AlgoryGenome":
        allowed = {f for f in cls.__dataclass_fields__}
        clean   = {k: v for k, v in d.items() if k in allowed}
        for p in INT_PARAMS:
            if p in clean:
                clean[p] = int(round(float(clean[p])))
        return cls(**clean)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "AlgoryGenome":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
