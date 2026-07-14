"""
PredictionEngine — محرك تنبؤ متقدم يدمج كل مصادر المعلومات.

يأخذ:
  - ai_prob: الاحتمالية الخام من الـ AI model
  - IndicatorSnapshot: لقطة المؤشرات الكاملة
  - PatternAnalyzer: تاريخ الأداء
  - setup performance: أداء هذا الإعداد تاريخياً

ويعطي:
  - enhanced_probability: احتمالية مُعزَّزة ومُضبَّطة [0.05, 0.95]
  - explanation: شرح تفصيلي لكل عامل
  - should_skip: True إذا يجب تجاهل الإشارة

المنطق:
  تُجمع التعديلات المضافة (additive adjustments) على الاحتمالية الأساسية،
  مع تسجيل سبب كل تعديل. النتيجة = clamp(base + Σ adjustments, 0.05, 0.95)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("friday.prediction")

# ── constants ──────────────────────────────────────────────────────────────
_CLIP_LO = 0.05
_CLIP_HI = 0.95


@dataclass
class PredictionResult:
    base_prob:    float
    final_prob:   float
    adjustments:  list[tuple[str, float]] = field(default_factory=list)
    should_skip:  bool  = False
    skip_reason:  str   = ""
    explanation:  str   = ""

    def __post_init__(self):
        lines = [f"base={self.base_prob:.3f}"]
        for name, adj in self.adjustments:
            sign = "+" if adj >= 0 else ""
            lines.append(f"{name}:{sign}{adj:+.3f}")
        lines.append(f"→final={self.final_prob:.3f}")
        if self.should_skip:
            lines.append(f"[SKIP:{self.skip_reason}]")
        self.explanation = "  ".join(lines)


class PredictionEngine:
    """
    يعالج الاحتمالية الخام بـ 10 عوامل مستقلة ليعطي تقديراً أكثر دقة.

    كل عامل يضيف أو ينقص من الاحتمالية بشكل مضاف (additive).
    بعض العوامل "قاطعة" (hard skip) تُلغي الإشارة مباشرة.
    """

    def predict(
        self,
        *,
        ai_prob: float,
        side: str,                          # "BUY" | "SELL"
        snap,                               # IndicatorSnapshot
        pattern_analyzer=None,              # PatternAnalyzer | None
        best_setups: list[str] | None = None,
        worst_setups: list[str] | None = None,
        learning_summary: dict | None = None,
    ) -> PredictionResult:
        """
        Returns PredictionResult with enhanced probability and full explanation.
        """
        adjustments: list[tuple[str, float]] = []
        skip_reason = ""

        is_buy = side.upper() == "BUY"

        # ══════════════════════════════════════════════════════════════════
        # HARD SKIPS — أسباب الاستبعاد الصارم (بدون رحمة)
        # ══════════════════════════════════════════════════════════════════

        # 1. Extreme volatility
        if snap.volatility_regime == "extreme":
            return PredictionResult(
                base_prob=ai_prob, final_prob=ai_prob,
                should_skip=True, skip_reason="extreme_volatility",
            )

        # 2. Spread too wide  (> 3× ATR)
        if snap.spread_ratio > 3.0:
            return PredictionResult(
                base_prob=ai_prob, final_prob=ai_prob,
                should_skip=True, skip_reason=f"spread_too_wide:{snap.spread_ratio:.1f}x_atr",
            )

        # 3. No trend (ADX < 12 = hard skip; 12-18 = soft penalty applied below)
        if snap.adx < 12:
            return PredictionResult(
                base_prob=ai_prob, final_prob=ai_prob,
                should_skip=True, skip_reason=f"no_trend_adx:{snap.adx:.1f}",
            )

        # 4. EMA totally against trade
        if is_buy and snap.ema_alignment == "bear_stack":
            # Only allow if we have very strong SMC signal
            if snap.smc_buy_score < 4:
                return PredictionResult(
                    base_prob=ai_prob, final_prob=ai_prob,
                    should_skip=True, skip_reason="ema_bear_stack_vs_buy",
                )
        if not is_buy and snap.ema_alignment == "bull_stack":
            if snap.smc_sell_score < 4:
                return PredictionResult(
                    base_prob=ai_prob, final_prob=ai_prob,
                    should_skip=True, skip_reason="ema_bull_stack_vs_sell",
                )

        # 5. PatternAnalyzer blacklist check
        if pattern_analyzer is not None:
            excluded, bl_reason = pattern_analyzer.snapshot_is_excluded(snap)
            if excluded:
                return PredictionResult(
                    base_prob=ai_prob, final_prob=ai_prob,
                    should_skip=True, skip_reason=bl_reason,
                )

        # ══════════════════════════════════════════════════════════════════
        # SOFT ADJUSTMENTS — تعديلات تراكمية على الاحتمالية
        # ══════════════════════════════════════════════════════════════════

        base = ai_prob

        # ── A. Session boost/penalty ────────────────────────────────────
        session_adj = {
            "overlap": +0.06,    # London/NY overlap — best liquidity
            "london":  +0.03,
            "ny":      +0.02,
            "tokyo":   -0.02,
            "off":     -0.08,
        }.get(snap.session, 0.0)
        adjustments.append(("session", session_adj))

        # ── B. ADX trend strength ───────────────────────────────────────
        if snap.adx >= 40:
            adx_adj = +0.05
        elif snap.adx >= 30:
            adx_adj = +0.03
        elif snap.adx >= 20:
            adx_adj = 0.0
        elif snap.adx >= 15:
            adx_adj = -0.03   # ADX 15-20 — weak trend, slight penalty
        else:
            adx_adj = -0.06   # ADX 12-15 — very weak trend, stronger penalty
        adjustments.append(("adx", adx_adj))

        # ── C. RSI zone alignment ───────────────────────────────────────
        rsi_adj = 0.0
        if is_buy:
            if snap.rsi > 75:
                rsi_adj = -0.07   # overbought — risky buy
            elif snap.rsi > 65:
                rsi_adj = -0.03
            elif 30 <= snap.rsi <= 50:
                rsi_adj = +0.04   # healthy RSI for buy
            elif snap.rsi < 25:
                rsi_adj = +0.05   # deeply oversold rebound
        else:
            if snap.rsi < 25:
                rsi_adj = -0.07   # oversold — risky sell
            elif snap.rsi < 35:
                rsi_adj = -0.03
            elif 50 <= snap.rsi <= 70:
                rsi_adj = +0.04   # healthy RSI for sell
            elif snap.rsi > 75:
                rsi_adj = +0.05   # overbought — sell opportunity
        adjustments.append(("rsi", rsi_adj))

        # ── D. Momentum alignment ───────────────────────────────────────
        m3 = snap.momentum_3
        if is_buy:
            mom_adj = +0.03 if m3 > 0.5 else (-0.04 if m3 < -1.0 else 0.0)
        else:
            mom_adj = +0.03 if m3 < -0.5 else (-0.04 if m3 > 1.0 else 0.0)
        adjustments.append(("momentum", mom_adj))

        # ── E. Spread penalty ───────────────────────────────────────────
        if snap.spread_ratio > 2.0:
            spread_adj = -0.05
        elif snap.spread_ratio > 1.5:
            spread_adj = -0.02
        elif snap.spread_ratio < 0.6:
            spread_adj = +0.02   # tight spread = cheaper entry
        else:
            spread_adj = 0.0
        adjustments.append(("spread", spread_adj))

        # ── F. Volatility regime ────────────────────────────────────────
        vol_adj = {
            "low":     -0.02,   # low ATR = choppy, signals less reliable
            "normal":  +0.02,
            "high":    -0.03,
            "extreme": -0.10,   # already caught by hard skip above
        }.get(snap.volatility_regime, 0.0)
        adjustments.append(("volatility", vol_adj))

        # ── G. Distance to nearest OB/FVG ──────────────────────────────
        d = snap.distance_to_ob
        if d < 0.3:
            dist_adj = +0.05   # price right at the zone — high precision
        elif d < 1.0:
            dist_adj = +0.02
        elif d > 3.0:
            dist_adj = -0.03   # far from any zone — low confluence
        else:
            dist_adj = 0.0
        adjustments.append(("dist_to_ob", dist_adj))

        # ── H. SMC score bonus ──────────────────────────────────────────
        score = snap.smc_buy_score if is_buy else snap.smc_sell_score
        if score >= 5:
            smc_adj = +0.08
        elif score >= 4:
            smc_adj = +0.05
        elif score >= 3:
            smc_adj = +0.02
        elif score <= 1:
            smc_adj = -0.04
        else:
            smc_adj = 0.0
        adjustments.append(("smc_score", smc_adj))

        # ── I. Setup history bonus/penalty ─────────────────────────────
        hist_adj = 0.0
        if best_setups and snap.setup_reason in best_setups:
            hist_adj = +0.07
        elif worst_setups and snap.setup_reason in worst_setups:
            hist_adj = -0.10
        if hist_adj != 0.0:
            adjustments.append(("setup_history", hist_adj))

        # ── J. PatternAnalyzer whitelist bonus ─────────────────────────
        if pattern_analyzer is not None:
            bonus = pattern_analyzer.confidence_bonus(snap)
            if bonus > 0:
                adjustments.append(("pattern_whitelist", +bonus))

        # ── K. EMA alignment bonus ──────────────────────────────────────
        if is_buy and snap.ema_alignment == "bull_stack":
            adjustments.append(("ema_aligned", +0.03))
        elif not is_buy and snap.ema_alignment == "bear_stack":
            adjustments.append(("ema_aligned", +0.03))

        # ── L. Day of week ──────────────────────────────────────────────
        # Friday afternoon (dow=4, h>=16) = low liquidity, avoid
        if snap.day_of_week == 4 and snap.hour >= 16:
            adjustments.append(("friday_close", -0.06))

        # ── M. Multi-SMC confluence ─────────────────────────────────────
        if is_buy:
            confluence = sum([
                snap.bos_up, snap.choch_up, snap.ssl_sweep,
                snap.in_bullish_ob, snap.bullish_fvg, snap.demand_zone,
            ])
        else:
            confluence = sum([
                snap.bos_down, snap.choch_down, snap.bsl_sweep,
                snap.in_bearish_ob, snap.bearish_fvg, snap.supply_zone,
            ])
        if confluence >= 4:
            adjustments.append(("smc_confluence", +0.06))
        elif confluence >= 3:
            adjustments.append(("smc_confluence", +0.03))

        # ══════════════════════════════════════════════════════════════════
        # FINAL PROBABILITY
        # ══════════════════════════════════════════════════════════════════
        total_adj = sum(a for _, a in adjustments)
        final = max(_CLIP_LO, min(_CLIP_HI, base + total_adj))

        result = PredictionResult(
            base_prob=round(base, 4),
            final_prob=round(final, 4),
            adjustments=adjustments,
            should_skip=False,
        )

        log.info(
            "[PredictionEngine] %s %s  base=%.3f adj=%+.3f final=%.3f  %s",
            snap.symbol, side, base, total_adj, final,
            "  ".join(f"{n}:{v:+.3f}" for n, v in adjustments),
        )
        return result
