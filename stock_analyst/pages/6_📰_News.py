"""News — aggregated market headlines + by-ticker search."""
import streamlit as st

st.set_page_config(page_title="News", page_icon="📰", layout="wide")

import sys, pathlib  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from lib import config, news  # noqa: E402

config.inject_base_style()
config.render_sidebar_brand()
st.title("📰 News")


def _rows(items: list[dict]) -> None:
    if not items:
        st.info("No headlines found.")
        return
    for n in items:
        st.markdown(f"**[{n['title']}]({n['link']})**")
        st.caption(f"{n['publisher']} · {news.time_ago(n['ts'])}")
        if n.get("summary"):
            st.write(n["summary"][:260] + ("…" if len(n["summary"]) > 260 else ""))
        st.write("")


t1, t2 = st.tabs(["Market headlines", "Search by ticker"])
with t1:
    _rows(news.market_news(15))
with t2:
    tk = st.text_input("Ticker", "AAPL").upper().strip()
    if tk:
        _rows(news.ticker_news(tk, 10))

config.render_footer()
