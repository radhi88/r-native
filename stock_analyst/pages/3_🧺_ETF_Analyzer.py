"""ETF Analyzer — returns, risk gauge, sectors, holdings, peer costs."""
import streamlit as st

st.set_page_config(page_title="ETF Analyzer", page_icon="🧺", layout="wide")

import sys, pathlib  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
from lib import charts, config, etf_peers, logos, risk  # noqa: E402
from lib import market_data as md  # noqa: E402

config.inject_base_style()
config.render_sidebar_brand()
st.title("🧺 ETF Analyzer")

c_in, c_per = st.columns([1, 3])
ticker = (c_in.text_input("ETF ticker", "SPY").upper().strip() or "SPY")
period = c_per.segmented_control("Period", list(md.PERIOD_MAP), default="1Y",
                                 key="etf_period") or "1Y"
is_1d = period == "1D"

if not md.is_etf(ticker):
    st.warning("Ticker does not look like an ETF — data may be incomplete.")

details = md.get_etf_details(ticker)
df = md.get_history(ticker, period)
if df is None:
    st.warning(f"Could not load price data for '{ticker}'.")
    config.render_footer()
    st.stop()


def _pct(v) -> str:
    if v is None:
        return "—"
    v = float(v)
    if abs(v) <= 1.5:  # fraction form
        v *= 100
    return f"{v:,.2f}%"


# ── Header ───────────────────────────────────────────────────────────────────
st.markdown(f"{logos.logo_html(ticker, 48)}"
            f"<span style='font-size:26px;font-weight:700'>{details['name']}</span> "
            f"<span style='color:#8ea4c5'>({ticker})</span>", unsafe_allow_html=True)
h1, h2, h3 = st.columns(3)
q = md.get_quote(ticker)
h1.metric("Price", f"{q['price']:,.2f}" if q else "—",
          f"{q['change_pct']:+.2f}%" if q else None)
h2.metric("Expense ratio", _pct(details["expense_ratio"]))
ta = details["total_assets"]
h3.metric("Total assets", f"${ta / 1e9:,.1f}B" if ta else "—")

# ── Chart ────────────────────────────────────────────────────────────────────
view = st.segmented_control("View", list(charts.VIEWS), default="Performance",
                            key="etf_view") or "Performance"
charts.render_price_chart(df, view=view,
                          baseline_price=md.get_prev_close(ticker) if is_1d else None,
                          height=440, key="etf_chart")

# ── Returns + Risk ───────────────────────────────────────────────────────────
cL, cR = st.columns([1, 1])
with cL:
    st.subheader("Returns")
    st.table(pd.DataFrame({
        "Metric": ["YTD return", "3Y avg return", "5Y avg return", "3Y beta"],
        "Value": [_pct(details["ytd_return"]), _pct(details["three_year_avg_return"]),
                  _pct(details["five_year_avg_return"]),
                  f"{details['beta3y']:.2f}" if details["beta3y"] else "—"],
    }).set_index("Metric"))
with cR:
    st.subheader("Risk profile")
    score, comps = risk.etf_risk_score(md.get_history(ticker, "1Y"), details)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score,
        gauge=dict(axis=dict(range=[0, 100]),
                   bar=dict(color="rgba(0,0,0,0)"),
                   steps=[dict(range=[0, 25], color="#14532d"),
                          dict(range=[25, 50], color="#365314"),
                          dict(range=[50, 75], color="#78350f"),
                          dict(range=[75, 100], color="#7f1d1d")],
                   threshold=dict(line=dict(color="#f5f5f5", width=4),
                                  thickness=0.9, value=score)),
        title=dict(text=risk.risk_band(score), font=dict(size=16)),
    ))
    fig.update_layout(template="plotly_dark", height=240,
                      margin=dict(l=25, r=25, t=45, b=5))
    st.plotly_chart(fig, use_container_width=True, key="etf_risk",
                    config={"displayModeBar": False})
    st.caption(" · ".join(f"{k}: {v:.2f}" if isinstance(v, float) else f"{k}: {v}"
                          for k, v in comps.items() if v is not None) or
               "Components unavailable")

# ── Sector breakdown ─────────────────────────────────────────────────────────
if details["sector_weights"]:
    st.subheader("Sector breakdown")
    sw = sorted(details["sector_weights"].items(), key=lambda x: x[1])
    fig = go.Figure(go.Bar(
        x=[v * 100 for _, v in sw], y=[k.replace("_", " ").title() for k, _ in sw],
        orientation="h", marker_color="#38bdf8",
        text=[f"{v * 100:.1f}%" for _, v in sw], textposition="outside"))
    fig.update_layout(template="plotly_dark", height=380, showlegend=False,
                      margin=dict(l=10, r=60, t=10, b=10),
                      xaxis=dict(ticksuffix="%"))
    st.plotly_chart(fig, use_container_width=True, key="etf_sectors",
                    config={"displayModeBar": False})

# ── Top holdings (two-column list, not a dataframe) ─────────────────────────
if details["top_holdings"]:
    st.subheader("Top holdings")
    half = (len(details["top_holdings"]) + 1) // 2
    c1, c2 = st.columns(2)
    for col, chunk in ((c1, details["top_holdings"][:half]),
                       (c2, details["top_holdings"][half:])):
        with col:
            for sym, nm, w in chunk:
                st.markdown(
                    f'{logos.logo_html(sym, 22)}<b>{sym}</b> '
                    f'<span style="color:#8ea4c5">{nm[:26]}</span> · '
                    f'{w * 100:.2f}%', unsafe_allow_html=True)

# ── Peer comparison by cost ──────────────────────────────────────────────────
peers = etf_peers.find_peers(ticker)
if peers:
    st.subheader("Peer cost comparison")
    rows = []
    for p in [ticker] + peers:
        d = md.get_etf_details(p)
        er = d["expense_ratio"]
        rows.append({"Ticker": p, "Name": d["name"],
                     "Expense ratio": float(er) if er is not None else None})
    dfp = pd.DataFrame(rows).sort_values("Expense ratio", na_position="last")
    dfp["Expense ratio"] = dfp["Expense ratio"].map(
        lambda v: _pct(v) if v is not None else "—")
    st.table(dfp.set_index("Ticker"))
    cur_er = next((float(d) for t, d in
                   [(r["Ticker"], r["Expense ratio"]) for r in rows]
                   if t == ticker and d is not None), None)
    cheaper = [r for r in rows if r["Ticker"] != ticker
               and r["Expense ratio"] is not None and cur_er is not None
               and r["Expense ratio"] < cur_er]
    if cheaper:
        best = min(cheaper, key=lambda r: r["Expense ratio"])
        sav = etf_peers.expense_savings(cur_er, best["Expense ratio"])
        st.success(
            f"Lower-cost peer in this group: **{best['Ticker']}** — about "
            f"**{sav['bps']:.1f} bps** less, ≈ **${sav['dollars_per_year']:,.0f}/year** "
            f"on a $100K position. (Cost is one factor among many.)")

config.render_footer()
