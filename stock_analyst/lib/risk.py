"""Neutral, descriptive risk scoring for ETFs and portfolios.

Purely statistical characterisations of historical price behaviour — never
advice, signals, or recommendations.

Public API:
  etf_risk_score(df, details) -> (score 0-100 int, components dict)
  portfolio_risk_score(hist_map, weights) -> (score 0-100 int, components dict)
  risk_band(score) -> "Conservative" | "Moderate" | "Aggressive" | "Very aggressive"

Scaling conventions (all component sub-scores are 0-100):
  * Annualized volatility: 10% -> 0 (low), 40%+ -> 100 (high), linear between.
  * Max drawdown over the window: 0% -> 0, 50%+ -> 100, linear between.
  * Concentration: weight fraction (0-1) mapped linearly to 0-100.
Composite weights ~ volatility 45 / drawdown 35 / concentration 20; when a
component cannot be computed the remaining weights are renormalized.
"""
from __future__ import annotations

import math

import pandas as pd

# Component blend (fractions of the composite score).
_W_VOL = 0.45
_W_DD = 0.35
_W_CONC = 0.20

# Volatility scaling anchors (annualized, as fractions).
_VOL_LOW = 0.10   # 10% annualized -> score 0
_VOL_HIGH = 0.40  # 40%+ annualized -> score 100

# Drawdown scaling anchor: a 50% peak-to-trough loss (or worse) -> score 100.
_DD_HIGH = 0.50


