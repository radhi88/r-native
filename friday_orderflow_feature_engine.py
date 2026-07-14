"""
FRIDAY Order Flow Intelligence Engine
Covers: PHASE 2 (Volume Profile), PHASE 3 (Delta/CVD), PHASE 4 (Absorption/Exhaustion),
         PHASE 5 (Footprint-style), PHASE 6 (Event Detection)

NOTE: All volume data is MT5 tick_volume (proxy), not exchange true bid/ask tape.
All delta/CVD/footprint values are PROXIES derived from OHLC + tick_volume.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5
import pandas as pd

from friday_symbol_universe import resolve_symbols


ROOT = Path(r"C:\Users\Radhi\MT5")
ORDERFLOW_STATE_FILE = ROOT / "friday_orderflow_state.json"
ORDERFLOW_EVENTS_FILE = ROOT / "friday_orderflow_events.json"
FEATURE_COUNCIL_FILE = ROOT / "friday_feature_council_state.json"
FVG_STATE_FILE = ROOT / "friday_fvg_state.json"

FVG_SCAN_BARS = 80     # how many bars to scan for active FVG zones
FVG_MAX_AGE_BARS = 50  # discard FVGs older than this

TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
}

DEMO_KEYWORDS = ["demo", "trial", "practice", "contest"]

# Volume profile: number of price buckets
VP_BUCKETS = 50
# Value area coverage (70% of total volume)
VALUE_AREA_PCT = 0.70
# Bars used for volume profile (session prefers today, fallback 200)
VP_LOOKBACK = 200
# Bars used for delta/CVD
DELTA_LOOKBACK = 100


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_mt5() -> None:
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")


def ensure_demo() -> None:
    ensure_mt5()
    acc = mt5.account_info()
    if acc is None:
        raise RuntimeError("No MT5 account info")
    server = str(getattr(acc, "server", "") or "")
    trade_mode = getattr(acc, "trade_mode", None)
    demo_const = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
    demo_by_mode = demo_const is not None and trade_mode == demo_const
    demo_by_server = any(k in server.lower() for k in DEMO_KEYWORDS)
    if not (demo_by_mode or demo_by_server):
        raise RuntimeError(f"BLOCKED: not demo account. server={server}")


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_json_atomic(path: Path, data: Any) -> None:
    """Write JSON atomically via temp file; retries on Windows file-lock errors."""
    import time as _t
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(str(tmp), str(path))
            return
        except OSError:
            if attempt == 4:
                # Last resort: direct write (no atomicity, but better than failing)
                try:
                    path.write_text(text, encoding="utf-8")
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
                return
            _t.sleep(0.05 * (attempt + 1))


def rates_df(symbol: str, timeframe: str, bars: int = VP_LOOKBACK) -> pd.DataFrame:
    if timeframe not in TIMEFRAMES:
        timeframe = "M1"
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Cannot select {symbol}")
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[timeframe], 0, bars)
    if rates is None or len(rates) < 20:
        raise RuntimeError(f"Not enough rates for {symbol} {timeframe}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def session_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Return bars from current session (today), with fallback to last 100."""
    today = pd.Timestamp.now().normalize()
    sb = df[df["time"] >= today]
    return sb if len(sb) >= 10 else df.tail(100)


# ---------------------------------------------------------------------------
# PHASE 2 — Volume Profile Proxy
# ---------------------------------------------------------------------------

