"""Pure computation layer: descriptive technical / fundamental scoring.

COMPLIANCE: nothing in this module is investment advice. Scores are neutral
composite descriptions of observable data (trend, momentum, profitability...)
and every driver string is a factual statement. No buy/hold/sell language.

Public API:
  _rsi(closes, n=14) -> float | None            (Wilder RSI, latest value)
  technical_score(df) -> (int 0-100, list[str])
  fundamental_score(info) -> (int 0-100, list[str])
  at_a_glance(df, info) -> list[(label, value)]  (always 7 tuples)

All inputs may be None / empty / missing fields — functions degrade to
neutral values ("Data unavailable", score 50) instead of raising.
"""
from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


def _rsi(closes, n: int = 14) -> float | None:
    """Wilder RSI of the last bar. Accepts a Series/list; None if too short."""
    try:
        s = pd.Series(list(closes), dtype="float64").dropna()
    except Exception:
        return None
    if len(s) < n + 1:
        return None
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Wilder smoothing == EMA with alpha = 1/n (adjust=False), seeded over n bars
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().iloc[-1]
    if pd.isna(avg_gain) or pd.isna(avg_loss):
        return None
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def _rsi_bucket(rsi: float) -> str:
    """Neutral one-word momentum descriptor for an RSI value."""
    if rsi < 30:
        return "weak momentum"
    if rsi < 45:
        return "soft momentum"
    if rsi < 55:
        return "neutral momentum"
    if rsi < 70:
        return "firm momentum"
    return "stretched momentum"


# ---------------------------------------------------------------------------
# Small helpers (None-safe)
# ---------------------------------------------------------------------------


