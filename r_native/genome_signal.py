"""genome_signal.py — turn a Genome's flags into a real entry decision.

THE problem this solves: prior to this module, trade_gate only used
Algory's 4 hardcoded archetypes (BREAKOUT_HUNTER, MEAN_REVERTER, etc.)
to decide whether to enter. The deployed_genome's actual signal flags
(use_sig_breakout, use_sig_williams, etc.) were never consulted at
decision time — they only affected SL/TP/session. So evolution was
running but its outputs couldn't actually drive trades.

This module reads the genome's `flags` dict + the live market snapshot
and produces an entry decision + confidence score.

INPUT snapshot shape (what brain_server sends):
  {
    h1:   {current, atr, rsi, swing_high, swing_low, range_size, bias, slope_atr},
    m15:  same shape,
    h4:   same shape,
    bid:  float, ask: float,
  }

OUTPUT:
  {
    decision:   "BUY" | "SELL" | "NO",
    confidence: 0..100,
    reasons:    [list of strings],
    signals_fired:    [(flag, dir, why), ...],
    biases_aligned:   [(flag, why), ...],
    filters_blocking: [(flag, why), ...],
  }
"""
from __future__ import annotations


def _h1(snap): return snap.get("h1") or {}
def _m15(snap): return snap.get("m15") or {}
def _h4(snap): return snap.get("h4") or {}
def _bid(snap): return snap.get("bid") or _h1(snap).get("current") or 0


# ─── Signal evaluators ───  return (vote, reason)
def _sig_breakout(snap):
    """Price near/above swing_high → BUY; near/below swing_low → SELL."""
    h1 = _h1(snap); bid = _bid(snap)
    sh = h1.get("swing_high"); sl = h1.get("swing_low")
    rng = h1.get("range_size") or 0
    if not (bid and sh and sl and rng): return 0, "no h1 levels"
    # Buffer = 5% of range from swing
    buf = rng * 0.05
    if bid >= sh - buf: return +1, f"near swing_high {sh}"
    if bid <= sl + buf: return -1, f"near swing_low {sl}"
    return 0, "mid-range"


def _sig_inside_break(snap):
    """Strong move from mid-range (slope_atr ≥ 0.7 either way)."""
    h1 = _h1(snap)
    slope = h1.get("slope_atr")
    if slope is None: return 0, "no slope"
    if slope >= 0.7:  return +1, f"slope_atr +{slope} (impulse up)"
    if slope <= -0.7: return -1, f"slope_atr {slope} (impulse down)"
    return 0, f"slope {slope} weak"


def _sig_williams(snap):
    """Use RSI as proxy for Williams %R (same oversold/overbought concept).
    Williams flag on a genome usually means "fade extreme RSI"."""
    h1 = _h1(snap); rsi = h1.get("rsi")
    if rsi is None: return 0, "no rsi"
    if rsi <= 28: return +1, f"rsi={rsi} oversold (bounce)"
    if rsi >= 72: return -1, f"rsi={rsi} overbought (fade)"
    return 0, f"rsi={rsi} neutral"


def _sig_rsi(snap):
    h1 = _h1(snap); rsi = h1.get("rsi")
    if rsi is None: return 0, "no rsi"
    if rsi <= 30: return +1, f"rsi={rsi} oversold"
    if rsi >= 70: return -1, f"rsi={rsi} overbought"
    return 0, f"rsi={rsi} neutral"


def _sig_bb(snap):
    """Bollinger touch via range proxy: top 10% of range → SELL, bottom → BUY."""
    h1 = _h1(snap); bid = _bid(snap)
    sh = h1.get("swing_high"); sl = h1.get("swing_low")
    if not (bid and sh and sl) or sh == sl: return 0, "no range"
    rel = (bid - sl) / (sh - sl)
    if rel <= 0.1: return +1, f"lower-10% of range (rel={rel:.2f})"
    if rel >= 0.9: return -1, f"upper-10% of range (rel={rel:.2f})"
    return 0, f"mid (rel={rel:.2f})"


def _sig_mom_break(snap):
    """Momentum break — slope_atr magnitude."""
    h1 = _h1(snap)
    slope = h1.get("slope_atr")
    if slope is None: return 0, "no slope"
    if slope >= 1.0:  return +1, f"strong up slope {slope}"
    if slope <= -1.0: return -1, f"strong down slope {slope}"
    return 0, "weak momentum"


