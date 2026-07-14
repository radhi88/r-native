"""
strategy_mirror.py — Adopt Algory's WINNING patterns into transparent FRIDAY code.

What Algory's vault taught us (XAUUSDm H1, 79 strategies, 24+ months OOS):

  WINNING FORMULA:
    • Sessions:     London + NY only (08:00-20:00 UTC)
    • Friday close: 17:00-19:00 UTC
    • TP/SL ratio:  4:1 to 5:1 (TP ~8×ATR, SL ~2×ATR)
    • Risk mgmt:    Always news_filter + daily_dd + friday_close + symbol_lock
    • Win mech:     FRIDAY_DRIFTER (catches end-of-week directional moves)
    • Archetypes:   MEAN_REVERTER (avg +226%), BREAKOUT_HUNTER (+174%),
                    MULTI_SIGNAL (+255%), PATTERN_SPOTTER (+182%)

  TRUSTED GENES (high pass-rate in Algory OOS):
    use_sig_breakout, use_sig_mom_break, use_filt_rsi, use_bias_rsi,
    use_filt_receding, use_filt_sma, use_bias_sma, use_bias_chandelier

  AVOID THESE (consistent losers):
    use_bias_psar, use_filt_doji, use_filt_keltner, use_partial_tp,
    use_bias_trailing, use_sl_lock, use_sl_reduce, use_filt_adr_exhaust

This module exposes:
  • TRUSTED_GENES / BLACKLISTED_GENES        — derived from gene_fitness_v2
  • build_archetype_template(name)           — typical genome for each archetype
  • evaluate_setup(market_snapshot)          — does the current market match a winner?
  • get_active_recommendation()              — read latest algory_report.json + decide

This is READ-ONLY logic — it does NOT place trades.  Pure analysis.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT          = Path(r"C:\Users\Radhi\MT5\friday_v3")
ALGORY_REPORT = ROOT / "data" / "algory_report.json"


# ───────────────────────── Knowledge derived from Algory ─────────────────────────
TRUSTED_GENES = {
    # gene → reason (so we can show provenance in the UI)
    "use_sig_breakout":  "100% pass rate (8/0) — pure breakout signal never failed OOS",
    "use_sig_mom_break": "80% pass rate (4/1) on XAUUSDm — momentum breaks confirm trend",
    "use_filt_rsi":      "66% pass rate — RSI filter rejects noise",
    "use_bias_rsi":      "57% pass rate — RSI as directional bias",
    "use_filt_receding": "53% pass rate on XAU — only act when recent move receded",
    "use_filt_sma":      "41% pass rate — SMA above/below for trend confirm",
    "use_bias_sma":      "35% pass rate but 28 wins (largest absolute count)",
    "use_bias_chandelier":"40% pass rate — chandelier exit catches trends",
    "use_bias_htf":      "26% pass rate but appears in 4 of top-5 strategies (HTF context)",
    "use_eod_close":     "30% pass rate — end-of-day close avoids overnight risk",
}

BLACKLISTED_GENES = {
    "use_bias_psar":     "0/6 — PSAR oscillates on gold, kills strategies",
    "use_filt_doji":     "0/13 — doji filter too restrictive on H1",
    "use_filt_keltner":  "0/7 — Keltner adds no edge",
    "use_partial_tp":    "0/15 — partial TPs degrade R:R below break-even",
    "use_bias_trailing": "2/23 — trailing stops bail too early on gold's wicks",
    "use_sl_lock":       "1/17 — locked SLs miss reversals",
    "use_sl_reduce":     "1/16 — reducing SL post-entry harms math",
    "use_filt_adr_exhaust":"0/12 — average daily range exhaustion fires false signals",
}

# Common to ALL top-5 strategies
UNIVERSAL_RISK_FRAME = {
    "session_start_utc": 8,
    "session_end_utc":   20,
    "friday_close_utc":  18,
    "use_news_filter":   True,
    "use_daily_dd":      True,    # cap daily loss
    "use_friday_close":  True,    # flatten before weekend
    "use_slippage":      True,    # account for slippage in sizing
    "use_symbol_lock":   True,    # one position at a time per symbol
}

# Archetype DNA — from clustering top-5 in vault
ARCHETYPE_TEMPLATES = {
    "MEAN_REVERTER": {
        "description":   "Buys oversold dips on XAU H1 during London/NY hours",
        "biases":        ["use_bias_sma", "use_bias_daily_mid", "use_bias_htf"],
        "signals":       ["use_sig_stoch", "use_sig_macd"],
        "filters":       ["use_filt_receding", "use_filt_rsi"],
        "sl_atr_mult":   2.0,
        "tp_atr_mult":   8.5,
        "session":       (8, 20),
        "friday_close":  18,
        "avg_return":    226,
        "avg_dd":        13,
    },
    "BREAKOUT_HUNTER": {
        "description":   "Trades range expansions during London open + NY open",
        "biases":        ["use_bias_chandelier", "use_bias_htf"],
        "signals":       ["use_sig_breakout", "use_sig_mom_break"],
        "filters":       ["use_filt_receding"],
        "sl_atr_mult":   2.05,
        "tp_atr_mult":   7.2,
        "session":       (7, 20),
        "friday_close":  17,
        "avg_return":    174,
        "avg_dd":        12,
    },
    "MULTI_SIGNAL": {
        "description":   "Combines 3+ indicators — needs strong confluence",
        "biases":        ["use_bias_sma", "use_bias_daily_mid", "use_bias_htf"],
        "signals":       ["use_sig_macd", "use_sig_stoch", "use_sig_pin_bar"],
        "filters":       ["use_filt_receding", "use_filt_sma"],
        "sl_atr_mult":   1.95,
        "tp_atr_mult":   8.65,
        "session":       (9, 17),
        "friday_close":  19,
        "avg_return":    255,
        "avg_dd":        15,
    },
    "PATTERN_SPOTTER": {
        "description":   "Watches for candlestick patterns at key levels",
        "biases":        ["use_bias_sma", "use_bias_chandelier"],
        "signals":       ["use_sig_engulfing", "use_sig_pin_bar"],
        "filters":       ["use_filt_consec", "use_filt_sma"],
        "sl_atr_mult":   2.1,
        "tp_atr_mult":   6.5,
        "session":       (8, 20),
        "friday_close":  18,
        "avg_return":    182,
        "avg_dd":        13,
    },
}


def get_active_recommendation(symbol: str = "XAUUSDm",
                              tf: str    = "H1") -> dict:
    """Read latest watcher report + return Friday's recommended setup."""
    if not ALGORY_REPORT.exists():
        return {"ok": False, "reason": "algory_report.json missing — run watcher first"}
    try:
        report = json.loads(ALGORY_REPORT.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "reason": str(e)}

    rec = report.get("friday_recommendations", {}) or {}
    vs  = report.get("vault_summary", {}) or {}
    top_for_symbol = [s for s in vs.get("top_10", [])
                      if s.get("symbol") == symbol and s.get("timeframe") == tf]

    # Aggregate genome from top-5 (consensus)
    consensus_genes = {}
    if top_for_symbol:
        # not stored in vault_index but we know from analysis they share patterns
        pass

    return {
        "ok":           True,
        "ts":           datetime.now(timezone.utc).isoformat(),
        "symbol":       symbol,
        "timeframe":    tf,
        "trusted":      TRUSTED_GENES,
        "blacklisted":  BLACKLISTED_GENES,
        "universal_risk_frame": UNIVERSAL_RISK_FRAME,
        "archetypes":   ARCHETYPE_TEMPLATES,
        "live_xau_whitelist": rec.get("xau_h1_whitelist", []),
        "live_xau_blacklist": rec.get("xau_h1_blacklist", []),
        "top_strategies_in_vault": top_for_symbol[:5],
        "recommendation": (
            "Adopt BREAKOUT_HUNTER archetype on XAU H1 with breakout+mom_break signals, "
            "RSI/receding filters, chandelier+HTF bias, 2×ATR SL, 7-8×ATR TP, "
            "trade only 08:00-20:00 UTC, close before Friday 18:00."
        ),
    }


