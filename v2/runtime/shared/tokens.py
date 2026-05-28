"""shared/tokens.py — Design Tokens for the trading system.

Born 2026-05-28 via /design-system audit.

These are the ATOMIC values that define the entire system's behavior.
Like CSS custom properties, but for trading.

Categories:
  • IDENTITY     — magic numbers + names
  • SYMBOLS      — tradable instruments + per-symbol params
  • REGIMES      — market state classifiers
  • SESSIONS     — time windows
  • RISK         — position sizing + stops
  • TIMING       — refresh intervals
  • PATHS        — data + config file locations
  • THRESHOLDS   — decision boundaries

USAGE:
    from runtime.shared.tokens import RISK, SYMBOLS, REGIMES, MAGICS
    sl_pts = RISK["XAU"]["sl_pts"]
    magic = MAGICS["genome"]
"""
from pathlib import Path

# ─────────────────────────────────────────────────────────────────
# IDENTITY — magic number registry (immutable mapping)
# ─────────────────────────────────────────────────────────────────
MAGICS = {
    "claude_auto":      99777,    # 7 rules engine
    "CLAUDE_BRAIN_EA":  99778,    # native MQL5
    "palace_council":   99779,    # 5-expert vote
    "claude_simple":    99780,    # aggressive 2/3 MTF
    "claude_smart":     99781,    # ADX + session filtered
    "claude_genome":    99782,    # evolved genome (LIVE)
    "manual":           0,        # user manual trades
    "FRIDAY_brain":     20260600, # LLM brain orders
    "algory_sniper":    20260605, # tactical_sniper
    "R_Native_v1":      20260650, # GA evolved (older)
}

# Reverse map: magic → name
NAMES = {v: k for k, v in MAGICS.items()}

# ─────────────────────────────────────────────────────────────────
# SYMBOLS — instrument config per symbol
# ─────────────────────────────────────────────────────────────────
SYMBOLS = {
    "XAUUSDm": {
        "type":        "metal",
        "pip_value":   1.0,      # USD per pip per 0.01 lot
        "tick_size":   0.01,
        "spread_max":  0.50,     # block trades if spread above
        "atr_min":     0.50,     # need this much volatility
        "atr_max":     8.00,     # too volatile = skip
    },
    "XAGUSDm": {
        "type":        "metal",
        "pip_value":   0.50,
        "tick_size":   0.001,
        "spread_max":  0.05,
        "atr_min":     0.05,
        "atr_max":     0.50,
    },
    "BTCUSDm": {
        "type":        "crypto",
        "pip_value":   1.0,
        "tick_size":   1.0,
        "spread_max":  50,
        "atr_min":     50,
        "atr_max":     2000,
    },
    "EURUSDm": {
        "type":        "fx",
        "pip_value":   1.0,
        "tick_size":   0.00001,
        "spread_max":  0.0003,
        "atr_min":     0.0002,
        "atr_max":     0.0050,
    },
}

# ─────────────────────────────────────────────────────────────────
# REGIMES — market state taxonomy
# ─────────────────────────────────────────────────────────────────
REGIMES = {
    "TREND_UP":   {"trade_allowed": True,  "preferred_side": "BUY"},
    "TREND_DOWN": {"trade_allowed": True,  "preferred_side": "SELL"},
    "CHOP":       {"trade_allowed": False, "preferred_side": None},
    "SPIKE":      {"trade_allowed": False, "preferred_side": None},
    "TRANSITION": {"trade_allowed": True,  "preferred_side": None},  # cautious
}

# ─────────────────────────────────────────────────────────────────
# SESSIONS — UTC time windows
# ─────────────────────────────────────────────────────────────────
SESSIONS = {
    "ASIAN":       {"start_h": 22, "end_h": 8,  "quality": "low"},
    "LONDON":      {"start_h": 8,  "end_h": 13, "quality": "high"},
    "NY_OVERLAP":  {"start_h": 13, "end_h": 17, "quality": "best"},
    "NY_LATE":     {"start_h": 17, "end_h": 21, "quality": "medium"},
    "TRANSITION":  {"start_h": 21, "end_h": 22, "quality": "skip"},
}

PREFERRED_SESSIONS = ["NY_OVERLAP", "LONDON", "NY_LATE"]

# ─────────────────────────────────────────────────────────────────
# RISK — sizing + stops per symbol (scaled to account)
# ─────────────────────────────────────────────────────────────────
RISK = {
    "XAUUSDm": {
        "sl_pts":         3.0,     # tight SL for $100 account
        "tp_pts":         8.0,     # R:R ~2.7:1
        "lot_micro":      0.01,    # for accounts < $200
        "lot_mini":       0.02,    # for $200-$500
        "lot_standard":   0.05,    # for > $500
        "max_open":       2,
        "max_lot_total":  0.05,
        "max_per_trade_pct": 5.0,
    },
    "XAGUSDm": {
        "sl_pts":         0.10,
        "tp_pts":         0.25,
        "lot_micro":      0.01,
        "max_open":       1,
        "max_lot_total":  0.02,
        "max_per_trade_pct": 3.0,
    },
}