def risk_band(score: int | float) -> str:
    """Map a 0-100 score to a descriptive band (25/50/75 thresholds)."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "Moderate"
    if s < 25:
        return "Conservative"
    if s < 50:
        return "Moderate"
    if s < 75:
        return "Aggressive"
    return "Very aggressive"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _periods_per_year(index: pd.Index) -> float:
    """Infer an annualization factor from bar spacing (daily=252 default)."""
    try:
        if len(index) < 3:
            return 252.0
        deltas = pd.Series(index).diff().dropna()
        med = deltas.median()
        days = med.total_seconds() / 86400.0
        if days <= 0:
            return 252.0
        if days <= 1.5:      # daily (or intraday collapsed to days)
            return 252.0
        if days <= 8.0:      # weekly bars
            return 52.0
        return 12.0          # monthly bars
    except Exception:
        return 252.0


def _returns_from_close(df: pd.DataFrame | None) -> pd.Series | None:
    """Simple percentage returns from a Close column. None when unusable."""
    if df is None or getattr(df, "empty", True) or "Close" not in df:
        return None
    closes = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(closes) < 3:
        return None
    rets = closes.pct_change().dropna()
    return rets if not rets.empty else None


def _annualized_vol(rets: pd.Series, periods_per_year: float) -> float | None:
    try:
        sd = float(rets.std())
        if not math.isfinite(sd):
            return None
        return sd * math.sqrt(periods_per_year)
    except Exception:
        return None


def _max_drawdown(rets: pd.Series) -> float | None:
    """Max peak-to-trough loss of the cumulative return path (positive frac)."""
    try:
        wealth = (1.0 + rets).cumprod()
        peak = wealth.cummax()
        dd = (wealth / peak - 1.0).min()
        if not math.isfinite(float(dd)):
            return None
        return abs(float(dd))
    except Exception:
        return None


def _vol_score(ann_vol: float) -> float:
    return _clamp01((ann_vol - _VOL_LOW) / (_VOL_HIGH - _VOL_LOW)) * 100.0


def _dd_score(max_dd: float) -> float:
    return _clamp01(max_dd / _DD_HIGH) * 100.0


def _compose(parts: list[tuple[str, float | None, float]]) -> tuple[int, dict]:
    """Blend (label, sub-score, weight) parts, renormalizing over available ones."""
    avail = [(label, s, w) for label, s, w in parts if s is not None]
    detail: dict = {f"{label}_score": (round(s, 1) if s is not None else None)
                    for label, s, _ in parts}
    if not avail:
        return 0, detail
    total_w = sum(w for _, _, w in avail)
    score = sum(s * w for _, s, w in avail) / total_w if total_w else 0.0
    return int(round(_clamp01(score / 100.0) * 100.0)), detail


def etf_risk_score(df: pd.DataFrame | None, details: dict | None) -> tuple[int, dict]:
    """Composite 0-100 risk characterisation of a single ETF.

    df: OHLCV history (market_data.get_history). details: market_data
    .get_etf_details dict — details["top_holdings"] is [(symbol, name, weight)]
    with weights as fractions; concentration = sum of the top-10 weights.
    Returns (score, components); components carry raw stats + sub-scores and
    the band label. Degrades gracefully: unavailable pieces are skipped.
    """
    rets = _returns_from_close(df)
    ann_vol = max_dd = None
    if rets is not None:
        ppy = _periods_per_year(rets.index)
        ann_vol = _annualized_vol(rets, ppy)
        max_dd = _max_drawdown(rets)

    concentration = None
    try:
        holdings = (details or {}).get("top_holdings") or []
        weights = [float(h[2]) for h in holdings[:10]
                   if len(h) >= 3 and h[2] is not None]
        if weights:
            concentration = _clamp01(sum(w for w in weights if math.isfinite(w)))
    except Exception:
        concentration = None

    score, detail = _compose([
        ("volatility", _vol_score(ann_vol) if ann_vol is not None else None, _W_VOL),
        ("drawdown", _dd_score(max_dd) if max_dd is not None else None, _W_DD),
        ("concentration",
         concentration * 100.0 if concentration is not None else None, _W_CONC),
    ])
    components = {
        "annualized_volatility": ann_vol,
        "max_drawdown": max_dd,
        "concentration_top10": concentration,
        "band": risk_band(score),
        **detail,
    }
    return score, components


def portfolio_risk_score(
    hist_map: dict[str, pd.DataFrame] | None,
    weights: dict[str, float] | None,
) -> tuple[int, dict]:
    """Composite 0-100 risk characterisation of a weighted portfolio.

    hist_map: {ticker: OHLCV df} (market_data.get_history_bulk). weights:
    {ticker: weight} (any positive scale; normalized internally). Builds a
    date-aligned weighted daily-return series, then applies the same
    volatility + drawdown scaling; concentration = largest single normalized
    weight. Returns (score, components); (0, {...}) when nothing computable.
    """
    hist_map = hist_map or {}
    weights = weights or {}

    ret_cols: dict[str, pd.Series] = {}
    usable_w: dict[str, float] = {}
    for tk, w in weights.items():
        try:
            wf = float(w)
        except (TypeError, ValueError):
            continue
        if wf <= 0 or not math.isfinite(wf):
            continue
        rets = _returns_from_close(hist_map.get(tk))
        if rets is None:
            continue
        ret_cols[tk] = rets
        usable_w[tk] = wf

    if not ret_cols:
        return 0, {
            "annualized_volatility": None, "max_drawdown": None,
            "concentration_max_weight": None, "band": risk_band(0),
            "volatility_score": None, "drawdown_score": None,
            "concentration_score": None, "tickers_used": [],
        }

    total_w = sum(usable_w.values())
    norm_w = {tk: w / total_w for tk, w in usable_w.items()}

    aligned = pd.concat(ret_cols, axis=1, join="inner").dropna(how="any")
    ann_vol = max_dd = None
    if len(aligned) >= 3:
        port_rets = sum(aligned[tk] * norm_w[tk] for tk in aligned.columns)
        ppy = _periods_per_year(aligned.index)
        ann_vol = _annualized_vol(port_rets, ppy)
        max_dd = _max_drawdown(port_rets)

    concentration = _clamp01(max(norm_w.values()))

    score, detail = _compose([
        ("volatility", _vol_score(ann_vol) if ann_vol is not None else None, _W_VOL),
        ("drawdown", _dd_score(max_dd) if max_dd is not None else None, _W_DD),
        ("concentration", concentration * 100.0, _W_CONC),
    ])
    components = {
        "annualized_volatility": ann_vol,
        "max_drawdown": max_dd,
        "concentration_max_weight": concentration,
        "band": risk_band(score),
        "tickers_used": sorted(norm_w),
        **detail,
    }
    return score, components
