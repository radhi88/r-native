import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .capabilities import CapabilityBroker
from .hardware import hardware_report
from .neural_memory import NeuralMemory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QADER_LIVE_STATE = PROJECT_ROOT / "dashboard" / "qader_live_state.json"
QADER_LOOP_LOG = PROJECT_ROOT / "logs" / "qader_realtime_loop.jsonl"


class LlamaCppClient:
    """HTTP client for a local llama.cpp server.

    Expected server:
      llama-server -m model.gguf --host 127.0.0.1 --port 8080
    """

    def __init__(self, model=None, host=None):
        self.model = model or os.environ.get("MT5_AI_LOCAL_MODEL", "qwen2.5-7b-instruct-q4_k_m")
        self.host = (host or os.environ.get("LLAMA_CPP_HOST", "http://127.0.0.1:8080")).rstrip("/")

    def available(self):
        for path in ("/health", "/v1/models"):
            try:
                with urllib.request.urlopen(f"{self.host}{path}", timeout=2) as response:
                    if response.status < 500:
                        return True
            except Exception:
                continue
        return False

    def generate(self, messages):
        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": 0.35,
                "max_tokens": 700,
                "stream": False,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{self.host}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            return f"llama.cpp error: {body}"
        except Exception as exc:
            return f"llama.cpp unavailable: {exc}"


