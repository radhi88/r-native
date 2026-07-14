"""Global configuration for the AI Geometric Agentic Desk.

Single source of truth for safety flags, micro-equity survival parameters,
per-market technical profiles, and the magic number that tags every order
this desk sends. Edit values here — never hard-code them downstream.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ─── Safety (ZERO TOLERANCE) ─────────────────────────────────────────
LIVE_TRADING: bool = False          # default OFF; demo execution still gated below
DEMO_ONLY: bool = True              # refuse to send orders on a real account, always
AUTONOMOUS_MODE: bool = True        # HR loop runs R&D + exam without asking
EXEC_MAGIC: int = 20260626          # tags every order from this desk

# Exam gates the spec mandates before any execution
EXAM_PASS_SCORE: float = 95.0       # no paper/live until exam >= this
EXAM_PERFECT: float = 100.0         # HR loops until this AND PF target
PF_TARGET: float = 2.5              # profit-factor the HR loop chases

# Risk ceilings (fractions of equity)
MAX_RISK_PER_TRADE: float = 0.05    # 5% hard cap per trade
MAX_DAILY_LOSS: float = 0.10        # 10% daily drawdown halt
KELLY_CAP: float = 0.15             # f* hard ceiling for a $10 account
SURVIVAL_REJECT_RISK: float = 0.15  # if min-lot risk > 15% of equity → DO NOT TRADE

# Confluence gate
MIN_CONFLUENCES: int = 2            # loosened to 2 (user) — more entries, weaker setups
ML_CONFIDENCE_GATE: float = 0.55    # lowered (user) to let it fire on demo;
#                                     honest ML ~coin-flip, 0.70 almost never clears

# Deployment mode. True = honest "Exam First" (no live trade until score>=95 &
# PF>=2.5). False = forward-test: execute the confluence rule live on DEMO and
# "let reality judge" (army_warroom precedent). Safety rails apply either way.
REQUIRE_EXAM_PASS: bool = False

# Micro-equity assumption (used when account_info is unavailable in sim)
ASSUMED_START_EQUITY: float = 10.0

# Cap on simultaneously open desk positions (sanity bound for all-symbols mode)
MAX_CONCURRENT_POSITIONS: int = 10

# Spread-trap filters (exclude illiquid wide-spread instruments)
MAX_REL_SPREAD: float = 0.004      # universe prune: drop symbols with spread/price > 0.4%
MAX_SPREAD_ATR: float = 0.25       # per-cycle: skip if spread > 25% of one ATR (~0.12R)

# Real-time reversal (Stop-and-Reverse on trend change — close early, don't wait
# for the far SL). Conviction-gated to avoid noise churn (overrides the original
# "zero reverse" rule per the user's explicit instruction).
ENABLE_REVERSAL: bool = True
REVERSAL_MIN_CONF: float = 0.60    # ML confidence required to flip a position
REVERSAL_MIN_HOLD_SEC: int = 120   # don't flip a position younger than this (anti-churn)

# Per-currency lessons — learn which symbols bleed and stop trading them.
# This encodes the one proven edge in the research record: prune bleeders.
LESSON_LOOKBACK_DAYS: int = 5
LESSON_MIN_TRADES: int = 6         # need this many closed trades before judging
LESSON_BLOCK_NET: float = -1.0     # block a symbol if realised net below this …
LESSON_BLOCK_WINRATE: float = 0.45 # … and its win-rate is under this


@dataclass(frozen=True)
class MarketProfile:
    """Per-market technical-analysis profile.

    Attributes:
        atr_sl_mult: Multiplier k for the volatility-adjusted stop (SL = ATR * k).
        sessions: Allowed trading windows in UTC hours, inclusive ranges.
        lot_scale: Relative aggression multiplier for sizing.
        sq9_key_degree: The dominant Square-of-9 rotation for this market.
        tags: Strategy emphasis tags for the analysis agent.
    """

    atr_sl_mult: float
    sessions: tuple[tuple[int, int], ...]
    lot_scale: float
    sq9_key_degree: float
    tags: tuple[str, ...]


# London = 07-16 UTC, NY = 12-21 UTC, NY-equity = 13:30-20:00 UTC (approx)
PROFILES: dict[str, MarketProfile] = {
    "gold": MarketProfile(2.0, ((7, 16), (12, 21)), 2.0, 360.0,
                          ("smc", "ob", "fvg", "sq9")),
    "forex": MarketProfile(1.6, ((0, 23),), 1.0, 90.0,
                           ("smc", "ob", "fvg", "sq9")),
    "indices": MarketProfile(1.8, ((13, 20),), 1.2, 180.0,
                             ("bos", "choch", "vwap", "gann1x1")),
    "crypto": MarketProfile(1.8, ((0, 23),), 1.0, 180.0,
                            ("vp", "footprint", "fractal")),
    "stocks": MarketProfile(1.5, ((14, 20),), 1.0, 90.0,
                            ("ob", "daily_fvg")),
}

# Symbol → market-class routing (suffix-tolerant; matched by prefix)
SYMBOL_CLASS: dict[str, str] = {
    "XAU": "gold", "XAG": "gold",
    "EUR": "forex", "GBP": "forex", "USD": "forex", "AUD": "forex",
    "NZD": "forex", "CHF": "forex", "CAD": "forex", "JPY": "forex",
    "US30": "indices", "US500": "indices", "USTEC": "indices",
    "DE40": "indices", "JP225": "indices", "NAS": "indices",
    "BTC": "crypto", "ETH": "crypto", "SOL": "crypto", "XRP": "crypto",
}


def classify(symbol: str) -> str:
    """Map an MT5 symbol to a market class, defaulting to forex.

    Args:
        symbol: Raw broker symbol, e.g. ``"XAUUSDm"`` or ``"BTCUSDm"``.

    Returns:
        The market-class key into :data:`PROFILES`.
    """
    up = symbol.upper()
    for prefix, klass in SYMBOL_CLASS.items():
        if up.startswith(prefix):
            return klass
    if "US30" in up or "US500" in up or "USTEC" in up or "225" in up:
        return "indices"
    return "forex"


def profile_for(symbol: str) -> MarketProfile:
    """Return the :class:`MarketProfile` governing ``symbol``."""
    return PROFILES[classify(symbol)]


def load_market_overrides(path: str | None = None) -> dict:
    """Load ``config/markets.json`` and return its parsed mapping.

    The JSON augments the in-code :data:`PROFILES` (symbol lists, per-market
    reward multiples). Missing/invalid files yield an empty mapping so the
    desk always falls back to safe in-code defaults.

    Args:
        path: Optional explicit path; defaults to ``config/markets.json``.

    Returns:
        Parsed dict, or ``{}`` on any error.
    """
    import json
    import os
    p = path or os.path.join(os.path.dirname(__file__), "config", "markets.json")
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def symbols_for(market: str) -> list[str]:
    """Return configured symbols for a market class from the JSON overrides."""
    data = load_market_overrides().get(market, {})
    return list(data.get("symbols", []))
