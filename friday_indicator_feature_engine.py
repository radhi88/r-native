from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5
import pandas as pd

from friday_symbol_universe import resolve_symbols


ROOT = Path(r"C:\Users\Radhi\MT5")
SNAPSHOT_FILE = ROOT / "friday_feature_snapshots.jsonl"
STATE_FILE = ROOT / "friday_feature_council_state.json"
GENES_FILE = ROOT / "friday_strategy_genes.json"
TOUCH_MEMORY_FILE = ROOT / "friday_touch_level_memory.json"
WEIGHTS_FILE = ROOT / "friday_indicator_weights.json"

TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
}

TF_WEIGHTS = {
    "M1": 1.35,
    "M5": 1.25,
    "M15": 1.00,
    "H1": 0.75,
}


@dataclass
class FeatureFrame:
    symbol: str
    timeframe: str
    close: float
    spread_points: float

    ema20: float
    ema50: float
    ema200: float
    ema_vote: str

    rsi: float
    adx: float
    atr: float
    macd: float
    macd_signal: float
    mfi: float

    vwap: float
    vol_pct: float
    delta: float
    spread_mode: str

    donchian_high: float
    donchian_low: float
    donchian_vote: str

    demand: float | None
    supply: float | None
    nearest_support: float | None
    nearest_resistance: float | None

    structure_vote: str
    breakout_vote: str
    candle_vote: str

    # PHASE 1 — Advanced VWAP fields
    session_vwap: float
    anchored_vwap: float
    vwap_deviation: float
    vwap_band_upper: float
    vwap_band_lower: float
    vwap_signal: str

    # Wick / structure intelligence
    wick_pattern: str         # SHOOTING_STAR | HAMMER | UPPER_REJECTION | LOWER_REJECTION | NEUTRAL
    wick_upper_ratio: float   # 0-1, upper wick / total range
    wick_lower_ratio: float   # 0-1, lower wick / total range
    zone: str                 # premium | discount
    near_top: bool            # price within 0.6 ATR of 50-bar swing high
    near_bottom: bool         # price within 0.6 ATR of 50-bar swing low
    fvg_signal: str           # bull_fvg_entry | bull_fvg_chasing | bear_fvg_entry | bear_fvg_chasing | ifvg_bull | ifvg_bear | none


@dataclass
class GroupScore:
    name: str
    buy_score: float
    sell_score: float
    neutral_score: float
    buy_percent: float
    sell_percent: float
    vote: str
    reasons: list[str]


@dataclass
class CouncilDecision:
    symbol: str
    action: str
    execution_mode: str
    confidence: float
    trade_type: str
    sl_mode: str
    tp_mode: str
    feature_signature: str
    group_a: dict[str, Any]
    group_b: dict[str, Any]
    group_c: dict[str, Any]
    forecast: dict[str, Any]
    reasons: list[str]
    created_at: str
    vwap_summary: dict[str, Any]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_mt5() -> None:
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")


def select_symbol(symbol: str):
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Could not select symbol: {symbol}")

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)

    if info is None or tick is None:
        raise RuntimeError(f"No symbol info/tick for {symbol}")

    return info, tick


def current_prices(symbol: str) -> dict[str, float]:
    info, tick = select_symbol(symbol)

    point = float(info.point or 0.01)
    bid = float(tick.bid)
    ask = float(tick.ask)

    return {
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2.0,
        "spread_points": abs(ask - bid) / point,
        "point": point,
        "digits": int(info.digits or 2),
    }


def round_price(symbol: str, price: float) -> float:
    info, _ = select_symbol(symbol)
    return round(float(price), int(info.digits or 2))


def rates_df(symbol: str, timeframe: str, bars: int = 500) -> pd.DataFrame:
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[timeframe], 0, bars)

    if rates is None or len(rates) < 250:
        raise RuntimeError(f"Not enough rates for {symbol} {timeframe}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.astype(float).ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    close = series.astype(float)
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean().replace(0, 1e-9)

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.rolling(period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr_val = tr.rolling(period).mean().replace(0, 1e-9)
    plus_di = 100 * plus_dm.rolling(period).mean() / atr_val
    minus_di = 100 * minus_dm.rolling(period).mean() / atr_val

    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)) * 100
    return dx.rolling(period).mean()