def _sig_macd(snap):
    """MACD proxy via M15 vs H1 RSI delta."""
    m15 = _m15(snap); h1 = _h1(snap)
    m_rsi = m15.get("rsi"); h_rsi = h1.get("rsi")
    if m_rsi is None or h_rsi is None: return 0, "no rsi pair"
    delta = m_rsi - h_rsi
    if delta > 8:  return +1, f"m15 rsi leads h1 by {delta:.0f}"
    if delta < -8: return -1, f"m15 rsi lags h1 by {abs(delta):.0f}"
    return 0, f"rsi delta {delta:.0f}"


def _sig_engulfing(snap):
    """Engulfing proxy: M15 bias flipped vs H1."""
    m15_bias = _m15(snap).get("bias", "RANGE")
    h1_bias  = _h1(snap).get("bias", "RANGE")
    if m15_bias == "UP" and h1_bias == "DOWN":   return +1, "m15 flip up"
    if m15_bias == "DOWN" and h1_bias == "UP":   return -1, "m15 flip down"
    return 0, f"m15={m15_bias} h1={h1_bias}"


def _sig_pin_bar(snap):
    """Pin bar proxy: large slope but near range extreme."""
    h1 = _h1(snap); bid = _bid(snap)
    slope = h1.get("slope_atr")
    sh = h1.get("swing_high"); sl = h1.get("swing_low")
    if slope is None or not (bid and sh and sl) or sh == sl:
        return 0, "no data"
    rel = (bid - sl) / (sh - sl)
    if slope >= 0.5 and rel <= 0.2: return +1, f"impulse off low (rel={rel:.2f})"
    if slope <= -0.5 and rel >= 0.8: return -1, f"impulse off high (rel={rel:.2f})"
    return 0, "no pin shape"


SIGNAL_EVALUATORS = {
    "use_sig_breakout":        _sig_breakout,
    "use_sig_inside_break":    _sig_inside_break,
    "use_sig_williams":        _sig_williams,
    "use_sig_rsi":             _sig_rsi,
    "use_sig_bb":              _sig_bb,
    "use_sig_mom_break":       _sig_mom_break,
    "use_sig_macd":            _sig_macd,
    "use_sig_engulfing":       _sig_engulfing,
    "use_sig_pin_bar":         _sig_pin_bar,
}

# Volume-Profile signals — register lazily so missing module never breaks import
try:
    from r_native.volume_profile import (
        vp_signal_poc_bounce, vp_signal_vah_resist, vp_signal_val_support,
        vp_signal_lvn_breakout, vp_signal_npoc_magnet,
    )
    SIGNAL_EVALUATORS.update({
        "use_sig_vp_poc":         vp_signal_poc_bounce,    # POC bounce/reject
        "use_sig_vp_vah":         vp_signal_vah_resist,    # VAH resistance
        "use_sig_vp_val":         vp_signal_val_support,   # VAL support
        "use_sig_vp_lvn":         vp_signal_lvn_breakout,  # LVN fast-move break
        "use_sig_vp_npoc":        vp_signal_npoc_magnet,   # naked POC magnet
    })
except Exception as _e:
    print(f"[genome_signal] volume_profile signals not loaded: {_e}", flush=True)

# Macro-context signals — DXY/VIX align with USD pair direction. Lazy import
# so a network outage at startup never breaks the trade gate.
try:
    from r_native.macro_context import macro_signal_align, macro_signal_vix_calm
    SIGNAL_EVALUATORS.update({
        "use_sig_macro_align":   macro_signal_align,    # DXY-vs-pair alignment
        "use_sig_vix_calm":      macro_signal_vix_calm, # VIX risk-on filter
    })
except Exception as _e:
    print(f"[genome_signal] macro_context signals not loaded: {_e}", flush=True)

# Retail-sentiment signal — ApeWisdom (free Reddit/WSB feed).
try:
    from r_native.sentiment_feed import sentiment_signal_align
    SIGNAL_EVALUATORS.update({
        "use_sig_sentiment_align": sentiment_signal_align,
    })
except Exception as _e:
    print(f"[genome_signal] sentiment_feed signal not loaded: {_e}", flush=True)

