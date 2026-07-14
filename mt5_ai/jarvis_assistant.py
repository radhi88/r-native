from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import joblib
import numpy as np
import pandas as pd
import tensorflow as tf

from .ai_brain import TradingBrain
from .config import (
    AGGRESSIVE_SCALPING_IGNORE_SPREAD,
    CSV_HISTORY,
    DEFAULT_LOT,
    FEATURE_COLUMNS,
    LOG_DIR,
    MAX_DEMO_OPEN_ORDERS,
    MAX_MARKET_SCAN_SYMBOLS,
    MAX_PAPER_SCAN_ORDERS,
    MODEL_PATH,
    MT5_SYMBOL,
    SCALER_PATH,
    SEQ_LEN,
)
from .execution import DemoMT5Executor, PaperExecutor
from .hardware import hardware_report
from .market_structure import add_market_structure
from .mt5_gateway import MT5Gateway
from .strategy_profiles import PROFILES

# Optional: route demo execution through ExecutionManager for Qader safety gates.
# Falls back to DemoMT5Executor silently if the core package is not importable.
_EXECUTION_MANAGER_AVAILABLE = False
try:
    from src.mt5_ai.core.execution_manager import get_execution_manager
    from src.mt5_ai.core.signal_schema import ExecutionRequest, Direction
    from src.mt5_ai.core.magic_registry import QADER_REAL_CONTROLLED_MAGIC
    _EXECUTION_MANAGER_AVAILABLE = True
except ImportError:
    QADER_REAL_CONTROLLED_MAGIC = 20260514  # fallback constant — never sent without ExecutionManager


ALLOWED_MODES = {"paper", "demo"}
BLOCKED_LIVE_MODES = {"live", "live_auto", "auto_live", "حقيقي", "حساب حقيقي"}
VALID_ACTIONS = {"BUY", "SELL"}


@dataclass
class JarvisState:
    symbol: str = MT5_SYMBOL
    timeframe: str = "M1"
    profile: str = "scalping"
    mode: str = "paper"
    source: str = "mt5"
    bars: int = 500
    lot: float = DEFAULT_LOT