def compute_volume_profile(df: pd.DataFrame, symbol: str) -> dict[str, Any]:
    """
    Build a tick-volume based price profile.
    Returns POC, VAH, VAL, HVN, LVN, clusters, distance_to_poc, price_location.
    NOTE: tick_volume is a proxy for exchange volume. Results are indicative.
    """
    sb = session_bars(df)
    close = float(sb["close"].iloc[-1])

    high_all = float(sb["high"].max())
    low_all = float(sb["low"].min())
    price_range = high_all - low_all

    if price_range < 1e-9:
        return _empty_vp(close)

    bucket_size = price_range / VP_BUCKETS
    buckets: list[dict[str, Any]] = []

    for i in range(VP_BUCKETS):
        lo = low_all + i * bucket_size
        hi = lo + bucket_size
        mid = (lo + hi) / 2.0
        buckets.append({"lo": lo, "hi": hi, "mid": mid, "vol": 0.0})

    # Distribute each bar's volume across touched price buckets
    for row in sb.itertuples():
        bar_vol = float(row.tick_volume) if row.tick_volume > 0 else 1.0
        bar_high = float(row.high)
        bar_low = float(row.low)
        bar_range = max(bar_high - bar_low, 1e-9)

        for b in buckets:
            overlap_lo = max(b["lo"], bar_low)
            overlap_hi = min(b["hi"], bar_high)
            if overlap_hi > overlap_lo:
                fraction = (overlap_hi - overlap_lo) / bar_range
                b["vol"] += bar_vol * fraction

    total_vol = sum(b["vol"] for b in buckets) or 1.0

    # POC — highest volume bucket
    poc_bucket = max(buckets, key=lambda b: b["vol"])
    poc = poc_bucket["mid"]

    # Value Area: expand from POC outward until VALUE_AREA_PCT is covered
    sorted_by_vol = sorted(buckets, key=lambda b: b["vol"], reverse=True)
    va_vol = 0.0
    va_buckets = []
    for b in sorted_by_vol:
        va_buckets.append(b)
        va_vol += b["vol"]
        if va_vol >= total_vol * VALUE_AREA_PCT:
            break

    va_lows = [b["lo"] for b in va_buckets]
    va_highs = [b["hi"] for b in va_buckets]
    val = min(va_lows) if va_lows else low_all
    vah = max(va_highs) if va_highs else high_all

    # HVN: buckets above 150% of average volume
    avg_vol = total_vol / VP_BUCKETS
    hvn = [round(b["mid"], 5) for b in buckets if b["vol"] > avg_vol * 1.5]
    lvn = [round(b["mid"], 5) for b in buckets if b["vol"] < avg_vol * 0.4]

    # Volume clusters: top 5 buckets
    clusters = sorted(
        [{"price": round(b["mid"], 5), "vol": round(b["vol"], 1)} for b in buckets],
        key=lambda x: x["vol"],
        reverse=True,
    )[:5]

    # price_location_vs_value_area
    if close > vah:
        price_location = "ABOVE_VALUE"
    elif close < val:
        price_location = "BELOW_VALUE"
    else:
        price_location = "INSIDE_VALUE"

    info = mt5.symbol_info(symbol)
    point = float(info.point or 0.01) if info else 0.01
    distance_to_poc = round((close - poc) / point, 1)

    return {
        "poc": round(poc, 5),
        "vah": round(vah, 5),
        "val": round(val, 5),
        "hvn": hvn[:8],
        "lvn": lvn[:8],
        "volume_clusters": clusters,
        "low_volume_rejection_zones": lvn[:4],
        "distance_to_poc_points": distance_to_poc,
        "price_location_vs_value_area": price_location,
        "total_vol": round(total_vol, 1),
        "session_bars_used": len(sb),
        "note": "tick_volume proxy — not exchange volume",
    }


def _empty_vp(close: float) -> dict[str, Any]:
    return {
        "poc": close, "vah": close, "val": close,
        "hvn": [], "lvn": [], "volume_clusters": [],
        "low_volume_rejection_zones": [], "distance_to_poc_points": 0.0,
        "price_location_vs_value_area": "INSIDE_VALUE",
        "total_vol": 0.0, "session_bars_used": 0,
        "note": "tick_volume proxy — insufficient data",
    }


# ---------------------------------------------------------------------------
# PHASE 3 — Delta Proxy + CVD Proxy + Flow Pressure
# ---------------------------------------------------------------------------