def macd(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    fast = ema(series, 12)
    slow = ema(series, 26)
    macd_line = fast - slow
    signal = ema(macd_line, 9)
    return macd_line, signal


def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    vol = df["tick_volume"].astype(float).replace(0, 1.0)

    typical = (high + low + close) / 3.0
    money_flow = typical * vol

    positive = money_flow.where(typical > typical.shift(1), 0.0)
    negative = money_flow.where(typical < typical.shift(1), 0.0)

    pos_sum = positive.rolling(period).sum()
    neg_sum = negative.rolling(period).sum().replace(0, 1e-9)

    ratio = pos_sum / neg_sum
    return 100 - (100 / (1 + ratio))


def rolling_vwap(df: pd.DataFrame, lookback: int = 100) -> float:
    d = df.tail(lookback)
    typical = (d["high"].astype(float) + d["low"].astype(float) + d["close"].astype(float)) / 3.0
    vol = d["tick_volume"].astype(float).replace(0, 1.0)
    return float((typical * vol).sum() / vol.sum())


def delta_approx(df: pd.DataFrame, lookback: int = 30) -> float:
    d = df.tail(lookback)
    body = d["close"].astype(float) - d["open"].astype(float)
    vol = d["tick_volume"].astype(float).replace(0, 1.0)

    signed = body.apply(lambda x: 1.0 if x > 0 else -1.0 if x < 0 else 0.0) * vol
    total = float(vol.sum()) or 1.0

    return float(signed.sum() / total)


def volume_pct(df: pd.DataFrame, lookback: int = 30) -> float:
    vol = df["tick_volume"].astype(float)
    last = float(vol.iloc[-1])
    avg = float(vol.tail(lookback).iloc[:-1].mean() or 1.0)
    return float(last / avg)


def candle_vote(df: pd.DataFrame) -> str:
    last = df.iloc[-1]
    prev = df.iloc[-2]

    o1, c1 = float(prev.open), float(prev.close)
    o2, h2, l2, c2 = float(last.open), float(last.high), float(last.low), float(last.close)

    if c2 > o2 and c1 < o1 and c2 > o1 and o2 < c1:
        return "BUY_ENGULFING"

    if c2 < o2 and c1 > o1 and c2 < o1 and o2 > c1:
        return "SELL_ENGULFING"

    rng = max(h2 - l2, 1e-9)
    upper = h2 - max(o2, c2)
    lower = min(o2, c2) - l2

    if lower / rng > 0.55:
        return "BUY_REJECTION"

    if upper / rng > 0.55:
        return "SELL_REJECTION"

    return "NEUTRAL"


def structure_vote(df: pd.DataFrame) -> str:
    if len(df) < 50:
        return "NEUTRAL"

    close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])

    swing_high = float(df["high"].iloc[-42:-3].max())
    swing_low = float(df["low"].iloc[-42:-3].min())

    if close > swing_high:
        return "BOS_BUY"

    if close < swing_low:
        return "BOS_SELL"

    if prev_close < swing_low and close > swing_low:
        return "SWEEP_BUY"

    if prev_close > swing_high and close < swing_high:
        return "SWEEP_SELL"

    return "NEUTRAL"


def breakout_vote(df: pd.DataFrame, lookback: int = 20) -> tuple[str, float, float]:
    high = float(df["high"].tail(lookback).iloc[:-1].max())
    low = float(df["low"].tail(lookback).iloc[:-1].min())
    close = float(df["close"].iloc[-1])

    if close > high:
        return "BREAKOUT_BUY", high, low

    if close < low:
        return "BREAKOUT_SELL", high, low

    return "NEUTRAL", high, low


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default



def indicator_weight(name: str) -> float:
    data = load_json(WEIGHTS_FILE, {})
    row = (data.get("indicators", {}) or {}).get(name, {})
    try:
        return float(row.get("weight", 1.0) or 1.0)
    except Exception:
        return 1.0


def group_weight(name: str) -> float:
    data = load_json(WEIGHTS_FILE, {})
    row = (data.get("groups", {}) or {}).get(name, {})
    try:
        return float(row.get("weight", 1.0) or 1.0)
    except Exception:
        return 1.0


def nearest_touch_levels(symbol: str, price: float) -> tuple[float | None, float | None]:
    memory = load_json(TOUCH_MEMORY_FILE, {})
    symbol_data = memory.get("symbols", {}).get(symbol, {})
    tfs = symbol_data.get("timeframes", {})

    supports = []
    resistances = []

    for tf, rows in tfs.items():
        for row in rows or []:
            try:
                level = float(row.get("level"))
            except Exception:
                continue

            if level < price:
                supports.append(level)
            elif level > price:
                resistances.append(level)

    support = max(supports) if supports else None
    resistance = min(resistances) if resistances else None

    return support, resistance


def detect_demand_supply(df: pd.DataFrame) -> tuple[float | None, float | None]:
    d = df.tail(80)

    demand = None
    supply = None

    lows = d["low"].astype(float)
    highs = d["high"].astype(float)
    closes = d["close"].astype(float)

    local_low = float(lows.iloc[-30:-2].min())
    local_high = float(highs.iloc[-30:-2].max())
    close = float(closes.iloc[-1])

    if close > local_low:
        demand = local_low

    if close < local_high:
        supply = local_high

    return demand, supply


def spread_mode(spread_points: float) -> str:
    if spread_points <= 350:
        return "LOW_MARKET_OK"
    if spread_points <= 800:
        return "MEDIUM_HIGH_CONF_ONLY"
    if spread_points <= 1500:
        return "HIGH_PENDING_ONLY"
    return "EXTREME_BLOCK"


# ---------------------------------------------------------------------------
# PHASE 1 — Advanced VWAP Functions
# ---------------------------------------------------------------------------

