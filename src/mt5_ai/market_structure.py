import numpy as np
import pandas as pd

from .config import (
    ESTIMATED_SPREAD_POINTS_CSV,
    FVG_MIN_ATR_MULT,
    LIQUIDITY_LOOKBACK,
    OB_LOOKBACK,
    SWING_LOOKBACK,
)


# ─── Indicator Helpers ────────────────────────────────────────────────────────

def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing: alpha = 1/period (not 2/(period+1) used by standard EMA)."""
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Wilder's Average Directional Index (ADX), range [0, 100].
    Replaces the old range.rolling().mean() which produced ATR, not ADX.
    """
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0).fillna(0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0).fillna(0.0)

    tr = _true_range(df).fillna(0.0)
    smoothed_tr = _wilder_smooth(tr, period)
    smoothed_plus_dm = _wilder_smooth(plus_dm, period)
    smoothed_minus_dm = _wilder_smooth(minus_dm, period)

    plus_di = (100.0 * smoothed_plus_dm / smoothed_tr.replace(0.0, np.nan)).fillna(0.0)
    minus_di = (100.0 * smoothed_minus_dm / smoothed_tr.replace(0.0, np.nan)).fillna(0.0)

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = (100.0 * (plus_di - minus_di).abs() / di_sum).fillna(0.0)

    return _wilder_smooth(dx, period).fillna(0.0)


def _mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Money Flow Index (MFI), range [0, 100].
    Replaces the old money_flow.rolling().mean() which returned raw money flow,
    not the normalised ratio-based MFI.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    raw_mf = tp * df["volume"]
    tp_rising = tp.diff() > 0  # first bar: NaN → False (treated as not rising)

    pos_mf = raw_mf.where(tp_rising, 0.0).rolling(period, min_periods=1).sum()
    neg_mf = raw_mf.where(~tp_rising, 0.0).rolling(period, min_periods=1).sum()

    # Safe division: clip denominator away from zero.
    # When neg_mf=0 and pos_mf>0 → mfr is very large → MFI ≈ 100 (correct).
    neg_mf_safe = neg_mf.clip(lower=1e-10)
    mfr = pos_mf / neg_mf_safe

    # When both are zero (no volume / flat price), default to neutral 50.
    both_zero = (pos_mf == 0) & (neg_mf == 0)
    mfi = (100.0 - 100.0 / (1.0 + mfr)).where(~both_zero, 50.0)
    return mfi.clip(0.0, 100.0).fillna(50.0)


def _order_blocks(
    close: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    bos_up: np.ndarray,
    bos_down: np.ndarray,
    lookback: int,
):
    """
    Compute Order Block zones per ICT methodology:
      - Bullish OB: last bearish candle (close < open) within `lookback` bars before a BOS_UP
      - Bearish OB: last bullish candle (close > open) within `lookback` bars before a BOS_DOWN

    Tracks the *active* OB; updates only when a new BOS is confirmed.
    Returns four np.ndarray: (bull_ob_low, bull_ob_high, bear_ob_low, bear_ob_high).

    Replaces the old rolling min/max approach which captured the entire window of
    qualifying candles instead of the single last one.
    """
    n = len(close)
    bull_low = np.full(n, np.nan)
    bull_high = np.full(n, np.nan)
    bear_low = np.full(n, np.nan)
    bear_high = np.full(n, np.nan)

    is_bearish = close < open_
    is_bullish = close > open_

    cur_bull = (np.nan, np.nan)
    cur_bear = (np.nan, np.nan)

    for i in range(1, n):
        if bos_up[i]:
            # Search backwards within lookback for last bearish candle
            for j in range(i - 1, max(i - lookback, 0) - 1, -1):
                if is_bearish[j]:
                    cur_bull = (low[j], high[j])
                    break
        if bos_down[i]:
            # Search backwards within lookback for last bullish candle
            for j in range(i - 1, max(i - lookback, 0) - 1, -1):
                if is_bullish[j]:
                    cur_bear = (low[j], high[j])
                    break
        bull_low[i], bull_high[i] = cur_bull
        bear_low[i], bear_high[i] = cur_bear

    return bull_low, bull_high, bear_low, bear_high


# ─── Feature Construction ─────────────────────────────────────────────────────