# Account-level risk
ACCOUNT_RISK = {
    "daily_loss_pct":    15.0,   # stop trading after -15% day
    "equity_floor_pct":  70.0,   # stop trading at -30% drawdown
    "consec_sl_pause":   2,      # 2 SLs → pause
    "consec_pause_min":  30,     # pause duration
}

# ─────────────────────────────────────────────────────────────────
# TIMING — refresh intervals (seconds)
# ─────────────────────────────────────────────────────────────────
TIMING = {
    "brain_capture":     2.0,    # market snapshot
    "regime_check":      5.0,    # regime classifier
    "orchestrator":      15.0,   # picks active engines
    "trader_poll":       5.0,    # each trader checks signal
    "genome_eval":       5.0,    # genomes evaluate snapshot
    "council_vote":      2.0,    # council reads new signals
    "perf_coordinator":  30.0,   # update engine PnL
    "evolver_cycle":     600.0,  # genome evolution (10 min)
    "promoter_check":    300.0,  # auto-promote check (5 min)
    "footprint_export":  3.0,    # MT5 indicator → JSON
    "dashboard_refresh": 3.0,    # live view
    "cooldown_default":  90.0,   # between trades
}

# ─────────────────────────────────────────────────────────────────
# THRESHOLDS — decision boundaries
# ─────────────────────────────────────────────────────────────────
THRESHOLDS = {
    "adx_chop_max":           18,    # ADX below = chop
    "adx_trend_min":          25,    # ADX above = trending
    "vol_spike_ratio":        2.0,   # vol > 2× avg = spike
    "rsi_buy_max":            65,    # don't BUY above this
    "rsi_sell_min":           35,    # don't SELL below this
    "rsi_oversold":           30,
    "rsi_overbought":         70,
    "pressure_min_abs":       3,     # |pressure| min for entry
    "mtf_min_agreement":      2,     # of 4 TFs need to agree
    "imbalance_ratio_l1":     2.0,
    "imbalance_ratio_l2":     3.0,
    "imbalance_ratio_l3":     4.0,
    "imbalance_min_vol":      10,
    "fp_imb_count_min":       2,     # min imbalances per 3 bars
    "spread_max_atr_ratio":   0.20,  # spread/atr_h1 must be below this
    "no_chase_pts":           3.0,   # don't re-enter within this distance
}

# ─────────────────────────────────────────────────────────────────
# PATHS — single source of truth
# ─────────────────────────────────────────────────────────────────
# Auto-detect ROOT from this file's location: <ROOT>/runtime/shared/tokens.py
# Falls back to the canonical path if detection looks wrong.
_detected = Path(__file__).resolve().parent.parent.parent
ROOT = _detected if (_detected / "runtime").exists() else Path(r"C:\Users\Radhi\MT5\r_native_v2")
DATA = ROOT / "data"
DOCS = ROOT / "docs"
RUNTIME = ROOT / "runtime"
COMMON_FILES = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")

PATHS = {
    # State (current snapshot, frequently overwritten)
    "brain_live":         DATA / "brain_live.json",
    "market_regime":      DATA / "market_regime.json",
    "active_engines":     DATA / "active_engines.json",
    "live_genome":        DATA / "live_genome.json",
    "engine_performance": DATA / "engine_performance.json",
    "genome_fitness":     DATA / "genome_fitness.json",
    "genomes_population": DATA / "genomes_population.json",
    "footprint_cells":    COMMON_FILES / "footprint_cells.json",
    "friday_orders":      COMMON_FILES / "friday_brain_orders.json",

    # History (append-only logs)
    "brain_memory":       DATA / "brain_memory.jsonl",
    "brain_decisions":    DATA / "brain_decisions.jsonl",
    "user_trades":        DATA / "user_trades.jsonl",
    "genome_signals":     DATA / "genome_signals.jsonl",
    "council_votes":      DATA / "council_votes.jsonl",
    "regime_history":     DATA / "regime_history.jsonl",
    "genome_lineage":     DATA / "genome_lineage.jsonl",
    "promotion_log":      DATA / "promotion_log.jsonl",
}

# Per-trader trade logs (append-only)
TRADE_LOGS = {
    "claude_simple":      DATA / "claude_simple_trades.jsonl",
    "claude_smart":       DATA / "claude_smart_trades.jsonl",
    "claude_genome":      DATA / "claude_genome_trades.jsonl",
    "council":            DATA / "council_executions.jsonl",
}

# ─────────────────────────────────────────────────────────────────
# DEFAULT SYMBOL (most code targets XAU)
# ─────────────────────────────────────────────────────────────────
DEFAULT_SYMBOL = "XAUUSDm"


def get_lot_for_balance(balance: float, symbol: str = DEFAULT_SYMBOL) -> float:
    """Returns appropriate lot size based on account balance."""
    risk = RISK.get(symbol, {})
    if balance < 200: return risk.get("lot_micro", 0.01)
    if balance < 500: return risk.get("lot_mini", 0.02)
    return risk.get("lot_standard", 0.05)
