"""Market-session and spread-quality helpers for Qader/FRIDAY runtimes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def current_market_session(now: datetime | None = None) -> str:
    """Return a coarse UTC session label used for logging and dashboard context."""
    current = now or datetime.now(timezone.utc)
    hour = current.astimezone(timezone.utc).hour
    if 12 <= hour < 14:
        return "london_ny_overlap"
    if 6 <= hour < 7:
        return "asia_london_overlap"
    if 0 <= hour < 7:
        return "asia"
    if 7 <= hour < 13:
        return "london"
    if 13 <= hour < 20:
        return "new_york"
    return "off_session"


def spread_quality(symbol: str, spread_points: float, max_spread_points: float | None = None) -> dict[str, Any]:
    """Classify spread without changing execution gates."""
    if max_spread_points is None:
        try:
            from .config_loader import get

            max_spread_points = (
                get(f"risk.max_spread_points.{symbol}")
                or get("risk.max_spread_points.default")
                or 350
            )
        except Exception:
            max_spread_points = 350

    try:
        spread = float(spread_points)
    except Exception:
        spread = float("inf")
    try:
        limit = max(1.0, float(max_spread_points or 350))
    except Exception:
        limit = 350.0

    ratio = spread / limit if spread != float("inf") else float("inf")
    if spread == float("inf"):
        label = "unknown"
    elif ratio <= 0.35:
        label = "excellent"
    elif ratio <= 0.70:
        label = "normal"
    elif ratio <= 1.00:
        label = "wide"
    else:
        label = "blocked"

    return {
        "spread_quality": label,
        "spread_limit": limit,
        "spread_ratio": round(ratio, 4) if ratio != float("inf") else ratio,
    }