def compute_session_vwap(df: pd.DataFrame) -> float:
    """VWAP anchored from session start (today's bars only, fallback to rolling-100)."""
    if df.empty:
        return 0.0

    today = pd.Timestamp.now().normalize()
    session_bars = df[df["time"] >= today]

    if len(session_bars) < 3:
        session_bars = df.tail(100)

    typical = (
        session_bars["high"].astype(float)
        + session_bars["low"].astype(float)
        + session_bars["close"].astype(float)
    ) / 3.0
    vol = session_bars["tick_volume"].astype(float).replace(0, 1.0)
    return float((typical * vol).sum() / vol.sum())


def compute_anchored_vwap(df: pd.DataFrame) -> float:
    """VWAP anchored from the most recent swing high or swing low (whichever is closer)."""
    if len(df) < 20:
        return compute_session_vwap(df)

    lookback = df.tail(60)
    close = float(df["close"].iloc[-1])

    swing_high_idx = lookback["high"].idxmax()
    swing_low_idx = lookback["low"].idxmin()
    swing_high_val = float(lookback.loc[swing_high_idx, "high"])
    swing_low_val = float(lookback.loc[swing_low_idx, "low"])

    # Anchor from the swing extreme closest to price
    if abs(close - swing_high_val) < abs(close - swing_low_val):
        anchor_idx = swing_high_idx
    else:
        anchor_idx = swing_low_idx

    anchor_pos = df.index.get_loc(anchor_idx)
    anchored_bars = df.iloc[anchor_pos:]

    if len(anchored_bars) < 2:
        return compute_session_vwap(df)

    typical = (
        anchored_bars["high"].astype(float)
        + anchored_bars["low"].astype(float)
        + anchored_bars["close"].astype(float)
    ) / 3.0
    vol = anchored_bars["tick_volume"].astype(float).replace(0, 1.0)
    return float((typical * vol).sum() / vol.sum())


def compute_vwap_bands(
    df: pd.DataFrame, session_vwap: float, atr_val: float
) -> tuple[float, float]:
    """VWAP bands using 2-sigma standard deviation of typical price (last 100 bars)."""
    lookback = df.tail(100)
    typical = (
        lookback["high"].astype(float)
        + lookback["low"].astype(float)
        + lookback["close"].astype(float)
    ) / 3.0

    std = float(typical.std())
    multiplier = 2.0

    upper = session_vwap + max(std * multiplier, atr_val * 1.2)
    lower = session_vwap - max(std * multiplier, atr_val * 1.2)
    return round(upper, 5), round(lower, 5)


def compute_vwap_signal(
    close: float,
    session_vwap: float,
    prev_close: float,
    prev_session_vwap: float,
) -> str:
    """Classify price action relative to VWAP."""
    if prev_close <= prev_session_vwap and close > session_vwap:
        return "VWAP_RECLAIM"
    if prev_close >= prev_session_vwap and close < session_vwap:
        return "VWAP_REJECTION"
    if close > session_vwap:
        return "ABOVE_VWAP"
    return "BELOW_VWAP"


def compute_wick_features(df: pd.DataFrame, atr_val: float) -> dict[str, Any]:
    """Wick pattern detection: pin bars, hammers, shooting stars, upper/lower rejections."""
    last = df.iloc[-1]
    h, l = float(last.high), float(last.low)
    o, c = float(last.open), float(last.close)
    rng = max(h - l, 1e-9)
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    upper_ratio = upper_wick / rng
    lower_ratio = lower_wick / rng
    body_ratio  = body / rng

    if body_ratio < 0.28:
        if upper_ratio > 0.62:
            pattern = "SHOOTING_STAR"
        elif lower_ratio > 0.62:
            pattern = "HAMMER"
        else:
            pattern = "DOJI"
    elif upper_ratio > 0.55:
        pattern = "UPPER_REJECTION"
    elif lower_ratio > 0.55:
        pattern = "LOWER_REJECTION"
    else:
        pattern = "NEUTRAL"

    close = float(df["close"].iloc[-1])
    swing_high = float(df["high"].iloc[-50:-3].max()) if len(df) >= 10 else h
    swing_low  = float(df["low"].iloc[-50:-3].min())  if len(df) >= 10 else l

    near_top    = (swing_high - close) / max(atr_val, 1e-9) < 0.6
    near_bottom = (close - swing_low)  / max(atr_val, 1e-9) < 0.6

    return {
        "pattern":     pattern,
        "upper_ratio": round(upper_ratio, 3),
        "lower_ratio": round(lower_ratio, 3),
        "near_top":    near_top,
        "near_bottom": near_bottom,
    }


