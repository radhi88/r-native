"""
algory_quick_genome.py
----------------------
Pre-built "broad signal" genomes for immediate live coverage.

These are hand-tuned genomes with multiple signals enabled — NOT evolved via
campaigns. They trade frequently across all timeframes until campaigns finish.

Signal logic: majority vote across 3-5 active signals (RSI + MACD + Stoch +
Engulfing + Wick) with a single lightweight filter (ADX trending).
Bias: EMA direction confirms signal side.

Designed for:
  - M5  : scalping, 8-15 signals/day
  - M15 : intraday, 3-6 signals/day
  - H1  : swing, 1-3 signals/day
  - H4  : position, 1 signal/2-3 days
"""

from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .algory_dna import AlgoryGenome

if TYPE_CHECKING:
    pass

log = logging.getLogger("algory_quick_genome")


def _base(symbol: str, tf: str, **overrides) -> AlgoryGenome:
    """Common base genome — multi-signal, minimal filters."""
    defaults = dict(
        id=str(uuid.uuid4())[:12].upper(),
        generation=0,
        parent_ids=[],
        created_at=datetime.now(timezone.utc).isoformat(),
        symbol=symbol, campaign="quick_genome", phase="live",
        # ── Exec: stop entry (aggressive) ─────────────────────────
        exec_stop=True, exec_limit=False, exec_limit2=False, exec_market2=False,
        # ── Bias: EMA trend confirmation ───────────────────────────
        use_bias_ema=True, use_bias_rsi=True,
        use_bias_adx=False, use_bias_chandelier=False, use_bias_daily_mid=False,
        use_bias_donchian_mid=False, use_bias_htf=False, use_bias_market_struct=False,
        use_bias_momentum=False, use_bias_psar=False, use_bias_sma=False,
        use_bias_trailing=False,
        # ── Signals: 4 active (majority vote = 2+ agree) ───────────
        use_sig_rsi=True, use_sig_macd=True, use_sig_stoch=True,
        use_sig_wick_rejection=True,
        use_sig_bb=False, use_sig_breakout=False, use_sig_cci=False,
        use_sig_engulfing=False, use_sig_fib=False, use_sig_inside_break=False,
        use_sig_mom_break=False, use_sig_pin_bar=False, use_sig_three_soldiers=False,
        use_sig_williams=False,
        # ── Filters: only ADX (trend strength check) ───────────────
        use_filt_adx=True,
        use_filt_adr_exhaust=False, use_filt_bb=False, use_filt_cci=False,
        use_filt_consec=False, use_filt_doji=False, use_filt_keltner=False,
        use_filt_receding=False, use_filt_rsi=False, use_filt_sma=False,
        use_filt_volatility=False,
        # ── Exits ──────────────────────────────────────────────────
        use_breakeven=False, use_eod_close=True, use_partial_tp=False,
        use_sl_lock=False, use_sl_reduce=False,
        # ── Risk ───────────────────────────────────────────────────
        risk_pct=1.0, atr_sl_mult=1.5, tp_max=3.0, sl_max=2.0, min_rr=1.5,
        # ── Hours ──────────────────────────────────────────────────
        start_hour=4, end_hour=20, friday_close=18,
        # ── Indicator defaults ─────────────────────────────────────
        rsi_period=14, ema_period=20, adx_period=14, adx_threshold=20.0,
        macd_fast=12, macd_slow=26,
        stoch_k_period=14, stoch_d_period=3, stoch_slowing=3,
        wick_ratio=1.5, atr_ma_period=14,
        name=f"QUICK_{symbol}_{tf}",
        advisor_note="Auto-generated broad-signal genome for immediate coverage",
    )
    defaults.update(overrides)
    # Filter to valid AlgoryGenome fields only
    valid = {k: v for k, v in defaults.items() if k in AlgoryGenome.__dataclass_fields__}
    return AlgoryGenome(**valid)


# ── Timeframe-tuned variants ──────────────────────────────────────────────────

def quick_m1(symbol: str) -> AlgoryGenome:
    return _base(symbol, "M1",
        rsi_period=5, ema_period=8, adx_period=8, adx_threshold=15.0,
        stoch_k_period=5, stoch_d_period=3, stoch_slowing=2,
        atr_sl_mult=1.0, tp_max=2.0, min_rr=1.1,
        stop_offset_atr=0.2, stop_expiry_bars=5,
        start_hour=7, end_hour=20, friday_close=17,
    )

def quick_m5(symbol: str) -> AlgoryGenome:
    return _base(symbol, "M5",
        rsi_period=7, ema_period=10, adx_period=10, adx_threshold=18.0,
        stoch_k_period=7, stoch_d_period=3, stoch_slowing=2,
        atr_sl_mult=1.2, tp_max=2.5, min_rr=1.2,
        stop_offset_atr=0.3, stop_expiry_bars=8,
        start_hour=7, end_hour=20, friday_close=17,
    )

def quick_m15(symbol: str) -> AlgoryGenome:
    return _base(symbol, "M15",
        rsi_period=10, ema_period=14, adx_period=12, adx_threshold=20.0,
        stoch_k_period=10, stoch_d_period=3,
        atr_sl_mult=1.3, tp_max=3.0, min_rr=1.2,
        stop_offset_atr=0.35, stop_expiry_bars=10,
        start_hour=6, end_hour=20, friday_close=17,
    )

def quick_m30(symbol: str) -> AlgoryGenome:
    return _base(symbol, "M30",
        rsi_period=12, ema_period=18, adx_period=14, adx_threshold=22.0,
        atr_sl_mult=1.4, tp_max=3.5, min_rr=1.3,
        stop_offset_atr=0.38, stop_expiry_bars=12,
    )

def quick_h1(symbol: str) -> AlgoryGenome:
    return _base(symbol, "H1",
        rsi_period=14, ema_period=20, adx_period=14, adx_threshold=22.0,
        atr_sl_mult=1.5, tp_max=4.0, min_rr=1.3,
        stop_offset_atr=0.4, stop_expiry_bars=12,
        use_sig_engulfing=True,
    )

def quick_h4(symbol: str) -> AlgoryGenome:
    return _base(symbol, "H4",
        rsi_period=14, ema_period=50, adx_period=14, adx_threshold=25.0,
        atr_sl_mult=1.8, tp_max=5.0, min_rr=1.5,
        stop_offset_atr=0.5, stop_expiry_bars=8,
        use_sig_engulfing=True, use_sig_bb=True,
    )


TF_FACTORY = {
    "M1":  quick_m1,
    "M5":  quick_m5,
    "M15": quick_m15,
    "M30": quick_m30,
    "H1":  quick_h1,
    "H4":  quick_h4,
}


def activate_quick_genomes(integrator, symbols: list[str], timeframes: list[str]) -> int:
    """
    For every (symbol, tf) that has NO active genome, create and activate
    a quick broad-signal genome immediately.

    Called from AlgoryRunner after bootstrap_from_algory_vault().
    Returns number of quick genomes activated.
    """
    activated = 0
    for sym in symbols:
        for tf in timeframes:
            if integrator.registry.get(sym, tf) is not None:
                continue  # already have a vault genome — keep it
            factory = TF_FACTORY.get(tf)
            if factory is None:
                continue
            g = factory(sym)
            integrator.registry.activate(g, sym, tf)
            activated += 1
            log.info("Quick genome activated: %s %s | signals=RSI+MACD+Stoch+Wick | filter=ADX",
                     sym, tf)

    if activated:
        integrator.registry.save()
        log.info("Quick genomes: %d activated across uncovered pairs", activated)
    return activated
