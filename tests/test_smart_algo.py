"""
Unit tests for IndicatorEngine, ConfluenceMatrix, ZoneDetector, RiskManager, ExecutionEngine.
"""
import sys
import unittest
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.indicators import IndicatorEngine
from src.confluence import ConfluenceMatrix
from src.zones import ZoneDetector
from src.risk import RiskManager, ExecutionEngine

class DummyMT5:
    def place_order(self, symbol, price, size):
        return f"order_{symbol}_{price}_{size}"

class TestSmartAlgorithmPro(unittest.TestCase):
    def setUp(self):
        # Minimal OHLCV data for 20 bars
        self.df = pd.DataFrame({
            'open': np.random.rand(20)*100,
            'high': np.random.rand(20)*100+1,
            'low': np.random.rand(20)*100-1,
            'close': np.random.rand(20)*100,
            'volume': np.random.randint(100, 1000, 20),
            'spread': np.random.rand(20)*10
        })
        self.df['ATR'] = self.df['high'] - self.df['low']
        self.data = {'M1': self.df.copy(), 'M5': self.df.copy()}

    def test_indicators(self):
        engine = IndicatorEngine(self.data)
        engine.calculate_all()
        results = engine.get_results('M1')
        self.assertIn('EMA_FAST', results)
        self.assertIn('RSI', results)
        self.assertIn('ATR', results)

    def test_confluence(self):
        engine = IndicatorEngine(self.data)
        engine.calculate_all()
        ind_results = {tf: {**engine.data[tf], **engine.results[tf]} for tf in self.data}
        matrix = ConfluenceMatrix(ind_results)
        scores = matrix.calculate_group_scores(['M1', 'M5'])
        score = matrix.calculate_final_score()
        signal = matrix.calculate_final_signal(spread=5)
        self.assertIsInstance(scores, dict)
        self.assertIsInstance(score, float)
        self.assertIn(signal, ['BUY/SELL', 'WAIT (weak)', 'WAIT (none)', 'BLOCK'])

    def test_zones(self):
        detector = ZoneDetector(self.df)
        zones = detector.detect_zones()
        self.assertIsInstance(zones, list)

    def test_risk(self):
        rm = RiskManager({'balance': 10000, 'max_risk_pct': 1})
        size = rm.calc_position_size(50)
        sl, tp = rm.calc_sl_tp(2000, 10)
        self.assertGreater(size, 0)
        self.assertNotEqual(sl, tp)

    def test_execution(self):
        exec_engine = ExecutionEngine(DummyMT5())
        orders = exec_engine.place_grid_orders('XAUUSD', 2000, 0.1)
        self.assertEqual(len(orders), 3)

if __name__ == '__main__':
    unittest.main()
