"""Cross-market bias rules for FRIDAY/GADER.

The rules are intentionally small and explicit. They do not replace the normal
SMC/risk pipeline; they only provide a directional bias that the orchestrator
can use as confirmation or as a guarded setup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


DEFAULT_LEADER = "XAUUSDm"
ENERGY_FOLLOWERS = ("USOILm", "UKOILm", "XNGUSDm")


@dataclass(frozen=True)
class CrossMarketRule:
    leader_symbol: str = DEFAULT_LEADER
    follower_symbols: tuple[str, ...] = ENERGY_FOLLOWERS
    lookback_bars: int = 5
    min_leader_atr_move: float = 0.35


def is_energy_symbol(symbol: str, followers: Iterable[str] = ENERGY_FOLLOWERS) -> bool:
    sym = str(symbol or "").upper()
    return any(sym == str(item).upper() for item in followers)


def _atr_like(df: pd.DataFrame, lookback: int) -> float:
    if "atr" in df.columns:
        val = float(df["atr"].tail(lookback).mean())
        if val > 0:
            return val

    recent = df.tail(max(lookback + 1, 2))
    ranges = (recent["high"].astype(float) - recent["low"].astype(float)).abs()
    val = float(ranges.mean()) if len(ranges) else 0.0
    return val if val > 0 else 1e-9


def gold_to_energy_bias(
    follower_symbol: str,
    gold_df: pd.DataFrame | None,
    rule: CrossMarketRule | None = None,
) -> dict:
    """Return BUY/SELL bias for oil/energy symbols from recent gold movement.

    Current operator rule:
    - Gold down strongly -> BUY oil/energy
    - Gold up strongly   -> SELL oil/energy
    """
    rule = rule or CrossMarketRule()
    if not is_energy_symbol(follower_symbol, rule.follower_symbols):
        return {"active": False, "reason": "not_energy_follower"}

    if gold_df is None or len(gold_df) < rule.lookback_bars + 1:
        return {"active": False, "reason": "gold_data_unavailable"}

    closes = gold_df["close"].astype(float)
    now = float(closes.iloc[-1])
    prev = float(closes.iloc[-1 - rule.lookback_bars])
    move = now - prev
    atr = _atr_like(gold_df, rule.lookback_bars)
    atr_move = move / atr if atr > 0 else 0.0

    if abs(atr_move) < rule.min_leader_atr_move:
        return {
            "active": False,
            "leader": rule.leader_symbol,
            "follower": follower_symbol,
            "leader_move": move,
            "leader_atr_move": atr_move,
            "reason": "gold_move_too_small",
        }

    side = "BUY" if atr_move < 0 else "SELL"
    direction = "down" if atr_move < 0 else "up"
    return {
        "active": True,
        "leader": rule.leader_symbol,
        "follower": follower_symbol,
        "side": side,
        "strength": min(abs(atr_move), 3.0) / 3.0,
        "leader_move": move,
        "leader_atr_move": atr_move,
        "reason": f"xau_{direction}_energy_{side.lower()}",
    }
