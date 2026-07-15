"""Shared configuration: disclosure, branding, base styling.

Every page MUST call render_sidebar_brand() near the top and render_footer()
at the bottom. Keys are loaded from .env at import time (python-dotenv).
"""
from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # reads ANTHROPIC_API_KEY / FRED_API_KEY from project-root .env

APP_NAME = "Stock Market Analyst"

DISCLOSURE = (
    "This dashboard is for educational and informational purposes only. "
    "It is not financial advice, not a recommendation to buy or sell any security, "
    "and is not personalized to your situation. Consult a licensed advisor before "
    "making investment decisions."
)

_BASE_CSS = """
<style>
  .block-container p, .block-container li, .block-container label { font-size: 17px; }
  .block-container { padding-top: 2.2rem; }
</style>
"""


def anthropic_key() -> str | None:
    """Return the Anthropic API key or None. Never print or display the key."""
    return os.getenv("ANTHROPIC_API_KEY") or None


def fred_key() -> str | None:
    """Return the FRED API key or None. Never print or display the key."""
    return os.getenv("FRED_API_KEY") or None


def inject_base_style() -> None:
    """Larger base font for accessibility (17px on main content)."""
    st.markdown(_BASE_CSS, unsafe_allow_html=True)


def render_sidebar_brand() -> None:
    """'📈 Market Analyst' branding shown on every page's sidebar."""
    st.sidebar.markdown("## 📈 Market Analyst")
    st.sidebar.caption("Personal research · educational use only")


def render_footer() -> None:
    """Mandatory compliance footer for every page."""
    st.divider()
    st.caption(DISCLOSURE)


def missing_key_notice(service: str, env_var: str, url: str) -> None:
    """Friendly in-page message when an API key is absent (never crash)."""
    st.info(
        f"**{service} key not configured.** Add `{env_var}` to the `.env` file in the "
        f"project root to enable this section. Get a free key at {url}."
    )