def compute_delta_features(df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute bar delta proxies, cumulative delta, session delta, divergences.
    All values are PROXIES derived from OHLC + tick_volume.
    """
    sb = session_bars(df)
    d = df.tail(DELTA_LOOKBACK).copy()

    bar_range = (d["high"] - d["low"]).astype(float).replace(0, 1e-9)
    body = (d["close"] - d["open"]).astype(float)
    vol = d["tick_volume"].astype(float).replace(0, 1.0)

    # Estimated buy/sell volume per bar using close position in range
    buy_frac = ((d["close"].astype(float) - d["low"].astype(float)) / bar_range).clip(0, 1)
    sell_frac = 1.0 - buy_frac
    buy_vol = buy_frac * vol
    sell_vol = sell_frac * vol

    bar_delta = buy_vol - sell_vol
    cum_delta = bar_delta.cumsum()

    # Session delta
    sb_idx = sb.index
    session_delta_val = float(bar_delta.loc[bar_delta.index.isin(sb_idx)].sum()) if len(sb_idx) > 0 else float(bar_delta.iloc[-20:].sum())

    # Body efficiency: |body| / range
    body_efficiency = (body.abs() / bar_range).iloc[-1]

    # Wick absorption score: large lower wick + high vol = potential buy absorption
    last_bar = d.iloc[-1]
    last_high = float(last_bar["high"])
    last_low = float(last_bar["low"])
    last_open = float(last_bar["open"])
    last_close = float(last_bar["close"])
    last_range = max(last_high - last_low, 1e-9)
    lower_wick = min(last_open, last_close) - last_low
    upper_wick = last_high - max(last_open, last_close)
    wick_absorption_score = round(float(lower_wick / last_range), 4)

    # Volume spike score: last bar vs rolling 20-bar average
    avg_vol_20 = float(vol.iloc[-21:-1].mean()) or 1.0
    volume_spike_score = round(float(vol.iloc[-1] / avg_vol_20), 3)

    # Spread pressure: use spread from council state if available (approximate 0 here)
    spread_pressure_score = 0.0  # filled externally if spread data passed

    # Delta divergence detection (last 20 bars)
    closes_20 = d["close"].astype(float).tail(20)
    delta_20 = bar_delta.tail(20)

    price_ll = closes_20.iloc[-1] < closes_20.min() * 1.0001  # near recent low
    price_hh = closes_20.iloc[-1] > closes_20.max() * 0.9999  # near recent high
    delta_improving = float(delta_20.iloc[-3:].mean()) > float(delta_20.iloc[-10:-3].mean())
    delta_weakening = float(delta_20.iloc[-3:].mean()) < float(delta_20.iloc[-10:-3].mean())

    if price_ll and delta_improving:
        delta_divergence = "BULLISH_DIVERGENCE"
    elif price_hh and delta_weakening:
        delta_divergence = "BEARISH_DIVERGENCE"
    else:
        delta_divergence = "NONE"

    return {
        "bar_delta_proxy": round(float(bar_delta.iloc[-1]), 2),
        "cumulative_delta_proxy": round(float(cum_delta.iloc[-1]), 2),
        "session_delta_proxy": round(session_delta_val, 2),
        "delta_divergence": delta_divergence,
        "buy_pressure": round(float(buy_vol.iloc[-1]), 2),
        "sell_pressure": round(float(sell_vol.iloc[-1]), 2),
        "body_efficiency": round(float(body_efficiency), 4),
        "wick_absorption_score": wick_absorption_score,
        "volume_spike_score": volume_spike_score,
        "spread_pressure_score": spread_pressure_score,
        "note": "proxy from OHLC+tick_volume — not true bid/ask tape",
    }


# ---------------------------------------------------------------------------
# PHASE 4 — Absorption / Exhaustion / Unfinished Auction
# ---------------------------------------------------------------------------

def compute_absorption_exhaustion(df: pd.DataFrame) -> dict[str, Any]:
    """
    Detect absorption, exhaustion, and unfinished auction proxy signals.
    Uses OHLC + tick_volume only (no DOM/tape available).
    """
    d = df.tail(30).copy()
    bar_range = (d["high"] - d["low"]).astype(float).replace(0, 1e-9)
    vol = d["tick_volume"].astype(float).replace(0, 1.0)
    avg_vol = float(vol.iloc[:-1].mean()) or 1.0

    last = d.iloc[-1]
    prev = d.iloc[-2]

    last_o = float(last["open"])
    last_c = float(last["close"])
    last_h = float(last["high"])
    last_l = float(last["low"])
    last_v = float(last["tick_volume"])
    last_range = max(last_h - last_l, 1e-9)

    lower_wick = min(last_o, last_c) - last_l
    upper_wick = last_h - max(last_o, last_c)
    body_size = abs(last_c - last_o)

    is_vol_spike = last_v > avg_vol * 1.4

    # Absorption BUY: large lower wick, high volume, close in upper half
    buy_close_pos = (last_c - last_l) / last_range
    sell_close_pos = (last_h - last_c) / last_range

    absorption_buy = (
        lower_wick / last_range > 0.45
        and is_vol_spike
        and buy_close_pos > 0.55
    )

    absorption_sell = (
        upper_wick / last_range > 0.45
        and is_vol_spike
        and sell_close_pos > 0.55
    )

    # Exhaustion: spike vol + small body (rejected move)
    exhaustion_buy = (
        last_c > last_o
        and body_size / last_range < 0.30
        and is_vol_spike
        and upper_wick / last_range > 0.40
    )

    exhaustion_sell = (
        last_c < last_o
        and body_size / last_range < 0.30
        and is_vol_spike
        and lower_wick / last_range > 0.40
    )

    # Unfinished auction proxy: prior session high/low not reached by current bar
    recent_high = float(d["high"].iloc[-10:-1].max())
    recent_low = float(d["low"].iloc[-10:-1].min())
    current_high = float(d["high"].iloc[-1])
    current_low = float(d["low"].iloc[-1])

    unfinished_auction_high = recent_high > current_high * 1.0002
    unfinished_auction_low = recent_low < current_low * 0.9998

    # Aggressive burst: 3+ consecutive same-direction bars with rising volume
    closes = d["close"].astype(float)
    vols = d["tick_volume"].astype(float)

    def check_burst(n: int = 3) -> tuple[bool, bool]:
        if len(d) < n + 1:
            return False, False
        tail_c = closes.iloc[-(n + 1):]
        tail_v = vols.iloc[-(n + 1):]
        all_up = all(tail_c.iloc[i + 1] > tail_c.iloc[i] for i in range(n))
        all_dn = all(tail_c.iloc[i + 1] < tail_c.iloc[i] for i in range(n))
        vol_rising = all(tail_v.iloc[i + 1] >= tail_v.iloc[i] * 0.85 for i in range(n))
        return (all_up and vol_rising), (all_dn and vol_rising)

    agg_buy, agg_sell = check_burst(3)

    return {
        "absorption_buy": absorption_buy,
        "absorption_sell": absorption_sell,
        "exhaustion_buy": exhaustion_buy,
        "exhaustion_sell": exhaustion_sell,
        "unfinished_auction_high_proxy": unfinished_auction_high,
        "unfinished_auction_low_proxy": unfinished_auction_low,
        "aggressive_buy_burst": agg_buy,
        "aggressive_sell_burst": agg_sell,
        "note": "OHLC+tick_volume proxy — no DOM or tape",
    }


# ---------------------------------------------------------------------------
# PHASE 5 — Footprint-style Visualization Data
# ---------------------------------------------------------------------------

def compute_footprint(df: pd.DataFrame, n_candles: int = 10, buckets_per_bar: int = 8) -> dict[str, Any]:
    """
    Build compact footprint-like data for the last n_candles.
    Returns: latest_footprint, footprint_rows, imbalance_rows
    NOTE: All volumes are tick_volume proxies split by close position.
    """
    d = df.tail(n_candles + 1).copy()
    if len(d) < 2:
        return {"latest_footprint": {}, "footprint_rows": [], "imbalance_rows": []}

    footprint_rows = []
    imbalance_rows = []

    for row in d.iloc[:-1].itertuples():
        bar_h = float(row.high)
        bar_l = float(row.low)
        bar_o = float(row.open)
        bar_c = float(row.close)
        bar_v = float(row.tick_volume) if row.tick_volume > 0 else 1.0
        bar_range = max(bar_h - bar_l, 1e-9)

        buy_frac = max(0.0, min(1.0, (bar_c - bar_l) / bar_range))
        sell_frac = 1.0 - buy_frac
        total_buy = bar_v * buy_frac
        total_sell = bar_v * sell_frac

        bucket_size = bar_range / buckets_per_bar
        price_levels = []

        for i in range(buckets_per_bar):
            lo = bar_l + i * bucket_size
            hi = lo + bucket_size
            mid = (lo + hi) / 2.0
            bucket_buy = total_buy / buckets_per_bar
            bucket_sell = total_sell / buckets_per_bar
            # Use safe epsilon and clamp imbalance to [0.01, 100]
            safe_sell = max(bucket_sell, 1e-3)
            safe_buy = max(bucket_buy, 1e-3)
            imb = round(min(100.0, max(0.01, safe_buy / safe_sell)), 2)
            price_levels.append({
                "price": round(mid, 5),
                "buy_vol": round(bucket_buy, 1),
                "sell_vol": round(bucket_sell, 1),
                "imbalance": imb,
            })

        bar_delta = total_buy - total_sell
        dominant = "BUY" if bar_delta > 0 else ("SELL" if bar_delta < 0 else "BALANCED")

        bar_info = {
            "time": int(row.time.timestamp()) if hasattr(row.time, "timestamp") else 0,
            "open": bar_o,
            "high": bar_h,
            "low": bar_l,
            "close": bar_c,
            "buy_vol": round(total_buy, 1),
            "sell_vol": round(total_sell, 1),
            "delta": round(bar_delta, 1),
            "dominant_side": dominant,
            "price_levels": price_levels,
            "absorption_marker": buy_frac > 0.75 and bar_v > 1.3,
            "exhaustion_marker": abs(bar_c - bar_o) / bar_range < 0.25 and bar_v > 1.2,
        }
        footprint_rows.append(bar_info)

        max_imb = max(price_levels, key=lambda x: abs(x["imbalance"] - 1.0), default=None)
        if max_imb and abs(max_imb["imbalance"] - 1.0) > 0.5:
            imbalance_rows.append({
                "time": bar_info["time"],
                "price": max_imb["price"],
                "imbalance": max_imb["imbalance"],
                "side": "BUY" if max_imb["imbalance"] > 1 else "SELL",
            })

    latest = footprint_rows[-1] if footprint_rows else {}

    return {
        "latest_footprint": latest,
        "footprint_rows": footprint_rows[-n_candles:],
        "imbalance_rows": imbalance_rows[-10:],
    }


# ---------------------------------------------------------------------------
# PHASE 6 — Order Flow Trade Event Detector
# ---------------------------------------------------------------------------

def detect_orderflow_events(
    symbol: str,
    timeframe: str,
    vp: dict[str, Any],
    delta: dict[str, Any],
    absorption: dict[str, Any],
    vwap_summary: dict[str, Any],
    close: float,
) -> list[dict[str, Any]]:
    """
    Detect significant order flow events for the given symbol/timeframe.
    Returns list of event dicts.
    """
    events: list[dict[str, Any]] = []
    ts = now()

    def evt(event_type: str, side: str, confidence: float, reason: str, related: list[str]) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "event_type": event_type,
            "side": side,
            "confidence": round(confidence, 3),
            "price": close,
            "reason": reason,
            "related_features": related,
            "created_at": ts,
        }

    poc = vp.get("poc", close)
    vah = vp.get("vah", close)
    val = vp.get("val", close)
    loc = vp.get("price_location_vs_value_area", "INSIDE_VALUE")
    dist_poc = abs(vp.get("distance_to_poc_points", 0.0))

    bar_delta = delta.get("bar_delta_proxy", 0.0)
    cum_delta = delta.get("cumulative_delta_proxy", 0.0)
    vol_spike = delta.get("volume_spike_score", 1.0)
    divergence = delta.get("delta_divergence", "NONE")
    abs_buy = absorption.get("absorption_buy", False)
    abs_sell = absorption.get("absorption_sell", False)
    exh_buy = absorption.get("exhaustion_buy", False)
    exh_sell = absorption.get("exhaustion_sell", False)
    agg_buy = absorption.get("aggressive_buy_burst", False)
    agg_sell = absorption.get("aggressive_sell_burst", False)

    v_signal = vwap_summary.get("vwap_signal", "") if vwap_summary else ""
    sess_vwap = vwap_summary.get("session_vwap", close) if vwap_summary else close

    # --- Event detection logic ---

    if vol_spike > 2.0 and bar_delta > 0:
        events.append(evt("big_buy_burst", "BUY", min(0.9, 0.5 + vol_spike * 0.1),
                          f"Volume spike {vol_spike:.1f}x with positive delta",
                          ["volume_spike_score", "bar_delta_proxy"]))

    if vol_spike > 2.0 and bar_delta < 0:
        events.append(evt("big_sell_burst", "SELL", min(0.9, 0.5 + vol_spike * 0.1),
                          f"Volume spike {vol_spike:.1f}x with negative delta",
                          ["volume_spike_score", "bar_delta_proxy"]))

    if abs_buy and close <= val * 1.002:
        events.append(evt("absorption_at_support", "BUY", 0.75,
                          f"Buy absorption at val={val:.5f}",
                          ["absorption_buy", "val"]))

    if abs_sell and close >= vah * 0.998:
        events.append(evt("absorption_at_resistance", "SELL", 0.75,
                          f"Sell absorption at vah={vah:.5f}",
                          ["absorption_sell", "vah"]))

    if exh_buy:
        events.append(evt("exhaustion_after_push", "SELL", 0.65,
                          "Buy exhaustion: spike vol + small body + large upper wick",
                          ["exhaustion_buy", "volume_spike_score"]))

    if exh_sell:
        events.append(evt("exhaustion_after_push", "BUY", 0.65,
                          "Sell exhaustion: spike vol + small body + large lower wick",
                          ["exhaustion_sell", "volume_spike_score"]))

    if divergence == "BULLISH_DIVERGENCE":
        events.append(evt("delta_divergence_reversal", "BUY", 0.70,
                          "Price lower low but delta improving — bullish divergence",
                          ["delta_divergence", "cumulative_delta_proxy"]))

    if divergence == "BEARISH_DIVERGENCE":
        events.append(evt("delta_divergence_reversal", "SELL", 0.70,
                          "Price higher high but delta weakening — bearish divergence",
                          ["delta_divergence", "cumulative_delta_proxy"]))

    if v_signal == "VWAP_RECLAIM":
        events.append(evt("vwap_reclaim", "BUY", 0.72,
                          f"Price reclaimed session VWAP={sess_vwap:.5f}",
                          ["vwap_signal", "session_vwap"]))

    if v_signal == "VWAP_REJECTION":
        events.append(evt("vwap_rejection", "SELL", 0.72,
                          f"Price rejected at session VWAP={sess_vwap:.5f}",
                          ["vwap_signal", "session_vwap"]))

    if dist_poc < 5 and abs_sell:
        events.append(evt("POC_rejection", "SELL", 0.68,
                          f"Sell absorption near POC={poc:.5f}",
                          ["poc", "absorption_sell"]))

    if dist_poc < 5 and abs_buy:
        events.append(evt("POC_rejection", "BUY", 0.68,
                          f"Buy absorption near POC={poc:.5f}",
                          ["poc", "absorption_buy"]))

    # value_area_breakout: price is outside value area with confirming CVD
    if loc == "ABOVE_VALUE" and cum_delta > 0:
        events.append(evt("value_area_breakout", "BUY", 0.65,
                          f"Price above VAH={vah:.5f} with positive CVD",
                          ["vah", "price_location_vs_value_area", "cumulative_delta_proxy"]))

    if loc == "BELOW_VALUE" and cum_delta < 0:
        events.append(evt("value_area_breakout", "SELL", 0.65,
                          f"Price below VAL={val:.5f} with negative CVD",
                          ["val", "price_location_vs_value_area", "cumulative_delta_proxy"]))

    # value_area_reversion: price is inside VA but near its edges (returning from outside)
    if loc == "INSIDE_VALUE" and vah > val:
        near_vah = close >= vah - (vah - val) * 0.10
        near_val = close <= val + (vah - val) * 0.10
        if near_vah and cum_delta < 0:
            events.append(evt("value_area_reversion", "SELL", 0.60,
                              f"Price near VAH={vah:.5f} returning inside VA",
                              ["vah", "price_location_vs_value_area"]))
        if near_val and cum_delta > 0:
            events.append(evt("value_area_reversion", "BUY", 0.60,
                              f"Price near VAL={val:.5f} returning inside VA",
                              ["val", "price_location_vs_value_area"]))

    if agg_buy and vol_spike > 1.5:
        events.append(evt("big_buy_burst", "BUY", 0.70,
                          "3+ consecutive bullish bars with rising volume",
                          ["aggressive_buy_burst", "volume_spike_score"]))

    if agg_sell and vol_spike > 1.5:
        events.append(evt("big_sell_burst", "SELL", 0.70,
                          "3+ consecutive bearish bars with rising volume",
                          ["aggressive_sell_burst", "volume_spike_score"]))

    return events


# ---------------------------------------------------------------------------
# Master compute function for one symbol + timeframe
# ---------------------------------------------------------------------------

def compute_orderflow(symbol: str, timeframe: str, vwap_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute all order flow features for a symbol/timeframe."""
    df = rates_df(symbol, timeframe, VP_LOOKBACK)
    close = float(df["close"].iloc[-1])

    vp = compute_volume_profile(df, symbol)
    delta = compute_delta_features(df)
    absorption = compute_absorption_exhaustion(df)
    footprint = compute_footprint(df, n_candles=10)
    events = detect_orderflow_events(symbol, timeframe, vp, delta, absorption, vwap_summary or {}, close)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "close": close,
        "updated_at": now(),
        "volume_profile": vp,
        "delta_features": delta,
        "absorption_exhaustion": absorption,
        "footprint": footprint,
        "events": events,
    }