class JarvisAssistant:
    """
    Trading assistant controller.

    Safety rules in this file:
    - PAPER and DEMO MT5 are allowed.
    - LIVE / AUTO LIVE is blocked at the assistant layer.
    - Spread override is allowed only for PAPER/DEMO, mainly for aggressive scalping tests.
    - Demo execution happens only when the latest decision is BUY or SELL.
    """

    def __init__(self, state: JarvisState | None = None, allow_live: bool = False):
        self.state = state or JarvisState()
        self.state.mode = self._normalize_mode(self.state.mode)
        if self.state.mode not in ALLOWED_MODES:
            self.state.mode = "paper"

        # Kept for backward compatibility with existing callers, but live remains blocked here.
        self.allow_live = bool(allow_live)

        self.ignore_spread_filter = bool(
            AGGRESSIVE_SCALPING_IGNORE_SPREAD
            and self.state.profile == "scalping"
            and self.state.mode in ALLOWED_MODES
        )

        self.model = tf.keras.models.load_model(MODEL_PATH, compile=False)
        self.scaler = joblib.load(SCALER_PATH)
        self.brain = TradingBrain(model=self.model, profile_name=self.state.profile)
        self.paper_executor = PaperExecutor()
        self.gateway: MT5Gateway | None = None
        self.last_decision: dict[str, Any] | None = None
        self.command_log = Path(LOG_DIR) / "jarvis_commands.jsonl"

    # ------------------------------------------------------------------
    # Core lifecycle
    # ------------------------------------------------------------------
    def connect_gateway(self) -> MT5Gateway:
        if self.gateway is None:
            self.gateway = MT5Gateway()
            self.gateway.initialize()
        return self.gateway

    def close(self) -> None:
        if self.gateway is not None:
            self.gateway.shutdown()
            self.gateway = None

    def log_event(self, event: dict[str, Any]) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        try:
            self.command_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.command_log, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            # Logging must never break analysis or execution.
            pass

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_mode(mode: str | None) -> str:
        raw = str(mode or "paper").strip().lower().replace("-", "_")
        aliases = {
            "demo_mt5": "demo",
            "mt5_demo": "demo",
            "demo mt5": "demo",
            "demo-mt5": "demo",
            "ديمو": "demo",
            "ديمو mt5": "demo",
            "تجريبي": "demo",
            "تجريبي mt5": "demo",
            "حساب وهمي": "demo",
            "paper_auto": "paper",
            "paper trading": "paper",
            "ورقي": "paper",
            "تجريبي ورقي": "paper",
        }
        return aliases.get(raw, raw)

    def set_mode(self, mode: str) -> str:
        normalized = self._normalize_mode(mode)

        if normalized in BLOCKED_LIVE_MODES or "live" in normalized or "حقيقي" in normalized:
            if self.state.mode not in ALLOWED_MODES:
                self.state.mode = "paper"
            self.log_event({"type": "mode_blocked", "requested_mode": mode, "current_mode": self.state.mode})
            return "LIVE AUTO محجوب من الباكند. الأوضاع المسموحة: PAPER أو DEMO MT5."

        if normalized not in ALLOWED_MODES:
            return "Mode must be Paper or Demo MT5"

        self.state.mode = normalized
        if self.state.profile == "scalping" and AGGRESSIVE_SCALPING_IGNORE_SPREAD:
            self.ignore_spread_filter = True

        self.log_event({"type": "mode_changed", "mode": self.state.mode})
        return f"Mode set to {self.state.mode}"

    def set_profile(self, profile: str) -> str:
        profile = str(profile or "").strip().lower()
        if profile not in PROFILES:
            return f"Unknown profile. Available: {', '.join(PROFILES)}"

        self.state.profile = profile
        self.brain = TradingBrain(model=self.model, profile_name=profile)

        if profile == "scalping" and self.state.mode in ALLOWED_MODES and AGGRESSIVE_SCALPING_IGNORE_SPREAD:
            self.ignore_spread_filter = True

        self.log_event({"type": "profile_changed", "profile": profile})
        return f"Profile set to {profile}"

    def set_symbol(self, symbol: str) -> str:
        symbol = str(symbol or "").strip()
        if not symbol:
            return "Symbol is required"
        self.state.symbol = symbol
        self.log_event({"type": "symbol_changed", "symbol": symbol})
        return f"Symbol set to {symbol}"

    def set_source(self, source: str) -> str:
        source = str(source or "").strip().lower()
        if source not in {"mt5", "csv"}:
            return "Source must be mt5 or csv"
        self.state.source = source
        self.log_event({"type": "source_changed", "source": source})
        return f"Source set to {source}"

    def set_spread_override(self, enabled: bool) -> dict[str, Any]:
        if self.state.mode not in ALLOWED_MODES:
            return {
                "enabled": self.ignore_spread_filter,
                "blocked": True,
                "message": "تجاوز السبريد غير مسموح في Live. استخدم Paper أو Demo.",
            }

        self.ignore_spread_filter = bool(enabled)
        state = "مفعل" if self.ignore_spread_filter else "متوقف"
        result = {
            "enabled": self.ignore_spread_filter,
            "blocked": False,
            "message": f"تجاوز فلتر السبريد {state} في وضع {self.state.mode}.",
        }
        self.log_event({"type": "spread_override", **result})
        return result

    def obey_aggressive_scalping(self, symbol: str | None = None, mode: str = "demo") -> dict[str, Any]:
        """One-shot preset: MT5 + XAU scalping + demo/paper + spread override."""
        messages: list[Any] = []
        messages.append(self.set_source("mt5"))
        messages.append(self.set_symbol(symbol or self.state.symbol or MT5_SYMBOL))
        messages.append(self.set_profile("scalping"))
        messages.append(self.set_mode(mode))
        messages.append(self.set_spread_override(True).get("message"))

        result = {
            "ok": True,
            "message": "تم ضبط وضع الطاعة الآمن: MT5 + scalping + DEMO/PAPER + spread override.",
            "details": messages,
            "status": self.status(),
        }
        self.log_event({"type": "obey_aggressive_scalping", "result": result})
        return result

    # ------------------------------------------------------------------
    # Status and data loading
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        mt5 = None
        if self.gateway is not None:
            try:
                mt5 = self.gateway.account_snapshot()
            except Exception as exc:
                mt5 = {"error": str(exc)}

        return {
            "symbol": self.state.symbol,
            "timeframe": self.state.timeframe,
            "profile": self.state.profile,
            "mode": self.state.mode,
            "source": self.state.source,
            "lot": self.state.lot,
            "bars": self.state.bars,
            "live_trading_enabled": False,
            "live_unlocked_argument": self.allow_live,
            "allowed_execution_modes": sorted(ALLOWED_MODES),
            "ignore_spread_filter": self.ignore_spread_filter,
            "mt5": mt5,
        }

    def load_market_data(self) -> pd.DataFrame:
        return self.load_market_data_for(self.state.symbol)

    def load_market_data_for(self, symbol: str) -> pd.DataFrame:
        symbol = str(symbol or self.state.symbol).strip()
        if not symbol:
            raise ValueError("symbol is required")

        if self.state.source == "csv":
            df = pd.read_csv(CSV_HISTORY).tail(int(self.state.bars)).reset_index(drop=True)
            return df

        gateway = self.connect_gateway()
        return gateway.fetch_rates(symbol, self.state.timeframe, int(self.state.bars))

    def make_sequence(self, df: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
        enriched = add_market_structure(df)
        seq = enriched[FEATURE_COLUMNS].tail(SEQ_LEN).to_numpy(dtype=np.float32)
        if len(seq) < SEQ_LEN:
            raise RuntimeError(f"Need at least {SEQ_LEN} bars, got {len(seq)}")
        seq = self.scaler.transform(seq)
        return seq.reshape(1, SEQ_LEN, len(FEATURE_COLUMNS)), enriched

    # ------------------------------------------------------------------
    # Analysis and scanning
    # ------------------------------------------------------------------
    def analyze(self, symbol: str | None = None) -> dict[str, Any]:
        symbol = str(symbol or self.state.symbol).strip()
        df = self.load_market_data_for(symbol)
        sequence, enriched = self.make_sequence(df)

        probability = float(np.asarray(self.model.predict(sequence, verbose=0)).squeeze())
        spread = float(enriched["spread"].iloc[-1]) if "spread" in enriched.columns else None

        decision = self.brain.decide(
            df=enriched,
            sequence=sequence,
            probability=probability,
            spread=spread,
            ignore_spread=self.ignore_spread_filter,
        ).to_dict()

        atr = float(enriched["atr"].iloc[-1]) if "atr" in enriched.columns else None
        decision.update(
            {
                "symbol": symbol,
                "timeframe": self.state.timeframe,
                "source": self.state.source,
                "close": float(enriched["close"].iloc[-1]),
                "spread": spread,
                "spread_filter_ignored": self.ignore_spread_filter,
                "mode": self.state.mode,
                "profile": self.state.profile,
                "atr": atr,
            }
        )

        self.last_decision = decision
        self.log_event({"type": "analysis", "decision": decision})
        return decision

    def market_symbols(self, limit: int = MAX_MARKET_SCAN_SYMBOLS) -> list[dict[str, Any]]:
        if self.state.source != "mt5":
            return [{"symbol": self.state.symbol, "source": "csv"}]
        gateway = self.connect_gateway()
        return gateway.symbols(visible_only=False, tradable_only=True, limit=int(limit))

    def scan_markets(self, limit: int = MAX_MARKET_SCAN_SYMBOLS) -> dict[str, Any]:
        symbols = self.market_symbols(limit=limit)
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for item in symbols:
            symbol = item["symbol"]
            try:
                decision = self.analyze(symbol=symbol)
                score = self._scan_score(decision)
                results.append(
                    {
                        "symbol": symbol,
                        "path": item.get("path"),
                        "action": decision.get("action"),
                        "probability": decision.get("probability"),
                        "confidence": decision.get("confidence"),
                        "spread": decision.get("spread"),
                        "reason": decision.get("reason"),
                        "close": decision.get("close"),
                        "score": score,
                        "decision": decision,
                    }
                )
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)})

        results.sort(key=lambda item: item["score"], reverse=True)
        summary = {
            "source": self.state.source,
            "timeframe": self.state.timeframe,
            "profile": self.state.profile,
            "scanned": len(results),
            "errors": errors[:20],
            "top": results[:10],
            "tradable": [item for item in results if item["action"] in VALID_ACTIONS][:10],
        }
        self.log_event({"type": "market_scan", "summary": summary})
        return summary

    def execute_market_scan_paper(
        self,
        limit: int = MAX_MARKET_SCAN_SYMBOLS,
        max_orders: int = MAX_PAPER_SCAN_ORDERS,
    ) -> dict[str, Any]:
        scan = self.scan_markets(limit=limit)
        executions = []
        old_mode = self.state.mode
        self.state.mode = "paper"
        try:
            for item in scan["tradable"][: int(max_orders)]:
                executions.append(self.execute_decision(item["decision"]))
        finally:
            self.state.mode = old_mode
        return {"scan": scan, "executions": executions, "mode": "paper"}

    def execute_market_scan_demo(
        self,
        limit: int = MAX_MARKET_SCAN_SYMBOLS,
        max_orders: int = MAX_DEMO_OPEN_ORDERS,
    ) -> dict[str, Any]:
        scan = self.scan_markets(limit=limit)
        executions = []
        old_mode = self.state.mode
        self.state.mode = "demo"
        try:
            for item in scan["tradable"][: int(max_orders)]:
                executions.append(self.execute_decision(item["decision"]))
        finally:
            self.state.mode = old_mode
        return {"scan": scan, "executions": executions, "mode": "demo_mt5"}

    @staticmethod
    def _scan_score(decision: dict[str, Any]) -> float:
        action = decision.get("action")
        confidence = float(decision.get("confidence") or 0.0)
        spread = float(decision.get("spread") or 0.0)
        action_bonus = 2.0 if action in VALID_ACTIONS else 0.0
        spread_penalty = min(spread / 1000.0, 0.75)
        return action_bonus + confidence - spread_penalty

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute_suitable_demo(self, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        """Switch to Demo MT5 and execute only if the decision is BUY or SELL."""
        self.set_source("mt5")
        mode_message = self.set_mode("demo")
        decision = decision or self.last_decision or self.analyze()
        action = decision.get("action", "NO_TRADE")

        if action not in VALID_ACTIONS:
            result = {
                "executed": False,
                "mode_message": mode_message,
                "reason": decision.get("reason", "no_trade"),
                "decision": decision,
            }
            self.log_event({"type": "demo_execution_skipped", "result": result})
            return result

        result = self.execute_decision(decision)
        result["mode_message"] = mode_message
        return result

    def execute_decision(self, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        decision = decision or self.last_decision or self.analyze()
        action = decision.get("action", "NO_TRADE")

        if action not in VALID_ACTIONS:
            return {
                "executed": False,
                "reason": decision.get("reason", "no_trade"),
                "decision": decision,
            }

        price = float(decision["close"])

        if self.state.mode == "paper":
            result = self.paper_executor.execute(
                symbol=decision.get("symbol", self.state.symbol),
                side=action,
                price=price,
                lot=self.state.lot,
            ).to_dict()
            self.log_event({"type": "paper_execution", "result": result, "decision": decision})
            return {"executed": True, "result": result, "decision": decision}

        if self.state.mode == "demo":
            sl, tp = self._risk_levels(decision)
            symbol = decision.get("symbol", self.state.symbol)

            if _EXECUTION_MANAGER_AVAILABLE:
                try:
                    req = ExecutionRequest(
                        action=Direction(action),
                        symbol=symbol,
                        lot=self.state.lot,
                        price=price,
                        sl=sl or 0.0,
                        tp=tp or 0.0,
                        magic=QADER_REAL_CONTROLLED_MAGIC,
                        comment="jarvis_demo",
                        confidence=float(decision.get("confidence") or 0.0),
                    )
                    em_result = get_execution_manager().execute(req)
                    result = {
                        "sent": em_result.success,
                        "order": em_result.order,
                        "retcode": em_result.retcode,
                        "message": em_result.message,
                        "simulated": em_result.simulated,
                        "via": "execution_manager",
                    }
                    self.log_event({"type": "demo_execution", "result": result, "decision": decision})
                    return {"executed": em_result.success, "result": result, "decision": decision}
                except Exception as exc:
                    self.log_event({"type": "demo_execution_manager_error", "error": str(exc), "fallback": "DemoMT5Executor"})

            # Fallback: ExecutionManager unavailable or raised — use DemoMT5Executor.
            gateway = self.connect_gateway()
            executor = DemoMT5Executor(gateway=gateway)
            result = executor.execute(
                symbol=symbol,
                side=action,
                price=price,
                lot=self.state.lot,
                sl=sl,
                tp=tp,
                magic=QADER_REAL_CONTROLLED_MAGIC,
            )
            self.log_event({"type": "demo_execution", "result": result, "decision": decision})
            return {"executed": bool(result.get("sent")), "result": result, "decision": decision}

        # Defensive fallback: live cannot execute from this assistant.
        result = {
            "sent": False,
            "mode": "blocked",
            "reason": "live_trading_blocked_by_jarvis_assistant",
            "allowed_execution_modes": sorted(ALLOWED_MODES),
        }
        self.log_event({"type": "live_execution_blocked", "result": result, "decision": decision})
        return {"executed": False, "result": result, "decision": decision}

    @staticmethod
    def _risk_levels(
        decision: dict[str, Any],
        sl_pct: float = 0.0010,
        tp_pct: float = 0.0015,
        atr_sl_mult: float = 1.5,
        atr_tp_mult: float = 2.0,
    ) -> tuple[float | None, float | None]:
        price = float(decision["close"])
        side = decision.get("action")
        atr = decision.get("atr")

        # Prefer ATR-based SL/TP when a valid ATR is present; fall back to pct.
        if atr and float(atr) > 0:
            sl_dist = float(atr) * atr_sl_mult
            tp_dist = float(atr) * atr_tp_mult
            if side == "BUY":
                return price - sl_dist, price + tp_dist
            if side == "SELL":
                return price + sl_dist, price - tp_dist
        else:
            if side == "BUY":
                return price * (1 - sl_pct), price * (1 + tp_pct)
            if side == "SELL":
                return price * (1 + sl_pct), price * (1 - tp_pct)
        return None, None

    # ------------------------------------------------------------------
    # Natural-language command handling
    # ------------------------------------------------------------------
    @staticmethod
    def _contains_any(text: str, phrases: list[str]) -> bool:
        return any(phrase in text for phrase in phrases)

    def handle(self, command: str) -> str:
        text = str(command or "").strip()
        lowered = text.lower()
        self.log_event({"type": "command", "command": text})

        if not text:
            return "اكتب أمر مثل: حلل، تداول، الحالة، gpu، profile scalping."

        if lowered in {"help", "مساعدة", "الاوامر", "الأوامر"}:
            return self.help_text()

        if lowered in {"quit", "exit", "خروج", "اطلع"}:
            return "__QUIT__"

        wants_trade = self._contains_any(
            lowered,
            ["تداول", "ادخل", "ادخلي", "دخول", "نفذ", "نفذي", "افتح", "افتحي", "trade", "execute", "open"],
        )
        wants_demo = self._contains_any(
            lowered,
            ["demo", "demo mt5", "ديمو", "ديمو mt5", "تجريبي", "تجريبي mt5", "حساب وهمي"],
        )
        wants_paper = self._contains_any(lowered, ["paper", "ورقي"])
        wants_gold = self._contains_any(lowered, ["ذهب", "gold", "xau", "xauusd", "xauusdm"])
        wants_scalping = self._contains_any(lowered, ["سكالب", "سكالبينج", "scalp", "scalping"])
        wants_spread_override = self._contains_any(
            lowered,
            ["تجاهل السبريد", "تجاهلي السبريد", "تجاوز السبريد", "ignore spread", "override spread"],
        )
        wants_obey = self._contains_any(
            lowered,
            ["اطيع", "أطيع", "طيع", "طيعني", "طيعيني", "obey", "خلها سكالب", "خليها سكالب", "سكالبينج الذهب", "ذهب سكالب"],
        )

        if wants_gold:
            self.set_symbol("XAUUSDm")
        if wants_scalping:
            self.set_profile("scalping")
        if wants_spread_override:
            self.set_spread_override(True)

        if "gpu" in lowered or "كرت" in lowered:
            return json.dumps(hardware_report(), indent=2, ensure_ascii=False, default=str)

        if "status" in lowered or "حالة" in lowered:
            return json.dumps(self.status(), indent=2, ensure_ascii=False, default=str)

        if wants_obey:
            symbol = "XAUUSDm" if wants_gold else self.state.symbol
            mode = "paper" if wants_paper else "demo"
            return json.dumps(self.obey_aggressive_scalping(symbol=symbol, mode=mode), indent=2, ensure_ascii=False, default=str)

        # Important: execution intent has priority over mode-only commands.
        # Example: "فرايدي نفذي ديمو MT5 إذا الصفقة مناسبة" must execute in Demo.
        if wants_trade and wants_demo:
            return json.dumps(self.execute_suitable_demo(self.last_decision), indent=2, ensure_ascii=False, default=str)

        if wants_trade and wants_paper:
            self.set_mode("paper")
            decision = self.last_decision or self.analyze()
            return json.dumps(self.execute_decision(decision), indent=2, ensure_ascii=False, default=str)

        if "profile" in lowered or "بروفايل" in lowered or "استراتيجية" in lowered:
            for profile in PROFILES:
                if profile in lowered:
                    return self.set_profile(profile)
            return f"Available profiles: {', '.join(PROFILES)}"

        if wants_demo:
            return self.set_mode("demo")

        if wants_paper:
            return self.set_mode("paper")

        if "live" in lowered or "حقيقي" in lowered:
            return self.set_mode("live")

        if "source csv" in lowered or "مصدر csv" in lowered:
            return self.set_source("csv")

        if "source mt5" in lowered or "مصدر mt5" in lowered:
            return self.set_source("mt5")

        if "حلل" in lowered or "analyze" in lowered or "تحليل" in lowered:
            return json.dumps(self.analyze(), indent=2, ensure_ascii=False, default=str)

        if wants_trade:
            decision = self.last_decision or self.analyze()
            return json.dumps(self.execute_decision(decision), indent=2, ensure_ascii=False, default=str)

        return (
            "ما فهمت الأمر. جرّب: حلل، تداول، الحالة، gpu، "
            "profile scalping، source csv، source mt5."
        )

    def help_text(self) -> str:
        return """
أوامر Jarvis:
  حلل / analyze                         يحلل السوق ويعطي قرار BUY/SELL/NO_TRADE
  تداول / trade                         ينفذ القرار حسب الوضع الحالي
  نفذي ديمو MT5 إذا الصفقة مناسبة       يحول الوضع إلى demo وينفذ BUY/SELL فقط
  أطيعيني / ذهب سكالبينج                يضبط MT5 + XAUUSDm + scalping + demo + spread override
  تجاهلي السبريد                       يتجاهل فلتر السبريد في Paper/Demo فقط
  الحالة / status                       يعرض الإعدادات والاتصال
  gpu / كرت الشاشة                      يفحص كرت الشاشة وتشغيل ML
  profile scalping|ict|sk               يغير عقل الاستراتيجية
  source csv / source mt5               يغير مصدر البيانات
  paper / ورقي                          يقفل التنفيذ على paper
  demo / ديمو mt5                       ينفذ فقط على حساب MT5 ديمو
  live / حقيقي                          محجوب من الباكند
  خروج                                  ينهي الجلسة
""".strip()
