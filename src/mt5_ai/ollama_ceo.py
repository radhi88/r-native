"""
OllamaCEO — المدير التنفيذي بالذكاء الاصطناعي المحلي.

يعمل في thread مستقل ويراقب جميع الوكلاء بشكل مستمر.
يستخدم Ollama (LLM محلي) لتحليل الأداء وإصدار التعليمات.
يُعتبر المدير التنفيذي CEO للنظام بأكمله.

المتطلبات:
    pip install ollama
    أو: curl -fsSL https://ollama.com/install.sh | sh
    ثم: ollama pull llama3
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agents.orchestrator import FridayOrchestrator

log = logging.getLogger("gader.ceo")

# حدود التعديل الآمن (متوافقة مع AIWatchdog)
_SAFE_BOUNDS = {
    "buy_threshold":  (0.52, 0.88),
    "sell_threshold": (0.12, 0.48),
    "min_smc_score":  (1, 5),
    "atr_sl_mult":    (1.0, 3.0),
    "min_rr":         (1.0, 2.8),
    "be_atr_mult":    (0.10, 0.40),
    "trail_atr_mult": (0.25, 0.70),
}

_SYSTEM_PROMPT = """\
أنت مدير تنفيذي CEO لنظام تداول آلي متعدد الرموز. مهمتك:
1. تحليل أداء جميع الوكلاء والرموز
2. إصدار تعليمات محددة لتحسين الأداء
3. الاهتمام بحماية رأس المال أولاً ثم الربح

قواعد:
- إذا كانت نسبة الفوز WR < 35% أو الخسائر المتتالية ≥ 4 → شدّد العتبات
- إذا كانت WR > 65% لفترة طويلة → خفّف العتبات قليلاً
- إذا كان متوسط R السلبي avg_R < -0.5 → تدخّل فوراً
- لا تجري تعديلات صغيرة جداً — كل تعديل يجب أن يكون له تأثير واضح

أجب دائماً بـ JSON فقط بهذا الشكل:
{
  "thoughts": "تحليلك في جملة واحدة",
  "mood": "calm|alert|urgent",
  "instructions": [
    {"symbol": "XAUUSDm", "param": "buy_threshold", "value": 0.65, "reason": "WR منخفض"},
    {"symbol": "ALL", "action": "pause_new_entries", "reason": "خسائر متتالية"}
  ]
}

