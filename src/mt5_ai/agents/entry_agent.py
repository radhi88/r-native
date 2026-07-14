"""
EntryAgent — محرك قرار الدخول بمنهجية SMC مع عتبات قابلة للتعلم.

جميع العتبات الداخلية (التي كانت مشفّرة ثابتة سابقاً) أصبحت الآن
ديناميكية تُحدَّث من LearningEngine بعد كل دفعة من الصفقات.

إعدادات الدخول (شراء):
  1. SSL sweep نشط + BOS_UP + OB صاعد
  2. SSL sweep نشط + BOS_UP + FVG صاعد
  3. CHOCH صاعد + منطقة طلب + احتمال نموذج جيد
  4. BOS صاعد + OB + احتمال جيد
  5. ثقة عالية (high_conf_buy) + SMC قوي + sweep أو BOS
  6. SSL sweep + CHOCH صاعد
  7. BOS صاعد قوي + SMC≥smc_score_strong + momentum
  8. BSL sweep + BOS صاعد (continuation)

إعدادات الدخول (بيع): مرايا للشراء.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── محركات التعلم والتنبؤ الجديدة (اختيارية — backward-compatible) ──────────
try:
    from ..indicator_snapshot import IndicatorSnapshot, PatternAnalyzer, save_snapshot
    from ..prediction_engine  import PredictionEngine
    _ENHANCED = True
except ImportError:
    _ENHANCED = False

_prediction_engine  = PredictionEngine()  if _ENHANCED else None
_pattern_analyzer   = PatternAnalyzer()   if _ENHANCED else None


# ── العتبات الافتراضية لكل إعداد (قابلة للتعلم) ────────────────────────────

_DEFAULT_SETUP_THRESHOLDS: dict[str, float | int] = {
    "high_conf_buy":           0.72,   # الحد الأدنى للاحتمال في إعداد الثقة العالية (شراء)
    "high_conf_sell":          0.28,   # الحد الأقصى للاحتمال في إعداد الثقة العالية (بيع)
    "bos_continuation_buy":   0.58,   # احتمال شراء في إعداد BSL+BOS continuation
    "bos_continuation_sell":  0.42,   # احتمال بيع في إعداد SSL+BOS continuation
    "pending_buy_min_prob":   0.62,   # الحد الأدنى لاحتمال BUY_LIMIT
    "pending_sell_max_prob":  0.38,   # الحد الأقصى لاحتمال SELL_LIMIT
    "smc_score_strong":        3,     # حد SMC القوي في إعدادي 7 و8
}

_THRESHOLD_BOUNDS: dict[str, tuple] = {
    "high_conf_buy":          (0.60, 0.88),
    "high_conf_sell":         (0.12, 0.40),
    "bos_continuation_buy":   (0.52, 0.80),
    "bos_continuation_sell":  (0.20, 0.48),
    "pending_buy_min_prob":   (0.55, 0.82),
    "pending_sell_max_prob":  (0.18, 0.45),
    "smc_score_strong":       (2, 5),
}


@dataclass
class EntrySignal:
    symbol: str
    side: str
    price: float
    atr: float
    confidence: float
    probability: float
    smc_score: int
    reason: str
    order_type: str = "MARKET"
    limit_price: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EntryAgent:
    name = "entry"

    _COOLDOWN_BARS     = 6
    _CONSEC_LOSS_LIMIT = 3

    def __init__(
        self,
        symbol: str,
        buy_prob_threshold: float  = 0.60,
        sell_prob_threshold: float = 0.40,
        min_smc_score: int = 2,
        setup_thresholds: dict | None = None,
    ):
        self.symbol              = symbol
        self.buy_prob_threshold  = buy_prob_threshold
        self.sell_prob_threshold = sell_prob_threshold
        self.min_smc_score       = min_smc_score
        self.log = logging.getLogger(f"friday.agent.{self.name}")

        # ── عتبات الإعدادات القابلة للتعلم ──────────────────────────────────
        self._setup_thresholds: dict = dict(_DEFAULT_SETUP_THRESHOLDS)
        if setup_thresholds:
            self._setup_thresholds.update(setup_thresholds)

        # ── تتبع أداء كل إعداد ─────────────────────────────────────────────
        self._setup_trades: dict[str, int]         = {}
        self._setup_wins:   dict[str, int]         = {}
        self._setup_pnl:    dict[str, list[float]] = {}

        # ── cooldown بعد خسائر متتالية ──────────────────────────────────────
        self._setup_losses:    dict[str, int] = {}
        self._setup_cooldowns: dict[str, int] = {}

    # ── تحديث العتبات من LearningEngine ─────────────────────────────────────

    def update_setup_thresholds(self, new_thresholds: dict) -> None:
        """يُستدعى من Orchestrator لتطبيق العتبات المُتعلَّمة."""
        for key, value in new_thresholds.items():
            if key not in _THRESHOLD_BOUNDS:
                continue
            lo, hi = _THRESHOLD_BOUNDS[key]
            clamped = max(lo, min(hi, value))
            old = self._setup_thresholds.get(key)
            if old != clamped:
                self.log.info(
                    "[%s] setup threshold updated: %s  %.4f → %.4f",
                    self.symbol, key, old, clamped,
                )
                self._setup_thresholds[key] = clamped

    def get_setup_threshold_report(self) -> dict:
        return dict(self._setup_thresholds)

    # ── API التداول ──────────────────────────────────────────────────────────

    def tick_cooldowns(self):
        for k in list(self._setup_cooldowns):
            self._setup_cooldowns[k] -= 1
            if self._setup_cooldowns[k] <= 0:
                del self._setup_cooldowns[k]
                self._setup_losses.pop(k, None)
                self.log.info("[%s] انتهى حظر الإعداد '%s'", self.symbol, k)

    def record_outcome(self, reason: str, won: bool, points: float = 0.0):
        """يُستدعى عند إغلاق كل صفقة لتحديث ذاكرة الإعدادات والأداء."""
        if not reason or reason in ("auto", ""):
            return
        base = reason.split("+")[0]

        # تتبع أداء الإعداد
        self._setup_trades[base] = self._setup_trades.get(base, 0) + 1
        if won:
            self._setup_wins[base] = self._setup_wins.get(base, 0) + 1
        if base not in self._setup_pnl:
            self._setup_pnl[base] = []
        self._setup_pnl[base].append(points)
        self._setup_pnl[base] = self._setup_pnl[base][-100:]  # احتفظ بآخر 100

        # إدارة cooldown
        if won:
            self._setup_losses[base] = 0
        else:
            self._setup_losses[base] = self._setup_losses.get(base, 0) + 1
            if self._setup_losses[base] >= self._CONSEC_LOSS_LIMIT:
                self._setup_cooldowns[base] = self._COOLDOWN_BARS
                self.log.warning(
                    "[%s] حظر الإعداد '%s' لـ %d شمعات بعد %d خسائر متتالية",
                    self.symbol, base, self._COOLDOWN_BARS, self._CONSEC_LOSS_LIMIT,
                )

    def setup_performance_summary(self) -> dict:
        """يُعيد ملخص أداء كل إعداد للمراقبة."""
        summary = {}
        for reason, trades in self._setup_trades.items():
            wins = self._setup_wins.get(reason, 0)
            pts = self._setup_pnl.get(reason, [])
            avg_pts = sum(pts) / len(pts) if pts else 0.0
            summary[reason] = {
                "trades": trades,
                "wins": wins,
                "wr": round(wins / trades, 3) if trades else 0.0,
                "avg_pts": round(avg_pts, 2),
            }
        return summary

    def _is_blocked(self, reason: str) -> bool:
        base = reason.split("+")[0]
        return base in self._setup_cooldowns

    # ── تقييم الدخول ─────────────────────────────────────────────────────────

    def evaluate(
        self,
        market_ctx: dict,
        liquidity_ctx: dict,
        probability: float,
        extra_ctx: dict | None = None,          # NEW: ema_fast/mid/slow, adx, momentum_3/10 …
        best_setups: list[str] | None = None,   # NEW: from LearningEngine
        worst_setups: list[str] | None = None,  # NEW: from LearningEngine
    ) -> EntrySignal | None:
        price = market_ctx["price"]
        atr   = market_ctx["atr"]
        ectx  = extra_ctx or {}

        # ── شراء ─────────────────────────────────────────────────────────────
        ok, reason = self._check_buy(market_ctx, liquidity_ctx, probability)
        if ok and not self._is_blocked(reason):
            # ── PredictionEngine: احسب احتمالية مُعزَّزة ───────────────────
            final_prob, skip, skip_reason = self._enhanced_predict(
                side="BUY", reason=reason,
                base_prob=probability,
                market_ctx=market_ctx, liquidity_ctx=liquidity_ctx,
                ectx=ectx, best_setups=best_setups, worst_setups=worst_setups,
            )
            if skip:
                self.log.info("BUY blocked by PredictionEngine: %s", skip_reason)
            else:
                conf = min(max((final_prob - 0.5) * 2.5, 0.0), 1.0)
                self.log.info(
                    "BUY signal: %s  price=%.5f  base_prob=%.3f  enhanced=%.3f",
                    reason, price, probability, final_prob,
                )
                return EntrySignal(
                    symbol=self.symbol, side="BUY",
                    price=price, atr=atr,
                    confidence=conf, probability=final_prob,
                    smc_score=market_ctx["smc_buy_score"],
                    reason=reason,
                    meta={"mctx": market_ctx, "lctx": liquidity_ctx,
                          "base_prob": probability, "enhanced_prob": final_prob},
                )

        # ── بيع ──────────────────────────────────────────────────────────────
        ok, reason = self._check_sell(market_ctx, liquidity_ctx, probability)
        if ok and not self._is_blocked(reason):
            final_prob, skip, skip_reason = self._enhanced_predict(
                side="SELL", reason=reason,
                base_prob=probability,
                market_ctx=market_ctx, liquidity_ctx=liquidity_ctx,
                ectx=ectx, best_setups=best_setups, worst_setups=worst_setups,
            )
            if skip:
                self.log.info("SELL blocked by PredictionEngine: %s", skip_reason)
            else:
                conf = min(max((0.5 - final_prob) * 2.5, 0.0), 1.0)
                self.log.info(
                    "SELL signal: %s  price=%.5f  base_prob=%.3f  enhanced=%.3f",
                    reason, price, probability, final_prob,
                )
                return EntrySignal(
                    symbol=self.symbol, side="SELL",
                    price=price, atr=atr,
                    confidence=conf, probability=final_prob,
                    smc_score=market_ctx["smc_sell_score"],
                    reason=reason,
                    meta={"mctx": market_ctx, "lctx": liquidity_ctx,
                          "base_prob": probability, "enhanced_prob": final_prob},
                )

        # ── أوامر معلقة ──────────────────────────────────────────────────────
        ok, reason, limit_px, otype = self._check_pending_buy(market_ctx, liquidity_ctx, probability)
        if ok and not self._is_blocked(reason):
            conf = min(max((probability - 0.5) * 2.5, 0.0), 1.0)
            self.log.info("PENDING BUY: %s  limit=%.5f  prob=%.3f", reason, limit_px, probability)
            return EntrySignal(
                symbol=self.symbol, side="BUY",
                price=price, atr=atr,
                confidence=conf, probability=probability,
                smc_score=market_ctx["smc_buy_score"],
                reason=reason,
                order_type=otype,
                limit_price=limit_px,
                meta={"mctx": market_ctx, "lctx": liquidity_ctx},
            )

        ok, reason, limit_px, otype = self._check_pending_sell(market_ctx, liquidity_ctx, probability)
        if ok and not self._is_blocked(reason):
            conf = min(max((0.5 - probability) * 2.5, 0.0), 1.0)
            self.log.info("PENDING SELL: %s  limit=%.5f  prob=%.3f", reason, limit_px, probability)
            return EntrySignal(
                symbol=self.symbol, side="SELL",
                price=price, atr=atr,
                confidence=conf, probability=probability,
                smc_score=market_ctx["smc_sell_score"],
                reason=reason,
                order_type=otype,
                limit_price=limit_px,
                meta={"mctx": market_ctx, "lctx": liquidity_ctx},
            )

        return None

    # ── شروط الشراء ───────────────────────────────────────────────────────────

    def _check_buy(self, mctx: dict, lctx: dict, prob: float) -> tuple[bool, str]:
        smc_ok  = mctx["smc_buy_score"] >= self.min_smc_score
        prob_ok = prob >= self.buy_prob_threshold
        t = self._setup_thresholds

        # الإعداد 1: اختراق SSL + كسر هيكل صاعد + دخول OB
        if lctx["ssl_sweep_active"] and mctx["bos_up"] and mctx["in_bullish_ob"] and smc_ok:
            return True, "ssl_sweep+bos_up+ob"

        # الإعداد 2: اختراق SSL + كسر هيكل صاعد + FVG صاعد
        if lctx["ssl_sweep_active"] and mctx["bos_up"] and mctx["bullish_fvg"] and smc_ok:
            return True, "ssl_sweep+bos_up+fvg"

        # الإعداد 3: CHOCH صاعد + منطقة طلب + احتمال جيد
        if mctx["choch_up"] and mctx["demand_zone"] and prob_ok and smc_ok:
            return True, "choch_up+demand_zone"

        # الإعداد 4: كسر هيكل صاعد + OB + احتمال جيد
        if mctx["bos_up"] and mctx["in_bullish_ob"] and prob_ok and smc_ok:
            return True, "bos_up+ob+prob"

        # الإعداد 5: ثقة عالية (مُتعلَّمة) + SMC قوي + تأكيد هيكل
        if (prob >= t["high_conf_buy"]
                and mctx["smc_buy_score"] >= 2
                and mctx["trend"] >= 0
                and (lctx["ssl_sweep_active"] or mctx["bos_up"] or mctx["choch_up"])):
            return True, "high_conf_buy"

        # الإعداد 6: اختراق SSL + CHOCH
        if lctx["ssl_sweep_active"] and mctx["choch_up"] and smc_ok:
            return True, "ssl_sweep+choch_up"

        # الإعداد 7: BOS صاعد قوي + SMC قوي (مُتعلَّم) + momentum
        if (mctx["bos_up"]
                and mctx["smc_buy_score"] >= int(t["smc_score_strong"])
                and prob_ok
                and mctx["trend"] >= 0):
            return True, "bos_up+smc_strong+momentum"

        # الإعداد 8: BSL sweep + BOS صاعد + احتمال continuation (مُتعلَّم)
        if (lctx["bsl_sweep_active"]
                and mctx["bos_up"]
                and prob >= t["bos_continuation_buy"]
                and smc_ok):
            return True, "bsl_sweep+bos_up+continuation"

        # ══ الإعدادات الجديدة 9-12 ══════════════════════════════════════════

        # الإعداد 9: IFVG صاعد (Inverse FVG) + BOS + اتجاه موافق
        if (mctx.get("ifvg_bull") and mctx["bos_up"]
                and mctx["trend"] >= 0 and prob_ok):
            return True, "ifvg_bull+bos_up+trend"

        # الإعداد 10: اختراق SSL مزدوج + انعكاس فوري (شمعة انعكاسية)
        if (lctx["ssl_sweep_active"] and lctx.get("prev_ssl_sweep_active")
                and mctx.get("reversal_bar") and prob_ok):
            return True, "double_ssl_sweep+reversal"

        # الإعداد 11: تخفيف OB (price returns to OB) + CHOCH + ADX قوي
        if (mctx["in_bullish_ob"] and mctx["choch_up"]
                and mctx.get("adx", 0) >= 25 and smc_ok):
            return True, "ob_mitigation+choch_up+adx"

        # الإعداد 12: FVG صاعد + توافق متعدد الإطارات (M1+M5+M15)
        if (mctx["bullish_fvg"]
                and mctx.get("mtf_buy_confluence", 0) >= 3
                and prob_ok and smc_ok):
            return True, "fvg_bull+mtf_confluence"

        return False, ""

    # ── شروط البيع ────────────────────────────────────────────────────────────

    def _check_sell(self, mctx: dict, lctx: dict, prob: float) -> tuple[bool, str]:
        smc_ok  = mctx["smc_sell_score"] >= self.min_smc_score
        prob_ok = prob <= self.sell_prob_threshold
        t = self._setup_thresholds

        # الإعداد 1: اختراق BSL + كسر هيكل هابط + OB
        if lctx["bsl_sweep_active"] and mctx["bos_down"] and mctx["in_bearish_ob"] and smc_ok:
            return True, "bsl_sweep+bos_down+ob"

        # الإعداد 2: اختراق BSL + كسر هيكل هابط + FVG هابط
        if lctx["bsl_sweep_active"] and mctx["bos_down"] and mctx["bearish_fvg"] and smc_ok:
            return True, "bsl_sweep+bos_down+fvg"

        # الإعداد 3: CHOCH هابط + منطقة عرض
        if mctx["choch_down"] and mctx["supply_zone"] and prob_ok and smc_ok:
            return True, "choch_down+supply_zone"

        # الإعداد 4: كسر هيكل هابط + OB + احتمال جيد
        if mctx["bos_down"] and mctx["in_bearish_ob"] and prob_ok and smc_ok:
            return True, "bos_down+ob+prob"

        # الإعداد 5: ثقة عالية بيع (مُتعلَّمة) + SMC قوي + تأكيد هيكل
        if (prob <= t["high_conf_sell"]
                and mctx["smc_sell_score"] >= 2
                and mctx["trend"] <= 0
                and (lctx["bsl_sweep_active"] or mctx["bos_down"] or mctx["choch_down"])):
            return True, "high_conf_sell"

        # الإعداد 6: اختراق BSL + CHOCH هابط
        if lctx["bsl_sweep_active"] and mctx["choch_down"] and smc_ok:
            return True, "bsl_sweep+choch_down"

        # الإعداد 7: BOS هابط قوي + SMC قوي (مُتعلَّم)
        if (mctx["bos_down"]
                and mctx["smc_sell_score"] >= int(t["smc_score_strong"])
                and prob_ok
                and mctx["trend"] <= 0):
            return True, "bos_down+smc_strong+momentum"

        # الإعداد 8: SSL sweep + BOS هابط + احتمال continuation (مُتعلَّم)
        if (lctx["ssl_sweep_active"]
                and mctx["bos_down"]
                and prob <= t["bos_continuation_sell"]
                and smc_ok):
            return True, "ssl_sweep+bos_down+continuation"

        # ══ الإعدادات الجديدة 9-12 (بيع) ══════════════════════════════════════

        # الإعداد 9: IFVG هابط (Inverse FVG) + BOS هابط + اتجاه موافق
        if (mctx.get("ifvg_bear") and mctx["bos_down"]
                and mctx["trend"] <= 0 and prob_ok):
            return True, "ifvg_bear+bos_down+trend"

        # الإعداد 10: اختراق BSL مزدوج + انعكاس فوري (شمعة انعكاسية هابطة)
        if (lctx["bsl_sweep_active"] and lctx.get("prev_bsl_sweep_active")
                and mctx.get("reversal_bar") and prob_ok):
            return True, "double_bsl_sweep+reversal"

        # الإعداد 11: تخفيف OB هابط + CHOCH هابط + ADX قوي
        if (mctx["in_bearish_ob"] and mctx["choch_down"]
                and mctx.get("adx", 0) >= 25 and smc_ok):
            return True, "ob_mitigation+choch_down+adx"

        # الإعداد 12: FVG هابط + توافق متعدد الإطارات (M1+M5+M15)
        if (mctx["bearish_fvg"]
                and mctx.get("mtf_sell_confluence", 0) >= 3
                and prob_ok and smc_ok):
            return True, "fvg_bear+mtf_confluence"

        return False, ""

    # ── أوامر معلقة ──────────────────────────────────────────────────────────

    def _check_pending_buy(
        self, mctx: dict, lctx: dict, prob: float
    ) -> tuple[bool, str, float, str]:
        price = mctx["price"]
        atr   = mctx["atr"]
        ob_low  = mctx.get("bullish_ob_low")
        ob_high = mctx.get("bullish_ob_high")
        t = self._setup_thresholds

        if (ob_low is not None and ob_high is not None
                and ob_low < price
                and lctx["ssl_sweep_active"]
                and mctx["trend"] >= 0
                and prob >= t["pending_buy_min_prob"]      # ← كان 0.62 ثابت
                and mctx["smc_buy_score"] >= int(t["smc_score_strong"])):
            limit_px = ob_low + (ob_high - ob_low) * 0.3
            if limit_px < price and (price - limit_px) >= atr * 1.5:
                estimated_risk = limit_px - (ob_low - atr * 0.1)
                if estimated_risk >= atr * 1.0:
                    return True, "pending_buy_ob+ssl", round(limit_px, 5), "BUY_LIMIT"

        return False, "", 0.0, ""

    # ── PredictionEngine helper ───────────────────────────────────────────────

    def _enhanced_predict(
        self,
        *,
        side: str,
        reason: str,
        base_prob: float,
        market_ctx: dict,
        liquidity_ctx: dict,
        ectx: dict,
        best_setups: list[str] | None,
        worst_setups: list[str] | None,
    ) -> tuple[float, bool, str]:
        """
        يُطبّق PredictionEngine لتعزيز الاحتمالية.
        يُعيد (final_prob, should_skip, skip_reason).
        إذا لم يكن _ENHANCED متاحاً يُعيد الاحتمالية الأصلية بدون تعديل.
        """
        if not _ENHANCED or _prediction_engine is None:
            return base_prob, False, ""

        # ── بناء IndicatorSnapshot (يتطابق مع توقيع build الفعلي) ────────────
        try:
            price = market_ctx["price"]
            atr   = market_ctx["atr"]
            snap = IndicatorSnapshot.build(
                symbol      = self.symbol,
                agent       = "smc",
                side        = side,
                setup_reason = reason,
                price       = price,
                spread      = market_ctx.get("spread", 0.0),
                atr         = atr,
                avg_atr     = market_ctx.get("atr_ref", atr),   # ATR مرجعي (متوسط)
                rsi         = ectx.get("rsi", 50.0),
                adx         = ectx.get("adx", float(market_ctx.get("adx", 20.0))),
                ema_fast    = ectx.get("ema_fast", price),
                ema_mid     = ectx.get("ema_mid",  price),
                ema_slow    = ectx.get("ema_slow", price),
                trend_score = float(market_ctx.get("trend", 0)),
                momentum_3  = ectx.get("momentum_3",  0.0),
                momentum_10 = ectx.get("momentum_10", 0.0),
                # SMC context packed into smc_ctx & liquidity_ctx dicts
                smc_ctx     = market_ctx,
                liquidity_ctx = liquidity_ctx,
                distance_to_ob = float(market_ctx.get("distance_to_ob", 2.0)),
            )
        except Exception as exc:
            self.log.warning("IndicatorSnapshot.build failed: %s", exc)
            return base_prob, False, ""

        # ── PredictionEngine.predict ──────────────────────────────────────────
        try:
            result = _prediction_engine.predict(
                ai_prob       = base_prob,
                side          = side,
                snap          = snap,
                pattern_analyzer = _pattern_analyzer,
                best_setups   = best_setups,
                worst_setups  = worst_setups,
            )
        except Exception as exc:
            self.log.warning("PredictionEngine.predict failed: %s", exc)
            return base_prob, False, ""

        self.log.debug("[Enhanced] %s", result.explanation)

        if result.should_skip:
            return result.final_prob, True, result.skip_reason

        # ── حفظ snapshot للتعلم المستقبلي (بدون نتيجة — ستُضاف عند الإغلاق) ──
        try:
            save_snapshot(snap, path="data/indicator_snapshots.csv")
        except Exception as exc:
            self.log.debug("save_snapshot failed (non-fatal): %s", exc)

        return result.final_prob, False, ""

    def _check_pending_sell(
        self, mctx: dict, lctx: dict, prob: float
    ) -> tuple[bool, str, float, str]:
        price = mctx["price"]
        atr   = mctx["atr"]
        ob_high = mctx.get("bearish_ob_high")
        ob_low  = mctx.get("bearish_ob_low")
        t = self._setup_thresholds

        if (ob_high is not None and ob_low is not None
                and ob_high > price
                and lctx["bsl_sweep_active"]
                and mctx["trend"] <= 0
                and prob <= t["pending_sell_max_prob"]     # ← كان 0.38 ثابت
                and mctx["smc_sell_score"] >= int(t["smc_score_strong"])):
            limit_px = ob_high - (ob_high - ob_low) * 0.3
            if limit_px > price and (limit_px - price) >= atr * 1.5:
                estimated_risk = (ob_high + atr * 0.1) - limit_px
                if estimated_risk >= atr * 1.0:
                    return True, "pending_sell_ob+bsl", round(limit_px, 5), "SELL_LIMIT"

        return False, "", 0.0, ""
