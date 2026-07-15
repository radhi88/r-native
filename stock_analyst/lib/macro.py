"""FRED macro-indicator data layer (fredapi) with Streamlit caching.

Public API (stable — pages code against these):
  INDICATORS                                  ordered dict of 8 dashboard indicators
  get_series(series_id, start) -> pd.Series | None
  latest_with_delta(series_id, yoy=False) -> (latest, delta_vs_prior, date_str) | None
  cpi_yoy_series() -> pd.Series | None        YoY % change of CPIAUCSL

The fredapi.Fred client is constructed lazily inside functions using
config.fred_key(); a missing key or any API error degrades to None so
callers can show a friendly notice instead of crashing.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

try:  # pages insert the project root on sys.path, so `lib` is importable
    from lib import config
except ImportError:  # fallback when imported from inside lib/ directly
    import config  # type: ignore

# Ordered: display label -> {series_id, unit, yoy (compute YoY % from levels)}.
INDICATORS: dict[str, dict] = {
    "GDP": {"series_id": "GDP", "unit": "$B", "yoy": False},
    "Unemployment": {"series_id": "UNRATE", "unit": "%", "yoy": False},
    "CPI YoY": {"series_id": "CPIAUCSL", "unit": "%", "yoy": True},
    "Core CPI YoY": {"series_id": "CPILFESL", "unit": "%", "yoy": True},
    "Fed Funds": {"series_id": "FEDFUNDS", "unit": "%", "yoy": False},
    "10Y-2Y Spread": {"series_id": "T10Y2Y", "unit": "pp", "yoy": False},
    "Retail Sales": {"series_id": "RSAFS", "unit": "$M", "yoy": False},
    "Industrial Production": {"series_id": "INDPRO", "unit": "index", "yoy": False},
}


def _fred_client():
    """Lazily build a fredapi.Fred client; None when the key is missing."""
    key = config.fred_key()
    if not key:
        return None
    try:
        from fredapi import Fred

        return Fred(api_key=key)
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_series(series_id: str, start: str = "2000-01-01") -> pd.Series | None:
    """Full FRED series from `start`. None when the key is missing or on error."""
    fred = _fred_client()
    if fred is None:
        return None
    try:
        s = fred.get_series(series_id, observation_start=start)
        if s is None:
            return None
        s = s.dropna()
        return s if not s.empty else None
    except Exception:
        return None


def _yoy(s: pd.Series | None) -> pd.Series | None:
    """Year-over-year % change of a monthly level series (needs 13+ points)."""
    if s is None or len(s) < 13:
        return None
    out = (s / s.shift(12) - 1.0) * 100.0
    out = out.dropna()
    return out if not out.empty else None


@st.cache_data(ttl=3600, show_spinner=False)
def latest_with_delta(
    series_id: str, yoy: bool = False
) -> tuple[float, float, str] | None:
    """Latest value, change vs the prior observation, and observation date.

    With yoy=True the series is first converted to YoY % change (so the
    returned latest/delta are in percentage points). None on any failure.
    """
    # Pull an extra year of history so YoY has a full 12-month base.
    s = get_series(series_id, start="1999-01-01" if yoy else "2000-01-01")
    if yoy:
        s = _yoy(s)
    if s is None or s.empty:
        return None
    try:
        latest = float(s.iloc[-1])
        prior = float(s.iloc[-2]) if len(s) >= 2 else latest
        dt = s.index[-1]
        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)
        return latest, latest - prior, date_str
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def cpi_yoy_series() -> pd.Series | None:
    """YoY % change series for headline CPI (CPIAUCSL). None on failure."""
    return _yoy(get_series("CPIAUCSL", start="1999-01-01"))
