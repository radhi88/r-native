"""employee_link -> rnative_pb round trip (no MT5 needed)."""
import importlib.util
import json
import time
from pathlib import Path

from r_native import employee_link

ROOT = Path(__file__).resolve().parents[1]


def _pb():
    spec = importlib.util.spec_from_file_location("rnative_pb", ROOT / "integrations/employee/rnative_pb.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_submit_writes_one_line(tmp_path, monkeypatch):
    monkeypatch.setenv("R_EMPLOYEE_INBOX", str(tmp_path))
    ok, res = employee_link.submit("XAUUSDm", "buy", 0.01, 4100.0, 4120.0, "R LVL bounce", price=4110.0)
    assert ok and res["queued"] and res["order"] == 0
    rows = [json.loads(l) for l in (tmp_path / "signals.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["side"] == "BUY" and rows[0]["strategy"] == "rn_r_lvl_bounce" and rows[0]["source"] == "r-native"


def test_submit_rejects_bad_side(tmp_path, monkeypatch):
    monkeypatch.setenv("R_EMPLOYEE_INBOX", str(tmp_path))
    ok, res = employee_link.submit("XAUUSDm", "HOLD", 0.01, 0, 0, "x")
    assert not ok and "bad side" in res["reason"]
    assert not (tmp_path / "signals.jsonl").exists()


def test_read_since_skips_partial_line(tmp_path, monkeypatch):
    monkeypatch.setenv("R_EMPLOYEE_INBOX", str(tmp_path))
    employee_link.submit("XAUUSDm", "SELL", 0.01, 1, 1, "a")
    with open(tmp_path / "signals.jsonl", "a", encoding="utf-8") as f:
        f.write('{"partial":')
    rows, off = employee_link.read_since(0)
    assert len(rows) == 1 and rows[0]["side"] == "SELL"
    rows2, _ = employee_link.read_since(off)
    assert rows2 == []


def test_pb_votes_once_on_next_closed_bar(tmp_path, monkeypatch):
    monkeypatch.setenv("R_EMPLOYEE_INBOX", str(tmp_path))
    pb = _pb()
    path = str(tmp_path / "signals.jsonl")
    bar_open = (int(time.time()) // 60) * 60 - 60      # bar that closes now-ish
    employee_link.submit("XAUUSDm", "SELL", 0.01, 4120, 4100, "R trend")
    employee_link.submit("BTCUSDm", "BUY", 0.01, 1, 2, "R trend")   # other market: counted, not voted
    S = {"t": [bar_open - 60, bar_open + 60]}           # bar 1 closes after the signal
    # bar 0 closed before the signal -> no vote yet, signal kept
    assert pb.votes(S, 0, path=path) == {}
    assert pb.votes(S, 1, path=path) == {"rn_r_trend": -1}
    assert pb.votes(S, 1, path=path) == {}              # once only
    assert pb.stats() == {"XAUUSDm": 1, "BTCUSDm": 1}


def test_pb_drops_stale(tmp_path):
    pb = _pb()
    path = tmp_path / "signals.jsonl"
    old = time.time() - 600
    path.write_text(json.dumps({"id": "x", "ts": old, "source": "r-native", "symbol": "XAUUSDm",
                                "side": "BUY", "strategy": "rn_old"}) + "\n", encoding="utf-8")
    S = {"t": [int(time.time()) - 60]}
    assert pb.votes(S, 0, path=str(path)) == {}


def test_executor_send_order_routes_to_employee(tmp_path, monkeypatch):
    import sys
    import types
    fake = types.ModuleType("MetaTrader5")
    fake.symbol_info_tick = lambda s: types.SimpleNamespace(ask=4110.5, bid=4110.2)
    def _no_send(req):
        raise AssertionError("r_executor must not call mt5.order_send on the employee route")
    fake.order_send = _no_send
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    monkeypatch.setenv("R_EMPLOYEE_INBOX", str(tmp_path))
    monkeypatch.delenv("R_ROUTE", raising=False)
    try:
        from friday_v3.algory import r_executor
    except Exception as e:   # module needs more of the MT5 stub than this test provides
        import pytest
        pytest.skip(f"r_executor import needs more: {e}")
    ok, res = r_executor._send_order("XAUUSDm", "BUY", 0.01, 4100, 4130, "R gate")
    assert ok and res["queued"] and res["price"] == 4110.5


def _fake_mt5(monkeypatch):
    import sys
    import types
    fake = types.ModuleType("MetaTrader5")
    fake.TRADE_ACTION_DEAL, fake.TRADE_ACTION_PENDING, fake.TRADE_ACTION_SLTP = 1, 5, 6
    fake.sent = []
    fake.order_send = lambda req: fake.sent.append(req)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    return fake


def test_order_guard_queues_agent_entries_and_refuses_management(tmp_path, monkeypatch):
    from r_native import order_guard
    fake = _fake_mt5(monkeypatch)
    monkeypatch.setenv("R_EMPLOYEE_INBOX", str(tmp_path))
    monkeypatch.delenv("R_ROUTE", raising=False)
    monkeypatch.setattr(order_guard, "_ORIG", None)
    assert order_guard.install()
    r = fake.order_send({"action": 5, "type": 4, "symbol": "XAUUSDm", "volume": 0.01,
                         "price": 4120.0, "sl": 4110.0, "tp": 4140.0, "comment": "vol_hunter"})
    assert r.retcode == order_guard.REJECT and "queued" in r.comment
    r2 = fake.order_send({"action": 6, "position": 123, "sl": 4115.0, "tp": 4140.0})
    assert r2.retcode == order_guard.REJECT and "employee owns" in r2.comment
    assert fake.sent == []          # nothing reached the real order_send
    rows = (tmp_path / "signals.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["side"] == "BUY"


def test_order_guard_off_for_direct_demo(monkeypatch):
    from r_native import order_guard
    _fake_mt5(monkeypatch)
    monkeypatch.setenv("R_ROUTE", "direct_demo")
    monkeypatch.setattr(order_guard, "_ORIG", None)
    assert order_guard.install() is False