# Extra indicators (precise math from MT5 bars): CCI, Stoch, Fib, 3-soldiers,
# Wick-rejection, no-friday-open. Lazy import so missing MT5 doesn't break us.
try:
    from r_native.extra_indicators import (
        sig_cci, sig_stoch, sig_fib, sig_three_soldiers, sig_wick_rejection,
        filt_no_fri_open,
    )
    SIGNAL_EVALUATORS.update({
        "use_sig_cci":              sig_cci,
        "use_sig_stoch":            sig_stoch,
        "use_sig_fib":              sig_fib,
        "use_sig_three_soldiers":   sig_three_soldiers,
        "use_sig_wick_rejection":   sig_wick_rejection,
    })
except Exception as _e:
    print(f"[genome_signal] extra_indicators signals not loaded: {_e}", flush=True)


# ─── Bias evaluators ───
def _bias_ema(snap):
    """EMA proxy: H1 bias direction + slope sign."""
    h1 = _h1(snap)
    slope = h1.get("slope_atr") or 0
    bias  = h1.get("bias", "RANGE")
    if bias == "UP" or slope > 0.2: return +1, f"bias={bias} slope={slope}"
    if bias == "DOWN" or slope < -0.2: return -1, f"bias={bias} slope={slope}"
    return 0, "neutral"


def _bias_rsi(snap):
    h1 = _h1(snap); rsi = h1.get("rsi")
    if rsi is None: return 0, "no rsi"
    return (+1, f"rsi={rsi}>50") if rsi > 50 else (-1, f"rsi={rsi}<50")


def _bias_market_struct(snap):
    bias = _h1(snap).get("bias", "RANGE")
    if bias == "UP": return +1, "h1 uptrend"
    if bias == "DOWN": return -1, "h1 downtrend"
    return 0, "range"


def _bias_chandelier(snap):
    """Chandelier proxy: slope_atr (trend strength)."""
    slope = _h1(snap).get("slope_atr")
    if slope is None: return 0, "no slope"
    if slope > 0.3: return +1, f"trend up (slope {slope})"
    if slope < -0.3: return -1, f"trend down (slope {slope})"
    return 0, "weak trend"


def _bias_donchian_mid(snap):
    """Donchian mid proxy: position vs swing midpoint."""
    h1 = _h1(snap); bid = _bid(snap)
    sh = h1.get("swing_high"); sl = h1.get("swing_low")
    if not (bid and sh and sl): return 0, "no range"
    mid = (sh + sl) / 2
    return (+1, f"above donchian mid {mid:.2f}") if bid > mid else (-1, f"below mid {mid:.2f}")


def _bias_htf(snap):
    """Higher-TF (H4) bias."""
    h4_bias = _h4(snap).get("bias", "RANGE")
    if h4_bias == "UP": return +1, "h4 up"
    if h4_bias == "DOWN": return -1, "h4 down"
    return 0, "h4 range"


def _bias_momentum(snap):
    slope = _h1(snap).get("slope_atr")
    if slope is None: return 0, "no slope"
    return (+1, f"+momentum {slope}") if slope > 0 else (-1, f"-momentum {slope}")


def _bias_adx(snap):
    """ADX proxy: |slope_atr| as trend strength."""
    h1 = _h1(snap); slope = abs(h1.get("slope_atr") or 0)
    if slope < 0.3: return 0, f"slope|{slope}| too weak"
    bias = h1.get("bias", "RANGE")
    if bias == "UP": return +1, "strong up trend"
    if bias == "DOWN": return -1, "strong down trend"
    return 0, "range"


def _bias_sma(snap):
    """SMA proxy: same as ema but uses H4 bias for slower view."""
    h4_bias = _h4(snap).get("bias", "RANGE")
    if h4_bias == "UP": return +1, "h4 sma up"
    if h4_bias == "DOWN": return -1, "h4 sma down"
    return 0, "h4 flat"


def _bias_daily_mid(snap):
    """Position vs H4 swing midpoint."""
    h4 = _h4(snap); bid = _bid(snap)
    sh = h4.get("swing_high"); sl = h4.get("swing_low")
    if not (bid and sh and sl): return 0, "no h4 range"
    mid = (sh + sl) / 2
    return (+1, f"above daily mid") if bid > mid else (-1, "below daily mid")