def compute_fvg_signal(df: pd.DataFrame, close: float) -> str:
    """
    Classify price position relative to the most recent FVG.
    bull_fvg_entry  → price is AT/IN a bullish FVG (good buy zone)
    bull_fvg_chasing → price jumped above the gap (chasing)
    bear_fvg_entry  → price is AT/IN a bearish FVG (good sell zone)
    bear_fvg_chasing → price dropped below the gap (chasing)
    ifvg_bull / ifvg_bear → price is inside a mitigated FVG that flipped
    none
    """
    d = df.tail(6).reset_index(drop=True)

    for i in range(2, len(d)):
        p2h = float(d.loc[i - 2, "high"])
        p2l = float(d.loc[i - 2, "low"])
        ch  = float(d.loc[i, "high"])
        cl  = float(d.loc[i, "low"])

        if cl > p2h:
            gap_lo, gap_hi = p2h, cl
            if gap_lo <= close <= gap_hi or close <= gap_hi * 1.0025:
                return "bull_fvg_entry"
            if close > gap_hi:
                return "bull_fvg_chasing"
            return "bull_fvg"

        if ch < p2l:
            gap_lo, gap_hi = ch, p2l
            if gap_lo <= close <= gap_hi or close >= gap_lo * 0.9975:
                return "bear_fvg_entry"
            if close < gap_lo:
                return "bear_fvg_chasing"
            return "bear_fvg"

    # Check IFVG: look back 30 bars for a filled FVG
    full = df.reset_index(drop=True)
    n = len(full)
    for i in range(max(0, n - 30), n - 4):
        p2h = float(full.loc[i, "high"])
        p2l = float(full.loc[i, "low"])
        if i + 2 >= n:
            break
        ch = float(full.loc[i + 2, "high"])
        cl = float(full.loc[i + 2, "low"])

        if cl > p2h:
            gap_lo, gap_hi = p2h, cl
            future = full.iloc[i + 3:]
            was_filled = any(float(r["low"]) <= gap_hi for _, r in future.iterrows())
            if was_filled and gap_lo <= close <= gap_hi:
                return "ifvg_bull"

        if ch < p2l:
            gap_lo, gap_hi = ch, p2l
            future = full.iloc[i + 3:]
            was_filled = any(float(r["high"]) >= gap_lo for _, r in future.iterrows())
            if was_filled and gap_lo <= close <= gap_hi:
                return "ifvg_bear"

    return "none"


def compute_fractal_features_safe(df: pd.DataFrame) -> dict:
    """
    Run fractal SMC pipeline and return AI feature dict.
    Wrapped in try/except — returns empty dict if fractal engine unavailable.
    Called from compute_feature_frame for optional feature enrichment.
    """
    try:
        from fractal_features import build_fractal_ai_features
        return build_fractal_ai_features(df)
    except Exception:
        return {}


def compute_feature_frame(symbol: str, timeframe: str) -> FeatureFrame:
    df = rates_df(symbol, timeframe, 500)
    px = current_prices(symbol)

    close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else close

    ema20 = float(ema(df["close"], 20).iloc[-1])
    ema50 = float(ema(df["close"], 50).iloc[-1])
    ema200 = float(ema(df["close"], 200).iloc[-1])

    if ema20 > ema50 > ema200:
        ema_vote = "BUY"
    elif ema20 < ema50 < ema200:
        ema_vote = "SELL"
    else:
        ema_vote = "MIXED"

    rsi_val = float(rsi(df["close"], 14).iloc[-1])
    adx_val = float(adx(df, 14).iloc[-1])
    atr_val = float(atr(df, 14).iloc[-1])

    macd_line, macd_sig = macd(df["close"])
    macd_val = float(macd_line.iloc[-1])
    macd_signal_val = float(macd_sig.iloc[-1])

    mfi_val = float(mfi(df, 14).iloc[-1])
    vwap_val = rolling_vwap(df, 100)
    vol = volume_pct(df, 30)
    delta = delta_approx(df, 30)

    # PHASE 1 — compute advanced VWAP features
    sess_vwap = compute_session_vwap(df)
    anch_vwap = compute_anchored_vwap(df)
    vwap_band_hi, vwap_band_lo = compute_vwap_bands(df, sess_vwap, atr_val)
    vwap_dev = (close - sess_vwap) / max(atr_val, 1e-9)

    # Use previous bar's session_vwap approximation (shift 1 bar) for signal
    prev_sess_vwap = sess_vwap  # conservative: treat as same (true multi-bar needs history)
    if len(df) > 1:
        df_prev = df.iloc[:-1]
        if len(df_prev) >= 3:
            prev_sess_vwap = compute_session_vwap(df_prev)
    v_signal = compute_vwap_signal(close, sess_vwap, prev_close, prev_sess_vwap)

    br_vote, d_high, d_low = breakout_vote(df, 20)
    st_vote = structure_vote(df)
    cd_vote = candle_vote(df)

    # Wick + structure intelligence
    wick_info = compute_wick_features(df, atr_val)
    fvg_sig   = compute_fvg_signal(df, close)

    # Premium/discount zone
    d100 = df.tail(100)
    zone_high = float(d100["high"].max())
    zone_low  = float(d100["low"].min())
    zone_mid  = (zone_high + zone_low) / 2.0
    zone = "premium" if close >= zone_mid else "discount"

    demand, supply = detect_demand_supply(df)
    support, resistance = nearest_touch_levels(symbol, close)

    # Fractal SMC feature enrichment (safe — won't break if engine unavailable)
    _fractal_feats = compute_fractal_features_safe(df)
    # _fractal_feats is available for downstream use or snapshot logging;
    # existing FeatureFrame fields are unchanged to preserve all existing logic.

    if close > d_high:
        donchian_vote = "BUY"
    elif close < d_low:
        donchian_vote = "SELL"
    else:
        donchian_vote = "INSIDE"

    digits = int(px.get("digits", 5) or 5)

    return FeatureFrame(
        symbol=symbol,
        timeframe=timeframe,
        close=round_price(symbol, close),
        spread_points=round(float(px["spread_points"]), 1),

        ema20=round_price(symbol, ema20),
        ema50=round_price(symbol, ema50),
        ema200=round_price(symbol, ema200),
        ema_vote=ema_vote,

        rsi=round(rsi_val, 2),
        adx=round(adx_val, 2),
        atr=round(atr_val, 5),
        macd=round(macd_val, 5),
        macd_signal=round(macd_signal_val, 5),
        mfi=round(mfi_val, 2),

        vwap=round_price(symbol, vwap_val),
        vol_pct=round(vol, 3),
        delta=round(delta, 4),
        spread_mode=spread_mode(px["spread_points"]),

        donchian_high=round_price(symbol, d_high),
        donchian_low=round_price(symbol, d_low),
        donchian_vote=donchian_vote,

        demand=round_price(symbol, demand) if demand else None,
        supply=round_price(symbol, supply) if supply else None,
        nearest_support=round_price(symbol, support) if support else None,
        nearest_resistance=round_price(symbol, resistance) if resistance else None,

        structure_vote=st_vote,
        breakout_vote=br_vote,
        candle_vote=cd_vote,

        session_vwap=round(sess_vwap, digits),
        anchored_vwap=round(anch_vwap, digits),
        vwap_deviation=round(vwap_dev, 4),
        vwap_band_upper=round(vwap_band_hi, digits),
        vwap_band_lower=round(vwap_band_lo, digits),
        vwap_signal=v_signal,

        wick_pattern=wick_info["pattern"],
        wick_upper_ratio=wick_info["upper_ratio"],
        wick_lower_ratio=wick_info["lower_ratio"],
        zone=zone,
        near_top=wick_info["near_top"],
        near_bottom=wick_info["near_bottom"],
        fvg_signal=fvg_sig,
    )


