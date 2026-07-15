"""Market Pulse — index cards, S&P chart, sector heatmap, movers, headlines."""
import streamlit as st

st.set_page_config(page_title="Market Pulse", page_icon="📈", layout="wide")

import sys, pathlib  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import plotly.graph_objects as go  # noqa: E402
from lib import charts, config, logos, news  # noqa: E402
from lib import market_data as md  # noqa: E402

config.inject_base_style()
config.render_sidebar_brand()
st.title("📈 Market Pulse")

period = st.segmented_control("Period", list(md.PERIOD_MAP), default="1D",
                              key="pulse_period") or "1D"
is_1d = period == "1D"

# ── Index cards grid (10 tickers, 5 per row) ───────────────────────────────
tickers = list(md.INDEX_TICKERS)
hist = md.get_history_bulk(tuple(tickers), period)
rows = [tickers[:5], tickers[5:]]
for row in rows:
    cols = st.columns(5)
    for c, tk in zip(cols, row):
        with c:
            df = hist.get(tk)
            if df is None or df.empty:
                st.metric(md.INDEX_TICKERS[tk], "—")
                continue
            base = md.get_prev_close(tk) if is_1d else float(df["Close"].iloc[0])
            last = float(df["Close"].iloc[-1])
            pct = (last / base - 1) * 100 if base else 0.0
            st.metric(md.INDEX_TICKERS[tk], f"{last:,.2f}", f"{pct:+.2f}%")
            st.plotly_chart(
                charts.sparkline_fig(df, baseline_price=base if is_1d else None),
                use_container_width=True, key=f"spark_{tk}",
                config={"displayModeBar": False, "staticPlot": True},
            )

st.divider()

# ── Big S&P 500 chart with view toggle ──────────────────────────────────────
st.subheader("S&P 500 (^GSPC)")
view = st.segmented_control("View", list(charts.VIEWS), default="Performance",
                            key="pulse_view") or "Performance"
spx = hist.get("^GSPC") if hist.get("^GSPC") is not None else md.get_history("^GSPC", period)
charts.render_price_chart(
    spx, view=view,
    baseline_price=md.get_prev_close("^GSPC") if is_1d else None,
    height=460, key="pulse_spx",
)

st.divider()

# ── Sector heatmap (11 SPDR ETFs, period returns) ───────────────────────────
st.subheader("Sector performance")
sec_hist = md.get_history_bulk(tuple(md.SECTOR_ETFS), period)
sec_rows = []
for tk, name in md.SECTOR_ETFS.items():
    df = sec_hist.get(tk)
    if df is None or df.empty:
        continue
    base = md.get_prev_close(tk) if is_1d else float(df["Close"].iloc[0])
    if not base:
        continue
    sec_rows.append((name, tk, (float(df["Close"].iloc[-1]) / base - 1) * 100))
if sec_rows:
    sec_rows.sort(key=lambda r: r[2])
    fig = go.Figure(go.Bar(
        x=[r[2] for r in sec_rows],
        y=[f"{r[0]} ({r[1]})" for r in sec_rows],
        orientation="h",
        marker_color=[charts.GREEN if r[2] >= 0 else charts.RED for r in sec_rows],
        text=[f"{r[2]:+.2f}%" for r in sec_rows], textposition="outside",
    ))
    fig.update_layout(template="plotly_dark", height=420,
                      margin=dict(l=10, r=60, t=10, b=10),
                      xaxis=dict(ticksuffix="%"), showlegend=False)
    st.plotly_chart(fig, use_container_width=True, key="sector_map",
                    config={"displayModeBar": False})
else:
    st.info("Sector data unavailable right now.")

st.divider()

# ── Movers: gainers / losers / most active ──────────────────────────────────
MOVERS_UNIVERSE = (
    "AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO JPM V MA UNH XOM LLY JNJ WMT PG "
    "HD COST ORCL CVX MRK ABBV KO PEP BAC ADBE CRM NFLX AMD INTC QCOM CSCO "
    "IBM MU PLTR UBER DIS BA CAT GE"
).split()


def _mover_row(q: dict) -> None:
    pct = q["change_pct"]
    color = "#22c55e" if pct >= 0 else "#ef4444"
    name = (q["name"] or q["ticker"])[:18]
    st.markdown(
        f'{logos.logo_html(q["ticker"], 22)}<b>{q["ticker"]}</b> '
        f'<span style="color:#8ea4c5">{name}</span> · {q["price"]:,.2f} '
        f'<span style="color:{color}"><b>{pct:+.2f}%</b></span>',
        unsafe_allow_html=True,
    )


quotes = md.get_quotes_bulk(tuple(MOVERS_UNIVERSE))
if quotes:
    ranked = sorted(quotes.values(), key=lambda q: q["change_pct"], reverse=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("Top gainers")
        for q in ranked[:5]:
            _mover_row(q)
    with c2:
        st.subheader("Top losers")
        for q in ranked[-5:][::-1]:
            _mover_row(q)
    with c3:
        st.subheader("Biggest moves")
        for q in sorted(quotes.values(), key=lambda q: abs(q["change_pct"]),
                        reverse=True)[:5]:
            _mover_row(q)
else:
    st.info("Movers data unavailable right now.")

st.divider()

# ── Top 3 market headlines from the last 24 hours ───────────────────────────
st.subheader("Top headlines")
import time as _time  # noqa: E402
items = [n for n in news.market_news(12) if n["ts"] and _time.time() - n["ts"] < 86400][:3]
if not items:
    items = news.market_news(3)
for n in items:
    st.markdown(f"**[{n['title']}]({n['link']})**")
    st.caption(f"{n['publisher']} · {news.time_ago(n['ts'])}")
    if n.get("summary"):
        st.write(n["summary"][:220] + ("…" if len(n["summary"]) > 220 else ""))
if not items:
    st.info("No headlines available right now.")

config.render_footer()