def _bias_psar(snap):
    """PSAR proxy: trending H1 + slope alignment."""
    h1 = _h1(snap); slope = h1.get("slope_atr") or 0
    if abs(slope) < 0.3: return 0, "no parabolic trend"
    return (+1, f"psar up {slope}") if slope > 0 else (-1, f"psar down {slope}")


def _bias_trailing(snap):
    """Trailing-stop proxy: H1 bias only."""
    return _bias_market_struct(snap)


BIAS_EVALUATORS = {
    "use_bias_ema":           _bias_ema,
    "use_bias_rsi":           _bias_rsi,
    "use_bias_market_struct": _bias_market_struct,
    "use_bias_chandelier":    _bias_chandelier,
    "use_bias_donchian_mid":  _bias_donchian_mid,
    "use_bias_htf":           _bias_htf,
    "use_bias_momentum":      _bias_momentum,
    "use_bias_adx":           _bias_adx,
    "use_bias_sma":           _bias_sma,
    "use_bias_daily_mid":     _bias_daily_mid,
    "use_bias_psar":          _bias_psar,
    "use_bias_trailing":      _bias_trailing,
}


# ─── Filter evaluators ───  return (blocks_trade, reason)
def _filt_doji(snap):
    """Doji proxy: very weak slope (no impulse) on H1."""
    slope = abs(_h1(snap).get("slope_atr") or 0)
    if slope < 0.1: return True, f"flat slope {slope} (doji-like)"
    return False, f"slope {slope} OK"


def _filt_bb(snap):
    """BB squeeze proxy: very small range relative to current price."""
    h1 = _h1(snap); bid = _bid(snap)
    rng = h1.get("range_size") or 0
    if not bid: return False, "no price"
    rng_pct = (rng / bid) * 100 if bid > 0 else 0
    if rng_pct < 0.3:
        return True, f"range only {rng_pct:.2f}% of price (squeeze)"
    return False, f"range {rng_pct:.2f}% OK"


def _filt_adx(snap):
    """ADX proxy via slope strength."""
    slope = abs(_h1(snap).get("slope_atr") or 0)
    if slope < 0.2: return True, f"|slope|={slope} weak trend"
    return False, f"|slope|={slope} OK"


def _filt_sma(snap):
    """Reject if H1 trend opposes H4 strongly."""
    h1_bias = _h1(snap).get("bias", "RANGE")
    h4_bias = _h4(snap).get("bias", "RANGE")
    if h1_bias == "UP" and h4_bias == "DOWN": return True, "h1-up vs h4-down conflict"
    if h1_bias == "DOWN" and h4_bias == "UP": return True, "h1-down vs h4-up conflict"
    return False, "tf aligned"


def _filt_rsi(snap):
    """Block if RSI in mid zone (no edge)."""
    rsi = _h1(snap).get("rsi")
    if rsi is None: return False, "no rsi"
    if 40 < rsi < 60: return True, f"rsi={rsi} stuck mid"
    return False, f"rsi={rsi} edge"


def _filt_volatility(snap):
    """Block if ATR too tiny."""
    atr = _h1(snap).get("atr") or 0
    bid = _bid(snap) or 1
    atr_pct = (atr / bid) * 100 if bid > 0 else 0
    if atr_pct < 0.15: return True, f"atr only {atr_pct:.2f}% of price"
    return False, f"atr {atr_pct:.2f}% OK"


def _filt_consec(snap):
    """No simple proxy — skip."""
    return False, "n/a"


def _filt_cci(snap):
    return _filt_rsi(snap)


def _filt_keltner(snap):
    return _filt_bb(snap)


def _filt_receding(snap):
    """Block if slope strongly reversing across TFs."""
    h1_slope = _h1(snap).get("slope_atr") or 0
    m15_slope = _m15(snap).get("slope_atr") or 0
    if h1_slope > 0 and m15_slope < -0.3: return True, "h1+ m15- diverging"
    if h1_slope < 0 and m15_slope > 0.3: return True, "h1- m15+ diverging"
    return False, "aligned"


def _filt_adr_exhaust(snap):
    """Block if price near H4 extremes (range exhausted)."""
    h4 = _h4(snap); bid = _bid(snap)
    sh = h4.get("swing_high"); sl = h4.get("swing_low")
    if not (bid and sh and sl) or sh == sl: return False, "no h4 range"
    rel = (bid - sl) / (sh - sl)
    if rel < 0.05 or rel > 0.95: return True, f"price at h4 extreme ({rel:.2f})"
    return False, f"rel={rel:.2f} OK"


