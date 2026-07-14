import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASH = PROJECT_ROOT / "scripts" / "friday_web_dashboard.py"


class TestLearningCard(unittest.TestCase):
    def setUp(self):
        self.src = DASH.read_text(encoding="utf-8")

    def test_learning_listener_registered(self):
        self.assertIn("es.addEventListener('learning'", self.src)

    def test_onLearning_handler_exists(self):
        self.assertIn("function onLearning", self.src)

    def test_card_renders_thresholds_counter_and_last5(self):
        self.assertIn("Last 5 P&L:", self.src)
        self.assertIn("adapt in ${n}/${LEARN_UPDATE_EVERY}", self.src)
        self.assertIn("e.last_p_and_l", self.src)

    def test_stale_128_text_removed(self):
        self.assertNotIn("Triggers after 128 closed trades", self.src)

    def test_n_cadence_text_present(self):
        self.assertIn("thresholds adapt every 5 trades", self.src)

    def test_file_still_parses(self):
        import ast
        ast.parse(self.src)  # raises on syntax error


if __name__ == "__main__":
    unittest.main()