def score_group_a(frames: list[FeatureFrame]) -> GroupScore:
    buy = sell = neutral = 0.0
    reasons = []

    for f in frames:
        w = TF_WEIGHTS.get(f.timeframe, 1.0)

        if f.ema_vote == "BUY":
            buy += 1.5 * w * indicator_weight('EMA')
            reasons.append(f"{f.timeframe}:EMA_BUY")
        elif f.ema_vote == "SELL":
            sell += 1.5 * w * indicator_weight('EMA')
            reasons.append(f"{f.timeframe}:EMA_SELL")
        else:
            neutral += 0.5 * w

        if f.rsi >= 55:
            buy += 0.9 * w * indicator_weight('RSI')
            reasons.append(f"{f.timeframe}:RSI_BUY")
        elif f.rsi <= 45:
            sell += 0.9 * w * indicator_weight('RSI')
            reasons.append(f"{f.timeframe}:RSI_SELL")
        else:
            neutral += 0.5 * w

        if f.adx >= 20:
            if f.ema_vote == "BUY":
                buy += 0.7 * w * indicator_weight('ADX')
                reasons.append(f"{f.timeframe}:ADX_TREND_BUY")
            elif f.ema_vote == "SELL":
                sell += 0.7 * w * indicator_weight('ADX')
                reasons.append(f"{f.timeframe}:ADX_TREND_SELL")
            else:
                neutral += 0.4 * w

        if f.macd > f.macd_signal:
            buy += 0.8 * w * indicator_weight('MACD')
            reasons.append(f"{f.timeframe}:MACD_BUY")
        elif f.macd < f.macd_signal:
            sell += 0.8 * w * indicator_weight('MACD')
            reasons.append(f"{f.timeframe}:MACD_SELL")

    return finalize_group("A_TREND_MOMENTUM", buy, sell, neutral, reasons)


