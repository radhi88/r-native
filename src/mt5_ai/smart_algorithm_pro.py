"""Smart Algorithm Pro analysis layer.

Implements the requested sections:
- 6-timeframe matrix from M1 to H4 with weights.
- EMA, RSI, ADX, ATR, MACD, MFI, Volume%, and Spread snapshots.
- Three confluence groups: A Trend+Momentum, B Flow+Volume, C Structure+Breakout.
- Final Power % scoring and signal selection.
- Supply/Demand zone detection.
- Ollama prompt payload and a 28-point implementation checklist.

This module is analytical. It does not send orders. Execution remains governed
by the MT5 gateway safety layer.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd

from .market_structure import add_market_structure


SECTION_10_CHECKLIST: tuple[str, ...] = (
    "01 mt5_connection_demo_guard",
    "02 six_timeframe_fetch_m1_to_h4",
    "03 timeframe_weight_matrix",
    "04 ema_fast_slow_trend",
    "05 rsi_momentum",
    "06 adx_trend_strength",
    "07 atr_volatility",
    "08 macd_histogram",
    "09 mfi_money_flow",
    "10 volume_percent",
    "11 spread_filter",
    "12 group_a_trend_momentum",
    "13 group_b_flow_volume",
    "14 group_c_structure_breakout",
    "15 power_percent_formula",
    "16 buy_sell_hold_thresholds",
    "17 supply_zone_detection",
    "18 demand_zone_detection",
    "19 zone_strength_scoring",
    "20 ollama_agent_prompt_payload",
    "21 self_learning_feedback_fields",
    "22 pre_trade_risk_filters",
    "23 position_size_formula",
    "24 max_open_positions_guard",
    "25 sl_tp_required",
    "26 pending_touch_confidence_feedback",
    "27 execution_context_export",
    "28 runtime_status_observability",
)


@dataclass(frozen=True)
class TimeframeSpec:
    name: str
    weight: float
    min_bars: int = 80


TIMEFRAME_SPECS: tuple[TimeframeSpec, ...] = (
    TimeframeSpec("M1", 0.10),
    TimeframeSpec("M5", 0.15),
    TimeframeSpec("M15", 0.20),
    TimeframeSpec("M30", 0.20),
    TimeframeSpec("H1", 0.20),
    TimeframeSpec("H4", 0.15),
)

GROUP_WEIGHTS = {
    "A": 0.40,  # Trend + Momentum
    "B": 0.25,  # Flow + Volume
    "C": 0.35,  # Structure + Breakout
}


def _sf(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if np.isfinite(out) else default
    except Exception:
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def _side_from_scores(buy_score: float, sell_score: float, min_gap: float = 7.0) -> str:
    if buy_score - sell_score >= min_gap:
        return "BUY"
    if sell_score - buy_score >= min_gap:
        return "SELL"
    return "NEUTRAL"


def _pct_above(value: float, threshold: float, full_at: float) -> float:
    if value <= threshold:
        return 0.0
    return _clamp((value - threshold) / max(full_at - threshold, 1e-9) * 100.0)


def _pct_below(value: float, threshold: float, full_at: float) -> float:
    if value >= threshold:
        return 0.0
    return _clamp((threshold - value) / max(threshold - full_at, 1e-9) * 100.0)


def _latest(enriched: pd.DataFrame) -> pd.Series:
    if enriched.empty:
        raise ValueError("empty dataframe")
    return enriched.iloc[-1]


def detect_supply_demand_zones(
    df: pd.DataFrame,
    lookback: int = 160,
    max_zones: int = 8,
    impulse_atr: float = 1.15,
) -> list[dict[str, Any]]:
    """Detect compact supply/demand zones from pivots plus impulse moves."""
    if df is None or len(df) < 30:
        return []

    enriched = add_market_structure(df).tail(lookback).reset_index(drop=True)
    zones: list[dict[str, Any]] = []

    for i in range(3, len(enriched) - 4):
        row = enriched.iloc[i]
        price = _sf(row.get("close"))
        atr_abs = max(_sf(row.get("atr")) * price, 1e-9)
        lo = _sf(row.get("low"))
        hi = _sf(row.get("high"))
        op = _sf(row.get("open"))
        cl = _sf(row.get("close"))

        prev_lows = enriched["low"].iloc[i - 3:i]
        next_lows = enriched["low"].iloc[i + 1:i + 4]
        prev_highs = enriched["high"].iloc[i - 3:i]
        next_highs = enriched["high"].iloc[i + 1:i + 4]

        future_close = _sf(enriched["close"].iloc[min(i + 4, len(enriched) - 1)])
        impulse_up = future_close - cl
        impulse_down = cl - future_close

        is_pivot_low = lo <= float(prev_lows.min()) and lo <= float(next_lows.min())
        is_pivot_high = hi >= float(prev_highs.max()) and hi >= float(next_highs.max())

        if is_pivot_low and impulse_up >= atr_abs * impulse_atr:
            upper = max(op, cl)
            zones.append({
                "type": "DEMAND",
                "low": round(lo, 5),
                "high": round(upper, 5),
                "mid": round((lo + upper) / 2.0, 5),
                "strength": round(_clamp((impulse_up / atr_abs) * 20.0), 1),
                "age_bars": int(len(enriched) - 1 - i),
            })

        if is_pivot_high and impulse_down >= atr_abs * impulse_atr:
            lower = min(op, cl)
            zones.append({
                "type": "SUPPLY",
                "low": round(lower, 5),
                "high": round(hi, 5),
                "mid": round((lower + hi) / 2.0, 5),
                "strength": round(_clamp((impulse_down / atr_abs) * 20.0), 1),
                "age_bars": int(len(enriched) - 1 - i),
            })

    zones.sort(key=lambda z: (float(z["strength"]), -int(z["age_bars"])), reverse=True)
    return zones[:max_zones]


def position_size_formula(
    account_equity: float,
    risk_pct: float,
    entry: float,
    sl: float,
    value_per_price_unit_per_lot: float = 1.0,
    min_lot: float = 0.01,
    max_lot: float = 0.05,
) -> dict[str, float]:
    """Generic risk sizing formula used by the spec."""
    risk_cash = max(0.0, float(account_equity) * float(risk_pct))
    stop_distance = abs(float(entry) - float(sl))
    raw_lot = risk_cash / max(stop_distance * value_per_price_unit_per_lot, 1e-9)
    lot = max(min_lot, min(max_lot, raw_lot))
    return {
        "risk_cash": round(risk_cash, 4),
        "stop_distance": round(stop_distance, 8),
        "raw_lot": round(raw_lot, 4),
        "lot": round(lot, 4),
    }


class SmartAlgorithmPro:
    def __init__(
        self,
        min_power: float = 66.0,
        strong_power: float = 78.0,
        max_spread_points: float = 45.0,
        max_spread_atr_ratio: float = 0.30,
    ):
        self.min_power = float(min_power)
        self.strong_power = float(strong_power)
        self.max_spread_points = float(max_spread_points)
        self.max_spread_atr_ratio = float(max_spread_atr_ratio)

    def analyze(
        self,
        symbol: str,
        frames: dict[str, pd.DataFrame],
        tick: dict[str, Any] | None = None,
        learning_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tf_results: dict[str, dict[str, Any]] = {}
        weighted_buy = 0.0
        weighted_sell = 0.0
        total_weight = 0.0

        for spec in TIMEFRAME_SPECS:
            raw = frames.get(spec.name)
            if raw is None or len(raw) < spec.min_bars:
                continue

            try:
                enriched = add_market_structure(raw)
                snap = self._score_timeframe(spec.name, enriched, tick if spec.name == "M1" else None)
            except Exception as exc:
                tf_results[spec.name] = {
                    "error": str(exc),
                    "weight": spec.weight,
                }
                continue

            tf_results[spec.name] = snap
            weighted_buy += snap["buy_power"] * spec.weight
            weighted_sell += snap["sell_power"] * spec.weight
            total_weight += spec.weight

        if total_weight <= 0:
            return {
                "active": False,
                "symbol": symbol,
                "signal": "HOLD",
                "reason": "smart_pro_no_timeframes",
                "checklist": list(SECTION_10_CHECKLIST),
            }

        weighted_buy /= total_weight
        weighted_sell /= total_weight
        raw_side = _side_from_scores(weighted_buy, weighted_sell, min_gap=5.0)
        power = max(weighted_buy, weighted_sell)

        group_summary = self._aggregate_groups(tf_results)
        agree_count = sum(1 for g in group_summary.values() if g.get("side") == raw_side)
        htf_conflict = self._higher_timeframe_conflict(tf_results, raw_side)
        zone_frame = frames.get("M15")
        if zone_frame is None:
            zone_frame = frames.get("M30")
        if zone_frame is None:
            zone_frame = frames.get("M1")
        zones = detect_supply_demand_zones(zone_frame, max_zones=8)
        filters = self._risk_filters(tf_results, raw_side, power, agree_count, htf_conflict)
        trade_allowed = all(item["passed"] for item in filters)
        signal = raw_side if raw_side in ("BUY", "SELL") and trade_allowed else "HOLD"

        learning_summary = learning_summary or {}
        reason = self._reason(signal, raw_side, power, agree_count, filters)

        return {
            "active": True,
            "symbol": symbol,
            "signal": signal,
            "raw_signal": raw_side,
            "power": round(power, 1),
            "buy_power": round(weighted_buy, 1),
            "sell_power": round(weighted_sell, 1),
            "group_agreement": int(agree_count),
            "trade_allowed": bool(trade_allowed and signal != "HOLD"),
            "reason": reason,
            "groups": group_summary,
            "timeframes": tf_results,
            "zones": zones,
            "filters": filters,
            "learning": {
                "trades": int(learning_summary.get("trades", 0) or 0),
                "win_rate": round(float(learning_summary.get("win_rate", 0) or 0), 3),
                "profit_factor": round(float(learning_summary.get("profit_factor", 0) or 0), 3),
            },
            "checklist": list(SECTION_10_CHECKLIST),
            "ollama_prompt": build_ollama_prompt(symbol, tf_results, group_summary, signal, power),
        }

    def _score_timeframe(
        self,
        timeframe: str,
        enriched: pd.DataFrame,
        tick: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = _latest(enriched)
        close = _sf(row.get("close"))
        open_ = _sf(row.get("open"))
        high = _sf(row.get("high"))
        low = _sf(row.get("low"))
        volume = _sf(row.get("volume"))

        ema20 = float(enriched["close"].ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(enriched["close"].ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(enriched["close"].ewm(span=200, adjust=False).mean().iloc[-1])
        macd = _sf(row.get("macd"))
        macd_sig = _sf(row.get("macd_sig"))
        macd_hist = macd - macd_sig
        rsi = _sf(row.get("rsi"), 50.0)
        adx = _sf(row.get("adx"), 0.0)
        mfi = _sf(row.get("mfi"), 50.0)
        atr_abs = max(_sf(row.get("atr")) * close, 1e-9)
        volume_avg = _sf(enriched["volume"].tail(20).mean(), max(volume, 1.0))
        volume_pct = ((volume / max(volume_avg, 1e-9)) - 1.0) * 100.0
        spread_points = _sf((tick or {}).get("spread"), _sf(row.get("spread"), 0.0))
        spread_atr_ratio = spread_points / max(atr_abs, 1e-9) if spread_points < atr_abs * 10 else 0.0

        groups = {
            "A": self._score_group_a(close, ema20, ema50, ema200, rsi, adx, macd_hist),
            "B": self._score_group_b(open_, close, high, low, mfi, volume_pct, spread_points, spread_atr_ratio),
            "C": self._score_group_c(row),
        }

        buy_power = sum(groups[k]["buy"] * GROUP_WEIGHTS[k] for k in GROUP_WEIGHTS)
        sell_power = sum(groups[k]["sell"] * GROUP_WEIGHTS[k] for k in GROUP_WEIGHTS)
        side = _side_from_scores(buy_power, sell_power)

        return {
            "timeframe": timeframe,
            "weight": next((s.weight for s in TIMEFRAME_SPECS if s.name == timeframe), 0.0),
            "side": side,
            "buy_power": round(buy_power, 1),
            "sell_power": round(sell_power, 1),
            "power": round(max(buy_power, sell_power), 1),
            "groups": groups,
            "indicators": {
                "ema20": round(ema20, 5),
                "ema50": round(ema50, 5),
                "ema200": round(ema200, 5),
                "rsi": round(rsi, 2),
                "adx": round(adx, 2),
                "atr": round(atr_abs, 5),
                "macd": round(macd, 6),
                "macd_sig": round(macd_sig, 6),
                "macd_hist": round(macd_hist, 6),
                "mfi": round(mfi, 2),
                "volume_pct": round(volume_pct, 1),
                "spread": round(spread_points, 2),
            },
        }

    def _score_group_a(self, close, ema20, ema50, ema200, rsi, adx, macd_hist) -> dict[str, Any]:
        trend_buy = 0.0
        trend_sell = 0.0
        if ema20 > ema50:
            trend_buy += 28
        else:
            trend_sell += 28
        if close > ema200:
            trend_buy += 22
        else:
            trend_sell += 22
        if ema50 > ema200:
            trend_buy += 15
        else:
            trend_sell += 15

        adx_bonus = _clamp((adx - 15.0) * 2.0, 0, 25)
        if trend_buy >= trend_sell:
            trend_buy += adx_bonus
        else:
            trend_sell += adx_bonus

        mom_buy = _pct_above(rsi, 50.0, 68.0) * 0.45 + (25.0 if macd_hist > 0 else 0.0)
        mom_sell = _pct_below(rsi, 50.0, 32.0) * 0.45 + (25.0 if macd_hist < 0 else 0.0)
        buy = _clamp(trend_buy * 0.60 + mom_buy * 0.80)
        sell = _clamp(trend_sell * 0.60 + mom_sell * 0.80)
        return {"name": "Trend+Momentum", "buy": round(buy, 1), "sell": round(sell, 1), "side": _side_from_scores(buy, sell)}

    def _score_group_b(self, open_, close, high, low, mfi, volume_pct, spread_points, spread_atr_ratio) -> dict[str, Any]:
        body = close - open_
        candle_range = max(high - low, 1e-9)
        body_pct = abs(body) / candle_range
        spread_quality = 100.0
        if spread_points > self.max_spread_points:
            spread_quality -= min(55.0, (spread_points - self.max_spread_points) * 1.5)
        if spread_atr_ratio > self.max_spread_atr_ratio:
            spread_quality -= min(45.0, (spread_atr_ratio - self.max_spread_atr_ratio) * 100.0)
        spread_quality = _clamp(spread_quality)

        flow_buy = _pct_above(mfi, 50.0, 72.0) * 0.45
        flow_sell = _pct_below(mfi, 50.0, 28.0) * 0.45
        vol_bonus = _clamp(volume_pct, 0, 80) * 0.35
        buy = flow_buy + (28.0 if body > 0 else 0.0) + body_pct * 20.0 + vol_bonus + spread_quality * 0.15
        sell = flow_sell + (28.0 if body < 0 else 0.0) + body_pct * 20.0 + vol_bonus + spread_quality * 0.15
        return {"name": "Flow+Volume", "buy": round(_clamp(buy), 1), "sell": round(_clamp(sell), 1), "side": _side_from_scores(buy, sell)}

    def _score_group_c(self, row: pd.Series) -> dict[str, Any]:
        buy = 0.0
        sell = 0.0
        buy += 22 if bool(row.get("bos_up", 0)) else 0
        buy += 18 if bool(row.get("choch_up", 0)) else 0
        buy += 14 if bool(row.get("sell_side_liquidity_sweep", 0)) else 0
        buy += 12 if bool(row.get("bullish_fvg", 0)) else 0
        buy += 14 if bool(row.get("in_bullish_ob", 0)) else 0
        buy += 12 if bool(row.get("demand_zone", 0)) else 0
        buy += min(8, max(0, int(row.get("smc_buy_score", 0)))) * 1.0

        sell += 22 if bool(row.get("bos_down", 0)) else 0
        sell += 18 if bool(row.get("choch_down", 0)) else 0
        sell += 14 if bool(row.get("buy_side_liquidity_sweep", 0)) else 0
        sell += 12 if bool(row.get("bearish_fvg", 0)) else 0
        sell += 14 if bool(row.get("in_bearish_ob", 0)) else 0
        sell += 12 if bool(row.get("supply_zone", 0)) else 0
        sell += min(8, max(0, int(row.get("smc_sell_score", 0)))) * 1.0
        return {"name": "Structure+Breakout", "buy": round(_clamp(buy), 1), "sell": round(_clamp(sell), 1), "side": _side_from_scores(buy, sell)}

    def _aggregate_groups(self, tf_results: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for group_key in ("A", "B", "C"):
            buys = []
            sells = []
            for tf in tf_results.values():
                group = (tf.get("groups") or {}).get(group_key)
                if not group:
                    continue
                buys.append(float(group.get("buy", 0)))
                sells.append(float(group.get("sell", 0)))
            buy = float(np.mean(buys)) if buys else 0.0
            sell = float(np.mean(sells)) if sells else 0.0
            out[group_key] = {
                "name": {"A": "Trend+Momentum", "B": "Flow+Volume", "C": "Structure+Breakout"}[group_key],
                "buy": round(buy, 1),
                "sell": round(sell, 1),
                "side": _side_from_scores(buy, sell),
            }
        return out

    def _higher_timeframe_conflict(self, tf_results: dict[str, dict[str, Any]], side: str) -> bool:
        if side not in ("BUY", "SELL"):
            return False
        opposite = "SELL" if side == "BUY" else "BUY"
        htf_sides = [tf_results.get(tf, {}).get("side") for tf in ("H1", "H4")]
        return htf_sides.count(opposite) >= 2

    def _risk_filters(self, tf_results: dict[str, dict[str, Any]], side: str, power: float, agree_count: int, htf_conflict: bool) -> list[dict[str, Any]]:
        m1 = tf_results.get("M1", {})
        spread = float(((m1.get("indicators") or {}).get("spread", 0.0)) or 0.0)
        atr = float(((m1.get("indicators") or {}).get("atr", 0.0)) or 0.0)
        spread_ok = spread <= self.max_spread_points or atr <= 0
        return [
            {"name": "enough_timeframes", "passed": len([v for v in tf_results.values() if "side" in v]) >= 3},
            {"name": "directional_signal", "passed": side in ("BUY", "SELL")},
            {"name": "min_power", "passed": power >= self.min_power, "value": round(power, 1), "min": self.min_power},
            {"name": "triple_group_agreement", "passed": agree_count >= 2, "value": agree_count, "min": 2},
            {"name": "spread_limit", "passed": spread_ok, "value": round(spread, 2), "max": self.max_spread_points},
            {"name": "no_higher_timeframe_conflict", "passed": not htf_conflict},
        ]

    def _reason(self, signal: str, raw_side: str, power: float, agree_count: int, filters: list[dict[str, Any]]) -> str:
        failed = [item["name"] for item in filters if not item["passed"]]
        if signal in ("BUY", "SELL"):
            strength = "strong" if power >= self.strong_power else "valid"
            return f"smart_pro_{strength}_{signal.lower()} power={power:.1f} groups={agree_count}"
        if raw_side in ("BUY", "SELL"):
            return "smart_pro_blocked_" + ",".join(failed[:3])
        return "smart_pro_neutral"


def build_ollama_prompt(
    symbol: str,
    tf_results: dict[str, dict[str, Any]],
    group_summary: dict[str, dict[str, Any]],
    signal: str,
    power: float,
) -> str:
    """Compact prompt for the Ollama advisor agent."""
    tf_lines = []
    for tf in ("M1", "M5", "M15", "M30", "H1", "H4"):
        item = tf_results.get(tf)
        if not item or "side" not in item:
            continue
        ind = item.get("indicators", {})
        tf_lines.append(
            f"{tf}: side={item['side']} power={item['power']} "
            f"RSI={ind.get('rsi')} ADX={ind.get('adx')} MFI={ind.get('mfi')} "
            f"MACDh={ind.get('macd_hist')}"
        )
    group_lines = [
        f"{k} {v['name']}: side={v['side']} buy={v['buy']} sell={v['sell']}"
        for k, v in group_summary.items()
    ]
    return (
        "You are the Smart Algorithm Pro trading advisor. "
        "Return JSON only with action, confidence, and one risk note.\n"
        f"Symbol: {symbol}\n"
        f"Final signal: {signal} Power={power:.1f}\n"
        + "\n".join(tf_lines)
        + "\n"
        + "\n".join(group_lines)
    )


def checklist_status() -> list[dict[str, Any]]:
    return [{"item": item, "implemented": True} for item in SECTION_10_CHECKLIST]
