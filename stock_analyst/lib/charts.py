"""Plotly chart layer — dark mode, green/red baseline-split lines, return badge.

Public API:
  VIEWS = ("Performance", "Price", "Candlestick", "Area")
  split_traces(x, y, baseline) -> (x_up, y_up, x_dn, y_dn)
  render_price_chart(df, view, baseline_price=None, show_volume=False,
                     height=430, title=None, key=None) -> None (st.plotly_chart)
  sparkline_fig(df, baseline_price=None, height=56) -> go.Figure
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

VIEWS: tuple[str, ...] = ("Performance", "Price", "Candlestick", "Area")

GREEN = "#22c55e"
RED = "#ef4444"


def _interp_x(x0, x1, y0: float, y1: float, level: float):
    """X of the linear crossing of `level` between (x0,y0)-(x1,y1)."""
    if y1 == y0:
        return x0
    frac = (level - y0) / (y1 - y0)
    try:  # datetime axis
        return x0 + (x1 - x0) * frac
    except TypeError:
        return x0 + (float(x1) - float(x0)) * frac


def split_traces(x: list, y: list[float], baseline: float):
    """Split a line at `baseline` with interpolated zero crossings.

    Returns (x_up, y_up, x_dn, y_dn); None entries break plotly line segments,
    so above/below render as separate green/red runs that meet exactly at the
    baseline instead of jumping across it.
    """
    x_up: list = []
    y_up: list = []
    x_dn: list = []
    y_dn: list = []
    prev_x = prev_y = None
    for xi, yi in zip(x, y):
        if yi is None or pd.isna(yi):
            continue
        if prev_y is not None and (prev_y - baseline) * (yi - baseline) < 0:
            cx = _interp_x(prev_x, xi, prev_y, yi, baseline)
            # close the leaving side and open the entering side at the crossing
            if prev_y > baseline:
                x_up += [cx, None]
                y_up += [baseline, None]
                x_dn += [cx]
                y_dn += [baseline]
            else:
                x_dn += [cx, None]
                y_dn += [baseline, None]
                x_up += [cx]
                y_up += [baseline]
        if yi >= baseline:
            x_up.append(xi)
            y_up.append(yi)
        else:
            x_dn.append(xi)
            y_dn.append(yi)
        prev_x, prev_y = xi, yi
    return x_up, y_up, x_dn, y_dn


def _badge(fig: go.Figure, x, y: float, text: str, positive: bool) -> None:
    fig.add_annotation(
        x=x, y=y, text=f"<b>{text}</b>", showarrow=False,
        xanchor="left", xshift=6,
        font=dict(color="#0b0f19", size=12),
        bgcolor=GREEN if positive else RED,
        borderpad=4, opacity=0.95,
    )


def _base_layout(fig: go.Figure, height: int, title: str | None) -> None:
    fig.update_layout(
        template="plotly_dark", height=height,
        margin=dict(l=10, r=70, t=40 if title else 16, b=10),
        title=title or None, showlegend=False,
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor="rgba(148,163,184,.15)"),
        hovermode="x unified",
    )


def render_price_chart(
    df: pd.DataFrame,
    view: str = "Performance",
    baseline_price: float | None = None,
    show_volume: bool = False,
    height: int = 430,
    title: str | None = None,
    key: str | None = None,
) -> None:
    """Main price chart with 4 views.

    baseline_price: for 1D intraday pass YESTERDAY'S CLOSE so overnight gaps
    read correctly; defaults to the first close of the window otherwise.
    """
    if df is None or df.empty or "Close" not in df:
        st.info("No price data available for this selection.")
        return
    closes = df["Close"].astype(float)
    x = list(df.index)
    base = float(baseline_price) if baseline_price else float(closes.iloc[0])
    last = float(closes.iloc[-1])
    ret_pct = (last / base - 1.0) * 100.0 if base else 0.0
    positive = ret_pct >= 0
    fig = go.Figure()

    if view == "Candlestick":
        fig.add_trace(go.Candlestick(
            x=x, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            increasing_line_color=GREEN, decreasing_line_color=RED,
        ))
        fig.update_layout(xaxis_rangeslider_visible=False)
        _badge(fig, x[-1], last, f"{ret_pct:+.2f}%", positive)
    elif view == "Price":
        fig.add_trace(go.Scatter(
            x=x, y=closes, mode="lines",
            line=dict(color=GREEN if positive else RED, width=2),
        ))
        _badge(fig, x[-1], last, f"{ret_pct:+.2f}%", positive)
    elif view == "Area":
        xu, yu, xd, yd = split_traces(x, list(closes), base)
        # fill each split run toward the baseline: invisible baseline companion
        # trace first, then the colored trace with fill="tonexty"
        for xs, ys, color, fillc in (
            (xu, yu, GREEN, "rgba(34,197,94,.15)"),
            (xd, yd, RED, "rgba(239,68,68,.15)"),
        ):
            base_ys = [None if v is None else base for v in ys]
            fig.add_trace(go.Scatter(x=xs, y=base_ys, mode="lines",
                                     line=dict(width=0), hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                                     line=dict(color=color, width=2),
                                     fill="tonexty", fillcolor=fillc))
        fig.add_hline(y=base, line_dash="dot", line_color="rgba(148,163,184,.5)")
        _badge(fig, x[-1], last, f"{ret_pct:+.2f}%", positive)
    else:  # Performance (default): % vs baseline, split at 0
        perf = [(c / base - 1.0) * 100.0 for c in closes]
        xu, yu, xd, yd = split_traces(x, perf, 0.0)
        fig.add_trace(go.Scatter(x=xu, y=yu, mode="lines", line=dict(color=GREEN, width=2)))
        fig.add_trace(go.Scatter(x=xd, y=yd, mode="lines", line=dict(color=RED, width=2)))
        fig.add_hline(y=0, line_dash="dot", line_color="rgba(148,163,184,.5)")
        fig.update_yaxes(ticksuffix="%")
        _badge(fig, x[-1], float(perf[-1]), f"{ret_pct:+.2f}%", positive)

    _base_layout(fig, height, title)

    if show_volume and "Volume" in df and view != "Candlestick":
        fig.add_trace(go.Bar(
            x=x, y=df["Volume"], yaxis="y2", marker_color="rgba(148,163,184,.35)",
            hoverinfo="skip",
        ))
        fig.update_layout(yaxis2=dict(
            overlaying="y", side="right", showgrid=False, visible=False,
            range=[0, float(df["Volume"].max()) * 4 or 1],
        ))

    st.plotly_chart(fig, use_container_width=True, key=key,
                    config={"displayModeBar": False})


def sparkline_fig(df: pd.DataFrame, baseline_price: float | None = None,
                  height: int = 56) -> go.Figure:
    """Tiny green/red sparkline split at the period's starting price.

    For 1D pass baseline_price=yesterday's close; it is prepended as the
    baseline bar so the overnight gap shows truthfully.
    """
    closes = list(df["Close"].astype(float))
    x = list(df.index)
    if baseline_price:
        base = float(baseline_price)
        x = [x[0] - (x[1] - x[0]) if len(x) > 1 else x[0]] + x
        closes = [base] + closes
    else:
        base = closes[0]
    xu, yu, xd, yd = split_traces(x, closes, base)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xu, y=yu, mode="lines", line=dict(color=GREEN, width=1.6)))
    fig.add_trace(go.Scatter(x=xd, y=yd, mode="lines", line=dict(color=RED, width=1.6)))
    fig.update_layout(
        template="plotly_dark", height=height, margin=dict(l=0, r=0, t=2, b=2),
        showlegend=False, xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig
