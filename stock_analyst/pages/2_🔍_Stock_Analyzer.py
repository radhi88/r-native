"""Stock Analyzer — chart, neutral snapshot gauges, key stats, AI analysis."""
import streamlit as st

st.set_page_config(page_title="Stock Analyzer", page_icon="🔍", layout="wide")

import sys, pathlib  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import plotly.graph_objects as go  # noqa: E402
from lib import charts, claude_analyst, config, logos, news, signals  # noqa: E402
from lib import market_data as md  # noqa: E402

config.inject_base_style()
config.render_sidebar_brand()
st.title("🔍 Stock Analyzer")

c_in, c_per = st.columns([1, 3])
ticker = (c_in.text_input("Ticker", "AAPL").upper().strip() or "AAPL")
period = c_per.segmented_control("Period", list(md.PERIOD_MAP), default="1Y",
                                 key="sa_period") or "1Y"
is_1d = period == "1D"

info = md.get_stock_fundamentals(ticker)
df = md.get_history(ticker, period)
if df is None or not any(info.values()):
    st.warning(f"Could not load data for '{ticker}'. Check the symbol.")
    config.render_footer()
    st.stop()


def _fmt_cap(v) -> str:
    if not v:
        return "—"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if v >= div:
            return f"${v / div:,.2f}{suf}"
    return f"${v:,.0f}"


def _fmt(v, pct=False, dec=2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v) * (100 if pct else 1):,.{dec}f}" + ("%" if pct else "")
    except Exception:
        return "—"


# ── Header ───────────────────────────────────────────────────────────────────
name = info.get("shortName") or info.get("longName") or ticker
lh = logos.logo_html(ticker, 64)
st.markdown(f"{lh}<span style='font-size:30px;font-weight:700'>{name}</span> "
            f"<span style='color:#8ea4c5'>({ticker})</span>", unsafe_allow_html=True)
st.caption(f"{info.get('sector') or '—'} · {info.get('industry') or '—'}")
q = md.get_quote(ticker)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Price", f"{q['price']:,.2f}" if q else "—",
          f"{q['change_pct']:+.2f}%" if q else None)
m2.metric("Market Cap", _fmt_cap(info.get("marketCap")))
m3.metric("Trailing P/E", _fmt(info.get("trailingPE")))
m4.metric("Beta", _fmt(info.get("beta")))

# ── Chart ────────────────────────────────────────────────────────────────────
view = st.segmented_control("View", list(charts.VIEWS), default="Performance",
                            key="sa_view") or "Performance"
charts.render_price_chart(df, view=view, show_volume=True,
                          baseline_price=md.get_prev_close(ticker) if is_1d else None,
                          height=460, key="sa_chart")

# ── Snapshot ─────────────────────────────────────────────────────────────────
st.subheader("Snapshot")
st.caption("Descriptive, factual measurements — not advice or a rating to act on.")
tscore, tdrivers = signals.technical_score(md.get_history(ticker, "1Y"))
fscore, fdrivers = signals.fundamental_score(info)


def _gauge(score: int, label: str) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score,
        gauge=dict(
            axis=dict(range=[0, 100], tickwidth=1),
            bar=dict(color="rgba(0,0,0,0)"),
            steps=[dict(range=[0, 35], color="#7f1d1d"),
                   dict(range=[35, 55], color="#78350f"),
                   dict(range=[55, 75], color="#365314"),
                   dict(range=[75, 100], color="#14532d")],
            threshold=dict(line=dict(color="#f5f5f5", width=4),
                           thickness=0.9, value=score),
        ),
        title=dict(text=label, font=dict(size=15)),
    ))
    fig.update_layout(template="plotly_dark", height=230,
                      margin=dict(l=25, r=25, t=40, b=5))
    return fig


g1, g2, g3 = st.columns(3)
with g1:
    st.markdown("**At a glance**")
    for label, value in signals.at_a_glance(df, info):
        st.markdown(f"- **{label}:** {value}")
with g2:
    st.plotly_chart(_gauge(tscore, "Technical strength"), use_container_width=True,
                    key="g_tech", config={"displayModeBar": False})
    st.caption("Trend, momentum, position vs averages")
    for d in tdrivers[:4]:
        st.markdown(f"- {d}")
with g3:
    st.plotly_chart(_gauge(fscore, "Fundamental quality"), use_container_width=True,
                    key="g_fund", config={"displayModeBar": False})
    st.caption("Margins, returns, leverage, growth")
    for d in fdrivers[:4]:
        st.markdown(f"- {d}")

