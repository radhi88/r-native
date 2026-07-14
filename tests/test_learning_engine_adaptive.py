import sys, tempfile, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mt5_ai.agents import learning_engine as le  # noqa: E402


class TestAdaptiveLoop(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        # redirect all persistence to the temp dir
        le._TRADE_LOG        = tmp / "agent_trades.csv"
        le._STATE_FILE       = tmp / "symbol_thresholds.json"
        le._SETUP_STATE_FILE = tmp / "setup_performance.json"
        le._pattern_analyzer = None  # avoid blacklist side effects in tests

    def tearDown(self):
        self._tmp.cleanup()

    def _eng(self, **kw):
        return le.LearningEngine(**kw)

    def test_counter_increments_and_resets_at_N(self):
        eng = self._eng(update_every=5)
        for i in range(4):
            eng.record("smc", "XAUUSDm", "buy", 100.0, 101.0, 10.0)
        self.assertEqual(eng.trades_since_last_update("smc", "XAUUSDm"), 4)
        eng.record("smc", "XAUUSDm", "buy", 100.0, 101.0, 10.0)  # 5th → resets
        self.assertEqual(eng.trades_since_last_update("smc", "XAUUSDm"), 0)

    def test_adapt_only_fires_every_N(self):
        # With update_every=5 and 8-row warm-up, thresholds must NOT move before
        # the counter first reaches 5 with >=8 rows present.
        eng = self._eng(update_every=5)
        before = dict(eng.thresholds("smc", "XAUUSDm"))
        for i in range(4):
            eng.record("smc", "XAUUSDm", "buy", 100.0, 110.0, 10.0)
        self.assertEqual(eng.thresholds("smc", "XAUUSDm"), before)  # no adapt yet

    def test_decay_pulls_toward_baseline_by_halflife(self):
        eng = self._eng(update_every=5, halflife_bars=100)
        t = eng.thresholds("smc", "EURUSD")
        t["buy_threshold"] = 0.90          # baseline is 0.60
        eng._save_state()
        out = eng.decay_toward_baseline("smc", "EURUSD", bars_elapsed=100)  # one halflife
        # distance 0.30 halved → 0.75 (within float tolerance)
        self.assertAlmostEqual(out["buy_threshold"], 0.75, places=4)

    def test_decay_noop_when_zero_bars(self):
        eng = self._eng()
        t = eng.thresholds("smc", "EURUSD"); t["buy_threshold"] = 0.88; eng._save_state()
        out = eng.decay_toward_baseline("smc", "EURUSD", bars_elapsed=0)
        self.assertAlmostEqual(out["buy_threshold"], 0.88, places=4)

    def test_int_threshold_stays_int_after_decay(self):
        eng = self._eng(halflife_bars=10)
        t = eng.thresholds("smc", "EURUSD"); t["min_smc_score"] = 5; eng._save_state()
        out = eng.decay_toward_baseline("smc", "EURUSD", bars_elapsed=10)
        self.assertIsInstance(out["min_smc_score"], int)


if __name__ == "__main__":
    unittest.main()
