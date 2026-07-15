"""News layer — yfinance primary, Yahoo RSS fallback. Never raises to callers.

Public API (stable — pages code against these):
  ticker_news(ticker, limit=10) -> list[dict]
  market_news(limit=10) -> list[dict]     (aggregates major index/ETF headlines)
  time_ago(ts) -> str                     ("3h ago" style label)

Each news item dict has exactly these keys:
  {title: str, publisher: str, link: str, ts: int unix epoch, summary: str}
Missing source fields degrade to sensible defaults ("" / 0 / "Yahoo Finance").
"""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests
import streamlit as st
import yfinance as yf

# Broad-market sources aggregated by market_news().
_MARKET_TICKERS: tuple[str, ...] = ("^GSPC", "^NDX", "^DJI", "SPY", "QQQ")

_RSS_URL = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline"
    "?s={ticker}&region=US&lang=en-US"
)

_TAG_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------- helpers ---

def _clean_text(value) -> str:
    """Strip HTML tags/entities and collapse whitespace. Safe on any input."""
    if value is None:
        return ""
    text = _TAG_RE.sub(" ", str(value))
    text = html.unescape(text)
    return " ".join(text.split())


def _iso_to_epoch(value) -> int:
    """ISO-8601 string (or numeric epoch) -> unix epoch int; 0 on failure."""
    if value in (None, ""):
        return 0
    try:
        if isinstance(value, (int, float)):
            return int(value)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0


def _parse_yf_item(item) -> dict | None:
    """Normalize one yfinance news entry (new nested or legacy flat format)."""
    if not isinstance(item, dict):
        return None
    content = item.get("content")
    if not isinstance(content, dict):
        content = item  # legacy flat format

    title = _clean_text(content.get("title") or item.get("title"))
    if not title:
        return None

    publisher = ""
    provider = content.get("provider")
    if isinstance(provider, dict):
        publisher = _clean_text(provider.get("displayName"))
    if not publisher:
        publisher = _clean_text(content.get("publisher") or item.get("publisher"))

    link = ""
    for key in ("canonicalUrl", "clickThroughUrl"):
        url_obj = content.get(key)
        if isinstance(url_obj, dict) and url_obj.get("url"):
            link = str(url_obj["url"])
            break
    if not link:
        link = str(content.get("link") or item.get("link") or "")

    ts = _iso_to_epoch(content.get("pubDate") or content.get("displayTime"))
    if not ts:
        raw = content.get("providerPublishTime") or item.get("providerPublishTime")
        try:
            ts = int(raw) if raw else 0
        except (TypeError, ValueError):
            ts = 0

    summary = _clean_text(content.get("summary") or content.get("description"))

    return {
        "title": title,
        "publisher": publisher or "Yahoo Finance",
        "link": link,
        "ts": ts,
        "summary": summary,
    }


def _rss_news(ticker: str, limit: int) -> list[dict]:
    """Fallback: Yahoo Finance RSS headline feed, parsed with xml.etree."""
    url = _RSS_URL.format(ticker=quote(str(ticker), safe=""))
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        return []
    items: list[dict] = []
    for node in root.findall(".//item"):
        title = _clean_text(node.findtext("title"))
        if not title:
            continue
        ts = 0
        pub = (node.findtext("pubDate") or "").strip()
        if pub:
            try:
                ts = int(parsedate_to_datetime(pub).timestamp())
            except Exception:
                ts = 0
        items.append({
            "title": title,
            "publisher": "Yahoo Finance",
            "link": (node.findtext("link") or "").strip(),
            "ts": ts,
            "summary": _clean_text(node.findtext("description")),
        })
        if len(items) >= limit:
            break
    return items


# ------------------------------------------------------------- public API ---

@st.cache_data(ttl=300, show_spinner=False)
def ticker_news(ticker: str, limit: int = 10) -> list[dict]:
    """Headlines for one ticker, newest first. Empty list on total failure."""
    limit = max(0, int(limit))
    if not ticker or limit == 0:
        return []
    items: list[dict] = []
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:
        raw = []
    for entry in raw:
        parsed = _parse_yf_item(entry)
        if parsed:
            items.append(parsed)
    if not items:  # yfinance empty or failed -> RSS fallback
        items = _rss_news(ticker, limit)
    items.sort(key=lambda d: d["ts"], reverse=True)
    return items[:limit]


@st.cache_data(ttl=300, show_spinner=False)
def market_news(limit: int = 10) -> list[dict]:
    """Broad-market headlines aggregated across major indices and ETFs.

    Deduped by normalized title, sorted newest first, capped at `limit`.
    """
    limit = max(0, int(limit))
    if limit == 0:
        return []
    seen: set[str] = set()
    merged: list[dict] = []
    for tk in _MARKET_TICKERS:
        for item in ticker_news(tk, limit=limit):
            key = item["title"].strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(item)
    merged.sort(key=lambda d: d["ts"], reverse=True)
    return merged[:limit]


def time_ago(ts) -> str:
    """Unix epoch -> compact relative label ("3h ago"). "" for missing/bad ts."""
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    delta = max(0, int(time.time()) - ts)
    if delta < 60:
        return "just now"
    minutes = delta // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    return f"{max(1, days // 365)}y ago"
