from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class QaderAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = os.environ.get("QADER_ROOT")
        os.environ["QADER_ROOT"] = self.tmp.name

    def tearDown(self):
        if self.old_root is None:
            os.environ.pop("QADER_ROOT", None)
        else:
            os.environ["QADER_ROOT"] = self.old_root
        self.tmp.cleanup()

    def test_bootstrap_creates_safe_runtime_files(self):
        from qader_app.services.config_service import ConfigService
        from qader_app.paths import data_dir, logs_dir, reports_dir

        ConfigService().bootstrap()
        self.assertTrue((data_dir() / "dna" / "default_genome.json").exists())
        self.assertTrue((data_dir() / "dna" / "active_genome.json").exists())
        self.assertTrue(logs_dir().exists())
        self.assertTrue(reports_dir().exists())

    def test_onboarding_storage_files(self):
        from qader_app.storage.profile_store import ProfileStore
        from qader_app.storage.settings_store import PermissionsStore, SettingsStore

        ProfileStore().save({"preferred_name": "Radhi", "language": "bilingual", "tone": "direct"})
        SettingsStore().save({"selected_symbols": ["XAUUSDm", "EURUSDm"], "mode": "dry_run_simulation"})
        PermissionsStore().save({"can_scan_market": True, "can_read_mt5": True, "can_place_live_orders": True})
        self.assertEqual(ProfileStore().load()["preferred_name"], "Radhi")
        self.assertEqual(SettingsStore().load()["selected_symbols"], ["XAUUSDm", "EURUSDm"])
        self.assertFalse(PermissionsStore().load()["can_place_live_orders"])

    def test_permissions_guard_denies_and_logs(self):
        from qader_app.assistant.permissions_guard import PermissionsGuard
        from qader_app.storage.audit_log import audit_log_path

        result = PermissionsGuard().check("can_run_dry_run", "unit_test_action", "test")
        self.assertFalse(result.allowed)
        self.assertTrue(audit_log_path().exists())

    def test_memory_strips_sensitive_fields(self):
        from qader_app.assistant.memory import QaderMemory

        memory = QaderMemory()
        saved = memory.save({"preferences": {"language": "Arabic"}, "password": "secret"})
        self.assertNotIn("password", saved)
        self.assertEqual(memory.load()["preferences"]["language"], "Arabic")

    def test_genome_mutation_requires_permission_and_approval(self):
        from qader_app.genome.gene_store import GeneStore
        from qader_app.genome.mutation_engine import MutationEngine
        from qader_app.storage.settings_store import PermissionsStore

        store = GeneStore()
        store.ensure_defaults()
        engine = MutationEngine(store)
        proposal = engine.propose_threshold_adjustment({"score": -0.2})
        self.assertFalse(engine.apply(proposal, approved=False)["applied"])
        PermissionsStore().save({"can_modify_strategy_dna": True})
        applied = engine.apply(proposal, approved=True)
        self.assertTrue(applied["applied"])
        self.assertGreaterEqual(applied["genome"]["version"], 2)

    def test_learning_service_applies_approved_proposal(self):
        from qader_app.genome.evaluation_engine import EvaluationEngine
        from qader_app.genome.gene_store import GeneStore
        from qader_app.genome.mutation_engine import MutationEngine
        from qader_app.services.learning_service import LearningService
        from qader_app.storage.settings_store import PermissionsStore

        store = GeneStore()
        store.ensure_defaults()
        PermissionsStore().save({"can_modify_strategy_dna": True})
        service = LearningService(
            evaluator=EvaluationEngine(store),
            mutations=MutationEngine(store),
        )
        result = service.collect_propose_and_apply(
            [
                {"final_action": "BUY", "confidence": 0.8, "risk_status": "approved"},
                {"final_action": "HOLD", "confidence": 0.2, "risk_status": "risk_blocked"},
            ],
            apply=True,
            approved=True,
            context={"source_event": "unit_test"},
        )
        self.assertTrue(result["application"]["applied"])
        active = store.load_active()
        self.assertEqual(
            active["confidence_thresholds"]["arbiter_pass"],
            result["proposal"].changes["confidence_thresholds"]["arbiter_pass"],
        )
        self.assertGreaterEqual(active["version"], 2)

    def test_trade_learning_auto_applies_strategy_dna(self):
        from qader_app.genome.gene_store import GeneStore
        from qader_app.services.real_time_loop_service import RealTimeLoopService
        from qader_app.storage.settings_store import PermissionsStore

        PermissionsStore().save({"can_modify_strategy_dna": True})
        store = GeneStore()
        before = store.load_active()["version"]
        loop = RealTimeLoopService()
        record = {
            "cycle_number": 1,
            "symbol": "XAUUSDm",
            "timeframe": "M1",
            "final_action": "BUY",
            "confidence": 0.72,
            "risk_status": "approved",
            "execution_status": "executed",
            "order_send_called": True,
            "demo_calibration": False,
            "reason": "unit_test",
            "order": 1001,
            "deal": 1001,
        }
        loop._record_trade_learning(
            {"event": "demo_trade_entry", "symbol": "XAUUSDm", "timeframe": "M1"},
            record,
            {
                "learning": {
                    "apply_on_trade_opened": True,
                    "auto_apply_proposals": True,
                    "min_samples_for_auto_apply": 1,
                    "sample_window": 1,
                    "apply_cooldown_seconds": 0,
                }
            },
        )

        application = loop._latest_learning_state["application"]
        self.assertTrue(application["applied"])
        self.assertGreater(store.load_active()["version"], before)

    def test_cycle_learning_auto_applies_strategy_dna(self):
        from qader_app.genome.gene_store import GeneStore
        from qader_app.services.real_time_loop_service import RealTimeLoopService
        from qader_app.storage.settings_store import PermissionsStore

        PermissionsStore().save({"can_modify_strategy_dna": True})
        store = GeneStore()
        before = store.load_active()["version"]
        loop = RealTimeLoopService()
        loop._record_learning_cycle(
            {
                "cycle_number": 7,
                "symbol": "XAUUSDm",
                "timeframe": "M1",
                "final_action": "BUY",
                "confidence": 0.72,
                "risk_status": "approved",
                "execution_status": "hold",
                "order_send_called": False,
                "demo_calibration": False,
                "reason": "unit_test_cycle",
            },
            {
                "learning": {
                    "collect_every_cycle": True,
                    "auto_apply_proposals": True,
                    "min_samples_for_auto_apply": 1,
                    "sample_window": 1,
                    "apply_cooldown_seconds": 0,
                }
            },
        )

        learning = loop._latest_learning_state
        self.assertTrue(learning["application"]["applied"])
        self.assertTrue(learning["approved"])
        self.assertEqual(learning["learning_config"]["sample_window"], 1)
        self.assertGreater(store.load_active()["version"], before)

    def test_signal_arbiter_uses_active_genome_threshold(self):
        from qader_app.genome.gene_store import GeneStore
        from mt5_ai.core.signal_arbiter import SignalArbiter
        from mt5_ai.core.signal_schema import Direction, SignalProposal

        store = GeneStore()
        genome = store.load_active()
        genome["confidence_thresholds"]["arbiter_pass"] = 0.95
        store.save_active(genome, "unit_test_threshold")

        arbiter = SignalArbiter()
        decision = arbiter.decide(
            [
                SignalProposal(
                    source="fractal_agent",
                    strategy_id="unit",
                    symbol="XAUUSDm",
                    timeframe="M1",
                    direction=Direction.BUY,
                    confidence=0.80,
                ),
                SignalProposal(
                    source="smc_agent",
                    strategy_id="unit",
                    symbol="XAUUSDm",
                    timeframe="M1",
                    direction=Direction.BUY,
                    confidence=0.80,
                ),
            ],
            "XAUUSDm",
            "M1",
        )

        self.assertEqual(decision.threshold_source, "active_genome")
        self.assertAlmostEqual(decision.effective_threshold, 0.95)
        self.assertEqual(decision.final_direction, Direction.HOLD)

    def test_scanner_denies_without_permissions_no_execution(self):
        from qader_app.services.scanner_service import ScannerService

        result = ScannerService().scan_symbol("XAUUSDm", "M1").to_dict()
        self.assertEqual(result["final_action"], "HOLD")
        self.assertIn("not granted", result["error"])

    def test_intent_routing_dangerous_commands(self):
        from qader_app.assistant.intent_router import IntentRouter

        router = IntentRouter()
        self.assertTrue(router.route("Qader enable live trading").requires_confirmation)
        self.assertEqual(router.route("Qader, scan gold.").name, "scan_market")
        self.assertEqual(router.route("Qader, stop all activity.").name, "emergency_stop")

    def test_no_live_permission_default(self):
        from qader_app.storage.settings_store import PermissionsStore

        self.assertFalse(PermissionsStore().load()["can_place_live_orders"])

    def test_real_controlled_mode_unlock_requires_phrase_and_clean_lockdown(self):
        from qader_app.storage.settings_store import PermissionsStore, REAL_UNLOCK_PHRASE

        store = PermissionsStore()
        clean_lockdown = {
            "exit_code": 0,
            "open_positions": 0,
            "pending_orders": 0,
            "external_magic0_exposure": False,
        }
        denied = store.unlock_real_controlled_mode("wrong phrase", clean_lockdown)
        self.assertFalse(denied["can_place_live_orders"])
        allowed = store.unlock_real_controlled_mode(REAL_UNLOCK_PHRASE, clean_lockdown)
        self.assertTrue(allowed["can_place_live_orders"])
        self.assertTrue(allowed["_real_controlled_mode_unlocked"])
        self.assertTrue(store.load()["can_place_live_orders"])

    def test_voice_live_request_requires_manual_permissions_screen(self):
        from qader_app.assistant.qader_brain import QaderBrain

        result = QaderBrain().handle_text("Qader enable live real trading")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "Real trading requires manual confirmation from the permissions screen.")

    def test_real_controlled_config_exists(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "config" / "real_controlled_mode.yaml").read_text(encoding="utf-8")
        self.assertIn("mode: REAL_CONTROLLED_MODE", text)
        self.assertIn("allow_live_trading: true", text)
        self.assertIn("simulate_only: false", text)

    def test_packaging_files_exist(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "packaging" / "qader.spec").exists())
        self.assertTrue((root / "packaging" / "build_qader.ps1").exists())

    def test_gui_import_smoke(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from qader_app.gui.main_window import MainWindow
        from qader_app.services.config_service import ConfigService

        ConfigService().bootstrap()
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        self.assertIn("Qader", window.windowTitle())
        window.close()
        app.quit()


if __name__ == "__main__":
    unittest.main()
