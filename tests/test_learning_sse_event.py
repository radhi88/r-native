import re, sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASH = PROJECT_ROOT / "scripts" / "friday_web_dashboard.py"


class TestInlineRecordPath(unittest.TestCase):
    """D-01/D-01a: record() is called synchronously inline in _check_closed —
    no queue / async / sleep between close detection and record()."""

    def setUp(self):
        self.src = DASH.read_text(encoding="utf-8")

    def _method_body(self, name):
        # extract text from `def {name}(` to the next top-level `    def ` (4-space indent)
        m = re.search(rf"\n    def {name}\(.*?\n(?=    def |\nclass )", self.src, re.S)
        self.assertIsNotNone(m, f"{name} not found")
        return m.group(0)

    def test_record_called_inside_check_closed(self):
        body = self._method_body("_check_closed")
        self.assertIn("self.learning_engine.record(", body,
                      "record() must be invoked inline within _check_closed")

    def test_no_async_or_queue_between_detection_and_record(self):
        body = self._method_body("_check_closed")
        idx = body.index("self.learning_engine.record(")
        # the record call must not be deferred behind a queue.put / await / threading / sleep
        # appearing in the same closed-ticket loop before it
        pre = body[:idx]
        for bad in ("await ", "queue.put", "Queue(", "asyncio", "time.sleep", "Thread("):
            self.assertNotIn(bad, pre,
                f"detection->record path must be synchronous; found '{bad}' before record()")

    def test_keeps_5s_poll_not_subsecond(self):
        # the close poll cadence is unchanged (5s), per D-01 "keep the 5s poll"
        self.assertIn("pos_check_counter >= 5", self.src)


class TestLearningEventShape(unittest.TestCase):
    """D-04: learning event has exactly {symbol, thresholds, trades_since_last_update, last_p_and_l}."""

    def setUp(self):
        self.src = DASH.read_text(encoding="utf-8")

    def test_emit_learning_exists_and_broadcasts(self):
        self.assertIn("def _emit_learning", self.src)
        self.assertIn('_broadcast("learning"', self.src)

    def test_event_has_required_keys(self):
        for key in ('"symbol"', '"thresholds"', '"trades_since_last_update"', '"last_p_and_l"'):
            self.assertIn(key, self.src, f"learning event missing key {key}")

    def test_last5_sourced_from_load_rows(self):
        self.assertIn("lookback=5", self.src)


if __name__ == "__main__":
    unittest.main()