def normalize_ohlcv(df):
    out = df.copy()
    out.columns = [column.strip().lower() for column in out.columns]

    required = ["open", "high", "low", "close"]
    missing = [column for column in required if column not in out.columns]
    if missing:
        raise ValueError(f"Missing OHLC columns: {missing}")

    if "volume" not in out.columns:
        if "tick_volume" in out.columns:
            out["volume"] = out["tick_volume"]
        else:
            out["volume"] = 1.0

    for column in required + ["volume"]:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    if "spread" in out.columns:
        out["spread"] = pd.to_numeric(out["spread"], errors="coerce").fillna(0)

    return out.dropna(subset=required).reset_index(drop=True)


def add_basic_features(df):
    out = normalize_ohlcv(df)

    out["ret"] = out["close"].pct_change().fillna(0)
    out["range"] = (out["high"] - out["low"]) / out["close"].replace(0, np.nan)
    out["body"] = (out["close"] - out["open"]) / out["close"].replace(0, np.nan)
    out["atr"] = out["range"].rolling(14, min_periods=1).mean().fillna(0)

    ema_fast = out["close"].ewm(span=8, adjust=False).mean()
    ema_slow = out["close"].ewm(span=21, adjust=False).mean()
    out["trend"] = ((ema_fast - ema_slow) / out["close"].replace(0, np.nan)).fillna(0)

    delta = out["close"].diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
    loss = -delta.clip(upper=0).rolling(14, min_periods=1).mean()
    rs = gain / (loss + 1e-9)
    out["rsi"] = (100 - (100 / (1 + rs))).fillna(50)

    macd = ema_fast - ema_slow
    out["macd"] = macd
    out["macd_sig"] = macd.ewm(span=9, adjust=False).mean()

    # Wilder's ADX — replaces incorrect range.rolling().mean() from prior version
    out["adx"] = _adx(out)

    # Money Flow Index — replaces incorrect raw money_flow.rolling().mean() from prior version
    out["mfi"] = _mfi(out)

    out["voi_pct"] = out["volume"].pct_change().replace([np.inf, -np.inf], 0).fillna(0)

    # "spr" is bar range used as a model feature — it is NOT bid-ask spread.
    # Kept as range for model-weight compatibility until Phase 1 retraining.
    out["spr"] = out["range"].fillna(0)

    out["dch"] = (
        out["high"].rolling(20, min_periods=1).max()
        - out["low"].rolling(20, min_periods=1).min()
    )
    out["demand"] = (out["close"] - out["low"]).rolling(14, min_periods=1).mean()
    out["supply"] = (out["high"] - out["close"]).rolling(14, min_periods=1).mean()

    # Ensure a "spread" column exists for the spread-filter check in ai_brain.py.
    # When real bid-ask spread data is absent (e.g. offline CSV), use the configured
    # estimate rather than silently skipping the spread filter entirely.
    if "spread" not in out.columns:
        out["spread"] = ESTIMATED_SPREAD_POINTS_CSV  # approximate, not real market spread

    return out.bfill().fillna(0)


