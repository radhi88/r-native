"""Portfolio — local holdings, value/return, allocation, risk, AI review."""
import streamlit as st

st.set_page_config(page_title="Portfolio", page_icon="💼", layout="wide")

import sys, pathlib  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
from lib import claude_analyst, config, portfolio, risk  # noqa: E402
from lib import market_data as md  # noqa: E402

config.inject_base_style()
config.render_sidebar_brand()
st.title("💼 Portfolio")
st.caption("Holdings stay local in `data/portfolio.json` (gitignored) — nothing leaves "
           "your machine except price lookups.")

# ── Editor ───────────────────────────────────────────────────────────────────
holdings = portfolio.load_portfolio()
seed = pd.DataFrame(holdings or [{"ticker": "", "shares": 0.0, "cost_basis": 0.0}])
with st.form("pf_form"):
    edited = st.data_editor(
        seed, num_rows="dynamic", use_container_width=True, key="pf_editor",
        column_config={
            "ticker": st.column_config.TextColumn("Ticker"),
            "shares": st.column_config.NumberColumn("Shares", min_value=0.0),
            "cost_basis": st.column_config.NumberColumn("Cost basis ($/share)",
                                                        min_value=0.0),
        })
    if st.form_submit_button("💾 Save portfolio"):
        rows = [r for r in edited.to_dict("records")
                if str(r.get("ticker") or "").strip()]
        portfolio.save_portfolio(rows)
        st.success(f"Saved {len(rows)} holdings.")
        holdings = portfolio.load_portfolio()

if not holdings:
    st.info("Add tickers, share counts, and cost basis above, then save — the "
            "dashboard fills in live values, allocation, and risk.")
    config.render_footer()
    st.stop()

# ── Metrics ──────────────────────────────────────────────────────────────────
dfp = portfolio.enrich(holdings)
total_value = float(dfp["value"].sum())
total_cost = float(dfp["cost"].sum())
gain = total_value - total_cost
gain_pct = (gain / total_cost * 100) if total_cost else 0.0
m1, m2, m3, m4 = st.columns(4)
m1.metric("Current value", f"${total_value:,.2f}")
m2.metric("Total cost", f"${total_cost:,.2f}")
m3.metric("Total return", f"${gain:,.2f}", f"{gain_pct:+.2f}%")
m4.metric("Positions", f"{len(dfp)}")

st.dataframe(dfp.style.format({
    "shares": "{:,.2f}", "cost_basis": "${:,.2f}", "price": "${:,.2f}",
    "value": "${:,.2f}", "cost": "${:,.2f}", "gain": "${:,.2f}",
    "gain_pct": "{:+.2f}%", "weight": "{:.1%}"}), use_container_width=True)

# ── Allocation + sectors ─────────────────────────────────────────────────────
cL, cR = st.columns(2)
with cL:
    st.subheader("Allocation")
    fig = go.Figure(go.Pie(labels=list(dfp["ticker"]), values=list(dfp["value"]),
                           hole=0.45))
    fig.update_layout(template="plotly_dark", height=340,
                      margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, key="pf_pie",
                    config={"displayModeBar": False})
with cR:
    st.subheader("Sector breakdown")
    sectors: dict[str, float] = {}
    for _, r in dfp.iterrows():
        sec = md.get_stock_fundamentals(r["ticker"]).get("sector") or "Other"
        sectors[sec] = sectors.get(sec, 0.0) + float(r["value"])
    if sectors:
        items = sorted(sectors.items(), key=lambda x: x[1])
        fig = go.Figure(go.Bar(x=[v for _, v in items], y=[k for k, _ in items],
                               orientation="h", marker_color="#8b5cf6",
                               text=[f"${v:,.0f}" for _, v in items],
                               textposition="outside"))
        fig.update_layout(template="plotly_dark", height=340, showlegend=False,
                          margin=dict(l=10, r=70, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True, key="pf_sectors",
                        config={"displayModeBar": False})

# ── Risk ─────────────────────────────────────────────────────────────────────
st.subheader("Portfolio risk profile")
hist_map = {t: md.get_history(t, "1Y") for t in dfp["ticker"]}
weights = {r["ticker"]: float(r["weight"]) for _, r in dfp.iterrows()}
score, comps = risk.portfolio_risk_score(hist_map, weights)
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
    title=dict(text=risk.risk_band(score), font=dict(size=16))))
fig.update_layout(template="plotly_dark", height=240,
                  margin=dict(l=25, r=25, t=45, b=5))
st.plotly_chart(fig, use_container_width=True, key="pf_risk",
                config={"displayModeBar": False})

# ── AI review ────────────────────────────────────────────────────────────────
st.subheader("AI portfolio review")
if st.button("Generate review", key="btn_pf_ai"):
    summary = "; ".join(
        f"{r['ticker']} {r['weight']:.0%} of portfolio, return {r['gain_pct']:+.1f}%"
        for _, r in dfp.iterrows() if pd.notna(r["gain_pct"]))
    out = claude_analyst.portfolio_review(
        f"Holdings: {summary}. Total value ${total_value:,.0f}, "
        f"overall return {gain_pct:+.1f}%.")
    if out is None:
        config.missing_key_notice("Anthropic", "ANTHROPIC_API_KEY",
                                  "https://console.anthropic.com")
    else:
        st.markdown(out)

config.render_footer()
