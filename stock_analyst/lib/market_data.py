"""yfinance data layer with Streamlit caching.

Public API (stable — pages code against these):
  INDEX_TICKERS, SECTOR_ETFS, PERIOD_MAP
  get_quote(ticker) -> dict | None
  get_quotes_bulk(tickers) -> dict[ticker, dict]
  get_history(ticker, period_key) -> DataFrame (OHLCV, DatetimeIndex) | None
  get_history_bulk(tickers, period_key) -> dict[ticker, DataFrame]
  get_prev_close(ticker) -> float | None            (1D baseline = yesterday's close)
  get_stock_fundamentals(ticker) -> dict
  get_etf_details(ticker) -> dict
  is_etf(ticker) -> bool
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import yfinance as yf

# Real indices, not ETFs (chart accuracy rule).
INDEX_TICKERS: dict[str, str] = {
    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq 100",
    "^DJI": "Dow Jones",
    "^RUT": "Russell 2000",
    "^VIX": "VIX",
    "^TNX": "10Y Yield",
    "GC=F": "Gold",
    "CL=F": "Crude WTI",
    "BTC-USD": "Bitcoin",
    "DX-Y.NYB": "US Dollar (DXY)",
}

# The 11 SPDR sector ETFs.
SECTOR_ETFS: dict[str, str] = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLB": "Materials",
    "XLC": "Communication Services",
}

# UI period -> (yfinance period, interval). 1D uses 5m bars.
PERIOD_MAP: dict[str, tuple[str, str]] = {
    "1D": ("1d", "5m"),
    "5D": ("5d", "15m"),
    "1M": ("1mo", "1h"),
    "3M": ("3mo", "1d"),
    "6M": ("6mo", "1d"),
    "YTD": ("ytd", "1d"),
    "1Y": ("1y", "1d"),
    "3Y": ("3y", "1wk"),
    "5Y": ("5y", "1wk"),
    "10Y": ("10y", "1wk"),
    "20Y": ("20y", "1mo"),
    "30Y": ("30y", "1mo"),
    "Max": ("max", "1mo"),
}


def _clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):  # single-ticker download quirk
        df = df.droplevel(axis=1, level=1)
    df = df.rename(columns=str.title)
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    df = df[keep].dropna(subset=["Close"])
    return df if not df.empty else None


@st.cache_data(ttl=60, show_spinner=False)
def get_quote(ticker: str) -> dict | None:
    """Lightweight quote: price, previous close, change, change_pct, name."""
    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        price = float(fi["last_price"])
        prev = float(fi["previous_close"])
        name = INDEX_TICKERS.get(ticker) or SECTOR_ETFS.get(ticker)
        if not name:
            info = t.info or {}
            name = info.get("shortName") or info.get("longName") or ticker
        chg = price - prev
        return {
            "ticker": ticker,
            "name": name,
            "price": price,
            "prev_close": prev,
            "change": chg,
            "change_pct": (chg / prev * 100.0) if prev else 0.0,
        }
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def get_quotes_bulk(tickers: tuple[str, ...] | list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for tk in tickers:
        q = get_quote(tk)
        if q:
            out[tk] = q
    return out


@st.cache_data(ttl=300, show_spinner=False)
def get_history(ticker: str, period_key: str) -> pd.DataFrame | None:
    """OHLCV history for a UI period key. Returns None on any failure."""
    period, interval = PERIOD_MAP.get(period_key, ("1y", "1d"))
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
        return _clean_ohlcv(df)
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def get_history_bulk(
    tickers: tuple[str, ...] | list[str], period_key: str
) -> dict[str, pd.DataFrame]:
    """One yf.download for many tickers -> {ticker: OHLCV df}. Missing tickers omitted."""
    period, interval = PERIOD_MAP.get(period_key, ("1y", "1d"))
    out: dict[str, pd.DataFrame] = {}
    try:
        raw = yf.download(
            list(tickers), period=period, interval=interval,
            group_by="ticker", auto_adjust=True, progress=False, threads=True,
        )
    except Exception:
        return out
    if raw is None or raw.empty:
        return out
    for tk in tickers:
        try:
            df = raw[tk] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = _clean_ohlcv(df.copy())
            if df is not None:
                out[tk] = df
        except Exception:
            continue
    return out


@st.cache_data(ttl=300, show_spinner=False)
def get_prev_close(ticker: str) -> float | None:
    """Yesterday's close — the correct 1D intraday baseline (overnight-gap rule)."""
    try:
        prev = yf.Ticker(ticker).fast_info["previous_close"]
        return float(prev) if prev else None
    except Exception:
        pass
    try:
        d = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=True)
        return float(d["Close"].iloc[-2]) if len(d) >= 2 else None
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def get_stock_fundamentals(ticker: str) -> dict:
    """Curated .info subset for the analyzer pages. Missing fields -> None."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    fields = [
        "shortName", "longName", "sector", "industry", "longBusinessSummary",
        "marketCap", "trailingPE", "forwardPE", "priceToBook", "pegRatio",
        "priceToSalesTrailing12Months", "enterpriseToEbitda",
        "profitMargins", "operatingMargins", "grossMargins",
        "returnOnEquity", "returnOnAssets", "revenueGrowth", "earningsGrowth",
        "debtToEquity", "currentRatio", "quickRatio", "totalCash", "totalDebt",
        "freeCashflow", "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
        "fiftyDayAverage", "twoHundredDayAverage", "averageVolume",
        "dividendYield", "payoutRatio", "trailingEps", "forwardEps",
        "recommendationMean", "numberOfAnalystOpinions", "targetMeanPrice",
        "currency", "quoteType", "website",
    ]
    return {k: info.get(k) for k in fields}


@st.cache_data(ttl=3600, show_spinner=False)
def is_etf(ticker: str) -> bool:
    try:
        qt = (yf.Ticker(ticker).info or {}).get("quoteType", "")
        return str(qt).upper() == "ETF"
    except Exception:
        return False


@st.cache_data(ttl=3600, show_spinner=False)
def get_etf_details(ticker: str) -> dict:
    """ETF metadata: expense ratio, yield, returns, sector weights, top holdings.

    Returns dict with keys: name, expense_ratio, yield, ytd_return,
    three_year_avg_return, five_year_avg_return, beta3y, total_assets,
    sector_weights {sector: weight 0-1}, top_holdings [(symbol, name, weight 0-1)].
    All values may be None/empty when unavailable — callers must handle that.
    """
    out: dict = {
        "name": ticker, "expense_ratio": None, "yield": None, "ytd_return": None,
        "three_year_avg_return": None, "five_year_avg_return": None, "beta3y": None,
        "total_assets": None, "sector_weights": {}, "top_holdings": [],
    }
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        out["name"] = info.get("shortName") or info.get("longName") or ticker
        # Normalize expense ratio to FRACTION form at the boundary:
        # Yahoo's netExpenseRatio is percent-form (SPY -> 0.0945 meaning 0.0945%),
        # annualReportExpenseRatio is fraction-form (0.000945). Field decides.
        ner = info.get("netExpenseRatio")
        arer = info.get("annualReportExpenseRatio")
        if ner is not None:
            out["expense_ratio"] = float(ner) / 100.0
        elif arer is not None:
            out["expense_ratio"] = float(arer)
        out["yield"] = info.get("yield") or info.get("dividendYield")
        out["ytd_return"] = info.get("ytdReturn")
        out["three_year_avg_return"] = info.get("threeYearAverageReturn")
        out["five_year_avg_return"] = info.get("fiveYearAverageReturn")
        out["beta3y"] = info.get("beta3Year") or info.get("beta")
        out["total_assets"] = info.get("totalAssets")
        try:
            fd = t.funds_data
            sw = fd.sector_weightings or {}
            out["sector_weights"] = {k: float(v) for k, v in sw.items() if v}
            th = fd.top_holdings
            if th is not None and not th.empty:
                th = th.reset_index()
                cols = {c.lower(): c for c in th.columns}
                sym_c = cols.get("symbol") or th.columns[0]
                name_c = cols.get("name") or cols.get("holding name") or th.columns[1]
                w_c = cols.get("holding percent") or cols.get("holdingpercent") or th.columns[-1]
                out["top_holdings"] = [
                    (str(r[sym_c]), str(r[name_c]), float(r[w_c]))
                    for _, r in th.iterrows()
                ]
        except Exception:
            pass
    except Exception:
        pass
    return out