# ── Key statistics ───────────────────────────────────────────────────────────
st.subheader("Key statistics")
groups = [
    ("Valuation", [("Trailing P/E", _fmt(info.get("trailingPE"))),
                   ("Forward P/E", _fmt(info.get("forwardPE"))),
                   ("Price/Book", _fmt(info.get("priceToBook"))),
                   ("PEG", _fmt(info.get("pegRatio"))),
                   ("Price/Sales", _fmt(info.get("priceToSalesTrailing12Months"))),
                   ("EV/EBITDA", _fmt(info.get("enterpriseToEbitda")))]),
    ("Profitability", [("Profit margin", _fmt(info.get("profitMargins"), pct=True)),
                       ("Operating margin", _fmt(info.get("operatingMargins"), pct=True)),
                       ("Gross margin", _fmt(info.get("grossMargins"), pct=True)),
                       ("ROE", _fmt(info.get("returnOnEquity"), pct=True)),
                       ("ROA", _fmt(info.get("returnOnAssets"), pct=True))]),
    ("Balance sheet", [("Total cash", _fmt_cap(info.get("totalCash"))),
                       ("Total debt", _fmt_cap(info.get("totalDebt"))),
                       ("Debt/Equity", _fmt(info.get("debtToEquity"))),
                       ("Current ratio", _fmt(info.get("currentRatio"))),
                       ("Free cash flow", _fmt_cap(info.get("freeCashflow")))]),
    ("Trading", [("Beta", _fmt(info.get("beta"))),
                 ("52w high", _fmt(info.get("fiftyTwoWeekHigh"))),
                 ("52w low", _fmt(info.get("fiftyTwoWeekLow"))),
                 ("50-day avg", _fmt(info.get("fiftyDayAverage"))),
                 ("200-day avg", _fmt(info.get("twoHundredDayAverage"))),
                 ("Avg volume", f"{info.get('averageVolume'):,}" if info.get("averageVolume") else "—")]),
    ("Income", [("EPS (ttm)", _fmt(info.get("trailingEps"))),
                ("EPS (fwd)", _fmt(info.get("forwardEps"))),
                # yfinance >=0.2.54 returns dividendYield percent-form (0.41 = 0.41%);
                # older versions fraction-form — disambiguate by magnitude (yields >20% unreal)
                ("Dividend yield",
                 (f"{info['dividendYield']:.2f}%" if info.get("dividendYield") and float(info["dividendYield"]) > 0.2
                  else _fmt(info.get("dividendYield"), pct=True))),
                ("Payout ratio", _fmt(info.get("payoutRatio"), pct=True)),
                ("Revenue growth", _fmt(info.get("revenueGrowth"), pct=True))]),
    ("Analyst (informational)", [("Consensus estimate", _fmt(info.get("recommendationMean"))),
                                 ("# opinions", f"{info.get('numberOfAnalystOpinions') or '—'}"),
                                 ("Target mean", _fmt(info.get("targetMeanPrice")))]),
]
cols = st.columns(3)
for i, (title, rows) in enumerate(groups):
    with cols[i % 3]:
        st.markdown(f"**{title}**")
        for k, v in rows:
            st.markdown(f"<span style='color:#8ea4c5'>{k}</span>: {v}",
                        unsafe_allow_html=True)
        st.write("")

if info.get("longBusinessSummary"):
    with st.expander("Business summary"):
        st.write(info["longBusinessSummary"])

# ── AI analysis ──────────────────────────────────────────────────────────────
st.subheader("AI analysis")
facts = {k: v for k, v in info.items() if v is not None and k != "longBusinessSummary"}
t1, t2, t3 = st.tabs(["Bull / Bear case", "Deep analysis", "Recent headlines"])
with t1:
    if st.button("Generate bull/bear case", key="btn_bb"):
        out = claude_analyst.bull_bear_case(ticker, facts)
        if out is None:
            config.missing_key_notice("Anthropic", "ANTHROPIC_API_KEY",
                                      "https://console.anthropic.com")
        else:
            st.markdown(out)
with t2:
    if st.button("Generate deep analysis", key="btn_deep"):
        out = claude_analyst.deep_analysis(ticker, facts)
        if out is None:
            config.missing_key_notice("Anthropic", "ANTHROPIC_API_KEY",
                                      "https://console.anthropic.com")
        else:
            st.markdown(out)
with t3:
    items = news.ticker_news(ticker, 8)
    for n in items:
        st.markdown(f"**[{n['title']}]({n['link']})**")
        st.caption(f"{n['publisher']} · {news.time_ago(n['ts'])}")
    if not items:
        st.info("No recent headlines found.")

config.render_footer()