def score_group_b(frames: list[FeatureFrame]) -> GroupScore:
    buy = sell = neutral = 0.0
    reasons = []

    for f in frames:
        w = TF_WEIGHTS.get(f.timeframe, 1.0)

        # Use session_vwap signal for richer VWAP scoring
        if f.vwap_signal == "VWAP_RECLAIM":
            buy += 1.6 * w * indicator_weight('VWAP')
            reasons.append(f"{f.timeframe}:VWAP_RECLAIM")
        elif f.vwap_signal == "VWAP_REJECTION":
            sell += 1.6 * w * indicator_weight('VWAP')
            reasons.append(f"{f.timeframe}:VWAP_REJECTION")
        elif f.vwap_signal == "ABOVE_VWAP":
            buy += 1.1 * w * indicator_weight('VWAP')
            reasons.append(f"{f.timeframe}:ABOVE_VWAP")
        elif f.vwap_signal == "BELOW_VWAP":
            sell += 1.1 * w * indicator_weight('VWAP')
            reasons.append(f"{f.timeframe}:BELOW_VWAP")

        # Reward if price is within VWAP bands (value area)
        if f.vwap_band_lower < f.close < f.vwap_band_upper:
            neutral += 0.2 * w
        elif f.close > f.vwap_band_upper:
            sell += 0.4 * w * indicator_weight('VWAP')
            reasons.append(f"{f.timeframe}:ABOVE_VWAP_BAND")
        elif f.close < f.vwap_band_lower:
            buy += 0.4 * w * indicator_weight('VWAP')
            reasons.append(f"{f.timeframe}:BELOW_VWAP_BAND")

        if f.mfi >= 55:
            buy += 0.9 * w * indicator_weight('RSI')
            reasons.append(f"{f.timeframe}:MFI_BUY")
        elif f.mfi <= 45:
            sell += 0.9 * w * indicator_weight('RSI')
            reasons.append(f"{f.timeframe}:MFI_SELL")
        else:
            neutral += 0.4 * w

        if f.delta >= 0.12:
            buy += 1.0 * w * indicator_weight('DELTA')
            reasons.append(f"{f.timeframe}:DELTA_BUY")
        elif f.delta <= -0.12:
            sell += 1.0 * w * indicator_weight('DELTA')
            reasons.append(f"{f.timeframe}:DELTA_SELL")
        else:
            neutral += 0.4 * w

        if f.vol_pct >= 1.35:
            if f.delta > 0:
                buy += 0.7 * w * indicator_weight('ADX')
                reasons.append(f"{f.timeframe}:VOL_SPIKE_BUY")
            elif f.delta < 0:
                sell += 0.7 * w * indicator_weight('ADX')
                reasons.append(f"{f.timeframe}:VOL_SPIKE_SELL")
            else:
                neutral += 0.4 * w

        if f.spread_mode == "EXTREME_BLOCK":
            neutral += 2.0 * w
            reasons.append(f"{f.timeframe}:SPREAD_EXTREME")
        elif f.spread_mode == "HIGH_PENDING_ONLY":
            neutral += 1.0 * w
            reasons.append(f"{f.timeframe}:SPREAD_PENDING_ONLY")

        # Wick scoring — rejection candles carry strong directional bias
        if f.wick_pattern in {"HAMMER", "LOWER_REJECTION"}:
            buy += 1.2 * w * indicator_weight("WICK")
            reasons.append(f"{f.timeframe}:WICK_{f.wick_pattern}")
        elif f.wick_pattern in {"SHOOTING_STAR", "UPPER_REJECTION"}:
            sell += 1.2 * w * indicator_weight("WICK")
            reasons.append(f"{f.timeframe}:WICK_{f.wick_pattern}")

    return finalize_group("B_FLOW_VOLUME", buy, sell, neutral, reasons)


def score_group_c(frames: list[FeatureFrame]) -> GroupScore:
    buy = sell = neutral = 0.0
    reasons = []

    for f in frames:
        w = TF_WEIGHTS.get(f.timeframe, 1.0)

        for key in [f.structure_vote, f.breakout_vote, f.candle_vote, f.donchian_vote]:
            if "BUY" in key:
                buy += 1.2 * w * indicator_weight('BOS')
                reasons.append(f"{f.timeframe}:{key}")
            elif "SELL" in key:
                sell += 1.2 * w * indicator_weight('BOS')
                reasons.append(f"{f.timeframe}:{key}")
            else:
                neutral += 0.25 * w

        if f.demand is not None and f.close >= f.demand:
            buy += 0.8 * w * indicator_weight('MACD')
            reasons.append(f"{f.timeframe}:DEMAND_SUPPORT")

        if f.supply is not None and f.close <= f.supply:
            sell += 0.8 * w * indicator_weight('MACD')
            reasons.append(f"{f.timeframe}:SUPPLY_RESISTANCE")

        if f.nearest_support is not None:
            buy += 0.45 * w * indicator_weight('TOUCH_MEMORY')
            reasons.append(f"{f.timeframe}:TOUCH_SUPPORT_MEMORY")

        if f.nearest_resistance is not None:
            sell += 0.45 * w * indicator_weight('TOUCH_MEMORY')
            reasons.append(f"{f.timeframe}:TOUCH_RESISTANCE_MEMORY")

        # FVG signal scoring — entry at FVG is strong, chasing is penalized
        if f.fvg_signal == "bull_fvg_entry":
            buy += 1.4 * w * indicator_weight("FVG")
            reasons.append(f"{f.timeframe}:FVG_BULL_ENTRY")
        elif f.fvg_signal == "bull_fvg_chasing":
            sell += 0.7 * w * indicator_weight("FVG")
            reasons.append(f"{f.timeframe}:FVG_BULL_CHASING")
        elif f.fvg_signal == "bear_fvg_entry":
            sell += 1.4 * w * indicator_weight("FVG")
            reasons.append(f"{f.timeframe}:FVG_BEAR_ENTRY")
        elif f.fvg_signal == "bear_fvg_chasing":
            buy += 0.7 * w * indicator_weight("FVG")
            reasons.append(f"{f.timeframe}:FVG_BEAR_CHASING")
        elif f.fvg_signal == "ifvg_bull":
            sell += 1.0 * w * indicator_weight("IFVG")
            reasons.append(f"{f.timeframe}:IFVG_BULL_RESISTANCE")
        elif f.fvg_signal == "ifvg_bear":
            buy += 1.0 * w * indicator_weight("IFVG")
            reasons.append(f"{f.timeframe}:IFVG_BEAR_SUPPORT")

        # Zone premium/discount — strong bias for entries in correct zone
        if f.zone == "discount":
            buy += 1.1 * w * indicator_weight("ZONE")
            reasons.append(f"{f.timeframe}:ZONE_DISCOUNT_BUY")
        elif f.zone == "premium":
            sell += 1.1 * w * indicator_weight("ZONE")
            reasons.append(f"{f.timeframe}:ZONE_PREMIUM_SELL")

        # Anti-top / anti-bottom structural filter
        if f.near_top:
            sell += 0.9 * w
            reasons.append(f"{f.timeframe}:NEAR_SWING_TOP")
        if f.near_bottom:
            buy += 0.9 * w
            reasons.append(f"{f.timeframe}:NEAR_SWING_BOTTOM")

    return finalize_group("C_STRUCTURE_BREAKOUT", buy, sell, neutral, reasons)


