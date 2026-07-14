import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import joblib
import numpy as np
import pandas as pd
import tensorflow as tf

from .ai_brain import TradingBrain
from .config import (
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
    AGGRESSIVE_SCALPING_IGNORE_SPREAD,
)
from .execution import DemoMT5Executor, PaperExecutor
from .hardware import hardware_report
from .market_structure import add_market_structure
from .mt5_gateway import MT5Gateway
from .strategy_profiles import PROFILES


AGGRESSIVE_XAU_BUY_THRESHOLD = 0.55
AGGRESSIVE_XAU_SELL_THRESHOLD = 0.45


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
    def __init__(self, state=None, allow_live=True):
        self.state = state or JarvisState()

        # Safety: live execution remains blocked. Paper/Demo only.
        if str(self.state.mode).lower() == "live":
            self.state.mode = "paper"

        self.allow_live = False
        self.ignore_spread_filter = self._default_spread_override()

        self.model = tf.keras.models.load_model(MODEL_PATH, compile=False)
        self.scaler = joblib.load(SCALER_PATH)
        self.brain = TradingBrain(model=self.model, profile_name=self.state.profile)

        self.paper_executor = PaperExecutor()
        self.gateway = None
        self.last_decision = None
        self.command_log = LOG_DIR / "jarvis_commands.jsonl"

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------
    def _default_spread_override(self):
        return bool(
            self.state.profile == "scalping"
            and str(self.state.mode).lower() in {"paper", "demo"}
        )

    @staticmethod
    def _is_xau_symbol(symbol):
        symbol = str(symbol or "").upper()
        return "XAU" in symbol or "GOLD" in symbol

    def _effective_ignore_spread(self, symbol=None):
        symbol = symbol or self.state.symbol

        # In scalping Paper/Demo, obey aggressive mode and ignore spread.
        if (
            self.state.profile == "scalping"
            and self.state.mode in {"paper", "demo"}
            and self._is_xau_symbol(symbol)
        ):
            return True

        return bool(self.ignore_spread_filter)

    @staticmethod
    def _json(data):
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)

    def connect_gateway(self):
        if self.gateway is None:
            self.gateway = MT5Gateway()
            self.gateway.initialize()
        return self.gateway

    def close(self):
        if self.gateway is not None:
            self.gateway.shutdown()

    def log_event(self, event):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        with open(self.command_log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True, default=str) + "\n")

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def set_profile(self, profile):
        profile = str(profile or "").strip().lower()

        if profile not in PROFILES:
            return f"Unknown profile. Available: {', '.join(PROFILES)}"

        self.state.profile = profile
        self.brain = TradingBrain(model=self.model, profile_name=profile)

        if profile == "scalping" and self.state.mode in {"paper", "demo"}:
            self.ignore_spread_filter = True

        return f"Profile set to {profile}"

    def set_mode(self, mode):
        """
        Set execution mode.

        Allowed:
          - paper
          - demo

        Blocked:
          - live
          - auto_live
          - live_auto
        """
        mode = str(mode or "paper").strip().lower()
        mode = mode.replace("demo_mt5", "demo")

        aliases = {
            "mt5_demo": "demo",
            "demo-mt5": "demo",
            "demo mt5": "demo",
            "ديمو": "demo",
            "ديمو mt5": "demo",
            "تجريبي": "demo",
            "تجريبي mt5": "demo",
            "حساب وهمي": "demo",
            "paper": "paper",
            "ورقي": "paper",
        }

        mode = aliases.get(mode, mode)

        if mode in {"live", "حقيقي", "auto_live", "live_auto", "auto live", "live auto"}:
            if self.state.mode not in {"paper", "demo"}:
                self.state.mode = "paper"
            return "LIVE AUTO محجوب من الباكند. الأوضاع المسموحة: PAPER أو DEMO MT5."

        if mode not in {"paper", "demo"}:
            return "Mode must be Paper or Demo"

        self.state.mode = mode

        if self.state.profile == "scalping":
            self.ignore_spread_filter = True

        return f"Mode set to {mode}"

    def set_spread_override(self, enabled):
        if self.state.mode == "live":
            return {
                "enabled": self.ignore_spread_filter,
                "blocked": True,
                "message": "تجاوز السبريد غير مسموح في Live. استخدم Paper أو Demo.",
            }

        self.ignore_spread_filter = bool(enabled)
        state = "مفعل" if self.ignore_spread_filter else "متوقف"

        return {
            "enabled": self.ignore_spread_filter,
            "blocked": False,
            "message": f"تجاوز فلتر السبريد {state} في وضع {self.state.mode}.",
        }

    def set_symbol(self, symbol):
        symbol = str(symbol or "").strip()
        if not symbol:
            return "Symbol is required"

        self.state.symbol = symbol
        return f"Symbol set to {symbol}"

    def set_timeframe(self, timeframe):
        timeframe = str(timeframe or "").strip().upper()
        if not timeframe:
            return "Timeframe is required"

        self.state.timeframe = timeframe
        return f"Timeframe set to {timeframe}"

    def obey_aggressive_scalping(self, symbol=None, mode="demo"):
        """
        Safe obey preset:
        - MT5 data
        - XAUUSDm
        - scalping
        - demo/paper
        - ignore spread
        - live remains blocked
        """
        messages = []

        self.state.source = "mt5"
        messages.append("Source set to mt5")

        symbol = symbol or "XAUUSDm"
        messages.append(self.set_symbol(symbol))

        messages.append(self.set_profile("scalping"))
        messages.append(self.set_mode(mode))

        spread_result = self.set_spread_override(True)
        messages.append(spread_result.get("message", str(spread_result)))

        return {
            "ok": True,
            "message": "تم ضبط وضع الطاعة الآمن: MT5 + XAUUSDm + scalping + DEMO/PAPER + spread override.",
            "details": messages,
            "status": self.status(),
        }

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def status(self):
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
            "live_unlocked": False,
            "live_trading_enabled": False,
            "allowed_execution_modes": ["paper", "demo"],
            "ignore_spread_filter": self.ignore_spread_filter,
            "effective_ignore_spread": self._effective_ignore_spread(),
            "aggressive_xau_buy_threshold": AGGRESSIVE_XAU_BUY_THRESHOLD,
            "aggressive_xau_sell_threshold": AGGRESSIVE_XAU_SELL_THRESHOLD,
            "mt5": mt5,
        }

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------
    def load_market_data(self):
        return self.load_market_data_for(self.state.symbol)

    def load_market_data_for(self, symbol):
        if self.state.source == "csv":
            df = pd.read_csv(CSV_HISTORY).tail(self.state.bars).reset_index(drop=True)
            return df

        gateway = self.connect_gateway()
        return gateway.fetch_rates(symbol, self.state.timeframe, self.state.bars)

    def make_sequence(self, df):
        enriched = add_market_structure(df)

        seq = enriched[FEATURE_COLUMNS].tail(SEQ_LEN).to_numpy(dtype=np.float32)
        if len(seq) < SEQ_LEN:
            raise RuntimeError(f"Need at least {SEQ_LEN} bars, got {len(seq)}")

        seq = self.scaler.transform(seq)
        return seq.reshape(1, SEQ_LEN, len(FEATURE_COLUMNS)), enriched

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------
    def analyze(self, symbol=None):
        symbol = symbol or self.state.symbol

        df = self.load_market_data_for(symbol)
        sequence, enriched = self.make_sequence(df)

        probability = float(np.asarray(self.model.predict(sequence, verbose=0)).squeeze())
        spread = float(enriched["spread"].iloc[-1]) if "spread" in enriched.columns else None
        ignore_spread = self._effective_ignore_spread(symbol)

        decision = self.brain.decide(
            df=enriched,
            sequence=sequence,
            probability=probability,
            spread=spread,
            ignore_spread=ignore_spread,
        ).to_dict()

        decision.update(
            {
                "symbol": symbol,
                "timeframe": self.state.timeframe,
                "source": self.state.source,
                "close": float(enriched["close"].iloc[-1]),
                "spread": spread,
                "spread_filter_ignored": ignore_spread,
            }
        )

        decision = self._force_aggressive_xau_scalping(decision)

        self.last_decision = decision
        self.log_event({"type": "analysis", "decision": decision})
        return decision

    def _force_aggressive_xau_scalping(self, decision):
        """
        For DEMO/PAPER XAU scalping only:
        If the model probability has a directional edge, convert NO_TRADE to BUY/SELL.

        This is intentionally NOT allowed for live.
        """
        if not isinstance(decision, dict):
            return decision

        if self.state.mode not in {"paper", "demo"}:
            return decision

        if self.state.profile != "scalping":
            return decision

        if not self._is_xau_symbol(decision.get("symbol", self.state.symbol)):
            return decision

        if not self._effective_ignore_spread(decision.get("symbol", self.state.symbol)):
            return decision

        if decision.get("risk_allowed") is False:
            return decision

        action = decision.get("action", "NO_TRADE")
        if action in {"BUY", "SELL"}:
            decision["spread_filter_ignored"] = True
            decision["aggressive_scalping_active"] = True
            return decision

        probability = float(decision.get("probability") or 0.0)

        forced_action = None
        forced_reason = None

        if probability >= AGGRESSIVE_XAU_BUY_THRESHOLD:
            forced_action = "BUY"
            forced_reason = (
                f"buy:aggressive_xau_scalping_demo("
                f"prob>={AGGRESSIVE_XAU_BUY_THRESHOLD},spread_ignored)"
            )

        elif probability <= AGGRESSIVE_XAU_SELL_THRESHOLD:
            forced_action = "SELL"
            forced_reason = (
                f"sell:aggressive_xau_scalping_demo("
                f"prob<={AGGRESSIVE_XAU_SELL_THRESHOLD},spread_ignored)"
            )

        if forced_action is None:
            return decision

        original = {
            "action": decision.get("action"),
            "reason": decision.get("reason"),
            "confidence": decision.get("confidence"),
        }

        confidence = float(decision.get("confidence") or 0.0)
        directional_confidence = abs(probability - 0.5) * 2.0

        decision["action"] = forced_action
        decision["reason"] = forced_reason
        decision["confidence"] = max(confidence, directional_confidence)
        decision["spread_filter_ignored"] = True
        decision["aggressive_scalping_active"] = True
        decision["forced_from_no_trade"] = True
        decision["original_decision"] = original

        return decision

    # ------------------------------------------------------------------
    # Market scan
    # ------------------------------------------------------------------
    def market_symbols(self, limit=MAX_MARKET_SCAN_SYMBOLS):
        if self.state.source != "mt5":
            return [{"symbol": self.state.symbol, "source": "csv"}]

        gateway = self.connect_gateway()
        return gateway.symbols(visible_only=False, tradable_only=True, limit=limit)

    def scan_markets(self, limit=MAX_MARKET_SCAN_SYMBOLS):
        symbols = self.market_symbols(limit=limit)
        results = []
        errors = []

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
            "tradable": [item for item in results if item["action"] in {"BUY", "SELL"}][:10],
        }

        self.log_event({"type": "market_scan", "summary": summary})
        return summary

    def execute_market_scan_paper(self, limit=MAX_MARKET_SCAN_SYMBOLS, max_orders=MAX_PAPER_SCAN_ORDERS):
        scan = self.scan_markets(limit=limit)
        executions = []
        old_mode = self.state.mode

        self.state.mode = "paper"

        try:
            for item in scan["tradable"][: int(max_orders)]:
                decision = item["decision"]
                old_symbol = self.state.symbol
                self.state.symbol = decision["symbol"]

                try:
                    executions.append(self.execute_decision(decision))
                finally:
                    self.state.symbol = old_symbol
        finally:
            self.state.mode = old_mode

        return {"scan": scan, "executions": executions, "mode": "paper"}

    def execute_market_scan_demo(self, limit=MAX_MARKET_SCAN_SYMBOLS, max_orders=MAX_DEMO_OPEN_ORDERS):
        scan = self.scan_markets(limit=limit)
        executions = []
        old_mode = self.state.mode

        self.state.mode = "demo"

        try:
            for item in scan["tradable"][: int(max_orders)]:
                decision = item["decision"]
                executions.append(self.execute_decision(decision))
        finally:
            self.state.mode = old_mode

        return {"scan": scan, "executions": executions, "mode": "demo_mt5"}

    @staticmethod
    def _scan_score(decision):
        action = decision.get("action")
        confidence = float(decision.get("confidence") or 0.0)
        spread = float(decision.get("spread") or 0.0)

        action_bonus = 2.0 if action in {"BUY", "SELL"} else 0.0
        spread_penalty = min(spread / 1000.0, 0.75)

        return action_bonus + confidence - spread_penalty

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute_suitable_demo(self, decision=None):
        """
        Switch to Demo MT5 and execute only when the decision is BUY or SELL.

        If the previous decision was NO_TRADE but the XAU scalping probability
        has enough edge, it will be converted to BUY/SELL by aggressive mode.
        """
        self.state.source = "mt5"
        mode_message = self.set_mode("demo")

        if self.state.profile == "scalping":
            self.set_spread_override(True)

        decision = decision or self.last_decision or self.analyze()
        decision = self._force_aggressive_xau_scalping(dict(decision))
        self.last_decision = decision

        action = decision.get("action", "NO_TRADE")

        if action not in {"BUY", "SELL"}:
            return {
                "executed": False,
                "mode_message": mode_message,
                "reason": decision.get("reason", "no_trade"),
                "decision": decision,
            }

        result = self.execute_decision(decision)
        result["mode_message"] = mode_message
        return result

    def execute_decision(self, decision=None):
        decision = decision or self.last_decision or self.analyze()
        decision = self._force_aggressive_xau_scalping(dict(decision))

        action = decision.get("action", "NO_TRADE")

        if action not in {"BUY", "SELL"}:
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

            return {
                "executed": True,
                "mode": "paper",
                "result": result,
                "decision": decision,
            }

        if self.state.mode == "demo":
            gateway = self.connect_gateway()
            executor = DemoMT5Executor(gateway=gateway)

            sl, tp = self._risk_levels(decision)

            result = executor.execute(
                symbol=decision.get("symbol", self.state.symbol),
                side=action,
                price=price,
                lot=self.state.lot,
                sl=sl,
                tp=tp,
            )

            self.log_event({"type": "demo_execution", "result": result, "decision": decision})

            return {
                "executed": bool(result.get("sent")),
                "mode": "demo_mt5",
                "result": result,
                "decision": decision,
            }

        if self.state.mode == "live":
            result = {
                "sent": False,
                "mode": "blocked",
                "reason": "live_trading_permanently_disabled",
                "message": "LIVE AUTO محجوب. استخدم Paper أو Demo MT5.",
            }

            self.log_event({"type": "live_blocked", "result": result, "decision": decision})

            return {
                "executed": False,
                "mode": "blocked",
                "result": result,
                "decision": decision,
            }

        result = {
            "sent": False,
            "mode": "unknown",
            "reason": f"unknown_mode_{self.state.mode}",
        }

        self.log_event({"type": "unknown_mode_execution", "result": result, "decision": decision})

        return {
            "executed": False,
            "result": result,
            "decision": decision,
        }

    @staticmethod
    def _risk_levels(decision, sl_pct=0.0010, tp_pct=0.0015):
        price = float(decision["close"])
        side = decision.get("action")

        if side == "BUY":
            return price * (1 - sl_pct), price * (1 + tp_pct)

        if side == "SELL":
            return price * (1 + sl_pct), price * (1 - tp_pct)

        return None, None

    # ------------------------------------------------------------------
    # Command handler
    # ------------------------------------------------------------------
    def handle(self, command):
        text = str(command or "").strip()
        lowered = text.lower()

        self.log_event({"type": "command", "command": text})

        if not text:
            return "اكتب أمر مثل: حلل، تداول، الحالة، gpu، profile scalping."

        if lowered in {"help", "مساعدة", "الاوامر", "الأوامر"}:
            return self.help_text()

        if lowered in {"quit", "exit", "خروج", "اطلع"}:
            return "__QUIT__"

        wants_trade = any(
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
                "بيع",
                "trade",
                "execute",
                "open",
                "buy",
                "sell",
            ]
        )

        wants_demo = any(
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

        wants_paper = any(
            phrase in lowered
            for phrase in [
                "paper",
                "ورقي",
            ]
        )

        wants_gold = any(
            word in lowered
            for word in [
                "ذهب",
                "gold",
                "xau",
                "xauusd",
                "xauusdm",
            ]
        )

        wants_scalping = any(
            word in lowered
            for word in [
                "سكالب",
                "سكالبينج",
                "scalp",
                "scalping",
            ]
        )

        wants_spread_override = any(
            phrase in lowered
            for phrase in [
                "تجاهل السبريد",
                "تجاهلي السبريد",
                "تجاوز السبريد",
                "تجاوزي السبريد",
                "ignore spread",
                "override spread",
                "بدون سبريد",
            ]
        )

        wants_obey = any(
            word in lowered
            for word in [
                "اطيع",
                "أطيع",
                "طيع",
                "طيعني",
                "طيعيني",
                "obey",
                "خلها سكالب",
                "خليها سكالب",
                "سكالبينج الذهب",
                "ذهب سكالب",
            ]
        )

        if wants_gold:
            self.set_symbol("XAUUSDm")

        if wants_scalping:
            self.set_profile("scalping")

        if wants_spread_override:
            self.set_spread_override(True)

        if "gpu" in lowered or "كرت" in lowered:
            return self._json(hardware_report())

        if "status" in lowered or "حالة" in lowered:
            return self._json(self.status())

        if wants_obey:
            symbol = "XAUUSDm" if wants_gold else self.state.symbol
            return self._json(self.obey_aggressive_scalping(symbol=symbol, mode="demo"))

        # Important:
        # "نفذي ديمو MT5 إذا الصفقة مناسبة"
        # must execute in demo, not be treated as mode-only.
        if wants_trade and wants_demo:
            return self._json(self.execute_suitable_demo(self.last_decision))

        if wants_trade and wants_paper:
            self.set_mode("paper")
            decision = self.last_decision or self.analyze()
            return self._json(self.execute_decision(decision))

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
            self.state.source = "csv"
            return "Source set to csv"

        if "source mt5" in lowered or "مصدر mt5" in lowered:
            self.state.source = "mt5"
            return "Source set to mt5"

        if "m1" in lowered:
            return self.set_timeframe("M1")

        if "m5" in lowered:
            return self.set_timeframe("M5")

        if "m15" in lowered:
            return self.set_timeframe("M15")

        if "حلل" in lowered or "analyze" in lowered or "تحليل" in lowered:
            return self._json(self.analyze())

        if wants_trade:
            decision = self.last_decision or self.analyze()
            return self._json(self.execute_decision(decision))

        return (
            "ما فهمت الأمر. جرّب: حلل، تداول، الحالة، gpu، "
            "profile scalping، source csv، source mt5، أطيعيني ذهب سكالبينج."
        )

    def help_text(self):
        return """
أوامر Jarvis:
  حلل / analyze                         يحلل السوق ويعطي قرار BUY/SELL/NO_TRADE
  تداول / trade                         ينفذ القرار حسب الوضع الحالي
  الحالة / status                       يعرض الإعدادات والاتصال
  gpu / كرت الشاشة                      يفحص كرت الشاشة وتشغيل ML
  profile scalping|ict|sk               يغير عقل الاستراتيجية
  source csv / source mt5               يغير مصدر البيانات
  paper / ورقي                          يقفل التنفيذ على Paper
  demo / ديمو mt5                       ينفذ فقط على حساب MT5 ديمو
  أطيعيني ذهب سكالبينج                  يضبط MT5 + XAUUSDm + scalping + demo + spread override
  تجاهلي السبريد                       يتجاهل فلتر السبريد في Paper/Demo فقط
  نفذي ديمو MT5 إذا الصفقة مناسبة       يحول الوضع إلى demo وينفذ BUY/SELL فقط
  live / حقيقي                          محجوب من الباكند
  خروج                                  ينهي الجلسة
""".strip()