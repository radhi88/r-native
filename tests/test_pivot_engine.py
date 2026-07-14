import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mt5_ai.pivot_engine import (  # noqa: E402
    apply_pivot_confidence,
    build_pivot_signal_output,
    calculate_daily_pivots,
    get_nearest_pivot,
    get_pivot_zone,
    is_near_level,
)


class TestPivotEngine(unittest.TestCase):
    def setUp(self):
        self.candle = {"high": 110.0, "low": 90.0, "close": 100.0}
        self.levels = calculate_daily_pivots(self.candle)

    def test_calculates_daily_pivot_levels(self):
        self.assertEqual(self.levels["PP"], 100.0)
        self.assertEqual(self.levels["R1"], 110.0)
        self.assertEqual(self.levels["R2"], 120.0)
        self.assertEqual(self.levels["S1"], 90.0)
        self.assertEqual(self.levels["S2"], 80.0)
        self.assertEqual(self.levels["M1"], 85.0)
        self.assertEqual(self.levels["M2"], 95.0)
        self.assertEqual(self.levels["M3"], 105.0)
        self.assertEqual(self.levels["M4"], 115.0)

    def test_legacy_numeric_calculation_still_works(self):
        self.assertEqual(calculate_daily_pivots(110.0, 90.0, 100.0), self.levels)

    def test_near_level_and_zone(self):
        self.assertTrue(is_near_level(90.5, 90.0, tolerance_points=60, point_size=0.01))
        zone = get_pivot_zone(90.5, self.levels, point_size=0.01, tolerance_points=60)
        self.assertEqual(zone["zone"], "support")
        self.assertIn("S1", zone["near_supports"])

    def test_nearest_pivot(self):
        name, price = get_nearest_pivot(104.9, self.levels)
        self.assertEqual(name, "M3")
        self.assertEqual(price, 105.0)

    def test_pivot_does_not_create_trade_from_hold(self):
        signal, confidence, reason = apply_pivot_confidence(
            "HOLD", 0.2, 90.0, self.levels, point_size=0.01
        )
        self.assertEqual(signal, "HOLD")
        self.assertEqual(confidence, 0.2)
        self.assertEqual(reason, "no_existing_trade_signal")

    def test_buy_support_and_pp_bias_boost(self):
        signal, confidence, reason = apply_pivot_confidence(
            "BUY", 0.50, 100.5, self.levels, point_size=0.01, tolerance_points=1200
        )
        self.assertEqual(signal, "BUY")
        self.assertAlmostEqual(confidence, 0.70)
        self.assertIn("buy_confidence_boost_from_support_pivot", reason)
        self.assertIn("bullish_bias_above_PP", reason)

    def test_sell_resistance_and_pp_bias_boost(self):
        signal, confidence, reason = apply_pivot_confidence(
            "SELL", 0.50, 99.5, self.levels, point_size=0.01, tolerance_points=1200
        )
        self.assertEqual(signal, "SELL")
        self.assertAlmostEqual(confidence, 0.70)
        self.assertIn("sell_confidence_boost_from_resistance_pivot", reason)
        self.assertIn("bearish_bias_below_PP", reason)

    def test_buy_limit_requires_support_below_price(self):
        output = build_pivot_signal_output(
            "BUY", 0.50, 97.5, self.levels, point_size=0.01, pending_distance_points=300
        )
        self.assertEqual(output["recommended_order"], "BUY_LIMIT")
        self.assertEqual(output["recommended_entry_price"], 95.0)

    def test_sell_limit_requires_resistance_above_price(self):
        output = build_pivot_signal_output(
            "SELL", 0.50, 102.5, self.levels, point_size=0.01, pending_distance_points=300
        )
        self.assertEqual(output["recommended_order"], "SELL_LIMIT")
        self.assertEqual(output["recommended_entry_price"], 105.0)


if __name__ == "__main__":
    unittest.main()
