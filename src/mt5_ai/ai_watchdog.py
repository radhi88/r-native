"""
AIWatchdog — رقيب الذكاء الاصطناعي.

يعمل في thread مستقل ويراقب جميع الوكلاء باستمرار.
كل N دورة يُحلّل الأداء ويُعدّل العتبات تلقائياً.

يستخدم Claude API لتشخيص المشاكل وتقديم التوصيات.
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

log = logging.getLogger("gader.watchdog")

# حدود التعديل الآمن للعتبات (لا يُعدّل خارجها)
_SAFE_BOUNDS = {
    "buy_threshold":  (0.52, 0.88),
    "sell_threshold": (0.12, 0.48),
    "min_smc_score":  (1, 5),
    "atr_sl_mult":    (1.0, 3.0),
    "min_rr":         (1.0, 2.8),
    "be_atr_mult":    (0.10, 0.40),
    "trail_atr_mult": (0.25, 0.70),
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class AIWatchdog:
    """
    مراقب ذكي يعمل بالتوازي مع التداول.

    يُحلّل الأداء كل `check_interval` ثانية.
    إذا كان Anthropic API متاحاً → يُرسل التقرير لـ Claude ويطبّق التوصيات.
    إذا لم يكن → يعتمد على قواعد داخلية صارمة.
    """

    # أول N دورات = فترة سماح لا توقف فيها الدخولات (تتجاهل البيانات القديمة)
    _GRACE_CYCLES = 3

    def __init__(
        self,
        orchestrators: "dict[str, FridayOrchestrator]",
        check_interval: int = 120,   # ثانية بين كل تحليل (2 دقيقة)
        api_key: str = "",
    ):
        self.orchs          = orchestrators
        self.check_interval = check_interval
        self._api_key       = api_key
        self._stop          = threading.Event()
        self._thread: threading.Thread | None = None
        self._report_history: list[dict] = []
        self._cycle_count   = 0        # عدد دورات الفحص منذ بدء الجلسة

    def start(self):
        # فلتر بدء التشغيل: يُوقف الرموز الكارثية فوراً قبل أي صفقة
        self._startup_filter()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="gader-watchdog"
        )
        self._thread.start()
        log.info("AIWatchdog بدأ — فحص كل %ds", self.check_interval)

    def _startup_filter(self):
        """
        يُشغَّل مرة واحدة عند البدء.
        يوقف فوراً أي رمز يملك سجلاً تاريخياً كارثياً:
          • WR = 0%  (≥8 صفقات) — لم يربح أبداً
          • WR < 15% (≥15 صفقات) — نادراً ما يربح
          • avg_r < -2.0 (≥8 صفقات) — خسارة ضخمة لكل صفقة
        """
        paused = []
        for sym, orch in self.orchs.items():
            try:
                lrn = orch.learning.summary("smc", sym, lookback=30)
                n   = int(lrn.get("trades", 0))
                wr  = float(lrn.get("win_rate", 0))
                ar  = float(lrn.get("avg_r", 0))

                reason = None
                if n >= 8 and wr == 0.0:
                    reason = f"WR=0% ({n} صفقات)"
                elif n >= 15 and wr < 0.15:
                    reason = f"WR={wr:.0%} ({n} صفقات)"
                elif n >= 8 and ar < -10.0:
                    # فقط الرموز الكارثية حقاً (BTC crosses)، لا XAUUSDm عادي
                    reason = f"avg_r={ar:.2f} ({n} صفقات)"

                if reason:
                    orch.entries_enabled = False
                    paused.append(sym)
                    log.warning("[STARTUP] حظر %s — %s", sym, reason)
            except Exception:
                pass

        if paused:
            log.warning("[STARTUP] تم حظر %d رمز كارثي: %s", len(paused), ", ".join(paused))
        else:
            log.info("[STARTUP] جميع الرموز مقبولة تاريخياً")

    def stop(self):
        self._stop.set()

    # ── الحلقة الرئيسية ──────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._run_check()
            except Exception as exc:
                log.error("Watchdog error: %s", exc)
            self._stop.wait(self.check_interval)

    def _run_check(self):
        self._cycle_count += 1
        report = self._collect_report()
        self._report_history.append(report)
        if len(self._report_history) > 20:
            self._report_history.pop(0)

        # ── قواعد داخلية فورية (بدون API) ───────────────────────────────────
        self._apply_rule_based_fixes(report)

        # ── Claude API للتوصيات الأعمق ────────────────────────────────────
        if self._api_key:
            try:
                self._ask_claude(report)
            except Exception as exc:
                log.warning("Claude API غير متاح: %s", exc)

    # ── جمع تقرير الأداء ──────────────────────────────────────────────────────

    def _collect_report(self) -> dict:
        ts      = datetime.now(timezone.utc).isoformat()
        symbols = {}
        for sym, orch in self.orchs.items():
            try:
                lrn  = orch.learning.summary("smc", sym, lookback=20)
                conf = orch.confidence.status()
                gs   = orch.guard.status()
                symbols[sym] = {
                    "trades":    int(lrn.get("trades", 0)),
                    "win_rate":  float(lrn.get("win_rate", 0)),
                    "pf":        float(lrn.get("profit_factor", 0)),
                    "avg_r":     float(lrn.get("avg_r", 0)),
                    "streak":    int(conf.get("streak", 0)),
                    "confidence":float(conf.get("confidence", 1.0)),
                    "consec_loss":int(gs.get("consec_losses", 0)),
                    "paused":    bool(gs.get("pause_bars_left", 0)),
                    "thresholds": dict(lrn.get("thresholds", {})),
                    "open_pos":  orch.monitor.count(),
                }
            except Exception:
                pass
        return {"ts": ts, "symbols": symbols}

    # ── قواعد داخلية: تُطبَّق فوراً بدون API ─────────────────────────────────

    def _apply_rule_based_fixes(self, report: dict):
        for sym, data in report["symbols"].items():
            orch = self.orchs.get(sym)
            if not orch:
                continue
            # تخطّ الرموز المحظورة بالفعل من فلتر بدء التشغيل
            if not getattr(orch, "entries_enabled", True) and self._cycle_count <= self._GRACE_CYCLES:
                continue

            n    = data["trades"]
            wr   = data["win_rate"]
            sk   = data["streak"]
            cl   = data["consec_loss"]
            thr  = data["thresholds"]

            # ── قاعدة 1: خسائر متتالية ≥ 4 → رفع عتبات فوراً ───────────────
            if cl >= 4:
                bt = _clamp(thr.get("buy_threshold",  0.60) + 0.03, *_SAFE_BOUNDS["buy_threshold"])
                st = _clamp(thr.get("sell_threshold", 0.40) - 0.03, *_SAFE_BOUNDS["sell_threshold"])
                orch.entry.buy_prob_threshold  = bt
                orch.entry.sell_prob_threshold = st
                log.warning("[%s] Watchdog: 4 خسائر متتالية → BUY_thr=%.2f  SELL_thr=%.2f", sym, bt, st)
                self._log_action(sym, "consecutive_loss_fix", {"bt": bt, "st": st})

            # ── قاعدة 2: WR < 35% (≥8 صفقات) → SL أوسع + عتبات أصعب ───────
            if n >= 8 and wr < 0.35:
                old_sl = thr.get("atr_sl_mult", 1.5)
                new_sl = _clamp(old_sl + 0.20, *_SAFE_BOUNDS["atr_sl_mult"])
                old_rr = thr.get("min_rr", 1.2)
                new_rr = _clamp(old_rr + 0.15, *_SAFE_BOUNDS["min_rr"])
                orch.risk.atr_sl_mult = new_sl
                orch.risk.min_rr      = new_rr
                log.warning("[%s] Watchdog: WR=%.0f%% < 35%% → SL_mult=%.2f  RR=%.2f",
                            sym, wr * 100, new_sl, new_rr)
                self._log_action(sym, "low_wr_risk_fix", {"sl_mult": new_sl, "rr": new_rr})

            # ── قاعدة 3: Streak سلبي ≤ -5 → زيادة SMC score مطلوبة ──────────
            if sk <= -5:
                ms = min(orch.entry.min_smc_score + 1, 5)
                orch.entry.min_smc_score = ms
                log.warning("[%s] Watchdog: streak=%d → min_smc_score=%d", sym, sk, ms)
                self._log_action(sym, "bad_streak_smc_fix", {"min_smc_score": ms})

            # ── قاعدة 4: WR > 65% (≥15 صفقات) → تخفيف طفيف للمزيد ─────────
            if n >= 15 and wr > 0.65:
                bt = _clamp(thr.get("buy_threshold",  0.60) - 0.01, *_SAFE_BOUNDS["buy_threshold"])
                st = _clamp(thr.get("sell_threshold", 0.40) + 0.01, *_SAFE_BOUNDS["sell_threshold"])
                orch.entry.buy_prob_threshold  = bt
                orch.entry.sell_prob_threshold = st
                log.info("[%s] Watchdog: WR=%.0f%% > 65%% → تخفيف عتبات", sym, wr * 100)
                self._log_action(sym, "good_wr_relax", {"bt": bt, "st": st})

            # قاعدة 5 محذوفة: تسريع BE كان يسبب خسائر السبريد
            # BE يبقى عند القيمة الافتراضية (0.40×ATR)

            entries_on = getattr(orch, "entries_enabled", True)

            # قواعد الإيقاف لا تُطبَّق خلال فترة السماح (أول 3 دورات)
            # تجنباً لإيقاف الرموز بسبب بيانات الجلسات السابقة
            if self._cycle_count <= self._GRACE_CYCLES:
                continue

            # ── قاعدة 6: WR < 20% (≥10 صفقات) → إيقاف الدخولات الجديدة ──────
            if n >= 10 and wr < 0.20 and entries_on:
                orch.entries_enabled = False
                log.warning(
                    "[%s] Watchdog: WR=%.0f%% < 20%% (%d صفقات) → إيقاف الدخولات",
                    sym, wr * 100, n,
                )
                self._log_action(sym, "pause_entries_low_wr", {"wr": wr, "trades": n})

            # ── قاعدة 7: avg_r شديد السلبية (≥8 صفقات) → إيقاف فوري ──────────
            # نرفع الحد إلى ≥8 صفقات لتجنب الإيقاف بسبب مراكز مستوردة قديمة
            if n >= 8 and data["avg_r"] < -1.0 and entries_on:
                orch.entries_enabled = False
                log.warning(
                    "[%s] Watchdog: avg_r=%.3f < -1.0 (%d صفقات) → إيقاف الدخولات فوراً",
                    sym, data["avg_r"], n,
                )
                self._log_action(sym, "pause_entries_bad_avgr", {"avg_r": data["avg_r"]})

            # ── قاعدة 8: استئناف تلقائي إذا تعافى الأداء (WR>42% بعد إيقاف) ─
            if not entries_on and n >= 5 and wr > 0.42:
                orch.entries_enabled = True
                log.info("[%s] Watchdog: WR=%.0f%% تعافى → استئناف الدخولات", sym, wr * 100)
                self._log_action(sym, "resume_entries_recovered", {"wr": wr})

    # ── Claude API: تحليل أعمق ───────────────────────────────────────────────

    def _ask_claude(self, report: dict):
        try:
            import anthropic
        except ImportError:
            log.debug("anthropic غير مثبّت — pip install anthropic")
            return

        # ملخص مضغوط للإرسال
        worst = sorted(
            [(s, d) for s, d in report["symbols"].items() if d["trades"] >= 5],
            key=lambda x: x[1]["win_rate"]
        )[:3]

        if not worst:
            return

        summary_lines = []
        for sym, d in worst:
            summary_lines.append(
                f"- {sym}: WR={d['win_rate']:.0%}  PF={d['pf']:.2f}  "
                f"avg_R={d['avg_r']:+.3f}  streak={d['streak']:+d}  "
                f"loss_streak={d['consec_loss']}  "
                f"BUY_thr={d['thresholds'].get('buy_threshold',0.6):.2f}  "
                f"SL_mult={d['thresholds'].get('atr_sl_mult',1.5):.2f}"
            )

        prompt = (
            "أنت مستشار نظام تداول آلي. هذه إحصاءات أداء الرموز الأسوأ:\n\n"
            + "\n".join(summary_lines)
            + "\n\nاقترح تعديلات محددة على العتبات لتحسين الأداء. "
            "أجب بـ JSON فقط بالشكل:\n"
            '{"adjustments": [{"symbol": "X", "param": "buy_threshold", "value": 0.65, "reason": "..."}]}'
        )

        client = anthropic.Anthropic(api_key=self._api_key)
        msg    = client.messages.create(
            model      = "claude-haiku-4-5-20251001",
            max_tokens = 400,
            messages   = [{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        try:
            data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            for adj in data.get("adjustments", []):
                self._apply_claude_adjustment(adj)
        except Exception as exc:
            log.warning("Watchdog: فشل تحليل رد Claude: %s — raw=%s", exc, raw[:200])

    def _apply_claude_adjustment(self, adj: dict):
        sym   = adj.get("symbol", "")
        param = adj.get("param", "")
        val   = adj.get("value")
        reason= adj.get("reason", "")

        orch = self.orchs.get(sym)
        if not orch or val is None:
            return

        bounds = _SAFE_BOUNDS.get(param)
        if bounds:
            val = _clamp(float(val), *bounds)

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
            return

        log.info("[%s] Claude → %s=%.3f  (%s)", sym, param, val, reason[:60])
        self._log_action(sym, f"claude_{param}", {"value": val, "reason": reason})

    def _log_action(self, sym: str, action: str, data: dict):
        log.info("Watchdog action [%s] %s: %s", sym, action, data)

    # ── حالة ─────────────────────────────────────────────────────────────────

    def latest_report(self) -> dict:
        return self._report_history[-1] if self._report_history else {}
