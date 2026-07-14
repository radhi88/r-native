"""
Daily Pivot Channels confirmation layer.

This module is decision support only:
- it never creates a BUY/SELL direction from HOLD/NO_TRADE,
- it never reverses an existing direction,
- it only boosts confidence when the pivot zone agrees with the existing signal.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any

from .config import (
    PIVOT_BIAS_BOOST,
    PIVOT_CONFIDENCE_BOOST,
    PIVOT_PENDING_DISTANCE_POINTS,
    PIVOT_TOUCH_TOLERANCE_POINTS,
    USE_MID_PIVOT_LEVELS,
    USE_PIVOT_CONFIDENCE_BOOST,
    USE_PIVOT_FILTER,
)

log = logging.getLogger("friday.pivot")

PIVOT_LEVEL_KEYS = ("PP", "R1", "R2", "S1", "S2", "M1", "M2", "M3", "M4")
BASE_SUPPORT_KEYS = ("S1", "S2")
MID_SUPPORT_KEYS = ("M1", "M2")
BASE_RESISTANCE_KEYS = ("R1", "R2")
MID_RESISTANCE_KEYS = ("M3", "M4")
PIVOT_MARKET_CONFIDENCE_MIN = 0.65


def _clamp_confidence(confidence: float) -> float:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        value = 0.0
    return max(0.0, min(1.0, value))


def _candle_value(candle: Any, *names: str) -> float:
    """Read a numeric OHLC value from dicts, pandas Series, or simple objects."""
    if isinstance(candle, Mapping):
        for name in names:
            if name in candle:
                return float(candle[name])
            lower_name = name.lower()
            if lower_name in candle:
                return float(candle[lower_name])
            upper_name = name.upper()
            if upper_name in candle:
                return float(candle[upper_name])

    getter = getattr(candle, "get", None)
    if callable(getter):
        for name in names:
            value = getter(name, None)
            if value is not None:
                return float(value)
            value = getter(name.lower(), None)
            if value is not None:
                return float(value)
            value = getter(name.upper(), None)
            if value is not None:
                return float(value)

    for name in names:
        if hasattr(candle, name):
            return float(getattr(candle, name))
        lower_name = name.lower()
        if hasattr(candle, lower_name):
            return float(getattr(candle, lower_name))

    raise KeyError(f"Missing candle value. Tried: {', '.join(names)}")


def _support_keys() -> tuple[str, ...]:
    return BASE_SUPPORT_KEYS + (MID_SUPPORT_KEYS if USE_MID_PIVOT_LEVELS else ())


def _resistance_keys() -> tuple[str, ...]:
    return BASE_RESISTANCE_KEYS + (MID_RESISTANCE_KEYS if USE_MID_PIVOT_LEVELS else ())


def calculate_daily_pivots(previous_daily_candle: Any, prev_low: float | None = None, prev_close: float | None = None) -> dict:
    """
    Calculate PP, R1, R2, S1, S2, M1, M2, M3, M4 from the previous completed D1 candle.

    Accepts either a candle-like object containing high/low/close, or the legacy
    numeric form calculate_daily_pivots(high, low, close).
    """
    if prev_low is not None and prev_close is not None:
        high = float(previous_daily_candle)
        low = float(prev_low)
        close = float(prev_close)
    else:
        high = _candle_value(previous_daily_candle, "high", "High", "HIGH")
        low = _candle_value(previous_daily_candle, "low", "Low", "LOW")
        close = _candle_value(previous_daily_candle, "close", "Close", "CLOSE")

    pp = (high + low + close) / 3.0
    r1 = 2.0 * pp - low
    r2 = pp + (high - low)
    s1 = 2.0 * pp - high
    s2 = pp - (high - low)
    m1 = (s1 + s2) / 2.0
    m2 = (s1 + pp) / 2.0
    m3 = (r1 + pp) / 2.0
    m4 = (r1 + r2) / 2.0

    return {
        "PP": round(pp, 10),
        "R1": round(r1, 10),
        "R2": round(r2, 10),
        "S1": round(s1, 10),
        "S2": round(s2, 10),
        "M1": round(m1, 10),
        "M2": round(m2, 10),
        "M3": round(m3, 10),
        "M4": round(m4, 10),
    }


def get_nearest_pivot(price: float, pivot_levels: dict) -> tuple[str, float | None]:
    """Return the nearest pivot name and price."""
    if not pivot_levels:
        return "NONE", None

    valid_levels = {
        name: float(value)
        for name, value in pivot_levels.items()
        if name in PIVOT_LEVEL_KEYS and value is not None
    }
    if not valid_levels:
        return "NONE", None

    name = min(valid_levels, key=lambda key: abs(valid_levels[key] - float(price)))
    return name, valid_levels[name]


def is_near_level(price: float, level: float, tolerance_points: int, point_size: float) -> bool:
    """True when price is within tolerance_points * point_size of level."""
    point = abs(float(point_size)) or 0.00001
    return abs(float(price) - float(level)) <= int(tolerance_points) * point


def get_pivot_zone(
    price: float,
    pivot_levels: dict,
    point_size: float,
    tolerance_points: int = PIVOT_TOUCH_TOLERANCE_POINTS,
) -> dict:
    """Classify current price as support, resistance, or neutral relative to pivots."""
    if not pivot_levels:
        return {
            "zone": "neutral",
            "near_supports": [],
            "near_resistances": [],
            "near_levels": [],
            "above_pp": False,
            "pp": None,
        }

    current = float(price)
    pp = pivot_levels.get("PP")
    above_pp = bool(pp is not None and current > float(pp))

    near_supports = [
        key
        for key in _support_keys()
        if key in pivot_levels
        and is_near_level(current, float(pivot_levels[key]), tolerance_points, point_size)
    ]
    near_resistances = [
        key
        for key in _resistance_keys()
        if key in pivot_levels
        and is_near_level(current, float(pivot_levels[key]), tolerance_points, point_size)
    ]

    zone = "support" if near_supports else ("resistance" if near_resistances else "neutral")
    return {
        "zone": zone,
        "near_supports": near_supports,
        "near_resistances": near_resistances,
        "near_levels": near_supports + near_resistances,
        "above_pp": above_pp,
        "pp": float(pp) if pp is not None else None,
    }


def apply_pivot_confidence(
    signal: str,
    confidence: float,
    price: float,
    pivot_levels: dict,
    point_size: float = 0.01,
    tolerance_points: int = PIVOT_TOUCH_TOLERANCE_POINTS,
    conf_boost: float = PIVOT_CONFIDENCE_BOOST,
    bias_boost: float = PIVOT_BIAS_BOOST,
) -> tuple[str, float, str]:
    """
    Return (updated_signal, updated_confidence, pivot_reason).

    The signal is returned unchanged. Pivot levels only increase confidence when
    they agree with an existing BUY/SELL decision.
    """
    normalized_signal = str(signal or "HOLD").upper()
    updated_confidence = _clamp_confidence(confidence)

    if not USE_PIVOT_FILTER:
        return normalized_signal, updated_confidence, "pivot_disabled"
    if not pivot_levels:
        return normalized_signal, updated_confidence, "pivot_levels_unavailable"
    if normalized_signal not in {"BUY", "SELL"}:
        return normalized_signal, updated_confidence, "no_existing_trade_signal"

    zone = get_pivot_zone(float(price), pivot_levels, point_size, tolerance_points)
    reasons: list[str] = []

    if normalized_signal == "BUY":
        if USE_PIVOT_CONFIDENCE_BOOST and zone["near_supports"]:
            updated_confidence = min(1.0, updated_confidence + float(conf_boost))
            reasons.append(
                "buy_confidence_boost_from_support_pivot:"
                + ",".join(zone["near_supports"])
            )
        if zone["pp"] is not None and float(price) > float(zone["pp"]):
            updated_confidence = min(1.0, updated_confidence + float(bias_boost))
            reasons.append("bullish_bias_above_PP")

    if normalized_signal == "SELL":
        if USE_PIVOT_CONFIDENCE_BOOST and zone["near_resistances"]:
            updated_confidence = min(1.0, updated_confidence + float(conf_boost))
            reasons.append(
                "sell_confidence_boost_from_resistance_pivot:"
                + ",".join(zone["near_resistances"])
            )
        if zone["pp"] is not None and float(price) < float(zone["pp"]):
            updated_confidence = min(1.0, updated_confidence + float(bias_boost))
            reasons.append("bearish_bias_below_PP")

    return normalized_signal, round(updated_confidence, 4), "|".join(reasons) if reasons else "no_pivot_boost"


def _nearest_directional_level(
    price: float,
    pivot_levels: dict,
    keys: tuple[str, ...],
    *,
    below_or_equal: bool,
) -> tuple[str, float | None]:
    current = float(price)
    candidates = {}
    for key in keys:
        if key not in pivot_levels:
            continue
        level = float(pivot_levels[key])
        if below_or_equal and level <= current:
            candidates[key] = level
        if not below_or_equal and level >= current:
            candidates[key] = level

    if not candidates:
        return "NONE", None

    name = min(candidates, key=lambda key: abs(candidates[key] - current))
    return name, candidates[name]


def _recommend_order(
    signal: str,
    confidence: float,
    price: float,
    pivot_levels: dict,
    point_size: float,
    zone: dict,
    tolerance_points: int,
    pending_distance_points: int,
) -> tuple[str, float | None]:
    if signal not in {"BUY", "SELL"} or not pivot_levels:
        return "NONE", None

    current = float(price)
    point = abs(float(point_size)) or 0.00001

    if signal == "BUY":
        support_name, support_price = _nearest_directional_level(
            current, pivot_levels, _support_keys(), below_or_equal=True
        )
        if support_price is None:
            return "NONE", None

        distance_points = abs(current - support_price) / point
        if zone["near_supports"] and confidence >= PIVOT_MARKET_CONFIDENCE_MIN:
            return "BUY_MARKET", current
        if support_name != "NONE" and support_price < current and distance_points <= pending_distance_points:
            return "BUY_LIMIT", support_price
        return "NONE", None

    resistance_name, resistance_price = _nearest_directional_level(
        current, pivot_levels, _resistance_keys(), below_or_equal=False
    )
    if resistance_price is None:
        return "NONE", None

    distance_points = abs(resistance_price - current) / point
    if zone["near_resistances"] and confidence >= PIVOT_MARKET_CONFIDENCE_MIN:
        return "SELL_MARKET", current
    if resistance_name != "NONE" and resistance_price > current and distance_points <= pending_distance_points:
        return "SELL_LIMIT", resistance_price
    return "NONE", None


def build_pivot_signal_output(
    signal: str,
    confidence: float,
    price: float,
    pivot_levels: dict,
    point_size: float = 0.01,
    tolerance_points: int = PIVOT_TOUCH_TOLERANCE_POINTS,
    pending_distance_points: int = PIVOT_PENDING_DISTANCE_POINTS,
) -> dict:
    """Return the full pivot decision-support payload used by trading scripts."""
    updated_signal, updated_confidence, pivot_reason = apply_pivot_confidence(
        signal=signal,
        confidence=confidence,
        price=price,
        pivot_levels=pivot_levels,
        point_size=point_size,
        tolerance_points=tolerance_points,
    )
    zone = get_pivot_zone(float(price), pivot_levels, point_size, tolerance_points)
    nearest_name, nearest_price = get_nearest_pivot(float(price), pivot_levels)
    recommended_order, recommended_entry = _recommend_order(
        signal=updated_signal,
        confidence=updated_confidence,
        price=float(price),
        pivot_levels=pivot_levels,
        point_size=point_size,
        zone=zone,
        tolerance_points=tolerance_points,
        pending_distance_points=pending_distance_points,
    )

    return {
        "signal": updated_signal,
        "confidence": updated_confidence,
        "pivot_reason": pivot_reason,
        "nearest_pivot": nearest_name,
        "nearest_pivot_price": nearest_price,
        "pivot_zone": zone["zone"],
        "recommended_order": recommended_order,
        "recommended_entry_price": recommended_entry,
        "above_pp": zone["above_pp"],
        "near_levels": zone["near_levels"],
        "pivot_levels": dict(pivot_levels or {}),
        "threshold_reduction": 0.0,
    }


class PivotEngine:
    """Stateful daily pivot cache recalculated once per new MT5 trading day."""

    def __init__(self, gateway, symbol: str, point_size: float = 0.01):
        self.gw = gateway
        self.symbol = symbol
        self.point_size = float(point_size) if point_size else 0.01
        self._levels: dict = {}
        self._calc_date: date | None = None
        self._prev_info: dict = {}
        self.pivot_levels: dict = self._levels

    def update(self) -> dict:
        """Recalculate from the previous completed D1 candle once per new trading day."""
        fallback_today = datetime.now(timezone.utc).date()

        for timeframe, bars in (("D1", 3), ("H4", 20), ("H1", 72)):
            try:
                df = self.gw.fetch_rates(self.symbol, timeframe, bars)
                if df is None or len(df) < 2:
                    continue

                if timeframe == "D1":
                    trading_day = self._date_from_value(df.iloc[-1].get("time"), fallback_today)
                    if self._calc_date == trading_day and self._levels:
                        return self._levels
                    previous_candle = df.iloc[-2]
                    prev_info = {
                        "high": _candle_value(previous_candle, "high"),
                        "low": _candle_value(previous_candle, "low"),
                        "close": _candle_value(previous_candle, "close"),
                        "time": str(previous_candle.get("time", "")),
                        "timeframe": "D1",
                    }
                else:
                    previous_candle, prev_info, trading_day = self._aggregate_previous_daily_candle(
                        df, timeframe, fallback_today
                    )
                    if self._calc_date == trading_day and self._levels:
                        return self._levels
                    if not previous_candle:
                        continue

                self._levels = calculate_daily_pivots(previous_candle)
                self.pivot_levels = self._levels
                self._prev_info = prev_info
                self._calc_date = trading_day

                log.info(
                    "[Pivot] %s %s PP=%.5f S1=%.5f S2=%.5f R1=%.5f R2=%.5f",
                    self.symbol,
                    timeframe,
                    self._levels["PP"],
                    self._levels["S1"],
                    self._levels["S2"],
                    self._levels["R1"],
                    self._levels["R2"],
                )
                return self._levels
            except Exception as exc:
                log.warning("[Pivot] update failed for %s %s: %s", self.symbol, timeframe, exc)

        return self._levels

    @staticmethod
    def _date_from_value(value, default: date) -> date:
        if value is None:
            return default
        try:
            if hasattr(value, "date"):
                return value.date()
            import pandas as pd

            return pd.to_datetime(value).date()
        except Exception:
            return default

    @staticmethod
    def _aggregate_previous_daily_candle(df, timeframe: str, default_day: date) -> tuple[dict, dict, date]:
        import pandas as pd

        times = pd.to_datetime(df["time"], utc=True)
        bar_dates = times.dt.date
        unique_dates = sorted(set(bar_dates))
        if len(unique_dates) < 2:
            return {}, {}, default_day

        trading_day = unique_dates[-1]
        previous_date = unique_dates[-2]
        previous_bars = df[bar_dates == previous_date]
        if len(previous_bars) == 0:
            return {}, {}, trading_day

        candle = {
            "high": float(previous_bars["high"].max()),
            "low": float(previous_bars["low"].min()),
            "close": float(previous_bars["close"].iloc[-1]),
        }
        info = {
            **candle,
            "time": str(previous_date),
            "timeframe": f"{timeframe}_aggregated_to_D1",
        }
        return candle, info, trading_day

    def apply(self, signal: str, confidence: float, price: float) -> dict:
        """Update cached levels if needed, then return the full pivot support payload."""
        levels = self.update()
        return build_pivot_signal_output(
            signal=signal,
            confidence=confidence,
            price=price,
            pivot_levels=levels,
            point_size=self.point_size,
        )

    @property
    def levels(self) -> dict:
        return self._levels

    def status(self) -> dict:
        return {
            "pivot_levels": self._levels,
            "levels": self._levels,
            "calc_date": str(self._calc_date),
            "prev_candle": self._prev_info,
        }