def add_market_structure(df):
    out = add_basic_features(df)

    prev_high = out["high"].rolling(SWING_LOOKBACK, min_periods=2).max().shift(1)
    prev_low = out["low"].rolling(SWING_LOOKBACK, min_periods=2).min().shift(1)
    liq_high = out["high"].rolling(LIQUIDITY_LOOKBACK, min_periods=2).max().shift(1)
    liq_low = out["low"].rolling(LIQUIDITY_LOOKBACK, min_periods=2).min().shift(1)

    out["prev_swing_high"] = prev_high.bfill()
    out["prev_swing_low"] = prev_low.bfill()
    out["liquidity_high"] = liq_high.bfill()
    out["liquidity_low"] = liq_low.bfill()

    out["bos_up"] = (out["close"] > out["prev_swing_high"]).astype(int)
    out["bos_down"] = (out["close"] < out["prev_swing_low"]).astype(int)
    out["choch_up"] = ((out["bos_up"] == 1) & (out["trend"].shift(1) < 0)).astype(int)
    out["choch_down"] = ((out["bos_down"] == 1) & (out["trend"].shift(1) > 0)).astype(int)

    out["buy_side_liquidity_sweep"] = (
        (out["high"] > out["liquidity_high"]) & (out["close"] < out["liquidity_high"])
    ).astype(int)
    out["sell_side_liquidity_sweep"] = (
        (out["low"] < out["liquidity_low"]) & (out["close"] > out["liquidity_low"])
    ).astype(int)

    min_gap = out["atr"] * FVG_MIN_ATR_MULT * out["close"]
    bull_gap = out["low"] - out["high"].shift(2)
    bear_gap = out["low"].shift(2) - out["high"]
    out["bullish_fvg"] = (bull_gap > min_gap).astype(int)
    out["bearish_fvg"] = (bear_gap > min_gap).astype(int)
    out["fvg_mid"] = np.where(
        out["bullish_fvg"] == 1,
        (out["low"] + out["high"].shift(2)) / 2,
        np.where(out["bearish_fvg"] == 1, (out["high"] + out["low"].shift(2)) / 2, np.nan),
    )
    out["ifvg_bull"] = (
        (out["bearish_fvg"].shift(1) == 1) & (out["close"] > out["high"].shift(1))
    ).astype(int)
    out["ifvg_bear"] = (
        (out["bullish_fvg"].shift(1) == 1) & (out["close"] < out["low"].shift(1))
    ).astype(int)

    # Order Blocks: last qualifying candle before BOS per ICT methodology.
    # Replaces rolling min/max which captured all candles in the window, not just the last OB.
    bull_ob_low, bull_ob_high, bear_ob_low, bear_ob_high = _order_blocks(
        close=out["close"].values,
        open_=out["open"].values,
        high=out["high"].values,
        low=out["low"].values,
        bos_up=out["bos_up"].values,
        bos_down=out["bos_down"].values,
        lookback=OB_LOOKBACK,
    )
    out["bullish_ob_low"] = bull_ob_low
    out["bullish_ob_high"] = bull_ob_high
    out["bearish_ob_low"] = bear_ob_low
    out["bearish_ob_high"] = bear_ob_high

    close_vals = out["close"].values
    out["in_bullish_ob"] = (
        ~np.isnan(bull_ob_low)
        & (close_vals >= bull_ob_low)
        & (close_vals <= bull_ob_high)
    ).astype(int)
    out["in_bearish_ob"] = (
        ~np.isnan(bear_ob_low)
        & (close_vals >= bear_ob_low)
        & (close_vals <= bear_ob_high)
    ).astype(int)

    out["demand_zone"] = (
        ((out["sell_side_liquidity_sweep"] == 1) | (out["choch_up"] == 1))
        & (out["close"] > out["open"])
    ).astype(int)
    out["supply_zone"] = (
        ((out["buy_side_liquidity_sweep"] == 1) | (out["choch_down"] == 1))
        & (out["close"] < out["open"])
    ).astype(int)

    out["smc_buy_score"] = (
        out["bos_up"]
        + out["choch_up"]
        + out["sell_side_liquidity_sweep"]
        + out["bullish_fvg"]
        + out["ifvg_bull"]
        + out["in_bullish_ob"]
        + out["demand_zone"]
        + (out["trend"] > 0).astype(int)
    )
    out["smc_sell_score"] = (
        out["bos_down"]
        + out["choch_down"]
        + out["buy_side_liquidity_sweep"]
        + out["bearish_fvg"]
        + out["ifvg_bear"]
        + out["in_bearish_ob"]
        + out["supply_zone"]
        + (out["trend"] < 0).astype(int)
    )
    out["smc_bias"] = out["smc_buy_score"] - out["smc_sell_score"]

    # ── ذيول الشمعات (Wick Analysis) ────────────────────────────────────────
    body_high = out[["open", "close"]].max(axis=1)
    body_low  = out[["open", "close"]].min(axis=1)
    candle_range = (out["high"] - out["low"]).clip(lower=1e-9)

    out["upper_wick"]       = (out["high"] - body_high).clip(lower=0)
    out["lower_wick"]       = (body_low - out["low"]).clip(lower=0)
    out["upper_wick_ratio"] = (out["upper_wick"] / candle_range).clip(0, 1)
    out["lower_wick_ratio"] = (out["lower_wick"] / candle_range).clip(0, 1)

    return out.bfill().fillna(0)


def latest_smc_snapshot(df):
    enriched = add_market_structure(df)
    row = enriched.iloc[-1]
    keys = [
        "bos_up",
        "bos_down",
        "choch_up",
        "choch_down",
        "buy_side_liquidity_sweep",
        "sell_side_liquidity_sweep",
        "bullish_fvg",
        "bearish_fvg",
        "ifvg_bull",
        "ifvg_bear",
        "in_bullish_ob",
        "in_bearish_ob",
        "demand_zone",
        "supply_zone",
        "smc_buy_score",
        "smc_sell_score",
        "smc_bias",
        "trend",
        "atr",
    ]
    return {key: float(row[key]) for key in keys}