FILTER_EVALUATORS = {
    "use_filt_doji":         _filt_doji,
    "use_filt_bb":           _filt_bb,
    "use_filt_adx":          _filt_adx,
    "use_filt_sma":          _filt_sma,
    "use_filt_rsi":          _filt_rsi,
    "use_filt_volatility":   _filt_volatility,
    "use_filt_consec":       _filt_consec,
    "use_filt_cci":          _filt_cci,
    "use_filt_keltner":      _filt_keltner,
    "use_filt_receding":     _filt_receding,
    "use_filt_adr_exhaust":  _filt_adr_exhaust,
}

# Calendar / weekend-gap filter from extra_indicators
try:
    from r_native.extra_indicators import filt_no_fri_open as _filt_no_fri_open
    FILTER_EVALUATORS["use_filt_no_fri_open"] = _filt_no_fri_open
except Exception as _e:
    print(f"[genome_signal] no_fri_open filter not loaded: {_e}", flush=True)


# ─── Main entry point ───
def evaluate_council(snapshot: dict) -> dict:
    """ENSEMBLE COUNCIL — runs EVERY registered signal + bias on the live
    snapshot, regardless of any specific genome's flag set. Returns the
    aggregated direction + a 0-100 ensemble confidence.

    Use case: the trade_gate can call this AS WELL AS the per-genome
    decide_entry, and use the council as a second opinion:
      • if council strongly DISAGREES with genome → veto entry
      • if council strongly AGREES → boost confidence
      • returns transparent vote tallies so the user can see what every
        indicator says even when their deployed genome doesn't use it.
    """
    sig_buy = 0; sig_sell = 0; sig_neutral = 0
    sig_votes = []
    for name, evaluator in SIGNAL_EVALUATORS.items():
        try:
            vote, reason = evaluator(snapshot)
        except Exception:
            vote, reason = 0, "err"
        sig_votes.append((name, vote, reason[:60]))
        if vote == +1:   sig_buy += 1
        elif vote == -1: sig_sell += 1
        else:            sig_neutral += 1

    bias_buy = 0; bias_sell = 0
    bias_votes = []
    for name, evaluator in BIAS_EVALUATORS.items():
        try:
            vote, reason = evaluator(snapshot)
        except Exception:
            vote, reason = 0, "err"
        bias_votes.append((name, vote, reason[:60]))
        if vote == +1:   bias_buy += 1
        elif vote == -1: bias_sell += 1

    # Direction = combined signal+bias majority
    total_buy  = sig_buy + bias_buy
    total_sell = sig_sell + bias_sell
    if total_buy > total_sell:
        direction = "BUY"
        agreement = total_buy / max(1, total_buy + total_sell)
    elif total_sell > total_buy:
        direction = "SELL"
        agreement = total_sell / max(1, total_buy + total_sell)
    else:
        direction = "NEUTRAL"
        agreement = 0.5

    # Active filters' veto count
    filter_vetos = []
    for name, evaluator in FILTER_EVALUATORS.items():
        try:
            blocks, reason = evaluator(snapshot)
            if blocks: filter_vetos.append((name, reason[:60]))
        except Exception: pass

    # Confidence 0-100
    confidence = round(agreement * 100)

    return {
        "direction":      direction,
        "confidence":     confidence,
        "agreement_pct":  round(agreement * 100, 1),
        "signals": {
            "buy":     sig_buy,
            "sell":    sig_sell,
            "neutral": sig_neutral,
            "total":   len(SIGNAL_EVALUATORS),
            "votes":   sig_votes,
        },
        "biases": {
            "buy":   bias_buy,
            "sell":  bias_sell,
            "total": len(BIAS_EVALUATORS),
            "votes": bias_votes,
        },
        "filter_vetos": filter_vetos,
    }