def _build_event_cache(events: list[dict], window_secs: int = 120) -> dict[str, tuple[str, float]]:
    """Build dedup cache: key->(last_created_at, last_price) for events in last window_secs."""
    cache: dict[str, tuple[str, float]] = {}
    cutoff_ts = datetime.now().timestamp() - window_secs
    for e in events:
        try:
            ts = datetime.fromisoformat(str(e.get("created_at", ""))).timestamp()
        except Exception:
            continue
        if ts < cutoff_ts:
            continue
        key = f"{e.get('symbol')}_{e.get('timeframe')}_{e.get('event_type')}_{e.get('side')}"
        cache[key] = (str(e.get("created_at", "")), float(e.get("price", 0.0) or 0.0))
    return cache


def _dedup_events(
    new_events: list[dict],
    cache: dict[str, tuple[str, float]],
    cooldown_secs: int = 60,
    price_thresh_pct: float = 0.0008,
) -> list[dict]:
    """Remove events that are duplicates within cooldown window.
    An event passes if: cooldown expired OR price moved more than price_thresh_pct.
    """
    result: list[dict] = []
    now_ts = datetime.now().timestamp()

    for e in new_events:
        key = f"{e.get('symbol')}_{e.get('timeframe')}_{e.get('event_type')}_{e.get('side')}"
        price = float(e.get("price", 0.0) or 0.0)

        if key in cache:
            last_ts_str, last_price = cache[key]
            try:
                last_ts = datetime.fromisoformat(last_ts_str).timestamp()
            except Exception:
                last_ts = 0.0

            cooldown_expired = (now_ts - last_ts) >= cooldown_secs
            price_moved = abs(price - last_price) / max(abs(last_price), 1e-9) >= price_thresh_pct

            if not cooldown_expired and not price_moved:
                continue  # Skip duplicate

        cache[key] = (e.get("created_at", now()), price)
        result.append(e)

    return result


