from __future__ import annotations

import json
import socket
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import FridayVoiceConfig, PROJECT_ROOT, log_event


TIMEFRAMES: dict[str, int] = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_json(path: Path, limit_chars: int | None = None) -> Any:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if limit_chars:
            text = text[:limit_chars]
        return json.loads(text)
    except Exception as exc:
        return {"error": str(exc), "path": str(path)}


class MT5Tools:
    """Read-only MT5 and FRIDAY state tools for the voice assistant."""

    def __init__(self, config: FridayVoiceConfig):
        self.config = config
        self.symbol = config.default_symbol
        self.timeframe = config.default_timeframe
        self._lock = threading.RLock()
        self._mt5 = None
        self._mt5_ready = False

    def _import_mt5(self):
        if self._mt5 is None:
            import MetaTrader5 as mt5

            self._mt5 = mt5
            if not TIMEFRAMES:
                TIMEFRAMES.update(
                    {
                        "M1": mt5.TIMEFRAME_M1,
                        "M5": mt5.TIMEFRAME_M5,
                        "M15": mt5.TIMEFRAME_M15,
                        "M30": mt5.TIMEFRAME_M30,
                        "H1": mt5.TIMEFRAME_H1,
                        "H4": mt5.TIMEFRAME_H4,
                        "D1": mt5.TIMEFRAME_D1,
                    }
                )
        return self._mt5

    def initialize(self) -> bool:
        with self._lock:
            mt5 = self._import_mt5()
            if self._mt5_ready:
                return True
            self._mt5_ready = bool(mt5.initialize())
            if not self._mt5_ready:
                log_event("MT5", f"initialize failed: {mt5.last_error()}")
            return self._mt5_ready

    def shutdown(self) -> None:
        with self._lock:
            if self._mt5 is not None and self._mt5_ready:
                self._mt5.shutdown()
            self._mt5_ready = False

    def set_symbol(self, symbol: str) -> dict[str, Any]:
        symbol = str(symbol or "").strip()
        if not symbol:
            return {"ok": False, "reason": "empty_symbol"}
        self.symbol = symbol
        return {"ok": True, "symbol": self.symbol}

    def account_snapshot(self) -> dict[str, Any]:
        with self._lock:
            if not self.initialize():
                return {"ok": False, "error": "mt5_not_initialized"}
            mt5 = self._import_mt5()
            account = mt5.account_info()
            if account is None:
                return {"ok": False, "error": "no_account_info"}
            data = account._asdict()
            return {
                "ok": True,
                "login": data.get("login"),
                "server": data.get("server"),
                "balance": data.get("balance"),
                "equity": data.get("equity"),
                "profit": data.get("profit"),
                "trade_allowed": data.get("trade_allowed"),
                "trade_expert": data.get("trade_expert"),
            }

    def tick(self, symbol: str | None = None) -> dict[str, Any]:
        symbol = symbol or self.symbol
        with self._lock:
            if not self.initialize():
                return {"ok": False, "error": "mt5_not_initialized", "symbol": symbol}
            mt5 = self._import_mt5()
            mt5.symbol_select(symbol, True)
            info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            if info is None or tick is None:
                return {"ok": False, "error": "missing_symbol_info_or_tick", "symbol": symbol}
            point = float(info.point or 0.0) or 0.01
            bid = float(tick.bid)
            ask = float(tick.ask)
            return {
                "ok": True,
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "last": float(getattr(tick, "last", 0.0) or 0.0),
                "spread_points": round(abs(ask - bid) / point, 2),
                "point": point,
                "digits": int(info.digits or 0),
                "time": int(getattr(tick, "time", 0) or 0),
            }

    def positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        symbol = symbol or self.symbol
        with self._lock:
            if not self.initialize():
                return []
            mt5 = self._import_mt5()
            rows = mt5.positions_get(symbol=symbol) or []
            return [
                {
                    "ticket": int(p.ticket),
                    "symbol": p.symbol,
                    "type": "BUY" if int(p.type) == mt5.POSITION_TYPE_BUY else "SELL",
                    "volume": float(p.volume),
                    "price_open": float(p.price_open),
                    "price_current": float(p.price_current),
                    "sl": float(p.sl or 0.0),
                    "tp": float(p.tp or 0.0),
                    "profit": float(p.profit),
                    "magic": int(p.magic),
                    "comment": str(p.comment),
                }
                for p in rows
            ]

    def orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        symbol = symbol or self.symbol
        with self._lock:
            if not self.initialize():
                return []
            mt5 = self._import_mt5()
            rows = mt5.orders_get(symbol=symbol) or []
            return [
                {
                    "ticket": int(o.ticket),
                    "symbol": o.symbol,
                    "type": int(o.type),
                    "volume": float(o.volume_current),
                    "price": float(o.price_open),
                    "sl": float(o.sl or 0.0),
                    "tp": float(o.tp or 0.0),
                    "magic": int(o.magic),
                    "comment": str(o.comment),
                }
                for o in rows
            ]

    def latest_rates(self, symbol: str | None = None, timeframe: str | None = None, bars: int = 5) -> list[dict[str, Any]]:
        symbol = symbol or self.symbol
        timeframe = (timeframe or self.timeframe).upper()
        with self._lock:
            if not self.initialize():
                return []
            mt5 = self._import_mt5()
            tf = TIMEFRAMES.get(timeframe, TIMEFRAMES.get("M1"))
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, int(bars)) if tf is not None else None
            if rates is None:
                return []
            out = []
            for row in rates:
                out.append(
                    {
                        "time": int(row["time"]),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "tick_volume": int(row["tick_volume"]),
                    }
                )
            return out

    def feature_council(self) -> dict[str, Any]:
        state = _load_json(PROJECT_ROOT / "friday_feature_council_state.json")
        decisions = state.get("decisions") if isinstance(state, dict) else None
        latest = decisions[-1] if isinstance(decisions, list) and decisions else None
        return {"ok": isinstance(state, dict) and "error" not in state, "latest": latest, "updated_at": state.get("updated_at") if isinstance(state, dict) else None}

    def live_brain_summary(self) -> dict[str, Any]:
        state = _load_json(PROJECT_ROOT / "friday_live_brain_state.json")
        if not isinstance(state, dict) or "error" in state:
            return state if isinstance(state, dict) else {"error": "invalid_brain_state"}
        return {
            "generated_at": state.get("generated_at"),
            "services": state.get("services"),
            "council": state.get("council"),
            "governor": state.get("governor"),
            "learning": state.get("learning"),
        }

    def market_snapshot(self, symbol: str | None = None) -> dict[str, Any]:
        symbol = symbol or self.symbol
        snapshot = {
            "time": _now(),
            "symbol": symbol,
            "account": self.account_snapshot(),
            "tick": self.tick(symbol),
            "positions": self.positions(symbol),
            "orders": self.orders(symbol),
            "rates": self.latest_rates(symbol, self.timeframe, bars=5),
            "feature_council": self.feature_council(),
        }
        return snapshot

    def get_qader_state(self) -> dict[str, Any]:
        """Read Qader's live trading state from dashboard/qader_live_state.json.

        Returns a flat dict with Arabic-labelled aliases so the LLM can answer
        questions like "كم صفقة فتحت؟" or "ما هي الثقة الحالية؟".
        Returns safe defaults when Qader is not running or the file is absent.
        """
        state_path = PROJECT_ROOT / "dashboard" / "qader_live_state.json"
        _DEFAULTS: dict[str, Any] = {
            "ok": False,
            "source": str(state_path),
            "qader_running": False,
            # English keys
            "loop_state": "UNKNOWN",
            "cycle_count": 0,
            "demo_trades_opened": 0,
            "demo_trades_managed": 0,
            "last_signal": None,
            "last_decision": None,
            "last_block_reason": None,
            "allow_new_entries": False,
            "thread_alive": False,
            "confidence": None,
            "spread": None,
            "execution_status": None,
            "open_positions": None,
            "symbol": None,
            "timeframe": None,
            "demo_only": None,
            "timestamp": None,
            # Arabic-labelled mirrors (for Arabic voice queries)
            "حالة_اللوب": "غير_معروف",
            "عدد_الدورات": 0,
            "عدد_الصفقات": 0,
            "آخر_إشارة": None,
            "الثقة": None,
            "السبريد": None,
            "حالة_التنفيذ": None,
            "السماح_بصفقات_جديدة": False,
        }
        try:
            raw = state_path.read_text(encoding="utf-8", errors="replace")
            data = json.loads(raw)
        except FileNotFoundError:
            log_event("QADER", "qader_live_state.json not found — Qader not running")
            return dict(_DEFAULTS)
        except Exception as exc:
            log_event("QADER", f"failed to read qader_live_state.json: {exc}")
            err = dict(_DEFAULTS)
            err["error"] = str(exc)
            return err

        loop: dict[str, Any] = data.get("loop") or {}
        history: list[dict[str, Any]] = data.get("chart_history") or []
        latest_chart: dict[str, Any] = history[-1] if history else {}

        loop_state = loop.get("state", "UNKNOWN")
        cycle_count = loop.get("cycle_count", 0)
        demo_trades_opened = loop.get("demo_trades_opened", 0)
        demo_trades_managed = loop.get("demo_trades_managed", 0)
        last_signal = loop.get("last_signal")
        last_decision = loop.get("last_decision")
        last_block_reason = loop.get("last_block_reason")
        allow_new_entries = bool(loop.get("allow_new_entries", False))
        thread_alive = bool(loop.get("thread_alive", False))

        confidence = latest_chart.get("confidence")
        spread = latest_chart.get("spread")
        execution_status = latest_chart.get("execution_status")
        open_positions = latest_chart.get("open_positions")
        symbol = latest_chart.get("symbol")
        timeframe = latest_chart.get("timeframe")

        return {
            "ok": True,
            "source": str(state_path),
            "qader_running": thread_alive,
            # English keys
            "loop_state": loop_state,
            "cycle_count": cycle_count,
            "demo_trades_opened": demo_trades_opened,
            "demo_trades_managed": demo_trades_managed,
            "last_signal": last_signal,
            "last_decision": last_decision,
            "last_block_reason": last_block_reason,
            "allow_new_entries": allow_new_entries,
            "thread_alive": thread_alive,
            "confidence": confidence,
            "spread": spread,
            "execution_status": execution_status,
            "open_positions": open_positions,
            "symbol": symbol,
            "timeframe": timeframe,
            "demo_only": data.get("demo_only"),
            "timestamp": data.get("timestamp"),
            # Arabic-labelled mirrors (for Arabic voice queries)
            "حالة_اللوب": loop_state,
            "عدد_الدورات": cycle_count,
            "عدد_الصفقات": demo_trades_opened,
            "آخر_إشارة": last_signal,
            "الثقة": confidence,
            "السبريد": spread,
            "حالة_التنفيذ": execution_status,
            "السماح_بصفقات_جديدة": allow_new_entries,
        }

    def system_status(self) -> dict[str, Any]:
        ports = {8799: "gateway", 8811: "chat", 8822: "dashboard", 8833: "agents", 8844: "brain", 8855: "jarvis_agent"}
        service_status = {}
        for port, name in ports.items():
            service_status[name] = self._port_open("127.0.0.1", port)
        return {
            "time": _now(),
            "project_root": str(PROJECT_ROOT),
            "services": service_status,
            "mt5": self.account_snapshot(),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "readonly": self.config.mt5_readonly,
        }

    @staticmethod
    def _port_open(host: str, port: int, timeout: float = 0.2) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False
