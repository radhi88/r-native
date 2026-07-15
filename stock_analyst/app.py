"""Stock Market Analyst — landing page.

Hero + quick market snapshot (S&P 500, Nasdaq 100, Dow, VIX), a 1-month
S&P 500 performance chart, and navigation cards to the six analysis pages.
Educational, descriptive information only — never advice or recommendations.
"""
import pathlib
import re
import sys

import streamlit as st

st.set_page_config(page_title="Stock Market Analyst", page_icon="📈", layout="wide")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[0]))

from lib import charts, config, market_data  # noqa: E402

config.inject_base_style()
config.render_sidebar_brand()

# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------
st.title("📈 Stock Market Analyst")
st.markdown(
    "An educational dashboard for exploring indices, stocks, ETFs, macro data "
    "and portfolios with descriptive analytics — informational only, never "
    "financial advice."
)

# ---------------------------------------------------------------------------
# Quick market snapshot
# ---------------------------------------------------------------------------
SNAPSHOT_TICKERS: tuple[str, ...] = ("^GSPC", "^NDX", "^DJI", "^VIX")

st.subheader("Market snapshot")
quotes = market_data.get_quotes_bulk(SNAPSHOT_TICKERS)
if not quotes:
    st.info("Live quotes are unavailable right now. Please try again shortly.")
else:
    cols = st.columns(len(SNAPSHOT_TICKERS))
    for col, tk in zip(cols, SNAPSHOT_TICKERS):
        q = quotes.get(tk)
        label = market_data.INDEX_TICKERS.get(tk, tk)
        with col:
            if q is None:
                st.metric(label=label, value="—")
            else:
                st.metric(
                    label=label,
                    value=f"{q['price']:,.2f}",
                    delta=f"{q['change_pct']:+.2f}%",
                    delta_color="inverse" if tk == "^VIX" else "normal",
                )

# ---------------------------------------------------------------------------
# S&P 500 — 1 month performance
# ---------------------------------------------------------------------------
st.subheader("S&P 500 — 1M performance")
gspc_hist = market_data.get_history("^GSPC", "1M")
charts.render_price_chart(
    gspc_hist,
    view="Performance",
    height=380,
    title="S&P 500 (^GSPC) — last month, % change",
    key="home_gspc_1m",
)

# ---------------------------------------------------------------------------
# Explore the dashboard — six page cards
# ---------------------------------------------------------------------------
# (number, fallback filename, one-line description). If a numbered page file
# exists on disk its real name wins, so links always match the build output.
PAGE_CARDS: list[tuple[int, str, str]] = [
    (1, "1_📈_Market_Pulse.py",
     "Indices, sector performance and the day's market-moving headlines."),
    (2, "2_🔍_Stock_Analyzer.py",
     "Fundamentals, descriptive technical stats and an AI narrative for any ticker."),
    (3, "3_🧺_ETF_Explorer.py",
     "ETF costs, holdings, peer comparisons and a descriptive risk profile."),
    (4, "4_🏛️_Macro_Monitor.py",
     "FRED economic indicators and the US Treasury yield curve."),
    (5, "5_💼_Portfolio.py",
     "Track your holdings with descriptive performance and risk statistics."),
    (6, "6_📰_News.py",
     "The latest market and single-ticker headlines in one place."),
]


def _discover_numbered_pages() -> dict[int, str]:
    """Map page number -> actual filename found in pages/ (may be empty)."""
    pages_dir = pathlib.Path(__file__).resolve().parent / "pages"
    found: dict[int, str] = {}
    try:
        if pages_dir.is_dir():
            for p in sorted(pages_dir.glob("*.py")):
                m = re.match(r"^(\d+)_", p.name)
                if m:
                    found.setdefault(int(m.group(1)), p.name)
    except OSError:
        pass
    return found


def _split_name(filename: str) -> tuple[str, str]:
    """'1_📈_Market_Pulse.py' -> ('📈', 'Market Pulse')."""
    stem = filename[:-3] if filename.endswith(".py") else filename
    parts = stem.split("_")
    if len(parts) >= 3:
        return parts[1], " ".join(parts[2:])
    if len(parts) == 2:
        return "", parts[1].replace("-", " ")
    return "", stem


st.subheader("Explore the dashboard")
real_pages = _discover_numbered_pages()
rows = [PAGE_CARDS[:3], PAGE_CARDS[3:]]
for row in rows:
    cols = st.columns(3)
    for col, (num, fallback, description) in zip(cols, row):
        filename = real_pages.get(num, fallback)
        emoji, title = _split_name(filename)
        label = f"{emoji} {title}".strip()
        with col:
            with st.container(border=True):
                try:
                    st.page_link(
                        f"pages/{filename}", label=label, use_container_width=True
                    )
                except Exception:
                    st.markdown(f"**{label}**")
                st.caption(description)

# ---------------------------------------------------------------------------
config.render_footer()