الـ actions المتاحة: adjust_param | pause_new_entries | resume_entries | log_only
"""


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _normalize_ollama_host(host: str | None) -> str:
    value = (host or "http://127.0.0.1:11434").strip().rstrip("/")
    if not value:
        value = "http://127.0.0.1:11434"
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    return value


class OllamaCEO:
    """
    المدير التنفيذي بالذكاء الاصطناعي المحلي (Ollama).

    يعمل في خلفية النظام ويصدر توجيهات كل `interval` ثانية.
    يتصل بـ Ollama عبر HTTP على المنفذ 11434 (الافتراضي).
    """

    def __init__(
        self,
        orchestrators: "dict[str, FridayOrchestrator]",
        interval:      int  = 60,
        model:         str  = "qwen2.5:3b-instruct",
        host:          str  = "http://localhost:11434",
        event_bus=None,
    ):
        self.orchs    = orchestrators
        self.interval = interval
        self.model    = model
        self.host     = _normalize_ollama_host(host)
        self._bus     = event_bus
        self._stop    = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_thoughts = "جاري الاتصال بـ Ollama…"
        self._mood          = "calm"
        self._cycle         = 0
        self._available     = False

    # ── API العام ─────────────────────────────────────────────────────────────

    def start(self):
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="gader-ceo"
        )
        self._thread.start()
        log.info("OllamaCEO بدأ (model=%s) — تحليل كل %ds", self.model, self.interval)

    def stop(self):
        self._stop.set()

    @property
    def thoughts(self) -> str:
        return self._last_thoughts

    @property
    def mood(self) -> str:
        return self._mood

    @property
    def available(self) -> bool:
        return self._available

    # ── الحلقة الرئيسية ───────────────────────────────────────────────────────

    def _loop(self):
        # انتظر أول 10 ثوانٍ حتى يستقر النظام
        self._stop.wait(10)

        while not self._stop.is_set():
            self._cycle += 1
            try:
                state  = self._collect_state()
                result = self._ask_ollama(state)
                if result:
                    self._apply_instructions(result)
            except Exception as exc:
                log.warning("OllamaCEO خطأ: %s", exc)
                self._last_thoughts = f"خطأ في الاتصال: {exc}"
                self._available = False

            self._stop.wait(self.interval)

    # ── جمع حالة النظام ───────────────────────────────────────────────────────

    def _collect_state(self) -> dict:
        symbols = {}
        total_open = 0

        for sym, orch in self.orchs.items():
            try:
                lrn  = orch.learning.summary("smc", sym, lookback=30)
                conf = orch.confidence.status()
                gs   = orch.guard.status()
                st   = orch.status()
                smart = st.get("smart_pro", {}) if isinstance(st, dict) else {}
                n_open = orch.monitor.count()
                total_open += n_open

                symbols[sym] = {
                    "trades":      int(lrn.get("trades", 0)),
                    "win_rate":    round(float(lrn.get("win_rate", 0)), 3),
                    "profit_factor": round(float(lrn.get("profit_factor", 0)), 2),
                    "avg_r":       round(float(lrn.get("avg_r", 0)), 4),
                    "streak":      int(conf.get("streak", 0)),
                    "confidence":  round(float(conf.get("confidence", 1.0)), 2),
                    "consec_loss": int(gs.get("consec_losses", 0)),
                    "paused":      bool(gs.get("pause_bars_left", 0)),
                    "open_pos":    n_open,
                    "buy_thr":     round(float(lrn.get("thresholds", {}).get("buy_threshold", 0.6)), 3),
                    "sell_thr":    round(float(lrn.get("thresholds", {}).get("sell_threshold", 0.4)), 3),
                    "smart_signal": str(smart.get("signal", "HOLD")),
                    "smart_power": round(float(smart.get("power", 0) or 0), 1),
                }
            except Exception:
                pass

        return {
            "ts":           datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "total_symbols": len(symbols),
            "total_open":   total_open,
            "cycle":        self._cycle,
            "symbols":      symbols,
        }

    # ── إرسال الحالة إلى Ollama ───────────────────────────────────────────────

    def _ask_ollama(self, state: dict) -> dict | None:
        raw: str | None = None
        client_error: Exception | None = None

        try:
            import ollama
        except ImportError as exc:
            client_error = exc
            log.debug("ollama python client غير مثبّت — استخدام HTTP fallback")
            ollama = None

        # تقليص: أسوأ 4 رموز فقط (بالترتيب)
        sym_list = [
            (s, d) for s, d in state["symbols"].items()
            if d["trades"] >= 3
        ]
        sym_list.sort(key=lambda x: (x[1]["consec_loss"], -x[1]["win_rate"]), reverse=True)
        worst = sym_list[:4]

        if not worst and not state["symbols"]:
            self._last_thoughts = "لا بيانات كافية بعد…"
            return None

        lines = [f"الوقت: {state['ts']}  |  رموز نشطة: {state['total_symbols']}  |  مفتوحات: {state['total_open']}"]
        for sym, d in (worst or list(state["symbols"].items())[:4]):
            status = "⛔ موقوف" if d["paused"] else ("🔴" if d["consec_loss"] >= 3 else "🟢")
            lines.append(
                f"{status} {sym}: WR={d['win_rate']:.0%} PF={d['profit_factor']:.2f} "
                f"avgR={d['avg_r']:+.4f} streak={d['streak']:+d} "
                f"loss×{d['consec_loss']} BUY_thr={d['buy_thr']:.2f}"
                f" Smart={d.get('smart_signal','HOLD')}:{d.get('smart_power',0):.1f}"
            )

        user_msg = "\n".join(lines)

        if ollama is not None:
            try:
                client_cls = getattr(ollama, "Client", None)
                client = client_cls(host=self.host) if client_cls else ollama
                resp = client.chat(
                    model=self.model,
                    messages=[
                        {"role": "system",  "content": _SYSTEM_PROMPT},
                        {"role": "user",    "content": user_msg},
                    ],
                    options={"temperature": 0.2, "num_predict": 300},
                )
                msg = resp.get("message") if isinstance(resp, dict) else getattr(resp, "message", None)
                if isinstance(msg, dict):
                    raw = str(msg.get("content", "")).strip()
                else:
                    raw = str(getattr(msg, "content", "")).strip()
                self._available = bool(raw)
            except Exception as exc:
                client_error = exc
                raw = None

        # جرّب HTTP مباشرة كبديل إذا فشل عميل Python أو لم يكن مثبتاً.
        if not raw:
            raw = self._ask_ollama_http(user_msg)

        if not raw:
            self._available = False
            self._last_thoughts = (
                f"Ollama غير متاح على {self.host}: {client_error}"
                if client_error else f"Ollama غير متاح على {self.host}"
            )
            return None

        # استخرج JSON من الرد
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            self._last_thoughts = raw[:120]
            return None

        try:
            data = json.loads(raw[start:end])
            self._last_thoughts = data.get("thoughts", raw[:80])
            self._mood          = data.get("mood", "calm")
            # أضف للـ event bus
            if self._bus:
                level = "warn" if self._mood == "urgent" else "info"
                self._bus.push(
                    "▣ CEO",
                    "► جميع الوكلاء",
                    f"[دورة {self._cycle}] {self._last_thoughts}",
                    level,
                )
            return data
        except Exception as exc:
            log.warning("OllamaCEO: فشل تحليل JSON: %s — raw=%s", exc, raw[:200])
            self._last_thoughts = raw[:100]
            return None

    def _ask_ollama_http(self, user_msg: str) -> str | None:
        """بديل مباشر عبر HTTP إذا فشلت مكتبة ollama."""
        try:
            import urllib.request
            payload = json.dumps({
                "model": self.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 300},
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self.host}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read().decode("utf-8"))
                self._available = True
                return body.get("message", {}).get("content", "")
        except Exception:
            self._available = False
            return None

    # ── تطبيق التعليمات ───────────────────────────────────────────────────────

    def _apply_instructions(self, result: dict):
        for inst in result.get("instructions", []):
            sym    = inst.get("symbol", "")
            action = inst.get("action", "adjust_param")
            param  = inst.get("param", "")
            val    = inst.get("value")
            reason = inst.get("reason", "")[:60]

            targets = list(self.orchs.items()) if sym == "ALL" else [
                (sym, self.orchs[sym]) for sym in [sym] if sym in self.orchs
            ]

            for t_sym, orch in targets:
                try:
                    if action == "adjust_param" and param and val is not None:
                        self._set_param(orch, t_sym, param, float(val), reason)

                    elif action == "pause_new_entries":
                        orch.entries_enabled = False
                        log.warning("[CEO→%s] إيقاف الدخولات الجديدة — %s", t_sym, reason)
                        if self._bus:
                            self._bus.push("▣ CEO", f"[{t_sym}]",
                                           f"⛔ إيقاف الدخولات: {reason}", "warn", t_sym)

                    elif action == "resume_entries":
                        orch.entries_enabled = True
                        log.info("[CEO→%s] استئناف الدخولات — %s", t_sym, reason)
                        if self._bus:
                            self._bus.push("▣ CEO", f"[{t_sym}]",
                                           f"✅ استئناف الدخولات: {reason}", "info", t_sym)

                    elif action == "log_only":
                        log.info("[CEO→%s] ملاحظة: %s", t_sym, reason)

                except Exception as exc:
                    log.warning("OllamaCEO: فشل تطبيق التعليمة [%s]: %s", t_sym, exc)

    def _set_param(self, orch, sym: str, param: str, val: float, reason: str):
        bounds = _SAFE_BOUNDS.get(param)
        if bounds:
            val = _clamp(val, *bounds)
        else:
            log.debug("OllamaCEO: معامل غير معروف '%s' — تجاهل", param)
            return

        applied = True
        if param == "buy_threshold":
            orch.entry.buy_prob_threshold = val
        elif param == "sell_threshold":
            orch.entry.sell_prob_threshold = val
        elif param == "min_smc_score":
            orch.entry.min_smc_score = int(val)
        elif param == "atr_sl_mult":
            orch.risk.atr_sl_mult = val
        elif param == "min_rr":
            orch.risk.min_rr = val
        elif param == "be_atr_mult":
            orch.monitor.be_atr_mult = val
        elif param == "trail_atr_mult":
            orch.monitor.trail_atr_mult = val
        else:
            applied = False

        if applied:
            log.info("[CEO→%s] %s=%.3f  (%s)", sym, param, val, reason)
            if self._bus:
                self._bus.push("▣ CEO", f"[{sym}]",
                               f"⚙ {param}={val:.3f} — {reason}", "info", sym)

    # ── حالة ─────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "available": self._available,
            "model":     self.model,
            "cycle":     self._cycle,
            "mood":      self._mood,
            "thoughts":  self._last_thoughts,
        }

