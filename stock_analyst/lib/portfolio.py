"""Portfolio persistence + enrichment layer.

Public API (stable — pages code against these):
  PORTFOLIO_PATH                       # <project root>/data/portfolio.json
  load_portfolio() -> list[dict]       # [{ticker, shares, cost_basis}], [] if missing/corrupt
  save_portfolio(holdings) -> None     # atomic write (tmp + replace)
  enrich(holdings) -> pd.DataFrame     # columns: ticker, shares, cost_basis, price,
                                       #          value, cost, gain, gain_pct, weight

Descriptive data only — no signals or recommendations are computed here.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import tempfile

import pandas as pd

from lib import market_data

# lib/portfolio.py -> parents: [0]=lib, [1]=stock_analyst root
PORTFOLIO_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "portfolio.json"

ENRICH_COLUMNS = [
    "ticker", "shares", "cost_basis", "price",
    "value", "cost", "gain", "gain_pct", "weight",
]


def _normalize_holding(raw: object) -> dict | None:
    """Validate one holding record; return a clean dict or None if unusable.

    Rules: ticker upper-stripped non-empty string, shares/cost_basis finite
    floats >= 0.
    """
    if not isinstance(raw, dict):
        return None
    ticker = str(raw.get("ticker", "")).strip().upper()
    if not ticker:
        return None
    try:
        shares = float(raw.get("shares", 0.0))
        cost_basis = float(raw.get("cost_basis", 0.0))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(shares) and math.isfinite(cost_basis)):
        return None
    if shares < 0 or cost_basis < 0:
        return None
    return {"ticker": ticker, "shares": shares, "cost_basis": cost_basis}


def load_portfolio() -> list[dict]:
    """Read holdings from PORTFOLIO_PATH.

    Returns [] when the file is missing, unreadable, corrupt JSON, or not a
    list. Invalid rows inside an otherwise valid file are dropped silently.
    """
    try:
        with open(PORTFOLIO_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for raw in data:
        h = _normalize_holding(raw)
        if h is not None:
            out.append(h)
    return out


def save_portfolio(holdings: list[dict]) -> None:
    """Persist holdings atomically (write tmp file, then os.replace).

    Input rows are validated/normalized; invalid rows are dropped so a bad
    entry can never corrupt the store.
    """
    clean = [h for h in (_normalize_holding(r) for r in (holdings or [])) if h is not None]
    PORTFOLIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".portfolio_", suffix=".tmp", dir=str(PORTFOLIO_PATH.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(clean, fh, indent=2)
        os.replace(tmp_path, PORTFOLIO_PATH)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def enrich(holdings: list[dict]) -> pd.DataFrame:
    """Attach live quotes and derived metrics to holdings.

    Per row (via market_data.get_quote):
      price    last price, NaN when the quote is unavailable
      value    shares * price (0.0 when price is unavailable)
      cost     shares * cost_basis
      gain     value - cost (NaN when price is unavailable)
      gain_pct gain / cost * 100 (NaN when cost is 0 or price unavailable)
      weight   value / total portfolio value (0.0 when total is 0)

    Always returns a DataFrame with ENRICH_COLUMNS, empty if no valid rows.
    """
    rows: list[dict] = []
    for raw in holdings or []:
        h = _normalize_holding(raw)
        if h is None:
            continue
        quote = market_data.get_quote(h["ticker"])
        price = float("nan")
        if quote and quote.get("price") is not None:
            try:
                price = float(quote["price"])
            except (TypeError, ValueError):
                price = float("nan")
        has_price = math.isfinite(price)
        value = h["shares"] * price if has_price else 0.0
        cost = h["shares"] * h["cost_basis"]
        gain = value - cost if has_price else float("nan")
        gain_pct = (gain / cost * 100.0) if (has_price and cost > 0) else float("nan")
        rows.append({
            "ticker": h["ticker"],
            "shares": h["shares"],
            "cost_basis": h["cost_basis"],
            "price": price,
            "value": value,
            "cost": cost,
            "gain": gain,
            "gain_pct": gain_pct,
            "weight": 0.0,
        })
    df = pd.DataFrame(rows, columns=ENRICH_COLUMNS)
    if df.empty:
        return df
    total = float(df["value"].sum())
    df["weight"] = df["value"] / total if total > 0 else 0.0
    return df
