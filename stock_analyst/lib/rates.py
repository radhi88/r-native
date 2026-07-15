"""US Treasury yield-curve data layer (FRED via fredapi) with caching.

Public API (stable — pages code against these):
  YIELD_SERIES                       maturity label -> FRED daily yield series id
  yield_curve() -> pd.Series | None  latest yield per maturity (index = labels)

The fredapi.Fred client is constructed lazily inside functions using
config.fred_key(); a missing key or any API error degrades to None.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

try:  # pages insert the project root on sys.path, so `lib` is importable
    from lib import config
except ImportError:  # fallback when imported from inside lib/ directly
    import config  # type: ignore

# Ordered short -> long maturity; FRED constant-maturity daily series.
YIELD_SERIES: dict[str, str] = {
    "1M": "DGS1MO",
    "3M": "DGS3MO",
    "6M": "DGS6MO",
    "1Y": "DGS1",
    "2Y": "DGS2",
    "3Y": "DGS3",
    "5Y": "DGS5",
    "7Y": "DGS7",
    "10Y": "DGS10",
    "20Y": "DGS20",
    "30Y": "DGS30",
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
def yield_curve() -> pd.Series | None:
    """Latest available yield for each maturity in YIELD_SERIES.

    Returns a pd.Series indexed by maturity label ("1M" ... "30Y", in curve
    order); maturities that fail to load are omitted. None when the FRED key
    is missing or nothing loads.
    """
    fred = _fred_client()
    if fred is None:
        return None
    # Daily series have gaps (weekends/holidays): pull a recent window and
    # take the last valid print per maturity.
    start = (pd.Timestamp.today() - pd.Timedelta(days=21)).strftime("%Y-%m-%d")
    values: dict[str, float] = {}
    for label, series_id in YIELD_SERIES.items():
        try:
            s = fred.get_series(series_id, observation_start=start)
            if s is None:
                continue
            s = s.dropna()
            if not s.empty:
                values[label] = float(s.iloc[-1])
        except Exception:
            continue
    if not values:
        return None
    return pd.Series(values, name="yield")