def compute_fvg_zones(df: pd.DataFrame, symbol: str, tf: str) -> list[dict[str, Any]]:
    """
    Scan all bars for FVG zones. For each:
      - status: active (unfilled) | mitigating (price entered zone) | ifvg (fully mitigated, now flipped)
      - direction: bullish | bearish
      - gap_lo / gap_hi / mid: price levels
      - entry_bar: bar index where the gap was created
    """
    d = df.reset_index(drop=True)
    n = len(d)
    zones: list[dict[str, Any]] = []

    close_now = float(d.iloc[-1]["close"])

    scan_start = max(0, n - FVG_SCAN_BARS - 3)

    for i in range(scan_start, n - 2):
        p2h = float(d.loc[i, "high"])
        p2l = float(d.loc[i, "low"])
        ch  = float(d.loc[i + 2, "high"])
        cl  = float(d.loc[i + 2, "low"])

        if cl > p2h:
            gap_lo, gap_hi = p2h, cl
            mid = (gap_lo + gap_hi) / 2.0
            gap_size = gap_hi - gap_lo

            if gap_size < 1e-9:
                continue

            future = d.iloc[i + 3:]
            # Was the zone entered (low of any future bar dipped into gap)?
            was_entered = any(float(r["low"]) <= gap_hi for _, r in future.iterrows())
            # Was it FULLY mitigated (close below gap_lo)?
            fully_mitigated = any(float(r["close"]) < gap_lo for _, r in future.iterrows())

            if fully_mitigated:
                status = "ifvg"  # zone flipped — acts as resistance now
            elif was_entered:
                status = "mitigating"
            else:
                status = "active"

            age_bars = n - i - 3
            if age_bars > FVG_MAX_AGE_BARS:
                continue

            zones.append({
                "direction": "bullish",
                "gap_lo": round(gap_lo, 5),
                "gap_hi": round(gap_hi, 5),
                "mid": round(mid, 5),
                "gap_size": round(gap_size, 5),
                "status": status,
                "age_bars": age_bars,
                "price_in_zone": gap_lo <= close_now <= gap_hi,
                "price_above": close_now > gap_hi,
                "price_below": close_now < gap_lo,
                "created_at": now(),
                "symbol": symbol,
                "tf": tf,
            })

        if ch < p2l:
            gap_lo, gap_hi = ch, p2l
            mid = (gap_lo + gap_hi) / 2.0
            gap_size = gap_hi - gap_lo

            if gap_size < 1e-9:
                continue

            future = d.iloc[i + 3:]
            was_entered = any(float(r["high"]) >= gap_lo for _, r in future.iterrows())
            fully_mitigated = any(float(r["close"]) > gap_hi for _, r in future.iterrows())

            if fully_mitigated:
                status = "ifvg"
            elif was_entered:
                status = "mitigating"
            else:
                status = "active"

            age_bars = n - i - 3
            if age_bars > FVG_MAX_AGE_BARS:
                continue

            zones.append({
                "direction": "bearish",
                "gap_lo": round(gap_lo, 5),
                "gap_hi": round(gap_hi, 5),
                "mid": round(mid, 5),
                "gap_size": round(gap_size, 5),
                "status": status,
                "age_bars": age_bars,
                "price_in_zone": gap_lo <= close_now <= gap_hi,
                "price_above": close_now > gap_hi,
                "price_below": close_now < gap_lo,
                "created_at": now(),
                "symbol": symbol,
                "tf": tf,
            })

    # Sort by age (youngest first) and keep most relevant 10 per tf
    zones.sort(key=lambda z: z["age_bars"])
    return zones[:10]