def evaluate_setup(snapshot: dict, archetype: str = "BREAKOUT_HUNTER") -> dict:
    """Given a live market snapshot, score how well it matches an archetype's preferred setup."""
    # Inherit bypass flags from trade_gate
    try:
        from friday_v3.algory.trade_gate import _BYPASS_SESSION, _BYPASS_FRIDAY, _BYPASS_WEEKEND
    except Exception:
        _BYPASS_SESSION = _BYPASS_FRIDAY = _BYPASS_WEEKEND = False

    tpl = ARCHETYPE_TEMPLATES.get(archetype)
    if not tpl: return {"ok": False, "reason": "unknown archetype"}

    now_utc = datetime.now(timezone.utc).hour
    in_session = True if _BYPASS_SESSION else (tpl["session"][0] <= now_utc < tpl["session"][1])
    is_friday  = datetime.now(timezone.utc).weekday() == 4
    after_fri_close = (not _BYPASS_FRIDAY) and is_friday and now_utc >= tpl["friday_close"]

    # Pull from snapshot
    mtf = snapshot.get("multi_tf", {}).get("tfs", {}) if snapshot else {}
    regime = snapshot.get("regime", {}) if snapshot else {}
    chart_levels = snapshot.get("chart", {}).get("levels", {}) if snapshot else {}

    h1 = mtf.get("H1", {})
    bias_h1   = h1.get("bias", "RANGE") if isinstance(h1, dict) else "RANGE"
    atr_h1    = h1.get("atr", 0) if isinstance(h1, dict) else 0
    spread_pt = chart_levels.get("spread_points", 0)
    bid = chart_levels.get("bid", 0) or 0
    # Symbol-aware: get point_size from MT5
    try:
        import MetaTrader5 as _mt5
        sym_name = snapshot.get("symbol", "XAUUSDm")
        sym_info = _mt5.symbol_info(sym_name)
        point_sz = sym_info.point if sym_info else 0.001
    except Exception:
        point_sz = 0.001
    spread_price = spread_pt * point_sz
    spread_atr = (spread_price / atr_h1) if atr_h1 > 0 else 99
    # ATR threshold: 0.1% of price (scales correctly for XAU/BTC/EUR)
    atr_threshold = max(0.0001, bid * 0.001) if bid > 0 else 5

    checks = {
        "in_session":         in_session,
        "not_friday_close":   not after_fri_close,
        "atr_sufficient":     atr_h1 >= atr_threshold,
        "spread_acceptable":  spread_atr < 0.2,
        "regime_ok":          regime.get("allow_trade", False) if regime else False,
        "trend_for_archetype":(
            (archetype == "BREAKOUT_HUNTER" and bias_h1 in ("UP","DOWN")) or
            (archetype == "MEAN_REVERTER"   and bias_h1 == "RANGE") or
            (archetype in ("MULTI_SIGNAL","PATTERN_SPOTTER"))
        ),
    }
    passed = sum(checks.values())
    return {
        "ok":          True,
        "archetype":   archetype,
        "checks":      checks,
        "passed":      passed,
        "total":       len(checks),
        "score":       round(passed / len(checks) * 100, 1),
        "verdict":     "OK" if passed >= 5 else "WAIT" if passed >= 3 else "NO_TRADE",
        "atr_h1":      atr_h1,
        "spread_pt":   spread_pt,
        "spread_atr_ratio": round(spread_atr, 3),
        "bias_h1":     bias_h1,
    }


if __name__ == "__main__":
    import sys
    rec = get_active_recommendation()
    print(json.dumps({k: rec[k] for k in ("symbol","timeframe","live_xau_whitelist",
                                          "live_xau_blacklist","recommendation")},
                     ensure_ascii=False, indent=2))
    print()
    # demo: evaluate with empty snapshot
    print("Setup evaluation (empty snapshot, BREAKOUT_HUNTER):")
    print(json.dumps(evaluate_setup({}, "BREAKOUT_HUNTER"), ensure_ascii=False, indent=2))