def finalize_group(name: str, buy: float, sell: float, neutral: float, reasons: list[str]) -> GroupScore:
    gw = group_weight(name)
    buy *= gw
    sell *= gw
    neutral *= max(0.60, min(1.40, 2.0 - gw))

    total = max(buy + sell + neutral, 1e-9)

    buy_percent = buy / total * 100
    sell_percent = sell / total * 100

    if buy_percent >= 65:
        vote = "BUY"
    elif buy_percent <= 40 and sell_percent >= 45:
        vote = "SELL"
    else:
        vote = "MIXED"

    return GroupScore(
        name=name,
        buy_score=round(buy, 4),
        sell_score=round(sell, 4),
        neutral_score=round(neutral, 4),
        buy_percent=round(buy_percent, 2),
        sell_percent=round(sell_percent, 2),
        vote=vote,
        reasons=reasons[-30:],
    )


def feature_signature(symbol: str, a: GroupScore, b: GroupScore, c: GroupScore) -> str:
    return (
        f"{symbol}|"
        f"A={a.vote}:{int(a.buy_percent)}|"
        f"B={b.vote}:{int(b.buy_percent)}|"
        f"C={c.vote}:{int(c.buy_percent)}"
    )


def forecast_path(symbol: str, frames: list[FeatureFrame], action: str, confidence: float, steps: int = 12) -> dict[str, Any]:
    base = frames[0].close
    point = current_prices(symbol)["point"]

    atr_points = max(50.0, frames[0].atr / point)
    direction = 0

    if action in {"BUY", "PENDING_BUY"}:
        direction = 1
    elif action in {"SELL", "PENDING_SELL"}:
        direction = -1

    candles = []
    price = base

    for i in range(1, steps + 1):
        drift = direction * atr_points * point * (0.10 + confidence * 0.06)
        wave = math.sin(i / 2.0) * atr_points * point * 0.03

        open_price = price
        close_price = price + drift + wave
        high = max(open_price, close_price) + atr_points * point * 0.06
        low = min(open_price, close_price) - atr_points * point * 0.06

        candles.append(
            {
                "step": i,
                "open": round_price(symbol, open_price),
                "high": round_price(symbol, high),
                "low": round_price(symbol, low),
                "close": round_price(symbol, close_price),
            }
        )

        price = close_price

    return {
        "base": round_price(symbol, base),
        "direction": action,
        "confidence": round(confidence, 4),
        "forecast_candles": candles,
    }


