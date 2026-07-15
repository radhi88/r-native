"""Macro — FRED indicators, CPI YoY, yield curve, AI pulse-check."""
import streamlit as st

st.set_page_config(page_title="Macro", page_icon="🌍", layout="wide")

import sys, pathlib  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import plotly.graph_objects as go  # noqa: E402
from lib import charts, claude_analyst, config, macro, rates  # noqa: E402

config.inject_base_style()
config.render_sidebar_brand()
st.title("🌍 Macro")

if config.fred_key() is None:
    config.missing_key_notice("FRED", "FRED_API_KEY",
                              "https://fred.stlouisfed.org/docs/api/api_key.html")
    config.render_footer()
    st.stop()

# ── Indicator grid ───────────────────────────────────────────────────────────
labels = list(macro.INDICATORS)
latest: dict[str, float] = {}
for row_labels in (labels[:4], labels[4:]):
    cols = st.columns(4)
    for c, label in zip(cols, row_labels):
        meta = macro.INDICATORS[label]
        res = macro.latest_with_delta(meta["series_id"], yoy=meta["yoy"])
        with c:
            if res is None:
                st.metric(label, "—")
                continue
            val, delta, date_str = res
            unit = meta["unit"]
            if unit == "$B":
                txt = f"${val:,.0f}B"
            elif unit == "$M":
                txt = f"${val / 1000:,.0f}B"
            elif unit == "%" or meta["yoy"]:
                txt = f"{val:,.2f}%"
            elif unit == "pp":
                txt = f"{val:+.2f}pp"
            else:
                txt = f"{val:,.1f}"
            st.metric(label, txt, f"{delta:+.2f} vs prior" if delta is not None else None)
            st.caption(date_str)
            latest[label] = round(float(val), 2)

st.divider()

cL, cR = st.columns(2)

# ── CPI YoY chart ────────────────────────────────────────────────────────────
with cL:
    st.subheader("CPI — year over year")
    s = macro.cpi_yoy_series()
    if s is not None and not s.empty:
        s = s.last("20Y") if hasattr(s, "last") else s
        fig = go.Figure(go.Scatter(x=list(s.index), y=list(s.values), mode="lines",
                                   line=dict(color="#38bdf8", width=2)))
        fig.add_hline(y=2.0, line_dash="dot", line_color="rgba(148,163,184,.6)",
                      annotation_text="2% reference")
        fig.update_layout(template="plotly_dark", height=340,
                          margin=dict(l=10, r=10, t=10, b=10),
                          yaxis=dict(ticksuffix="%"))
        st.plotly_chart(fig, use_container_width=True, key="cpi_yoy",
                        config={"displayModeBar": False})
    else:
        st.info("CPI series unavailable.")

# ── Yield curve ──────────────────────────────────────────────────────────────
with cR:
    st.subheader("US Treasury yield curve")
    yc = rates.yield_curve()
    if yc is not None and not yc.empty:
        fig = go.Figure(go.Scatter(x=list(yc.index), y=list(yc.values),
                                   mode="lines+markers",
                                   line=dict(color=charts.GREEN, width=2),
                                   marker=dict(size=8)))
        fig.update_layout(template="plotly_dark", height=340,
                          margin=dict(l=10, r=10, t=10, b=10),
                          yaxis=dict(ticksuffix="%"),
                          xaxis=dict(title="Maturity"))
        st.plotly_chart(fig, use_container_width=True, key="yield_curve",
                        config={"displayModeBar": False})
    else:
        st.info("Yield curve unavailable.")

st.divider()

# ── AI pulse-check ───────────────────────────────────────────────────────────
st.subheader("AI macro pulse-check")
if st.button("Generate pulse-check", key="btn_macro_ai"):
    out = claude_analyst.macro_pulse(latest)
    if out is None:
        config.missing_key_notice("Anthropic", "ANTHROPIC_API_KEY",
                                  "https://console.anthropic.com")
    else:
        st.markdown(out)

config.render_footer()