def decide_entry_with_council(genome_flags: dict, snapshot: dict,
                               council_required_agreement: float = 0.55
                               ) -> dict:
    # Cycle 25 REVERT: cycle-23's loosening to 0.65 fired 2 metals trades
    # that hit -$13 in 30 min. Restored to 0.55. The "more entries" goal
    # is still achievable via volatility_hunter pending grid + safer
    # symbol_learning thresholds — without lowering council quality.
    """Genome's decide_entry + council cross-check.

    Process:
      1. Run the genome's own evaluation (the standard decide_entry)
      2. Run the council (all 22 signals + 12 biases) regardless
      3. If genome wants BUY but council mostly says SELL → VETO
      4. If they agree → boost genome's confidence by +15
      5. If council neutral → no change

    Returns the genome decision dict with extra fields:
      • council: full council eval
      • council_agrees: bool
      • original_confidence + final_confidence
    """
    genome_decision = decide_entry(genome_flags, snapshot)
    council = evaluate_council(snapshot)
    genome_decision["council"] = {
        "direction":     council["direction"],
        "confidence":    council["confidence"],
        "signals_buy":   council["signals"]["buy"],
        "signals_sell":  council["signals"]["sell"],
        "biases_buy":    council["biases"]["buy"],
        "biases_sell":   council["biases"]["sell"],
        "vetos":         len(council["filter_vetos"]),
    }
    if genome_decision.get("decision") in ("BUY", "SELL"):
        gdir = genome_decision["decision"]
        cdir = council["direction"]
        orig_conf = genome_decision.get("confidence", 0)
        genome_decision["original_confidence"] = orig_conf
        # 3) Council strongly opposes → veto
        if cdir != "NEUTRAL" and cdir != gdir and \
           council["confidence"] >= int(council_required_agreement * 100):
            genome_decision["decision"]   = "NO"
            genome_decision["confidence"] = 0
            genome_decision["council_agrees"] = False
            genome_decision.setdefault("reasons", []).append(
                f"🛑 council vetoed: {council['signals']['sell']}S vs "
                f"{council['signals']['buy']}B says {cdir} ({council['confidence']}%)"
            )
        # 4) Council agrees → boost confidence
        elif cdir == gdir:
            boost = 15
            genome_decision["confidence"] = min(100, orig_conf + boost)
            genome_decision["council_agrees"] = True
            genome_decision.setdefault("reasons", []).insert(0,
                f"✅ council agrees {gdir} ({council['confidence']}%) → +{boost}"
            )
        else:
            genome_decision["council_agrees"] = None  # neutral
    return genome_decision


