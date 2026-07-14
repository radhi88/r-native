"""
market_sentiment.py — Crypto sentiment from public APIs (no auth needed).

Sources:
  • CoinGecko  — BTC/ETH price, community sentiment votes
  • Alternative.me — Fear & Greed Index (0=extreme fear, 100=extreme greed)
  • Binance     — BTC funding rate (positive=longs dominant, negative=shorts)

Note: Polymarket requires Cloudflare bypass — use these reliable alternatives instead.
"""

import json
import logging
import time
import urllib.request

log = logging.getLogger("friday.sentiment")

_TIMEOUT   = 8
_CACHE_TTL = 60   # cache 60 seconds

_cache: dict    = {}
_cache_ts: float = 0.0


def _get(url: str) -> dict | list | None:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept":     "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        log.warning("sentiment fetch failed %s: %s", url[-50:], exc)
        return None


def get_btc_markets(force: bool = False) -> dict:
    """Aggregate crypto sentiment from CoinGecko + Fear&Greed + Binance funding."""
    global _cache, _cache_ts
    now = time.time()
    if not force and _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    result: dict = {
        "markets":       [],
        "count":         0,
        "btc_sentiment": {"signal": "NEUTRAL", "bull_pct": None, "bear_pct": None},
        "fetched_at":    now,
        "note":          "Data from CoinGecko + Fear&Greed Index + Binance",
    }

    # ── 1. Fear & Greed Index ──────────────────────────────────────────────────
    fg = _get("https://api.alternative.me/fng/?limit=3")
    fg_val  = None
    fg_label = "NEUTRAL"
    fg_history = []
    if fg and fg.get("data"):
        for item in fg["data"]:
            v = int(item.get("value", 50))
            fg_history.append({"value": v, "label": item.get("value_classification", "")})
        fg_val   = fg_history[0]["value"]
        fg_label = fg_history[0]["label"]

    # ── 2. CoinGecko BTC community sentiment ──────────────────────────────────
    cg = _get(
        "https://api.coingecko.com/api/v3/coins/bitcoin"
        "?localization=false&tickers=false&community_data=true&developer_data=false"
    )
    bull_pct = bear_pct = None
    btc_price = btc_change_24h = None
    if cg:
        bull_pct       = cg.get("sentiment_votes_up_percentage")
        bear_pct       = cg.get("sentiment_votes_down_percentage")
        md             = cg.get("market_data", {})
        btc_price      = md.get("current_price", {}).get("usd")
        btc_change_24h = md.get("price_change_percentage_24h")

    # ── 3. CoinGecko global market ─────────────────────────────────────────────
    gl = _get("https://api.coingecko.com/api/v3/global")
    btc_dom = mc_change = None
    if gl:
        data    = gl.get("data", {})
        btc_dom = data.get("market_cap_percentage", {}).get("btc")
        mc_change = data.get("market_cap_change_percentage_24h_usd")

    # ── 4. Binance BTC funding rate (perps) ────────────────────────────────────
    bf = _get("https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1")
    funding_rate = None
    if bf and isinstance(bf, list) and bf:
        try:
            funding_rate = round(float(bf[0].get("fundingRate", 0)) * 100, 4)
        except Exception:
            pass

    # ── Compute combined signal ────────────────────────────────────────────────
    scores = []
    if bull_pct is not None:
        scores.append(bull_pct - 50)           # +ve = bull
    if fg_val is not None:
        scores.append((fg_val - 50) * 0.8)    # fear&greed weighted
    if funding_rate is not None:
        scores.append(funding_rate * 200)      # longs paying = bull

    composite = sum(scores) / len(scores) if scores else 0
    signal = "BULL" if composite > 5 else "BEAR" if composite < -5 else "NEUTRAL"

    # ── Build markets list (synthetic "markets" for the UI) ───────────────────
    markets = []
    if btc_price:
        markets.append({
            "question":   f"BTC Price ${btc_price:,.0f} — 24h: {btc_change_24h:+.2f}%" if btc_change_24h else f"BTC ${btc_price:,.0f}",
            "volume_usd": 0,
            "outcomes": [
                {"outcome": "Community Bull", "probability_pct": round(bull_pct, 1) if bull_pct else None},
                {"outcome": "Community Bear", "probability_pct": round(bear_pct, 1) if bear_pct else None},
            ],
        })
    if fg_val is not None:
        markets.append({
            "question":   f"Fear & Greed Index: {fg_val}/100 — {fg_label}",
            "volume_usd": 0,
            "outcomes":   [{"outcome": fg_label, "probability_pct": fg_val}],
        })
    if btc_dom:
        markets.append({
            "question":   f"BTC Dominance: {btc_dom:.1f}%",
            "volume_usd": 0,
            "outcomes":   [{"outcome": "Dominance", "probability_pct": round(btc_dom, 1)}],
        })
    if funding_rate is not None:
        lbl = "Longs paying" if funding_rate > 0 else "Shorts paying"
        markets.append({
            "question":   f"Binance Funding Rate: {funding_rate:+.4f}%",
            "volume_usd": 0,
            "outcomes":   [{"outcome": lbl, "probability_pct": None}],
        })
    if fg_history:
        for item in fg_history[1:]:
            markets.append({
                "question":   f"F&G History: {item['value']}/100 — {item['label']}",
                "volume_usd": 0,
                "outcomes":   [{"outcome": item["label"], "probability_pct": item["value"]}],
            })

    result.update({
        "markets": markets,
        "count":   len(markets),
        "btc_sentiment": {
            "signal":        signal,
            "bull_pct":      round(bull_pct, 1) if bull_pct else None,
            "bear_pct":      round(bear_pct, 1) if bear_pct else None,
            "fear_greed":    fg_val,
            "fear_label":    fg_label,
            "btc_price":     btc_price,
            "btc_dom":       round(btc_dom, 2) if btc_dom else None,
            "funding_rate":  funding_rate,
            "composite":     round(composite, 2),
            "markets_used":  len(scores),
        },
        "note": "CoinGecko + Fear&Greed Index + Binance Funding Rate",
    })

    _cache    = result
    _cache_ts = now
    return result