def decide(symbol: str) -> CouncilDecision:
    frames = [compute_feature_frame(symbol, tf) for tf in TIMEFRAMES]

    a = score_group_a(frames)
    b = score_group_b(frames)
    c = score_group_c(frames)

    reasons = []
    reasons.extend([f"A:{x}" for x in a.reasons[-8:]])
    reasons.extend([f"B:{x}" for x in b.reasons[-8:]])
    reasons.extend([f"C:{x}" for x in c.reasons[-8:]])

    spread = frames[0].spread_points
    spread_mode_now = frames[0].spread_mode

    votes = [a.vote, b.vote, c.vote]

    buy_votes = votes.count("BUY")
    sell_votes = votes.count("SELL")

    action = "HOLD"
    execution_mode = "NONE"
    trade_type = "mixed"
    sl_mode = "protective"
    tp_mode = "dynamic"

    if a.buy_percent >= 65 and buy_votes >= 2:
        action = "BUY"
        trade_type = "trend_flow_structure_buy"
    elif a.buy_percent <= 40 and sell_votes >= 2:
        action = "SELL"
        trade_type = "trend_flow_structure_sell"
    elif c.vote == "BUY" and b.vote in {"BUY", "MIXED"}:
        action = "PENDING_BUY"
        trade_type = "structure_touch_pending_buy"
    elif c.vote == "SELL" and b.vote in {"SELL", "MIXED"}:
        action = "PENDING_SELL"
        trade_type = "structure_touch_pending_sell"

    raw_conf = (
        abs(a.buy_percent - a.sell_percent) * 0.30
        + abs(b.buy_percent - b.sell_percent) * 0.30
        + abs(c.buy_percent - c.sell_percent) * 0.40
    ) / 100.0

    confidence = min(0.99, max(0.0, raw_conf))

    if spread_mode_now == "LOW_MARKET_OK":
        if action == "BUY":
            execution_mode = "MARKET_BUY"
        elif action == "SELL":
            execution_mode = "MARKET_SELL"
        else:
            execution_mode = action if action.startswith("PENDING") else "NONE"

    elif spread_mode_now == "MEDIUM_HIGH_CONF_ONLY":
        if confidence >= 0.72 and action == "BUY":
            execution_mode = "MARKET_BUY"
        elif confidence >= 0.72 and action == "SELL":
            execution_mode = "MARKET_SELL"
        elif action in {"BUY", "PENDING_BUY"}:
            execution_mode = "PENDING_BUY"
        elif action in {"SELL", "PENDING_SELL"}:
            execution_mode = "PENDING_SELL"
        else:
            execution_mode = "NONE"

    elif spread_mode_now == "HIGH_PENDING_ONLY":
        if action in {"BUY", "PENDING_BUY"}:
            execution_mode = "PENDING_BUY"
        elif action in {"SELL", "PENDING_SELL"}:
            execution_mode = "PENDING_SELL"
        else:
            execution_mode = "NONE"

    else:
        execution_mode = "BLOCK"

    if confidence >= 0.68 and c.vote != "MIXED":
        sl_mode = "profit_only"
        tp_mode = "dynamic_expandable"

    sig = feature_signature(symbol, a, b, c)
    forecast = forecast_path(symbol, frames, action, confidence)

    # Build aggregated VWAP summary for dashboard (use M1 as primary, fallback to first)
    primary = frames[0]
    vwap_summary = {
        "session_vwap": primary.session_vwap,
        "anchored_vwap": primary.anchored_vwap,
        "vwap_band_upper": primary.vwap_band_upper,
        "vwap_band_lower": primary.vwap_band_lower,
        "vwap_deviation": primary.vwap_deviation,
        "vwap_signal": primary.vwap_signal,
        "per_tf": {
            f.timeframe: {
                "session_vwap": f.session_vwap,
                "vwap_signal": f.vwap_signal,
                "vwap_deviation": f.vwap_deviation,
            }
            for f in frames
        },
    }

    decision = CouncilDecision(
        symbol=symbol,
        action=action,
        execution_mode=execution_mode,
        confidence=round(confidence, 4),
        trade_type=trade_type,
        sl_mode=sl_mode,
        tp_mode=tp_mode,
        feature_signature=sig,
        group_a=asdict(a),
        group_b=asdict(b),
        group_c=asdict(c),
        forecast=forecast,
        reasons=reasons,
        created_at=now(),
        vwap_summary=vwap_summary,
    )

    return decision


def append_snapshot(decision: CouncilDecision) -> None:
    event = {
        "type": "feature_council_snapshot",
        "decision": asdict(decision),
        "time": now(),
    }

    with SNAPSHOT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def save_state(decisions: list[CouncilDecision]) -> None:
    state = {
        "version": "0.1",
        "updated_at": now(),
        "decisions": [asdict(d) for d in decisions],
    }

    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="all", help="Comma-separated symbols, or all/auto for every tradable MT5 symbol")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    ensure_mt5()

    symbols = resolve_symbols(args.symbols, mt5)
    print(f"[{now()}] Feature Council symbols={len(symbols)} {symbols[:12]}{' ...' if len(symbols) > 12 else ''}")

    while True:
        decisions = []

        for symbol in symbols:
            try:
                d = decide(symbol)
                decisions.append(d)
                append_snapshot(d)

                print(
                    f"[{now()}] {symbol} "
                    f"action={d.action} exec={d.execution_mode} "
                    f"conf={d.confidence} sig={d.feature_signature} "
                    f"A={d.group_a['buy_percent']}%/{d.group_a['vote']} "
                    f"B={d.group_b['buy_percent']}%/{d.group_b['vote']} "
                    f"C={d.group_c['buy_percent']}%/{d.group_c['vote']}"
                )

            except Exception as exc:
                print(f"[{now()}] ERROR {symbol}: {exc}")

        save_state(decisions)

        if not args.loop:
            break

        time.sleep(max(0.5, args.interval))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