def compute_all(symbols: list[str]) -> dict[str, Any]:
    """Compute order flow for all symbols across primary timeframes."""
    state: dict[str, Any] = {"updated_at": now(), "symbols": {}}
    all_events: list[dict[str, Any]] = []

    council_state = load_json(FEATURE_COUNCIL_FILE, {})
    decisions = council_state.get("decisions", [])
    vwap_map: dict[str, dict[str, Any]] = {}
    for dec in decisions:
        sym = dec.get("symbol", "")
        vs = dec.get("vwap_summary")
        if sym and vs:
            vwap_map[sym] = vs

    for symbol in symbols:
        state["symbols"][symbol] = {}
        vs = vwap_map.get(symbol)

        for timeframe in ["M1", "M5", "M15", "H1"]:
            try:
                result = compute_orderflow(symbol, timeframe, vs)
                state["symbols"][symbol][timeframe] = result
                all_events.extend(result.get("events", []))
            except Exception as exc:
                state["symbols"][symbol][timeframe] = {"error": str(exc)}

    # Compute and save FVG zones per symbol/tf
    fvg_state: dict[str, Any] = {"updated_at": now(), "symbols": {}}

    for symbol in symbols:
        fvg_state["symbols"][symbol] = {}

        for timeframe in ["M1", "M5", "M15", "H1"]:
            try:
                tf_code = TIMEFRAMES.get(timeframe)
                if tf_code is None:
                    continue
                rates = mt5.copy_rates_from_pos(symbol, tf_code, 0, FVG_SCAN_BARS + 10)
                if rates is None or len(rates) < 10:
                    continue
                df_fvg = pd.DataFrame(rates)
                df_fvg["time"] = pd.to_datetime(df_fvg["time"], unit="s")
                zones = compute_fvg_zones(df_fvg, symbol, timeframe)
                fvg_state["symbols"][symbol][timeframe] = {
                    "zones": zones,
                    "active_count": sum(1 for z in zones if z["status"] == "active"),
                    "ifvg_count": sum(1 for z in zones if z["status"] == "ifvg"),
                }
            except Exception as exc:
                fvg_state["symbols"][symbol][timeframe] = {"error": str(exc)}

    save_json_atomic(FVG_STATE_FILE, fvg_state)

    # Atomic save of state
    save_json_atomic(ORDERFLOW_STATE_FILE, state)

    # Load existing events, build dedup cache, filter new events, save
    existing_events = load_json(ORDERFLOW_EVENTS_FILE, [])
    if not isinstance(existing_events, list):
        existing_events = []

    dedup_cache = _build_event_cache(existing_events, window_secs=120)
    deduped = _dedup_events(all_events, dedup_cache, cooldown_secs=60, price_thresh_pct=0.0008)

    combined = existing_events + deduped
    # Keep last 500 only
    save_json_atomic(ORDERFLOW_EVENTS_FILE, combined[-500:])

    return state


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="FRIDAY Order Flow Feature Engine")
    parser.add_argument("--symbols", default="all", help="Comma-separated symbols, or all/auto for every tradable MT5 symbol")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--once", action="store_true", help="Run once and exit (alias for no --loop)")
    parser.add_argument("--interval", type=float, default=5.0, help="Loop interval seconds")
    args = parser.parse_args()

    ensure_mt5()

    symbols = resolve_symbols(args.symbols, mt5)
    run_loop = args.loop and not args.once

    print(f"[{now()}] Order Flow Engine starting. symbols={symbols} loop={run_loop}")

    while True:
        try:
            state = compute_all(symbols)
            for sym, tfs in state.get("symbols", {}).items():
                for tf, data in tfs.items():
                    if "error" in data:
                        print(f"[{now()}] ERROR {sym}/{tf}: {data['error']}")
                    else:
                        vp = data.get("volume_profile", {})
                        df_ = data.get("delta_features", {})
                        evts = data.get("events", [])
                        print(
                            f"[{now()}] {sym}/{tf} "
                            f"POC={vp.get('poc', '?')} VAH={vp.get('vah', '?')} VAL={vp.get('val', '?')} "
                            f"loc={vp.get('price_location_vs_value_area', '?')} "
                            f"cvd={df_.get('cumulative_delta_proxy', '?')} "
                            f"div={df_.get('delta_divergence', '?')} "
                            f"events={len(evts)}"
                        )
        except Exception as exc:
            print(f"[{now()}] WARNING: {exc}")

        if not run_loop:
            break

        time.sleep(max(1.0, args.interval))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
