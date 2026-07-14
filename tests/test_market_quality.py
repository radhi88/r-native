"""
test_market_quality.py
----------------------
Unit tests for market_quality helpers:
  - current_market_session() — session boundary classification
  - spread_quality()         — spread label + ratio calculation

No MT5 or config dependencies needed for these pure-function tests.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mt5_ai.core.market_quality import current_market_session, spread_quality


# ── current_market_session ────────────────────────────────────────────────────

def _at_hour(h: int) -> datetime:
    return datetime(2024, 6, 15, h, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("hour,expected_session", [
    # London–NY overlap
    (12, "london_ny_overlap"),
    (13, "london_ny_overlap"),  # boundary
    # Asia–London overlap
    (6,  "asia_london_overlap"),
    # Asia
    (0,  "asia"),
    (3,  "asia"),
    # London (7–12)
    (7,  "london"),
    (10, "london"),
    # New York (13–19)
    (13, "london_ny_overlap"),  # 12–14 is overlap; 13 is in overlap
    (14, "new_york"),
    (19, "new_york"),
    # Off session
    (20, "off_session"),
    (23, "off_session"),
])
def test_session_at_hour(hour, expected_session):
    result = current_market_session(now=_at_hour(hour))
    assert result == expected_session


def test_session_uses_utc_when_no_arg():
    """Calling without arguments should not raise and return a known label."""
    valid_labels = {
        "london_ny_overlap", "asia_london_overlap", "asia",
        "london", "new_york", "off_session",
    }
    result = current_market_session()
    assert result in valid_labels


def test_session_boundary_hour_12():
    # 12 is start of london_ny_overlap, not london
    assert current_market_session(now=_at_hour(12)) == "london_ny_overlap"


def test_session_boundary_hour_6():
    # 6 is start of asia_london_overlap, not asia
    assert current_market_session(now=_at_hour(6)) == "asia_london_overlap"


def test_session_boundary_hour_7():
    # 7 is start of london
    assert current_market_session(now=_at_hour(7)) == "london"


def test_session_all_24_hours_return_valid_label():
    valid = {"london_ny_overlap", "asia_london_overlap", "asia",
             "london", "new_york", "off_session"}
    for h in range(24):
        label = current_market_session(now=_at_hour(h))
        assert label in valid, f"Hour {h} returned invalid label: {label!r}"


# ── spread_quality ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("spread,limit,expected_label", [
    # excellent: ratio ≤ 0.35
    (0,     350, "excellent"),
    (100,   350, "excellent"),   # 100/350 = 0.286
    (122,   350, "excellent"),   # 122/350 = 0.349
    # normal: 0.35 < ratio ≤ 0.70
    (123,   350, "normal"),      # 123/350 = 0.351
    (245,   350, "normal"),
    # wide: 0.70 < ratio ≤ 1.00
    (246,   350, "wide"),        # 246/350 = 0.703
    (350,   350, "wide"),        # 350/350 = 1.00
    # blocked: ratio > 1.00
    (351,   350, "blocked"),
    (9999,  350, "blocked"),
])
def test_spread_quality_labels(spread, limit, expected_label):
    result = spread_quality("XAUUSDm", spread, limit)
    assert result["spread_quality"] == expected_label


def test_spread_quality_returns_correct_ratio():
    result = spread_quality("EURUSDm", 175, 350)
    assert result["spread_ratio"] == pytest.approx(175 / 350, abs=1e-4)


def test_spread_quality_returns_limit():
    result = spread_quality("XAUUSDm", 100, 200)
    assert result["spread_limit"] == pytest.approx(200.0)


def test_spread_quality_zero_spread_is_excellent():
    result = spread_quality("XAUUSDm", 0, 350)
    assert result["spread_quality"] == "excellent"


def test_spread_quality_non_numeric_spread_returns_unknown():
    result = spread_quality("XAUUSDm", "bad", 350)
    assert result["spread_quality"] == "unknown"


def test_spread_quality_none_limit_falls_back_to_default():
    """When max_spread_points is None and config unavailable, uses 350 default."""
    with patch("mt5_ai.core.market_quality.get", side_effect=Exception("no config")):
        result = spread_quality("XAUUSDm", 100, None)
    assert result["spread_limit"] == pytest.approx(350.0)
    assert result["spread_quality"] == "excellent"


def test_spread_quality_zero_limit_clamped_to_1():
    """limit=0 is clamped to max(1.0, ...) to avoid ZeroDivisionError."""
    result = spread_quality("XAUUSDm", 10, 0)
    assert result["spread_quality"] == "blocked"   # 10/1 = 10 > 1
    assert result["spread_limit"] == pytest.approx(1.0)


def test_spread_quality_negative_limit_clamped():
    result = spread_quality("XAUUSDm", 10, -50)
    assert result["spread_limit"] == pytest.approx(1.0)
    assert result["spread_quality"] == "blocked"


@pytest.mark.parametrize("symbol", ["XAUUSDm", "EURUSDm", "BTCUSDm", "GBPJPYm"])
def test_spread_quality_symbol_passed_through(symbol):
    result = spread_quality(symbol, 100, 350)
    assert "spread_quality" in result


# ── Ratio precision ───────────────────────────────────────────────────────────

def test_spread_ratio_rounded_to_4_decimals():
    result = spread_quality("XAUUSDm", 1, 3)  # 0.3333...
    ratio = result["spread_ratio"]
    assert ratio == round(ratio, 4)


def test_spread_ratio_infinite_when_spread_unknown():
    result = spread_quality("XAUUSDm", "bad", 350)
    assert result["spread_quality"] == "unknown"
    # ratio should be inf
    import math
    assert math.isinf(result["spread_ratio"])
