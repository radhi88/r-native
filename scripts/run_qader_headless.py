"""Headless Qader loop starter — unlocks permissions and starts the demo trading loop.

Usage:
    .venv\\Scripts\\python.exe scripts\\run_qader_headless.py
    .venv\\Scripts\\python.exe scripts\\run_qader_headless.py --monitor 180
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / "src"
for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QADER_ROOT", str(ROOT))
os.environ.setdefault("FRIDAY_PROJECT_ROOT", str(ROOT))

# ── 1. Unlock permissions ──────────────────────────────────────────────────
from qader_app.storage.settings_store import PermissionsStore, REAL_UNLOCK_PHRASE


def _build_lockdown_summary() -> dict:
    summary = {
        "ok": False,
        "exit_code": 1,
        "open_positions": 1,
        "pending_orders": 1,
        "external_magic0_exposure": True,
        "clean": False,
        "account_info_readable": False,
        "note": "headless_preflight_failed",
    }
    try:
        import MetaTrader5 as mt5
        from mt5_ai.core.magic_registry import QADER_REAL_CONTROLLED_MAGIC

        initialized = mt5.initialize()
        if not initialized:
            summary["last_error"] = mt5.last_error()
            return summary

        try:
            info = mt5.account_info()
            positions = list(mt5.positions_get() or [])
            orders = list(mt5.orders_get() or [])
        finally:
            mt5.shutdown()

        def _magic(item) -> int:
            try:
                return int(getattr(item, "magic", -1) or -1)
            except Exception:
                return -1

        balance = float(getattr(info, "balance", 0.0) or 0.0) if info else 0.0
        equity = float(getattr(info, "equity", 0.0) or 0.0) if info else 0.0
        free_margin = float(getattr(info, "margin_free", 0.0) or 0.0) if info else 0.0
        min_balance = float(os.getenv("QADER_MIN_BALANCE_TO_START", "20") or 20)
        min_equity = float(os.getenv("QADER_MIN_EQUITY_TO_START", "20") or 20)
        min_free_margin = float(os.getenv("QADER_MIN_FREE_MARGIN_TO_START", "10") or 10)
        capital_ok = (
            bool(info)
            and balance >= min_balance
            and equity >= min_equity
            and free_margin >= min_free_margin
        )

        qader_positions = [p for p in positions if _magic(p) == QADER_REAL_CONTROLLED_MAGIC]
        qader_orders = [o for o in orders if _magic(o) == QADER_REAL_CONTROLLED_MAGIC]
        magic0_positions = [p for p in positions if _magic(p) == 0]
        magic0_orders = [o for o in orders if _magic(o) == 0]
        clean = bool(info) and not positions and not orders and not magic0_positions and not magic0_orders and capital_ok
        summary.update({
            "ok": clean,
            "exit_code": 0 if clean else 2,
            "balance": balance,
            "equity": equity,
            "free_margin": free_margin,
            "min_balance_to_start": min_balance,
            "min_equity_to_start": min_equity,
            "min_free_margin_to_start": min_free_margin,
            "capital_guard_ok": capital_ok,
            "open_positions": len(positions),
            "qader_open_positions": len(qader_positions),
            "non_qader_open_positions": len(positions) - len(qader_positions),
            "pending_orders": len(orders),
            "qader_pending_orders": len(qader_orders),
            "non_qader_pending_orders": len(orders) - len(qader_orders),
            "external_magic0_position_exposure": bool(magic0_positions),
            "external_magic0_pending_exposure": bool(magic0_orders),
            "external_magic0_exposure": bool(magic0_positions or magic0_orders),
            "clean": clean,
            "account_info_readable": bool(info),
            "note": "headless_preflight_verified",
            "orders": [
                {
                    "ticket": int(getattr(o, "ticket", 0) or 0),
                    "symbol": str(getattr(o, "symbol", "")),
                    "magic": _magic(o),
                    "volume": float(getattr(o, "volume_current", 0.0) or 0.0),
                    "price": float(getattr(o, "price_open", 0.0) or 0.0),
                    "comment": str(getattr(o, "comment", "") or ""),
                }
                for o in orders[:20]
            ],
            "positions": [
                {
                    "ticket": int(getattr(p, "ticket", 0) or 0),
                    "symbol": str(getattr(p, "symbol", "")),
                    "magic": _magic(p),
                    "volume": float(getattr(p, "volume", 0.0) or 0.0),
                    "profit": float(getattr(p, "profit", 0.0) or 0.0),
                    "sl": float(getattr(p, "sl", 0.0) or 0.0),
                    "tp": float(getattr(p, "tp", 0.0) or 0.0),
                    "comment": str(getattr(p, "comment", "") or ""),
                }
                for p in positions[:20]
            ],
        })
    except Exception as exc:
        summary["error"] = str(exc)
    return summary


def _write_lockdown_dashboard_state(summary: dict, reason: str = "headless_preflight_blocked") -> None:
    state_path = ROOT / "dashboard" / "qader_live_state.json"
    previous_loop: dict = {}
    try:
        raw = state_path.read_text(encoding="utf-8").replace("\x00", "").strip()
        if raw:
            previous = json.loads(raw)
            if isinstance(previous, dict) and isinstance(previous.get("loop"), dict):
                previous_loop = previous["loop"]
    except Exception:
        previous_loop = {}

    demo_trades_opened = int(previous_loop.get("demo_trades_opened", 0) or 0)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "loop": {
            "state": "BLOCKED",
            "reason": reason,
            "cycle_count": int(previous_loop.get("cycle_count", 0) or 0),
            "last_cycle_time": str(previous_loop.get("last_cycle_time", "") or ""),
            "last_signal": str(previous_loop.get("last_signal", "") or ""),
            "last_decision": str(previous_loop.get("last_decision", "") or ""),
            "last_block_reason": reason,
            "order_send_called": False,
            "demo_trades_opened": demo_trades_opened,
            "demo_trades_managed": int(previous_loop.get("demo_trades_managed", 0) or 0),
            "allow_new_entries": False,
            "thread_alive": False,
        },
        "latest_record": {
            "loop_state": "BLOCKED",
            "execution_status": "lockdown_blocked",
            "execution_decision": "lockdown_blocked",
            "reason": reason,
            "blocked_reason": reason,
            "open_positions": int(summary.get("open_positions", 0) or 0),
            "open_positions_total": int(summary.get("open_positions", 0) or 0),
            "pending_orders": int(summary.get("pending_orders", 0) or 0),
            "pending_orders_total": int(summary.get("pending_orders", 0) or 0),
            "qader_pending_tickets": [],
            "preflight": summary,
        },
        "chart_history": [],
        "fvg_zones": [],
        "market_levels": {},
        "fusion_candle": {},
        "structure_map": {},
        "indicator_pack": {},
        "pending_plan": {},
        "learning_state": {},
        "session_info": {},
        "log_path": str(ROOT / "logs" / "qader_realtime_loop.jsonl"),
        "journal_path": str(ROOT / "logs" / "live_performance_journal.jsonl"),
        "dna_journal_path": str(ROOT / "dna" / "live_performance_journal.jsonl"),
        "demo_only": True,
    }
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        pass


lockdown_summary = _build_lockdown_summary()
print(
    "[PREFLIGHT] "
    f"clean={lockdown_summary.get('clean')} "
    f"positions={lockdown_summary.get('open_positions')} "
    f"pending={lockdown_summary.get('pending_orders')} "
    f"qader_pending={lockdown_summary.get('qader_pending_orders')} "
    f"equity={lockdown_summary.get('equity')} "
    f"capital_ok={lockdown_summary.get('capital_guard_ok')} "
    f"magic0={lockdown_summary.get('external_magic0_exposure')}"
)

store = PermissionsStore()
result = store.unlock_real_controlled_mode(REAL_UNLOCK_PHRASE, lockdown_summary)
print(f"[UNLOCK] can_place_live_orders={result.get('can_place_live_orders')} "
      f"unlocked={result.get('_real_controlled_mode_unlocked')} "
      f"phrase_ok={result.get('_real_unlock_phrase_confirmed')}")

perms = store.load()
if not perms.get("can_place_live_orders"):
    _write_lockdown_dashboard_state(lockdown_summary)
    print(f"[LOCKDOWN] {json.dumps(lockdown_summary, ensure_ascii=False, default=str)}")
    print("[ERROR] Permission unlock failed — check permissions.json")
    sys.exit(1)
perms = store.save({"can_modify_strategy_dna": True})
print(f"[DNA]    can_modify_strategy_dna={perms.get('can_modify_strategy_dna')}")

# ── 2. Start the loop ──────────────────────────────────────────────────────
from qader_app.services.real_time_loop_service import RealTimeLoopService

loop = RealTimeLoopService()
start_result = loop.start(final_confirmation=True)
print(f"[START]  {start_result}")

if not start_result.get("ok"):
    _write_lockdown_dashboard_state({"reason": start_result.get("reason"), **lockdown_summary}, "loop_start_failed")
    print(f"[ERROR] Loop failed to start: {start_result.get('reason')}")
    sys.exit(1)

print("[OK] RealTimeLoopService started — monitoring...\n")
print(f"{'Cycle':>6}  {'State':<12}  {'Signal':<6}  {'Conf':>6}  {'Trades':>6}  {'Managed':>7}  {'Exec Status':<28}  Positions")
print("─" * 95)

# ── 3. Monitor (runs indefinitely — Ctrl+C to stop) ────────────────────────
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--monitor", type=int, default=0, help="Seconds to run (0 = infinite)")
args, _ = parser.parse_known_args()

state_path = ROOT / "dashboard" / "qader_live_state.json"
start_time = time.monotonic()
last_cycle  = -1
trades_seen = 0
target_announced = False

try:
    while True:
        if args.monitor > 0 and time.monotonic() - start_time > args.monitor:
            print("\n[TIMEOUT] Monitor duration reached.")
            break

        time.sleep(1)
        status = loop.status()
        cycle   = status.get("cycle_count", 0)
        state   = status.get("state", "?")
        trades  = status.get("demo_trades_opened", 0)
        managed = status.get("demo_trades_managed", 0)
        signal  = status.get("last_signal", "?")

        # read latest record from dashboard state for detail
        exec_status = "-"
        conf = 0.0
        open_pos = 0
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            lr  = raw.get("latest_record", {})
            exec_status = lr.get("execution_status", "-")
            conf = float(lr.get("confidence", 0.0))
            open_pos = int(lr.get("open_positions", 0))
        except Exception:
            pass

        if cycle != last_cycle:
            trades_marker = " ★ TRADE!" if trades > trades_seen else ""
            print(f"{cycle:>6}  {state:<12}  {signal:<6}  {conf:>6.3f}  {trades:>6}  {managed:>7}  "
                  f"{exec_status:<28}  pos={open_pos}{trades_marker}")
            last_cycle  = cycle
            trades_seen = trades

        if trades >= 300 and not target_announced:
            target_announced = True
            print(f"\n  [✓] 300 demo trades opened — continuing to MANAGE positions (SL/TP/breakeven/trailing)")
            print(f"  Loop stays alive. Ctrl+C to stop manually.\n")

        if not status.get("thread_alive"):
            print(f"\n[STOPPED] Loop thread died — state={state}, reason={status.get('reason')}")
            break

except KeyboardInterrupt:
    print("\n[Ctrl+C] User stopped monitoring.")
finally:
    loop.stop("headless_monitor_complete")
    final = loop.status()
    print(f"\n── FINAL STATUS ──────────────────────────────────────")
    print(f"  State          : {final['state']}")
    print(f"  Cycles run     : {final['cycle_count']}")
    print(f"  Trades opened  : {final['demo_trades_opened']}")
    print(f"  Positions managed: {final['demo_trades_managed']}")
    print(f"  Allow entries  : {final['allow_new_entries']}")
    print(f"──────────────────────────────────────────────────────")