def decide_entry(genome_flags: dict, snapshot: dict) -> dict:
    """Apply the genome's active flags to the current market snapshot.

    snapshot fields expected (build via build_snapshot from trade_gate snap):
      h1/m15/h4: {current, atr, rsi, swing_high, swing_low, range_size,
                  bias, slope_atr}
      bid, ask: floats
    """
    if not isinstance(genome_flags, dict):
        return {"decision": "NO", "confidence": 0,
                "reasons": ["genome_flags not a dict"]}

    signals_fired   = []
    biases_aligned  = []
    filters_blocking = []
    all_reasons     = []

    # ── 1. Signals vote ──
    buy_votes = 0
    sell_votes = 0
    for flag, evaluator in SIGNAL_EVALUATORS.items():
        if not genome_flags.get(flag): continue
        try:
            vote, reason = evaluator(snapshot)
        except Exception as e:
            all_reasons.append(f"{flag} err: {e}")
            continue
        if vote == +1:
            buy_votes += 1
            signals_fired.append((flag, "BUY", reason))
            all_reasons.append(f"📈 {flag}: {reason}")
        elif vote == -1:
            sell_votes += 1
            signals_fired.append((flag, "SELL", reason))
            all_reasons.append(f"📉 {flag}: {reason}")

    if buy_votes == 0 and sell_votes == 0:
        return {"decision": "NO", "confidence": 0,
                "reasons": all_reasons + ["no active signal fired"],
                "signals_fired": [], "biases_aligned": [],
                "filters_blocking": []}

    # ── 2. Direction = majority signal vote ──
    if buy_votes > sell_votes:
        direction = "BUY"
        sig_strength = buy_votes / (buy_votes + sell_votes)
    elif sell_votes > buy_votes:
        direction = "SELL"
        sig_strength = sell_votes / (buy_votes + sell_votes)
    else:
        return {"decision": "NO", "confidence": 0,
                "reasons": all_reasons + ["signal votes tied"],
                "signals_fired": signals_fired,
                "biases_aligned": [],
                "filters_blocking": []}

    direction_vote = +1 if direction == "BUY" else -1

    # ── 3. Biases must align (majority) ──
    bias_agree = 0
    bias_total = 0
    for flag, evaluator in BIAS_EVALUATORS.items():
        if not genome_flags.get(flag): continue
        try:
            vote, reason = evaluator(snapshot)
        except Exception: continue
        if vote == 0: continue
        bias_total += 1
        if vote == direction_vote:
            bias_agree += 1
            biases_aligned.append((flag, reason))
            all_reasons.append(f"✓ bias {flag}: {reason}")
        else:
            all_reasons.append(f"✗ bias {flag} opposes: {reason}")

    if bias_total > 0 and bias_agree / bias_total < 0.5:
        return {"decision": "NO", "confidence": 0,
                "reasons": all_reasons + ["biases mostly oppose"],
                "signals_fired": signals_fired,
                "biases_aligned": biases_aligned,
                "filters_blocking": []}
    bias_strength = (bias_agree / bias_total) if bias_total > 0 else 0.6

    # ── 4. Filters: any veto kills the trade ──
    for flag, evaluator in FILTER_EVALUATORS.items():
        if not genome_flags.get(flag): continue
        try:
            blocks, reason = evaluator(snapshot)
        except Exception: continue
        if blocks:
            filters_blocking.append((flag, reason))
            all_reasons.append(f"🚫 filter {flag} vetoes: {reason}")
            return {"decision": "NO", "confidence": 0,
                    "reasons": all_reasons,
                    "signals_fired": signals_fired,
                    "biases_aligned": biases_aligned,
                    "filters_blocking": filters_blocking}

    # ── 5. Confidence (0-100) ──
    n_signals_on = sum(1 for f in SIGNAL_EVALUATORS if genome_flags.get(f))
    n_signals_fired = buy_votes + sell_votes
    fire_ratio = n_signals_fired / max(1, n_signals_on)

    confidence = round(
        sig_strength    * 40 +
        bias_strength   * 35 +
        fire_ratio      * 15 +
        10  # filter cleanliness (we'd have returned earlier on veto)
    )
    confidence = max(0, min(100, confidence))

    return {
        "decision":          direction,
        "confidence":        confidence,
        "reasons":           all_reasons,
        "signals_fired":     signals_fired,
        "biases_aligned":    biases_aligned,
        "filters_blocking":  filters_blocking,
        "vote_counts":       {"buy": buy_votes, "sell": sell_votes},
        "bias_agreement":    f"{bias_agree}/{bias_total}",
    }


def build_snapshot_from_trade_gate_snap(snap: dict) -> dict:
    """Convert trade_gate's snap shape (multi_tf.tfs.H1, chart.levels.bid)
    into the flat shape decide_entry expects (h1/m15/h4/bid/ask)."""
    mtf = (snap.get("multi_tf") or {}).get("tfs") or {}
    chl = (snap.get("chart") or {}).get("levels") or {}
    return {
        "h1":  mtf.get("H1", {}) or {},
        "m15": mtf.get("M15", {}) or {},
        "h4":  mtf.get("H4", {}) or {},
        "bid": chl.get("bid"),
        "ask": chl.get("ask"),
    }


if __name__ == "__main__":
    import json
    fake = {
        "h1":  {"current": 75500, "atr": 343, "rsi": 75, "bias": "UP",
                "swing_high": 76000, "swing_low": 75000, "range_size": 1000,
                "slope_atr": 0.8},
        "m15": {"rsi": 80, "bias": "UP", "slope_atr": 1.2,
                "swing_high": 75600, "swing_low": 75400, "range_size": 200},
        "h4":  {"bias": "UP", "rsi": 65, "swing_high": 77000, "swing_low": 74000,
                "range_size": 3000, "slope_atr": 0.5},
        "bid": 75500, "ask": 75510,
    }
    flags = {"use_sig_breakout": True, "use_sig_williams": True,
             "use_sig_inside_break": True,
             "use_bias_ema": True, "use_bias_market_struct": True,
             "use_bias_chandelier": True, "use_bias_donchian_mid": True,
             "use_bias_rsi": True, "use_filt_doji": True, "use_filt_bb": True}
    out = decide_entry(flags, fake)
    print(json.dumps(out, indent=2, default=str))