def _num(v) -> float | None:
    """Coerce to float, treating None/NaN/garbage as None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _closes(df) -> pd.Series | None:
    if df is None or getattr(df, "empty", True) or "Close" not in df:
        return None
    c = df["Close"].astype("float64").dropna()
    return c if not c.empty else None


def _de_ratio(raw) -> float | None:
    """yfinance debtToEquity is usually a percent (e.g. 145 = 1.45x)."""
    v = _num(raw)
    if v is None or v < 0:
        return None
    return v / 100.0 if v > 5 else v  # small values are already a ratio


def _range_position(closes: pd.Series, info: dict) -> float | None:
    """Position of last close inside the 52-week range, 0..1."""
    last = float(closes.iloc[-1])
    hi = _num(info.get("fiftyTwoWeekHigh")) if info else None
    lo = _num(info.get("fiftyTwoWeekLow")) if info else None
    if hi is None or lo is None:
        window = closes.iloc[-252:]
        hi, lo = float(window.max()), float(window.min())
    if hi <= lo:
        return None
    return min(1.0, max(0.0, (last - lo) / (hi - lo)))


def _range_words(pos: float) -> str:
    if pos >= 2 / 3:
        return "Upper third of range"
    if pos >= 1 / 3:
        return "Middle of range"
    return "Lower third of range"


# ---------------------------------------------------------------------------
# Technical score
# ---------------------------------------------------------------------------


def technical_score(df: pd.DataFrame | None) -> tuple[int, list[str]]:
    """Composite 0-100 description of price trend/momentum, with factual drivers.

    Components (skipped and re-weighted when data is insufficient):
      close vs 50DMA (15), close vs 200DMA (20), 50DMA vs 200DMA (15),
      RSI bucket (20), 52-week range position (15), 3-month momentum sign (15).
    """
    closes = _closes(df)
    if closes is None:
        return 50, ["Insufficient price history for technical scoring"]

    earned = 0.0
    possible = 0.0
    drivers: list[str] = []
    last = float(closes.iloc[-1])

    dma50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None
    dma200 = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else None

    if dma50 is not None:
        possible += 15
        if last >= dma50:
            earned += 15
            drivers.append("Price above 50-day average")
        else:
            drivers.append("Price below 50-day average")

    if dma200 is not None:
        possible += 20
        if last >= dma200:
            earned += 20
            drivers.append("Price above 200-day average")
        else:
            drivers.append("Price below 200-day average")

    if dma50 is not None and dma200 is not None:
        possible += 15
        if dma50 >= dma200:
            earned += 15
            drivers.append("50-day average above 200-day average")
        else:
            drivers.append("50-day average below 200-day average")

    rsi = _rsi(closes)
    if rsi is not None:
        possible += 20
        if rsi < 30:
            earned += 4
        elif rsi < 45:
            earned += 9
        elif rsi < 55:
            earned += 12
        elif rsi < 70:
            earned += 20
        else:
            earned += 14
        drivers.append(f"RSI {rsi:.0f} — {_rsi_bucket(rsi)}")

    pos = _range_position(closes, {})
    if pos is not None:
        possible += 15
        earned += 15 * pos
        drivers.append(f"{_range_words(pos)} — {pos * 100:.0f}% of 52-week range")

    if len(closes) >= 64:  # ~3 months of trading days
        possible += 15
        mom = last / float(closes.iloc[-64]) - 1.0
        if mom >= 0:
            earned += 15
        drivers.append(f"3-month price change {mom * 100:+.1f}%")

    if possible == 0:
        return 50, ["Insufficient price history for technical scoring"]
    return int(round(100.0 * earned / possible)), drivers


# ---------------------------------------------------------------------------
# Fundamental score
# ---------------------------------------------------------------------------


def fundamental_score(info: dict | None) -> tuple[int, list[str]]:
    """Composite 0-100 description of reported fundamentals, with drivers.

    Components (skipped and re-weighted when a field is None):
      profitMargins (20), returnOnEquity (20), revenueGrowth (15),
      debtToEquity (15), freeCashflow sign (10), trailingPE tier (20).
    """
    info = info or {}
    earned = 0.0
    possible = 0.0
    drivers: list[str] = []

    pm = _num(info.get("profitMargins"))
    if pm is not None:
        possible += 20
        if pm >= 0.20:
            earned += 20
            tier = "wide"
        elif pm >= 0.10:
            earned += 14
            tier = "solid"
        elif pm >= 0:
            earned += 8
            tier = "thin"
        else:
            tier = "negative"
        drivers.append(f"Profit margin {pm * 100:.1f}% — {tier}")

    roe = _num(info.get("returnOnEquity"))
    if roe is not None:
        possible += 20
        if roe >= 0.25:
            earned += 20
            tier = "high"
        elif roe >= 0.15:
            earned += 15
            tier = "solid"
        elif roe >= 0.05:
            earned += 8
            tier = "modest"
        else:
            earned += 2 if roe >= 0 else 0
            tier = "low" if roe >= 0 else "negative"
        drivers.append(f"Return on equity {roe * 100:.1f}% — {tier}")

    rg = _num(info.get("revenueGrowth"))
    if rg is not None:
        possible += 15
        if rg >= 0.15:
            earned += 15
            tier = "fast"
        elif rg >= 0.05:
            earned += 11
            tier = "steady"
        elif rg >= 0:
            earned += 6
            tier = "slow"
        else:
            tier = "declining"
        drivers.append(f"Revenue growth {rg * 100:+.1f}% year over year — {tier}")

    de = _de_ratio(info.get("debtToEquity"))
    if de is not None:
        possible += 15
        if de < 0.5:
            earned += 15
            tier = "low leverage"
        elif de < 1.0:
            earned += 11
            tier = "moderate leverage"
        elif de < 2.0:
            earned += 5
            tier = "elevated leverage"
        else:
            tier = "high leverage"
        drivers.append(f"Debt-to-equity {de:.2f}x — {tier}")

    fcf = _num(info.get("freeCashflow"))
    if fcf is not None:
        possible += 10
        if fcf > 0:
            earned += 10
            drivers.append("Positive free cash flow")
        else:
            drivers.append("Negative free cash flow")

    pe = _num(info.get("trailingPE"))
    if pe is not None and pe > 0:
        possible += 20
        if pe < 15:
            earned += 20
            tier = "low multiple"
        elif pe < 30:
            earned += 15
            tier = "moderate multiple"
        elif pe < 45:
            earned += 8
            tier = "elevated multiple"
        else:
            earned += 3
            tier = "high multiple"
        drivers.append(f"Trailing P/E {pe:.1f} — {tier}")

    if possible == 0:
        return 50, ["Insufficient fundamental data for scoring"]
    return int(round(100.0 * earned / possible)), drivers


# ---------------------------------------------------------------------------
# At-a-glance table
# ---------------------------------------------------------------------------

_NA = "Data unavailable"


def at_a_glance(df: pd.DataFrame | None, info: dict | None) -> list[tuple[str, str]]:
    """Exactly 7 (label, value) rows of neutral descriptive facts."""
    info = info or {}
    closes = _closes(df)
    rows: list[tuple[str, str]] = []

    # 1. Trend — last close vs 200-day average
    trend = _NA
    if closes is not None:
        last = float(closes.iloc[-1])
        dma200 = (
            float(closes.rolling(200).mean().iloc[-1])
            if len(closes) >= 200
            else _num(info.get("twoHundredDayAverage"))
        )
        if dma200:
            trend = "Above 200-day average" if last >= dma200 else "Below 200-day average"
    rows.append(("Trend", trend))

    # 2. Momentum — RSI bucket
    rsi = _rsi(closes) if closes is not None else None
    rows.append(
        ("Momentum", f"RSI {rsi:.0f} — {_rsi_bucket(rsi)}" if rsi is not None else _NA)
    )

    # 3. 52-week range position
    rng = _NA
    if closes is not None:
        pos = _range_position(closes, info)
        if pos is not None:
            rng = f"{_range_words(pos)} ({pos * 100:.0f}%)"
    rows.append(("52-week range", rng))

    # 4. Profitability — ROE tier
    roe = _num(info.get("returnOnEquity"))
    if roe is None:
        prof = _NA
    elif roe >= 0.25:
        prof = f"High ROE ({roe * 100:.0f}%)"
    elif roe >= 0.15:
        prof = f"Solid ROE ({roe * 100:.0f}%)"
    elif roe >= 0:
        prof = f"Modest ROE ({roe * 100:.0f}%)"
    else:
        prof = f"Negative ROE ({roe * 100:.0f}%)"
    rows.append(("Profitability", prof))

    # 5. Leverage — debt/equity tier
    de = _de_ratio(info.get("debtToEquity"))
    if de is None:
        lev = _NA
    elif de < 0.5:
        lev = f"Low debt-to-equity ({de:.2f}x)"
    elif de < 1.0:
        lev = f"Moderate debt-to-equity ({de:.2f}x)"
    elif de < 2.0:
        lev = f"Elevated debt-to-equity ({de:.2f}x)"
    else:
        lev = f"High debt-to-equity ({de:.2f}x)"
    rows.append(("Leverage", lev))

    # 6. Volatility — beta vs market
    beta = _num(info.get("beta"))
    if beta is None:
        vol = _NA
    elif beta > 1.15:
        vol = f"Higher than market (beta {beta:.2f})"
    elif beta >= 0.85:
        vol = f"Similar to market (beta {beta:.2f})"
    else:
        vol = f"Lower than market (beta {beta:.2f})"
    rows.append(("Volatility", vol))

    # 7. Valuation — trailing P/E tier
    pe = _num(info.get("trailingPE"))
    if pe is None or pe <= 0:
        val = "No trailing P/E" if pe is not None else _NA
    elif pe < 15:
        val = f"Low multiple (P/E {pe:.1f})"
    elif pe < 30:
        val = f"Moderate multiple (P/E {pe:.1f})"
    else:
        val = f"Elevated multiple (P/E {pe:.1f})"
    rows.append(("Valuation", val))

    return rows
