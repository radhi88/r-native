"""Tests for execution.py — PaperExecutor, SafeMT5Executor, DemoMT5Executor."""

import pytest
from unittest.mock import MagicMock, patch
from src.mt5_ai.execution import (
    PaperExecutor,
    SafeMT5Executor,
    DemoMT5Executor,
    ExecutionResult,
)


class TestExecutionResult:
    def test_to_dict_contains_all_fields(self):
        r = ExecutionResult(
            mode="paper", action="OPEN", symbol="EURUSDm",
            side="BUY", lot=0.01, price=1.1000, sent=True,
            reason="paper_trade_logged", timestamp="2026-01-01T00:00:00+00:00",
        )
        d = r.to_dict()
        assert d["mode"] == "paper"
        assert d["symbol"] == "EURUSDm"
        assert d["lot"] == 0.01


class TestPaperExecutor:
    def setup_method(self):
        self.exec = PaperExecutor()

    def test_execute_returns_dict(self):
        r = self.exec.execute("EURUSDm", "BUY", 1.1000)
        assert isinstance(r, dict)

    def test_execute_mode_is_paper(self):
        r = self.exec.execute("EURUSDm", "BUY", 1.1000)
        assert r["mode"] == "paper"

    def test_execute_sent_true(self):
        r = self.exec.execute("EURUSDm", "BUY", 1.1000)
        assert r["sent"] is True

    def test_execute_stores_sl_tp(self):
        r = self.exec.execute("EURUSDm", "BUY", 1.1000, sl=1.0950, tp=1.1100)
        assert r["sl"] == 1.0950
        assert r["tp"] == 1.1100

    def test_execute_price_cast_to_float(self):
        r = self.exec.execute("EURUSDm", "BUY", "1.1000")
        assert isinstance(r["price"], float)

    def test_execute_lot_stored(self):
        r = self.exec.execute("EURUSDm", "SELL", 1.1000, lot=0.02)
        assert r["lot"] == 0.02

    def test_execute_has_timestamp(self):
        r = self.exec.execute("EURUSDm", "BUY", 1.1000)
        assert "timestamp" in r
        assert "T" in r["timestamp"]

    def test_execute_pending_mode_is_paper_pending(self):
        r = self.exec.execute_pending("EURUSDm", "BUY", 1.0950)
        assert r["mode"] == "paper_pending"

    def test_execute_pending_action_is_PENDING(self):
        r = self.exec.execute_pending("EURUSDm", "BUY", 1.0950)
        assert r["action"] == "PENDING"

    def test_execute_pending_limit_price_stored(self):
        r = self.exec.execute_pending("EURUSDm", "BUY", 1.0950)
        assert r["limit_price"] == pytest.approx(1.0950)


class TestSafeMT5Executor:
    def _make_executor(self, gateway_result: dict, allow_live=False):
        gateway = MagicMock()
        gateway.send_market_order.return_value = gateway_result
        return SafeMT5Executor(gateway, allow_live=allow_live), gateway

    def test_execute_calls_gateway(self):
        executor, gw = self._make_executor({"sent": False, "reason": "live_blocked"})
        executor.execute("EURUSDm", "BUY", 1.1000)
        gw.send_market_order.assert_called_once()

    def test_execute_returns_dict_with_timestamp(self):
        executor, _ = self._make_executor({"sent": False})
        r = executor.execute("EURUSDm", "BUY", 1.1000)
        assert "timestamp" in r

    def test_execute_passes_allow_live_flag(self):
        executor, gw = self._make_executor({"sent": True}, allow_live=True)
        executor.execute("EURUSDm", "BUY", 1.1000)
        call_args = gw.send_market_order.call_args
        assert call_args.kwargs.get("allow_live") is True or call_args.args[-1] is True

    def test_execute_merges_gateway_result(self):
        executor, _ = self._make_executor({"ticket": 999, "sent": True})
        r = executor.execute("EURUSDm", "BUY", 1.1000)
        assert r.get("ticket") == 999

    def test_execute_gateway_exception_propagates(self):
        gateway = MagicMock()
        gateway.send_market_order.side_effect = ConnectionError("MT5 offline")
        executor = SafeMT5Executor(gateway)
        with pytest.raises(ConnectionError):
            executor.execute("EURUSDm", "BUY", 1.1000)


class TestDemoMT5Executor:
    def _make_executor(self):
        gateway = MagicMock()
        gateway.send_demo_market_order.return_value = {"sent": True, "ticket": 1234}
        gateway.send_demo_pending_order.return_value = {"sent": True}
        gateway.modify_demo_position_sl_tp.return_value = {"modified": True}
        return DemoMT5Executor(gateway), gateway

    def test_execute_mode_is_demo_mt5(self):
        executor, _ = self._make_executor()
        r = executor.execute("XAUUSDm", "BUY", 2300.0)
        assert r["mode"] == "demo_mt5"

    def test_execute_has_requested_price(self):
        executor, _ = self._make_executor()
        r = executor.execute("XAUUSDm", "BUY", 2300.0)
        assert r["requested_price"] == pytest.approx(2300.0)

    def test_execute_passes_comment_to_gateway(self):
        executor, gw = self._make_executor()
        executor.execute("XAUUSDm", "BUY", 2300.0)
        call = gw.send_demo_market_order.call_args
        plan = call.args[0]
        assert plan.comment == "friday-demo-only"

    def test_execute_pending_mode_is_demo_pending(self):
        executor, _ = self._make_executor()
        r = executor.execute_pending("XAUUSDm", "BUY", 2290.0)
        assert r["mode"] == "demo_pending"

    def test_execute_pending_limit_price_stored(self):
        executor, _ = self._make_executor()
        r = executor.execute_pending("XAUUSDm", "BUY", 2290.0)
        assert r["limit_price"] == pytest.approx(2290.0)

    def test_modify_position_returns_dict(self):
        executor, _ = self._make_executor()
        r = executor.modify_position("XAUUSDm", ticket=1234, sl=2280.0, tp=2350.0)
        assert "modified" in r or "timestamp" in r

    def test_modify_position_calls_gateway(self):
        executor, gw = self._make_executor()
        executor.modify_position("XAUUSDm", ticket=1234, sl=2280.0)
        gw.modify_demo_position_sl_tp.assert_called_once_with(
            ticket=1234, symbol="XAUUSDm", sl=2280.0, tp=None
        )

    def test_execute_gateway_failure_propagates(self):
        gateway = MagicMock()
        gateway.send_demo_market_order.side_effect = RuntimeError("timeout")
        executor = DemoMT5Executor(gateway)
        with pytest.raises(RuntimeError):
            executor.execute("XAUUSDm", "BUY", 2300.0)