class LocalMind:
    def __init__(self, memory=None, llm=None, broker=None, event_bus=None, orchestrator=None):
        self.memory = memory or NeuralMemory()
        self.llm = llm or LlamaCppClient()
        self.broker = broker or CapabilityBroker(memory=self.memory)
        self.event_bus = event_bus
        self.orch = orchestrator  # OrchestratorAdapter أو None

    def status(self):
        return {
            "identity": "FRIDAY Private Local Neural Assistant",
            "cloud": False,
            "llama_cpp_available": self.llm.available(),
            "llama_cpp_host": self.llm.host,
            "llama_cpp_model": self.llm.model,
            "memory": self.memory.stats(),
            "capabilities": {
                "project_files": "brokered",
                "system": "brokered",
                "mt5": "paper_demo_allowed",
                "paper_trading": "allowed",
                "demo_trading": "allowed",
                "live_trading": "locked",
            },
        }

    def chat(self, text, assistant=None):
        self.memory.record_command(text, status="received")
        self.memory.remember("user", text, tags=["chat"], importance=1.0)
        self._event("thinking", {"message": "processing_command"})
        market_context = self.market_snapshot(assistant)
        self._event(
            "market_context",
            {
                "symbol": market_context.get("symbol"),
                "source": market_context.get("source"),
                "stale": market_context.get("stale"),
                "tick": market_context.get("tick"),
                "qader": market_context.get("qader", {}),
            },
        )

        # جرّب أوامر Orchestrator أولاً إذا كان مربوطاً
        tool_result = self._maybe_use_orch_tool(text) if self.orch else None
        if tool_result is None and assistant is not None:
            tool_result = self._maybe_use_tool(text, assistant)

        memories = [
            item for item in self.memory.search(text, limit=8)
            if item.get("content") != text
        ]

        if tool_result is not None:
            answer = self._summarize_tool(tool_result)
            if self._looks_like_market_question(str(text or "").lower()):
                answer = f"{answer}\n{self._market_summary_line(market_context)}"
        elif self.llm.available():
            answer = self._llama_answer(text, tool_result, memories, assistant, market_context)
        else:
            answer = self._local_answer(text, tool_result, memories, assistant, market_context)

        self.memory.remember("friday", answer, tags=["chat"], importance=0.8)
        self.memory.record_command(text, result=answer[:1000], status="ok")
        self._event("answer", {"answer": answer, "tool_result": tool_result, "market_context": market_context})

        return {
            "answer": answer,
            "tool_result": tool_result,
            "market_context": market_context,
            "mind": self.status(),
        }

    def _event(self, event_type, payload=None):
        if self.event_bus is not None:
            self.event_bus.publish(event_type, payload or {})

    @staticmethod
    def _safe_json(data):
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)

    def market_snapshot(self, assistant=None) -> dict[str, Any]:
        symbol = self._assistant_symbol(assistant)
        qader_state = self._read_json_file(QADER_LIVE_STATE)
        latest = qader_state.get("latest_record") if isinstance(qader_state, dict) else {}
        latest = latest if isinstance(latest, dict) else {}
        decision_record = latest if self._is_qader_decision_record(latest) else self._latest_qader_decision_record()
        decision_record = decision_record or latest
        loop = qader_state.get("loop") if isinstance(qader_state, dict) else {}
        loop = loop if isinstance(loop, dict) else {}
        last_chart = self._last_chart_point(qader_state)

        symbol = str(decision_record.get("symbol") or latest.get("symbol") or last_chart.get("symbol") or symbol or "XAUUSDm")
        mt5_data = self._mt5_snapshot(symbol)
        tick = mt5_data.get("tick") or self._tick_from_state(latest, last_chart)

        state_ts = qader_state.get("timestamp") if isinstance(qader_state, dict) else None
        age_seconds = self._age_seconds(state_ts)
        sources = []
        if qader_state:
            sources.append("qader_live_state")
        if mt5_data.get("connected"):
            sources.append("mt5_direct")

        context = {
            "connected": bool(sources),
            "source": "+".join(sources) if sources else "unavailable",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "state_timestamp": state_ts,
            "state_age_seconds": age_seconds,
            "stale": age_seconds is not None and age_seconds > 20,
            "symbol": symbol,
            "timeframe": decision_record.get("timeframe") or latest.get("timeframe") or last_chart.get("timeframe") or self._assistant_timeframe(assistant),
            "tick": tick,
            "qader": {
                "state": loop.get("state"),
                "thread_alive": bool(loop.get("thread_alive")),
                "allow_new_entries": bool(loop.get("allow_new_entries")),
                "cycle_count": loop.get("cycle_count"),
                "last_signal": loop.get("last_signal"),
                "last_decision": loop.get("last_decision"),
                "last_block_reason": loop.get("last_block_reason"),
                "decision_cycle": decision_record.get("cycle_number"),
                "final_action": self._first_value(decision_record.get("final_action"), latest.get("final_action"), last_chart.get("final_action")),
                "arbiter_result": self._first_value(decision_record.get("arbiter_result"), latest.get("arbiter_result")),
                "confidence": self._first_value(decision_record.get("confidence"), latest.get("confidence"), last_chart.get("confidence")),
                "buy_agent_score": self._first_value(decision_record.get("buy_agent_score"), latest.get("buy_agent_score")),
                "sell_agent_score": self._first_value(decision_record.get("sell_agent_score"), latest.get("sell_agent_score")),
                "risk_status": self._first_value(decision_record.get("risk_status"), latest.get("risk_status"), last_chart.get("risk_status")),
                "execution_status": self._first_value(decision_record.get("execution_status"), latest.get("execution_status"), last_chart.get("execution_status")),
                "reason": self._first_value(decision_record.get("reason"), latest.get("reason")),
                "blocked_reason": self._first_value(decision_record.get("blocked_reason"), latest.get("blocked_reason")),
                "pending_order_status": self._first_value(decision_record.get("pending_order_status"), latest.get("pending_order_status")),
            },
            "positions": mt5_data.get("positions", []),
            "pending_orders": mt5_data.get("pending_orders", []),
            "account": mt5_data.get("account", {}),
            "levels": qader_state.get("market_levels") or decision_record.get("market_levels") or latest.get("market_levels") or {},
            "pending_plan": qader_state.get("pending_plan") or decision_record.get("pending_plan") or latest.get("pending_plan") or {},
            "fusion_candle": qader_state.get("fusion_candle") or decision_record.get("fusion_candle") or latest.get("fusion_candle") or {},
            "structure": self._compact_structure(qader_state.get("structure_map") or decision_record.get("structure_map") or latest.get("structure_map") or {}),
            "indicators": self._compact_indicators(qader_state.get("indicator_pack") or decision_record.get("indicator_pack") or latest.get("indicator_pack") or {}),
            "mt5_error": mt5_data.get("error"),
            "qader_state_path": str(QADER_LIVE_STATE),
        }
        return context

    @staticmethod
    def _first_value(*values: Any) -> Any:
        for value in values:
            if value is not None and value != "":
                return value
        return None

    @staticmethod
    def _is_qader_decision_record(record: dict[str, Any]) -> bool:
        if not isinstance(record, dict):
            return False
        return any(record.get(key) not in (None, "") for key in ("final_action", "arbiter_result", "execution_status"))

    def _latest_qader_decision_record(self) -> dict[str, Any]:
        try:
            lines = QADER_LOOP_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return {}
        for line in reversed(lines[-500:]):
            try:
                record = json.loads(line)
            except Exception:
                continue
            if self._is_qader_decision_record(record):
                return record
        return {}

    @staticmethod
    def _read_json_file(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return {}

    @staticmethod
    def _last_chart_point(state: dict[str, Any]) -> dict[str, Any]:
        try:
            history = state.get("chart_history") or []
            if isinstance(history, list) and history:
                point = history[-1]
                return point if isinstance(point, dict) else {}
        except Exception:
            pass
        return {}

    @staticmethod
    def _age_seconds(timestamp: Any) -> float | None:
        if not timestamp:
            return None
        try:
            text = str(timestamp).replace("Z", "+00:00")
            if text.endswith("+00:00"):
                from datetime import datetime, timezone

                dt = datetime.fromisoformat(text)
                return max(0.0, time.time() - dt.astimezone(timezone.utc).timestamp())
            from datetime import datetime

            dt = datetime.fromisoformat(text)
            return max(0.0, time.time() - dt.timestamp())
        except Exception:
            return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        try:
            if value is None or value == "":
                return None
            value = float(value)
            if value != value:
                return None
            return value
        except Exception:
            return None

    def _tick_from_state(self, latest: dict[str, Any], chart: dict[str, Any]) -> dict[str, Any]:
        bid = self._to_float(latest.get("bid")) or self._to_float(chart.get("bid"))
        ask = self._to_float(latest.get("ask")) or self._to_float(chart.get("ask"))
        mid = self._to_float(latest.get("mid")) or self._to_float(chart.get("mid"))
        if mid is None and bid is not None and ask is not None:
            mid = round((bid + ask) / 2.0, 5)
        spread = self._to_float(latest.get("spread")) or self._to_float(chart.get("spread"))
        return {
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": spread,
            "source": "qader_live_state",
        }

    @staticmethod
    def _assistant_symbol(assistant) -> str:
        try:
            return str(getattr(assistant.state, "symbol", "XAUUSDm"))
        except Exception:
            return "XAUUSDm"

    @staticmethod
    def _assistant_timeframe(assistant) -> str:
        try:
            return str(getattr(assistant.state, "timeframe", "M1"))
        except Exception:
            return "M1"

    def _mt5_snapshot(self, symbol: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "connected": False,
            "tick": {},
            "positions": [],
            "pending_orders": [],
            "account": {},
            "error": None,
        }
        try:
            import MetaTrader5 as mt5
        except Exception as exc:
            result["error"] = f"MetaTrader5 import failed: {exc}"
            return result

        try:
            if not mt5.initialize():
                result["error"] = f"mt5.initialize failed: {mt5.last_error()}"
                return result

            result["connected"] = True
            try:
                mt5.symbol_select(symbol, True)
            except Exception:
                pass

            info = mt5.symbol_info(symbol)
            point = float(getattr(info, "point", 0.01) or 0.01)
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                bid = self._to_float(getattr(tick, "bid", None))
                ask = self._to_float(getattr(tick, "ask", None))
                result["tick"] = {
                    "bid": bid,
                    "ask": ask,
                    "last": self._to_float(getattr(tick, "last", None)),
                    "mid": round((bid + ask) / 2.0, 5) if bid is not None and ask is not None else None,
                    "spread": round((ask - bid) / point, 1) if bid is not None and ask is not None and point else None,
                    "time": getattr(tick, "time", None),
                    "source": "mt5_direct",
                }

            account = mt5.account_info()
            if account:
                result["account"] = {
                    "login": getattr(account, "login", None),
                    "server": getattr(account, "server", None),
                    "balance": self._to_float(getattr(account, "balance", None)),
                    "equity": self._to_float(getattr(account, "equity", None)),
                    "margin_free": self._to_float(getattr(account, "margin_free", None)),
                }

            positions = mt5.positions_get(symbol=symbol) or []
            result["positions"] = [self._mt5_position_dict(mt5, pos) for pos in positions]

            orders = mt5.orders_get(symbol=symbol) or []
            result["pending_orders"] = [self._mt5_order_dict(mt5, order) for order in orders]
            return result
        except Exception as exc:
            result["error"] = str(exc)
            return result

    def _mt5_position_dict(self, mt5, pos) -> dict[str, Any]:
        return {
            "ticket": int(getattr(pos, "ticket", 0) or 0),
            "symbol": getattr(pos, "symbol", ""),
            "type": "BUY" if int(getattr(pos, "type", 0) or 0) == int(getattr(mt5, "POSITION_TYPE_BUY", 0)) else "SELL",
            "volume": self._to_float(getattr(pos, "volume", None)),
            "open_price": self._to_float(getattr(pos, "price_open", None)),
            "current": self._to_float(getattr(pos, "price_current", None)),
            "sl": self._to_float(getattr(pos, "sl", None)),
            "tp": self._to_float(getattr(pos, "tp", None)),
            "profit": self._to_float(getattr(pos, "profit", None)),
            "magic": int(getattr(pos, "magic", 0) or 0),
            "comment": str(getattr(pos, "comment", "") or ""),
        }

    def _mt5_order_dict(self, mt5, order) -> dict[str, Any]:
        type_names = {
            int(getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2)): "BUY_LIMIT",
            int(getattr(mt5, "ORDER_TYPE_SELL_LIMIT", 3)): "SELL_LIMIT",
            int(getattr(mt5, "ORDER_TYPE_BUY_STOP", 4)): "BUY_STOP",
            int(getattr(mt5, "ORDER_TYPE_SELL_STOP", 5)): "SELL_STOP",
        }
        raw_type = int(getattr(order, "type", -1) or -1)
        return {
            "ticket": int(getattr(order, "ticket", 0) or 0),
            "symbol": getattr(order, "symbol", ""),
            "type": type_names.get(raw_type, str(raw_type)),
            "volume": self._to_float(getattr(order, "volume_current", None)),
            "price": self._to_float(getattr(order, "price_open", None)),
            "sl": self._to_float(getattr(order, "sl", None)),
            "tp": self._to_float(getattr(order, "tp", None)),
            "magic": int(getattr(order, "magic", 0) or 0),
            "comment": str(getattr(order, "comment", "") or ""),
        }

    @staticmethod
    def _compact_structure(structure: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(structure, dict):
            return {}
        return {
            "prediction": structure.get("prediction") or {},
            "bos": structure.get("bos"),
            "order_block": structure.get("order_block") or {},
            "liquidity": (structure.get("liquidity") or [])[:4],
            "ifvg": (structure.get("ifvg") or [])[:4],
            "drift": structure.get("drift") or {},
            "micro_pattern": structure.get("micro_pattern"),
            "volume_surge": structure.get("volume_surge"),
        }

    @staticmethod
    def _compact_indicators(indicators: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(indicators, dict):
            return {}
        return {
            "classic": indicators.get("classic") or {},
            "trend": indicators.get("trend") or {},
            "structure": indicators.get("structure") or {},
            "volume": indicators.get("volume") or {},
            "microstructure": indicators.get("microstructure") or {},
        }

    def _market_summary_line(self, market_context: dict[str, Any]) -> str:
        tick = market_context.get("tick") or {}
        qader = market_context.get("qader") or {}
        structure = market_context.get("structure") or {}
        prediction = structure.get("prediction") or {}
        bid = tick.get("bid")
        ask = tick.get("ask")
        spread = tick.get("spread")
        stale = "، الحالة قديمة" if market_context.get("stale") else ""
        action = qader.get("final_action") or qader.get("arbiter_result") or "HOLD"
        bias = prediction.get("bias") or "HOLD"
        confidence = qader.get("confidence") or prediction.get("confidence")
        exec_status = qader.get("execution_status") or "unknown"
        reason = qader.get("blocked_reason") or qader.get("reason") or qader.get("last_block_reason")
        reason_text = f" السبب: {self._arabic_reason(reason)}." if reason else ""
        return (
            f"السوق المباشر {market_context.get('symbol')}: bid={bid} ask={ask} spread={spread}{stale}. "
            f"قرار Qader الآن: {action}، توقع البنية: {bias}، الثقة={confidence}، التنفيذ={exec_status}."
            f"{reason_text}"
        )

    @staticmethod
    def _looks_like_market_question(lowered: str) -> bool:
        return any(
            word in lowered
            for word in [
                "السوق",
                "سعر",
                "الشارت",
                "شراء",
                "بيع",
                "صفقة",
                "صفقات",
                "دخل",
                "وقف",
                "قادِر",
                "قادر",
                "qader",
                "mt5",
                "market",
                "price",
                "trade",
                "position",
            ]
        )

    def _safe_record_trade(self, mode, symbol, side, result):
        try:
            self.memory.record_trade(
                mode=mode,
                symbol=symbol,
                side=side,
                payload=json.dumps(result, ensure_ascii=True, default=str),
                sent=bool(result.get("executed")) if isinstance(result, dict) else False,
            )
        except Exception:
            pass

    @staticmethod
    def _looks_like_live_request(lowered):
        return any(
            phrase in lowered
            for phrase in [
                "live",
                "حقيقي",
                "حساب حقيقي",
                "auto live",
                "live auto",
            ]
        )

    @staticmethod
    def _looks_like_gold_request(lowered):
        return any(
            word in lowered
            for word in [
                "ذهب",
                "gold",
                "xau",
                "xauusd",
                "xauusdm",
            ]
        )

    @staticmethod
    def _looks_like_scalping_request(lowered):
        return any(
            word in lowered
            for word in [
                "سكالب",
                "سكالبينج",
                "scalp",
                "scalping",
            ]
        )

    @staticmethod
    def _looks_like_trade_request(lowered):
        return any(
            word in lowered
            for word in [
                "تداول",
                "ادخل",
                "ادخلي",
                "دخول",
                "نفذ",
                "نفذي",
                "افتح",
                "افتحي",
                "اشتري",
                "شراء",
                "بيع",
                "بيعي",
                "trade",
                "execute",
                "open",
                "buy",
                "sell",
            ]
        )

    @staticmethod
    def _looks_like_demo_request(lowered):
        return any(
            phrase in lowered
            for phrase in [
                "demo",
                "demo mt5",
                "ديمو",
                "ديمو mt5",
                "تجريبي",
                "تجريبي mt5",
                "حساب وهمي",
            ]
        )

    @staticmethod
    def _looks_like_paper_request(lowered):
        return any(
            phrase in lowered
            for phrase in [
                "paper",
                "ورقي",
            ]
        )

    @staticmethod
    def _looks_like_spread_override(lowered):
        return any(
            phrase in lowered
            for phrase in [
                "تجاوز السبريد",
                "تجاهل السبريد",
                "تجاهلي السبريد",
                "تجاوزي السبريد",
                "الغاء فلتر السبريد",
                "إلغاء فلتر السبريد",
                "ignore spread",
                "override spread",
                "بدون سبريد",
            ]
        )

    @staticmethod
    def _looks_like_spread_respect(lowered):
        return any(
            phrase in lowered
            for phrase in [
                "فعل فلتر السبريد",
                "فعّل فلتر السبريد",
                "ارجع فلتر السبريد",
                "رجع فلتر السبريد",
                "enable spread filter",
                "respect spread",
            ]
        )

    @staticmethod
    def _looks_like_obey(lowered):
        return any(
            phrase in lowered
            for phrase in [
                "اطيع",
                "أطيع",
                "طيعني",
                "طيعيني",
                "obey",
                "ذهب سكالب",
                "سكالبينج الذهب",
                "خله يطيعني",
                "خليها تطيعني",
                "خله يطيع",
                "خليها تطيع",
            ]
        )

    @staticmethod
    def _looks_like_market_scan(lowered):
        return any(
            phrase in lowered
            for phrase in [
                "كل الاسواق",
                "كل الأسواق",
                "جميع الاسواق",
                "جميع الأسواق",
                "all markets",
                "market scan",
                "scan markets",
            ]
        )

    def _maybe_use_orch_tool(self, text) -> dict | None:
        """أوامر مرتبطة مباشرة بـFridayOrchestrator عبر OrchestratorAdapter."""
        lowered = str(text or "").lower()

        # حالة / status
        if any(w in lowered for w in ["حالة", "status", "وضع النظام", "كيف النظام"]):
            return {"type": "orch_status", "data": self.orch.status()}

        # الصفقات المفتوحة
        if any(w in lowered for w in ["صفقات", "positions", "مفتوحة", "عندي"]):
            pos = self.orch.positions()
            return {"type": "orch_positions", "data": pos}

        # إحصائيات التعلم
        if any(w in lowered for w in ["تعلم", "learning", "أداء", "نتائج", "إحصائيات"]):
            return {"type": "orch_learning", "data": self.orch.learning_summary()}

        # طلب إيقاف
        if any(w in lowered for w in ["أوقف", "وقف", "stop", "إيقاف", "اوقف"]):
            msg = self.orch.request_stop()
            return {"type": "orch_stop", "data": {"message": msg}}

        return None

    def _maybe_use_tool(self, text, assistant):
        lowered = str(text or "").lower()

        wants_trade = self._looks_like_trade_request(lowered)
        wants_demo = self._looks_like_demo_request(lowered)
        wants_paper = self._looks_like_paper_request(lowered)
        wants_gold = self._looks_like_gold_request(lowered)
        wants_scalping = self._looks_like_scalping_request(lowered)
        wants_spread_override = self._looks_like_spread_override(lowered)
        wants_spread_respect = self._looks_like_spread_respect(lowered)
        wants_obey = self._looks_like_obey(lowered)
        wants_all_markets = self._looks_like_market_scan(lowered)
        wants_live = self._looks_like_live_request(lowered)

        if wants_gold and hasattr(assistant, "set_symbol"):
            assistant.set_symbol("XAUUSDm")

        if wants_scalping and hasattr(assistant, "set_profile"):
            assistant.set_profile("scalping")

        if wants_spread_override and hasattr(assistant, "set_spread_override"):
            return {
                "type": "risk_override",
                "data": assistant.set_spread_override(True),
            }

        if wants_spread_respect and hasattr(assistant, "set_spread_override"):
            return {
                "type": "risk_override",
                "data": assistant.set_spread_override(False),
            }

        if wants_obey:
            symbol = "XAUUSDm" if wants_gold else getattr(assistant.state, "symbol", "XAUUSDm")

            if hasattr(assistant, "obey_aggressive_scalping"):
                data = assistant.obey_aggressive_scalping(symbol=symbol, mode="demo")
            else:
                assistant.state.source = "mt5"
                assistant.set_profile("scalping")
                assistant.set_mode("demo")
                assistant.set_spread_override(True)
                data = assistant.status()

            self._event("tool", {"tool": "obey_aggressive_scalping", "mode": assistant.state.mode})
            return {
                "type": "obey",
                "data": data,
            }

        if wants_live:
            message = assistant.set_mode("live") if hasattr(assistant, "set_mode") else "LIVE AUTO محجوب."
            return {
                "type": "mode",
                "data": {
                    "message": message,
                    "status": assistant.status(),
                },
            }

        # أهم إصلاح:
        # "فرايدي نفذي ديمو MT5 إذا الصفقة مناسبة"
        # لا يمر على CapabilityBroker القديم؛ لأنه عندك يطلع رسالة Mode must be Live.
        # هذا المسار يضبط Demo ثم ينفذ execute_suitable_demo مباشرة.
        if wants_trade and wants_demo:
            result = self._execute_demo_suitable(assistant)
            return {
                "type": "execution",
                "data": result,
            }

        if wants_trade and wants_paper:
            result = self._execute_paper_suitable(assistant)
            return {
                "type": "execution",
                "data": result,
            }

        if wants_demo and not wants_trade:
            assistant.set_mode("demo")

            if getattr(assistant.state, "profile", "") == "scalping" and hasattr(assistant, "set_spread_override"):
                assistant.set_spread_override(True)

            return {
                "type": "mode",
                "data": {
                    "message": "Mode set to demo",
                    "status": assistant.status(),
                },
            }

        if wants_paper and not wants_trade:
            assistant.set_mode("paper")
            return {
                "type": "mode",
                "data": {
                    "message": "Mode set to paper",
                    "status": assistant.status(),
                },
            }

        if wants_all_markets and wants_trade:
            if assistant.state.mode == "demo":
                data = assistant.execute_market_scan_demo()
            else:
                data = assistant.execute_market_scan_paper()

            return {
                "type": "market_scan_execution",
                "data": data,
            }

        if wants_all_markets:
            decision = self.broker.authorize("mt5", "analyze", {"scope": "all_markets"})
            if not decision.allowed:
                return {
                    "type": "blocked",
                    "data": decision.__dict__,
                }

            self._event("tool", {"tool": "market_scan"})
            return {
                "type": "market_scan",
                "data": assistant.scan_markets(),
            }

        if any(word in lowered for word in ["حلل", "analyze", "تحليل"]):
            decision = self.broker.authorize("mt5", "analyze", {"source": assistant.state.source})
            if not decision.allowed:
                return {
                    "type": "blocked",
                    "data": decision.__dict__,
                }

            self._event("tool", {"tool": "analyze"})
            return {
                "type": "analysis",
                "data": assistant.analyze(),
            }

        if wants_trade:
            if assistant.state.mode == "demo":
                result = self._execute_demo_suitable(assistant)
            elif assistant.state.mode == "paper":
                result = self._execute_paper_suitable(assistant)
            else:
                result = {
                    "executed": False,
                    "mode": "blocked",
                    "result": {
                        "sent": False,
                        "reason": "live_trading_permanently_disabled",
                        "message": "LIVE AUTO محجوب. استخدم Paper أو Demo MT5.",
                    },
                    "decision": assistant.last_decision or {},
                }

            return {
                "type": "execution",
                "data": result,
            }

        if any(word in lowered for word in ["حالة", "status"]):
            return {
                "type": "status",
                "data": assistant.status(),
            }

        if any(word in lowered for word in ["gpu", "كرت", "الشاشة"]):
            gate = self.broker.authorize("system", "hardware_status", {})
            if not gate.allowed:
                return {
                    "type": "blocked",
                    "data": gate.__dict__,
                }

            return {
                "type": "hardware",
                "data": hardware_report(),
            }

        if any(word in lowered for word in ["النظام", "صلاحيات", "جهازي", "system"]):
            return {
                "type": "system",
                "data": self.broker.system_snapshot(),
            }

        remember_intents = [
            "تذكري أن",
            "تذكري ان",
            "تذكر أن",
            "تذكر ان",
            "احفظ ",
            "احفظي",
            "remember that",
            "remember:",
        ]

        if any(phrase in lowered for phrase in remember_intents):
            gate = self.broker.authorize("memory", "remember", {"text": text})
            if not gate.allowed:
                return {
                    "type": "blocked",
                    "data": gate.__dict__,
                }

            if any(word in lowered for word in ["أفضل", "افضل", "prefer"]):
                self.memory.set_fact("trading_preference", text)

            self.memory.remember("user_fact", text, tags=["explicit_memory"], importance=2.0)
            return {
                "type": "memory",
                "data": {
                    "saved": True,
                },
            }

        return None

    def _execute_demo_suitable(self, assistant):
        assistant.state.source = "mt5"
        mode_message = assistant.set_mode("demo")

        if getattr(assistant.state, "profile", "") == "scalping" and hasattr(assistant, "set_spread_override"):
            assistant.set_spread_override(True)

        self._event("tool", {"tool": "demo_trade", "mode": "demo"})

        if hasattr(assistant, "execute_suitable_demo"):
            result = assistant.execute_suitable_demo(assistant.last_decision)
        else:
            decision = assistant.last_decision or assistant.analyze()
            result = assistant.execute_decision(decision)

        if isinstance(result, dict):
            result.setdefault("mode_message", mode_message)
            decision = result.get("decision") or assistant.last_decision or {}

            self._safe_record_trade(
                mode="demo",
                symbol=decision.get("symbol", assistant.state.symbol),
                side=decision.get("action", "NO_TRADE"),
                result=result,
            )

        return result

    def _execute_paper_suitable(self, assistant):
        mode_message = assistant.set_mode("paper")
        self._event("tool", {"tool": "paper_trade", "mode": "paper"})

        decision = assistant.last_decision or assistant.analyze()
        result = assistant.execute_decision(decision)

        if isinstance(result, dict):
            result.setdefault("mode_message", mode_message)
            decision = result.get("decision") or decision or {}

            self._safe_record_trade(
                mode="paper",
                symbol=decision.get("symbol", assistant.state.symbol),
                side=decision.get("action", "NO_TRADE"),
                result=result,
            )

        return result

    def _llama_answer(self, text, tool_result, memories, assistant, market_context):
        messages = self._build_messages(text, tool_result, memories, assistant, market_context)
        return self.llm.generate(messages)

    def _build_messages(self, text, tool_result, memories, assistant, market_context):
        memory_text = "\n".join(
            f"- [{item['role']}] {item['content']}" for item in memories
        )

        tool_text = json.dumps(tool_result, ensure_ascii=False, indent=2, default=str) if tool_result else "No tool used."
        status_text = json.dumps(assistant.status(), ensure_ascii=False, indent=2, default=str)
        market_text = json.dumps(market_context, ensure_ascii=False, indent=2, default=str)

        system = """
أنت FRIDAY — مساعد تداول محلي خاص. تعمل دون إنترنت. تتحدث العربية بشكل مختصر ودقيق.
لديك: ذاكرة محلية، نموذج Keras للتنبؤ، مؤشرات SMC، ومنفذ صفقات ورقية/ديمو.
لديك سياق سوق مباشر من Qader و MT5 في كل رسالة. لا تخمن السعر أو الصفقة؛ استخدم Market context، وإذا كانت stale فاذكر ذلك.

قواعد التداول:
- Paper و Demo MT5 مسموحان.
- Live / Auto Live محجوبان من الباكند.
- في وضع XAUUSDm scalping demo/paper يمكن تجاهل السبريد حسب إعدادات المستخدم.
- إذا كان القرار BUY أو SELL في الديمو، نفذ ديمو فقط.
- لا تدّعي تنفيذ live حقيقي.

قواعد الرد:
1. اذكر القرار والسبب باختصار.
2. لا تطيل ولا تبدأ بمقدمات.
3. إذا كان هناك تنفيذ، اذكر هل executed=true أو false.
""".strip()

        user = f"""
System status:
{status_text}

Relevant local memory:
{memory_text}

Live market context:
{market_text}

Tool result:
{tool_text}

User said:
{text}

Reply briefly and practically. If there is a trading decision, explain the reason.
""".strip()

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _local_answer(self, text, tool_result, memories, assistant, market_context=None):
        if tool_result:
            return self._summarize_tool(tool_result)

        lowered = text.lower()
        if self._looks_like_market_question(lowered):
            return self._market_summary_line(market_context or {})

        if any(word in lowered for word in ["تفضيل", "صفقات", "prefer"]):
            preference = self.memory.get_fact("trading_preference")
            if preference:
                return f"أتذكر تفضيلك المحلي: {preference}"

        if "من انت" in lowered or "who are you" in lowered:
            return (
                "أنا FRIDAY المحلي الخاص بك: ذاكرة عصبية SQLite، عقل تداول، "
                "وموصل MT5 وصلاحيات عبر بوابة أمان. نموذج المحادثة الكبير سيعمل عبر llama.cpp "
                "بعد تثبيت GGUF محلي."
            )

        if "نموذج" in lowered or "model" in lowered:
            return (
                "نموذج التداول الخاص بك موجود في models/hybrid_model.keras. "
                "نموذج المحادثة المحلي المستهدف هو GGUF عبر llama.cpp على 127.0.0.1:8080. "
                "الذاكرة الخاصة موجودة في data/journal/jarvis_memory.sqlite3."
            )

        if memories:
            remembered = self._select_memory(memories)["content"]
            return f"استرجعت من ذاكرتي المحلية: {remembered}\nقل لي: حللي السوق، أو اعرضي حالة النظام."

        return (
            "أنا FRIDAY شغالة محليًا بذاكرة وأدوات تداول. نموذج llama.cpp غير متصل بعد، "
            "لكن الشات الآن يستقبل سياق السوق المباشر مع كل رسالة، وأقدر أحلل السوق وأدير Paper/Demo Trading."
        )

    def _select_memory(self, memories):
        explicit = [item for item in memories if "explicit_memory" in (item.get("tags") or "")]
        if explicit:
            return explicit[0]

        conversational = [
            item for item in memories
            if not self._looks_like_question(item.get("content", ""))
        ]

        return (conversational or memories)[0]

    @staticmethod
    def _looks_like_question(text):
        lowered = (text or "").strip().lower()

        return (
            "؟" in lowered
            or "?" in lowered
            or lowered.startswith(("ما ", "وش ", "هل ", "what ", "which "))
        )

    def _summarize_tool(self, tool_result):
        data = tool_result.get("data")
        kind = tool_result.get("type")

        # ── أوامر Orchestrator ───────────────────────────────────────────────────
        if kind == "orch_status":
            sym   = data.get("symbol", "?")
            bars  = data.get("bars", 0)
            opened= data.get("trades_opened", 0)
            open_c= data.get("open_count", 0)
            lrn   = data.get("learning", {})
            wr    = lrn.get("win_rate", 0)
            pf    = lrn.get("profit_factor", 0)
            return (
                f"FRIDAY [{sym}] — bars={bars}  صفقات فُتحت={opened}  مفتوحة الآن={open_c}\n"
                f"تعلّم: WR={wr:.0%}  PF={pf:.2f}  ({lrn.get('trades',0)} صفقة محفوظة)"
            )

        if kind == "orch_positions":
            if not data:
                return "لا توجد صفقات مفتوحة الآن."
            lines = []
            for tid, pos in data.items():
                side  = pos.get("side","?")
                entry = pos.get("entry", 0)
                sl    = pos.get("sl", 0)
                tp    = pos.get("tp", 0)
                be    = "✓" if pos.get("be_applied") else "·"
                lines.append(f"  {tid}: {side} @ {entry:.2f}  SL={sl:.2f}  TP={tp:.2f}  BE={be}")
            return "الصفقات المفتوحة:\n" + "\n".join(lines)

        if kind == "orch_learning":
            if not data or not data.get("trades"):
                return "لا توجد بيانات تعلم بعد."
            return (
                f"تعلّم ({data['trades']} صفقة): "
                f"WR={data.get('win_rate',0):.0%}  "
                f"PF={data.get('profit_factor',0):.2f}  "
                f"متوسط R={data.get('avg_r',0):.2f}"
            )

        if kind == "orch_stop":
            return data.get("message", "طلب الإيقاف مُسجَّل.")



        if kind == "analysis":
            action = data.get("action")
            reason = self._arabic_reason(data.get("reason"))
            probability = data.get("probability")
            spread = data.get("spread")
            ignored = data.get("spread_filter_ignored")

            probability_text = f"{float(probability):.3f}" if probability is not None else "غير متاح"
            spread_text = "غير متاح" if spread is None else str(spread)
            override_text = " تم تجاهل فلتر السبريد لهذا التحليل." if ignored else ""

            return (
                f"حللت السوق: القرار {action}. الاحتمال {probability_text}، "
                f"السبريد {spread_text}. السبب: {reason}.{override_text}"
            )

        if kind == "execution":
            if not isinstance(data, dict):
                return f"أمر التنفيذ انتهى: {data}"

            executed = data.get("executed")
            result = data.get("result") or {}
            decision = data.get("decision") or {}

            reason = (
                data.get("reason")
                or result.get("reason")
                or result.get("comment")
                or result.get("retcode")
                or "غير محدد"
            )

            symbol = decision.get("symbol", "")
            action = decision.get("action", "")
            mode = data.get("mode") or result.get("mode") or "unknown"
            sent = result.get("sent")
            sent_text = f"، sent={sent}" if sent is not None else ""

            return (
                f"أمر التنفيذ انتهى. التنفيذ={executed}{sent_text}. "
                f"الوضع {mode}. الرمز {symbol}، القرار {action}. "
                f"السبب: {self._arabic_reason(reason)}."
            )

        if kind == "market_scan":
            return self._summarize_market_scan(data)

        if kind == "market_scan_execution":
            scan = data.get("scan", {})
            executions = data.get("executions", [])
            base = self._summarize_market_scan(scan)
            sent = sum(1 for item in executions if item.get("executed"))
            mode = data.get("mode", "paper")

            return f"{base}\nوضع التنفيذ: {mode}. أوامر منفذة: {sent} من {len(executions)}."

        if kind == "blocked":
            reason = data.get("reason") if isinstance(data, dict) else data
            return f"أوقفت الأمر عبر بوابة الصلاحيات: {self._arabic_reason(reason)}."

        if kind in {"status", "hardware", "system"}:
            return json.dumps(data, ensure_ascii=False, indent=2, default=str)

        if kind == "memory":
            return "حفظت المعلومة في ذاكرتي المحلية."

        if kind == "mode":
            if isinstance(data, dict):
                return data.get("message", "تم تغيير الوضع.")
            return "تم تغيير الوضع."

        if kind == "risk_override":
            if isinstance(data, dict):
                return data.get("message", "تم تحديث فلتر السبريد.")
            return "تم تحديث فلتر السبريد."

        if kind == "obey":
            if isinstance(data, dict):
                return data.get("message", "تم ضبط وضع الطاعة الآمن.")
            return "تم ضبط وضع الطاعة الآمن."

        return json.dumps(tool_result, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def _summarize_market_scan(data):
        scanned = data.get("scanned", 0)
        tradable = data.get("tradable", [])
        top = data.get("top", [])

        if tradable:
            picks = ", ".join(
                f"{item['symbol']} {item['action']} ({LocalMind._arabic_reason(item.get('reason'))})"
                for item in tradable[:5]
            )
            return f"مسحت {scanned} سوق. أفضل فرص قابلة للتنفيذ: {picks}."

        if top:
            picks = ", ".join(
                f"{item['symbol']} {item['action']} ({LocalMind._arabic_reason(item.get('reason'))})"
                for item in top[:5]
            )
            return f"مسحت {scanned} سوق. لا توجد BUY/SELL الآن. أعلى المرشحين: {picks}."

        errors = data.get("errors", [])
        return f"لم أجد رموزًا قابلة للمسح. الأخطاء: {len(errors)}."

    @staticmethod
    def _arabic_reason(reason):
        if reason is None:
            return "غير محدد"

        text = str(reason)

        if text.startswith("spread_too_high:"):
            value = text.split(":", 1)[1]
            return f"السبريد مرتفع ({value})"

        if text.startswith("prob_neutral"):
            return "احتمال النموذج محايد"

        if "structure_without_entry_confirmation" in text:
            return "الاتجاه موجود لكن لم يصل تأكيد دخول كاف من البنية/SMC"

        if "smc_no_active_setup" in text:
            return "لا توجد setup SMC نشطة عند السعر الحالي"

        if "pending_no_level" in text:
            return "لم يجد مستوى مناسباً للأمر المعلق ضمن شروط المسافة والسيولة"

        if text == "hold_no_order":
            return "انتظار بدون إرسال أمر"

        translations = {
            "filters_not_aligned": "الفلاتر لم تتوافق بعد",
            "model_and_smc_buy": "النموذج و SMC متوافقان على الشراء",
            "model_and_smc_sell": "النموذج و SMC متوافقان على البيع",
            "no_trade": "لا توجد صفقة مناسبة الآن",
            "decision_not_tradeable": "القرار غير قابل للتنفيذ",
            "live_trading_permanently_disabled": "التداول الحقيقي محجوب من الباكند",
            "live_mode_not_allowed": "وضع live غير مسموح",
            "blocked_not_demo_account": "الحساب المتصل ليس ديمو",
            "demo_trading_disabled": "تداول الديمو معطل من الإعدادات",
            "Mode must be Live": "رسالة قديمة من مسار خاطئ؛ تم تجاوزها لمسار الديمو",
        }

        return translations.get(text, text)
