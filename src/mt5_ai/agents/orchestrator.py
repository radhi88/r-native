"""
FridayOrchestrator — المنسق المركزي لجميع وكلاء FRIDAY.

تسلسل التنفيذ كل bar:
  1. MarketAnalystAgent   → market_context   (تحليل SMC)
  2. LiquidityHunterAgent → liquidity_context (سيولة + اختراقات)
  3. نموذج AI             → probability       (احتمال الحركة)
  4. MonitorAgent.update  → closures          (إغلاق الصفقات المكتملة)
  5. EntryAgent           → entry_signal      (قرار الدخول)
  6. RiskAgent            → risk_signal       (SL / TP)
  7. تنفيذ الصفقة على MT5
  8. MonitorAgent.register → تسجيل الصفقة المفتوحة
  9. LearningEngine       → تسجيل الصفقات المغلقة

لا قيود على السبريد. لا قيود زمنية. لا قيود أخبار.
"""

import logging
from datetime import datetime, timezone
from typing import Callable

import numpy as np

from .market_analyst_agent  import MarketAnalystAgent
from .liquidity_hunter_agent import LiquidityHunterAgent
from .entry_agent           import EntryAgent, EntrySignal
from .risk_agent            import RiskAgent
from .monitor_agent         import MonitorAgent
from .learning_engine       import LearningEngine
from .drawdown_guard        import DrawdownGuard
from .wick_agent            import WickAgent
from ..learning_journal     import LearningJournal
from ..lot_sizer            import compute_lot
from ..market_structure     import add_market_structure
from ..confidence_engine    import ConfidenceEngine
from ..human_learner        import HumanBehaviorLearner
from ..adaptive_trainer     import AdaptiveTrainer
from ..config               import MAX_DEMO_OPEN_ORDERS, DEFAULT_LOT, FEATURE_COLUMNS, SEQ_LEN, MT5_SYMBOL
from ..pivot_engine         import PivotEngine


class FridayOrchestrator:
    def __init__(
        self,
        executor,
        model,
        scaler,
        symbol: str,
        feature_columns: list[str] | None = None,
        seq_len: int | None = None,
        max_positions: int  = MAX_DEMO_OPEN_ORDERS,
        event_cb: Callable | None = None,
        entries_enabled: bool = True,
        pivot_engine: PivotEngine | None = None,
    ):
        self.executor        = executor
        self.model           = model
        self.scaler          = scaler
        self.symbol          = symbol
        self.feature_columns = feature_columns or FEATURE_COLUMNS
        self.seq_len         = seq_len or SEQ_LEN
        self.max_positions   = max_positions
        self.event_cb        = event_cb
        self.entries_enabled = entries_enabled
        self.pivot           = pivot_engine
        self.log = logging.getLogger("friday.orchestrator")

        # ── الوكلاء ───────────────────────────────────────────────────────────
        self.analyst  = MarketAnalystAgent(symbol)
        self.hunter   = LiquidityHunterAgent(symbol)
        self.entry    = EntryAgent(symbol)
        self.risk     = RiskAgent(symbol)
        self.monitor  = MonitorAgent(symbol, event_cb=self._on_event)
        self.learning = LearningEngine()
        self.journal  = LearningJournal()

        self._trade_counter = 0
        self._bar_counter   = 0
        self._last_status: dict = {}
        self._pending_submitted: dict[str, list[tuple[float, int]]] = {"BUY": [], "SELL": []}
        self._pending_touch_predictions: list[dict] = []
        self.guard      = DrawdownGuard(symbol)
        self.confidence = ConfidenceEngine(symbol)
        self.human      = HumanBehaviorLearner()
        self.wick       = WickAgent(symbol)
        self.monitor.human_learner = self.human

        # ── التعلم التكيفي: يُدرَّب النموذج تدريجياً بعد كل صفقة مغلقة ──
        self.adaptive_trainer = AdaptiveTrainer()
        self._last_sequence: np.ndarray | None = None   # تسلسل الميزات عند آخر دخول

    # ── نقطة الدخول الرئيسية ────────────────────────────────────────────────────

    def on_bar(self, raw_df, external_context: dict | None = None) -> dict:
        """
        تشغيل دورة كاملة لـbar واحد.
        raw_df: DataFrame خام من MT5 (OHLCV).
        يُعيد dict بملخص ما جرى في هذا الـbar.
        """
        self._bar_counter += 1
        self._bar_last_side = None   # reset كل bar
        status = {
            "bar": self._bar_counter,
            "time": datetime.now(timezone.utc).isoformat(),
            "action": "HOLD",
        }

        try:
            external_context = external_context or {}
            smart_ctx = external_context.get("smart_pro") or {}
            # ── تثرية البيانات مرة واحدة ───────────────────────────────────────
            enriched = add_market_structure(raw_df)

            # ── 1. تحليل هيكل السوق ────────────────────────────────────────────
            market_ctx = self.analyst.extract_context(enriched)
            price  = market_ctx["price"]
            atr    = market_ctx["atr"]
            touch_stats = self._update_pending_touch_predictions(enriched, price, atr)

            # ── 2. صيد السيولة ──────────────────────────────────────────────────
            liquidity_ctx = self.hunter.analyze(enriched, atr)

            # ── 3. توقع النموذج ────────────────────────────────────────────────
            probability = self._predict(enriched)

            # ── 4. مراقبة الصفقات المفتوحة + الإغلاق ──────────────────────────
            self.entry.tick_cooldowns()
            closed = self.monitor.update(price, atr)
            for trade in closed:
                self._record_closed(trade, market_ctx)

            status.update({
                "price":    round(price, 5),
                "atr":      round(atr, 5),
                "prob":     round(probability, 4),
                "smc_buy":  market_ctx["smc_buy_score"],
                "smc_sell": market_ctx["smc_sell_score"],
                "open_pos": self.monitor.count(),
                "ssl_active": liquidity_ctx["ssl_sweep_active"],
                "bsl_active": liquidity_ctx["bsl_sweep_active"],
                "bos_up":   market_ctx["bos_up"],
                "bos_down": market_ctx["bos_down"],
                "touch_hits": touch_stats["hits"],
                "touch_misses": touch_stats["misses"],
                "cross_bias": external_context.get("cross_market", {}),
            })
            if self.pivot is not None:
                status["pivot"] = self.pivot.apply("HOLD", 0.0, price)
            if smart_ctx.get("active"):
                status["smart_pro"] = {
                    "signal": smart_ctx.get("signal", "HOLD"),
                    "raw_signal": smart_ctx.get("raw_signal", "HOLD"),
                    "power": smart_ctx.get("power", 0),
                    "group_agreement": smart_ctx.get("group_agreement", 0),
                    "trade_allowed": smart_ctx.get("trade_allowed", False),
                    "reason": smart_ctx.get("reason", ""),
                }

            if not self.entries_enabled:
                status["action"] = "HOLD"
                status["reason"] = "entries_disabled_manage_only"
                return status

            if smart_ctx.get("active") and not smart_ctx.get("trade_allowed", False):
                status["action"] = "HOLD"
                status["reason"] = smart_ctx.get("reason", "smart_pro_filter")
                return status

            # ── 5. فحص حد الصفقات + حارس الخسائر ─────────────────────────────
            effective_max = self.max_positions + self.confidence.extra_positions
            if self.monitor.count() >= effective_max:
                status["action"] = "HOLD"
                status["reason"] = f"max_positions={effective_max}"
                return status

            self._apply_learning_thresholds()
            perf_ok, perf_reason, tighten = self._recent_performance_adjustment()
            if not perf_ok:
                status["action"] = "HOLD"
                status["reason"] = perf_reason
                return status

            if not self.guard.tick():
                gs = self.guard.status()
                status["action"] = "HOLD"
                status["reason"] = f"drawdown_pause  losses={gs['consec_losses']}  bars_left={gs['pause_bars_left']}"
                return status

            # ── 6. قرار الدخول ──────────────────────────────────────────────────
            # تعديل العتبات مؤقتاً بعد خسائر متتالية
            buy_thr, sell_thr = self.guard.adjust_thresholds(
                self.entry.buy_prob_threshold, self.entry.sell_prob_threshold
            )
            if tighten:
                buy_thr = min(buy_thr + 0.03, 0.90)
                sell_thr = max(sell_thr - 0.03, 0.10)
                self.entry.min_smc_score = min(self.entry.min_smc_score + 1, 5)
            self.entry.buy_prob_threshold  = buy_thr
            self.entry.sell_prob_threshold = sell_thr

            entry_sig = self.entry.evaluate(market_ctx, liquidity_ctx, probability)
            entry_sig = self._apply_smart_pro_signal(
                entry_sig=entry_sig,
                market_ctx=market_ctx,
                liquidity_ctx=liquidity_ctx,
                probability=probability,
                external_context=external_context,
            )
            entry_sig = self._apply_cross_market_bias(
                entry_sig=entry_sig,
                market_ctx=market_ctx,
                liquidity_ctx=liquidity_ctx,
                probability=probability,
                external_context=external_context,
            )
            if entry_sig is None:
                smart_reject = external_context.get("_smart_reject_reason")
                if smart_reject:
                    status["reason"] = smart_reject
                    return status
                cross_reject = external_context.get("_cross_reject_reason")
                if cross_reject:
                    status["reason"] = cross_reject
                return status

            pivot_result = self._apply_pivot_confirmation(entry_sig, price)
            if pivot_result:
                status["pivot"] = pivot_result
                status["pivot_reason"] = pivot_result.get("pivot_reason")
                status["nearest_pivot"] = pivot_result.get("nearest_pivot")
                status["nearest_pivot_price"] = pivot_result.get("nearest_pivot_price")
                status["pivot_zone"] = pivot_result.get("pivot_zone")
                status["recommended_order"] = pivot_result.get("recommended_order")
                status["recommended_entry_price"] = pivot_result.get("recommended_entry_price")

            # ── فلتر الذيول ─────────────────────────────────────────────────
            if entry_sig.order_type == "MARKET":
                if entry_sig.side == "BUY":
                    wblocked, wreason = self.wick.should_block_buy(market_ctx)
                else:
                    wblocked, wreason = self.wick.should_block_sell(market_ctx)
                if wblocked:
                    status["action"] = "HOLD"
                    status["reason"] = wreason
                    return status

            # منع أي صفقتين بنفس الاتجاه — سواء مفتوحة أو فُتحت في نفس الـbar
            if entry_sig.order_type == "MARKET":
                if self.monitor.has_side(entry_sig.side):
                    status["action"] = "HOLD"
                    status["reason"] = f"already_{entry_sig.side.lower()}"
                    return status
                # منع تكرار الاتجاه في نفس الـbar (الصفقة الثانية بنفس السبب)
                if getattr(self, "_bar_last_side", None) == entry_sig.side:
                    status["action"] = "HOLD"
                    status["reason"] = f"same_bar_duplicate_{entry_sig.side.lower()}"
                    return status
                self._bar_last_side = entry_sig.side

            # ── 7. حساب SL / TP ─────────────────────────────────────────────────
            # للأوامر المعلقة: احسب SL/TP بالنسبة لسعر الأمر (limit_price) لا للسعر الحالي
            if entry_sig.order_type in ("BUY_LIMIT", "SELL_LIMIT") and entry_sig.limit_price:
                from copy import copy as _copy
                sig_for_risk = _copy(entry_sig)
                sig_for_risk.price = entry_sig.limit_price
            else:
                sig_for_risk = entry_sig
            risk_sig = self.risk.compute(sig_for_risk, market_ctx, liquidity_ctx)
            if risk_sig is None:
                self.log.warning("RiskAgent rejected signal: %s", entry_sig.reason)
                return status

            # ── 8. تنفيذ الصفقة ─────────────────────────────────────────────────
            # منع تكرار الأوامر المعلقة: أمر واحد لكل اتجاه حتى يتغير المستوى
            order_type = getattr(entry_sig, "order_type", "MARKET")
            if order_type in ("BUY_LIMIT", "SELL_LIMIT"):
                lp = entry_sig.limit_price or 0.0
                # تنظيف الإدخالات القديمة (> 50 bar)
                recent_list = [
                    (px, bar) for px, bar in self._pending_submitted[entry_sig.side]
                    if (self._bar_counter - bar) < 50
                ]
                # رفض إذا نفس المستوى (±0.5) سُجِّل مؤخراً
                if any(abs(px - lp) < 0.5 for px, bar in recent_list):
                    self._pending_submitted[entry_sig.side] = recent_list
                    status["action"] = "HOLD"
                    status["reason"] = f"pending_duplicate_{entry_sig.side}"
                    return status
                recent_list.append((lp, self._bar_counter))
                self._pending_submitted[entry_sig.side] = recent_list

            lot    = self._compute_lot()
            result = self._execute(risk_sig, lot)
            if order_type in ("BUY_LIMIT", "SELL_LIMIT") and result.get("sent", False):
                self._remember_pending_touch_prediction(entry_sig, atr)

            self._trade_counter += 1
            trade_id = f"T{self._trade_counter:04d}"

            # استخراج تذكرة MT5 لمتابعة التدخلات اليدوية لاحقاً
            mt5_res = result.get("result") or {}
            ticket  = mt5_res.get("order") or mt5_res.get("deal")

            # الأوامر المعلقة لا تُسجَّل في Monitor — تُتابع من MT5 مباشرة
            if order_type == "MARKET":
                self.monitor.register(trade_id, {
                    "side":   risk_sig.side,
                    "entry":  risk_sig.price,
                    "sl":     risk_sig.sl,
                    "tp":     risk_sig.tp,
                    "lot":    lot,
                    "ticket": ticket,
                })
                # سجّل تسلسل الميزات لاستخدامه في التعلم التكيفي عند إغلاق الصفقة
                if self._last_sequence is not None:
                    self.adaptive_trainer.record_entry(
                        self.symbol,
                        risk_sig.side.lower(),
                        self._last_sequence,
                    )

            status.update({
                "action":     risk_sig.side if order_type == "MARKET" else order_type,
                "trade_id":   trade_id,
                "sl":         round(risk_sig.sl, 5),
                "tp":         round(risk_sig.tp, 5),
                "lot":        lot,
                "rr":         round(risk_sig.rr_ratio, 2),
                "reason":     risk_sig.reason,
                "sent":       result.get("sent", False),
                "order_type": order_type,
                "limit_price": getattr(entry_sig, "limit_price", None),
                "confidence":  round(float(getattr(entry_sig, "confidence", 0.0)), 4),
            })

            self._emit("trade_open", {
                **status,
                "symbol": self.symbol,
            })

        except Exception as exc:
            self.log.error("Orchestrator error on bar %d: %s", self._bar_counter, exc, exc_info=True)
            status["error"] = str(exc)
        finally:
            self._last_status = dict(status)

        return status

    # ── توقع النموذج ────────────────────────────────────────────────────────────

    def _predict(self, enriched) -> float:
        try:
            available = [c for c in self.feature_columns if c in enriched.columns]
            seq = enriched[available].tail(self.seq_len).to_numpy(dtype=np.float32)
            if len(seq) < self.seq_len:
                self._last_sequence = None
                return 0.5
            seq_scaled = self.scaler.transform(seq)
            # احفظ التسلسل المُحوَّل للاستخدام في AdaptiveTrainer
            self._last_sequence = seq_scaled.copy()
            inp = seq_scaled.reshape(1, self.seq_len, len(available))
            prob = float(np.asarray(self.model.predict(inp, verbose=0)).squeeze())
            return max(0.0, min(1.0, prob))
        except Exception as exc:
            self.log.warning("Model prediction failed: %s", exc)
            self._last_sequence = None
            return 0.5

    def _apply_pivot_confirmation(self, entry_sig: EntrySignal, price: float) -> dict:
        """Apply daily pivot confluence without creating or reversing signals."""
        if self.pivot is None:
            return {}

        pivot_result = self.pivot.apply(
            signal=entry_sig.side,
            confidence=float(entry_sig.confidence),
            price=float(price),
        )
        entry_sig.confidence = float(pivot_result.get("confidence", entry_sig.confidence))
        entry_sig.meta["pivot"] = pivot_result

        pivot_reason = str(pivot_result.get("pivot_reason") or "")
        if pivot_reason not in {
            "",
            "no_pivot_boost",
            "no_existing_trade_signal",
            "pivot_levels_unavailable",
            "pivot_disabled",
        }:
            entry_sig.reason = f"{entry_sig.reason}+{pivot_reason}"

        return pivot_result

    # ── التنفيذ ──────────────────────────────────────────────────────────────────

    def _execute(self, sig, lot: float) -> dict:
        try:
            if getattr(sig, "order_type", "MARKET") in ("BUY_LIMIT", "SELL_LIMIT"):
                return self.executor.execute_pending(
                    symbol=self.symbol,
                    side=sig.side,
                    limit_price=sig.limit_price,
                    lot=lot,
                    sl=sig.sl,
                    tp=sig.tp,
                )
            return self.executor.execute(
                symbol=self.symbol,
                side=sig.side,
                price=sig.price,
                lot=lot,
                sl=sig.sl,
                tp=sig.tp,
            )
        except Exception as exc:
            self.log.error("Execution failed: %s", exc)
            return {"sent": False, "error": str(exc)}

    def _compute_lot(self) -> float:
        try:
            rows = self.learning._load_rows(
                agent="smc", symbol=self.symbol, lookback=200
            )
            lot = compute_lot(rows).lot
        except Exception:
            lot = DEFAULT_LOT
        return self.guard.adjust_lot(lot)

    def _apply_learning_thresholds(self):
        """Apply persisted per-symbol thresholds AND risk params before evaluating a new entry."""
        thresholds = self.learning.thresholds("smc", self.symbol)
        self.entry.buy_prob_threshold = float(
            thresholds.get("buy_threshold", self.entry.buy_prob_threshold)
        )
        self.entry.sell_prob_threshold = float(
            thresholds.get("sell_threshold", self.entry.sell_prob_threshold)
        )
        self.entry.min_smc_score = int(
            thresholds.get("min_smc_score", self.entry.min_smc_score)
        )
        # تطبيق معاملات المخاطرة المكتسبة من التعلم على RiskAgent
        rp = self.learning.risk_params("smc", self.symbol)
        self.risk.atr_sl_mult = float(rp.get("atr_sl_mult", self.risk.atr_sl_mult))
        self.risk.min_rr      = float(rp.get("min_rr",      self.risk.min_rr))

    def _recent_performance_adjustment(self) -> tuple[bool, str, bool]:
        """
        Stop or tighten symbols with weak recent history.

        This uses win rate and profit factor, not raw points, because point scales
        differ wildly between FX, metals, oil, and crypto symbols.
        """
        perf = self.learning.summary("smc", self.symbol, lookback=30)
        trades = int(perf.get("trades") or 0)
        if trades < 8:
            return True, "", False

        win_rate = float(perf.get("win_rate") or 0.0)
        profit_factor = float(perf.get("profit_factor") or 0.0)

        if trades >= 15 and (win_rate < 0.35 or profit_factor < 0.70):
            if self.symbol == MT5_SYMBOL:
                return True, "", True
            reason = (
                f"symbol_paused_recent_perf trades={trades} "
                f"wr={win_rate:.0%} pf={profit_factor:.2f}"
            )
            return False, reason, False

        tighten = win_rate < 0.45 or profit_factor < 1.00
        return True, "", tighten

    def _apply_cross_market_bias(
        self,
        entry_sig: EntrySignal | None,
        market_ctx: dict,
        liquidity_ctx: dict,
        probability: float,
        external_context: dict,
    ) -> EntrySignal | None:
        """Use cross-market context as a guarded oil/energy bias."""
        bias = external_context.get("cross_market") or {}
        if not bias.get("active"):
            return entry_sig

        side = str(bias.get("side") or "").upper()
        if side not in ("BUY", "SELL"):
            return entry_sig

        strength = float(bias.get("strength") or 0.0)
        if entry_sig is not None:
            if entry_sig.side != side and strength >= 0.45:
                external_context["_cross_reject_reason"] = (
                    f"cross_market_conflict {bias.get('reason', '')}"
                )
                return None

            entry_sig.confidence = min(1.0, entry_sig.confidence + 0.10 * strength)
            entry_sig.reason = f"{entry_sig.reason}+{bias.get('reason', 'cross_market')}"
            entry_sig.meta["cross_market"] = bias
            return entry_sig

        score_key = "smc_buy_score" if side == "BUY" else "smc_sell_score"
        smc_score = int(market_ctx.get(score_key, 0))
        min_score = max(1, int(self.entry.min_smc_score) - 1)
        structure_ok = (
            market_ctx.get("bos_up") if side == "BUY" else market_ctx.get("bos_down")
        ) or (
            liquidity_ctx.get("ssl_sweep_active") if side == "BUY"
            else liquidity_ctx.get("bsl_sweep_active")
        ) or smc_score >= int(self.entry.min_smc_score)

        if strength < 0.35 or smc_score < min_score or not structure_ok:
            external_context["_cross_reject_reason"] = (
                f"cross_market_wait smc={smc_score} strength={strength:.2f}"
            )
            return None

        conf_base = min(1.0, 0.35 + strength * 0.45)
        prob_for_side = probability if side == "BUY" else 1.0 - probability
        return EntrySignal(
            symbol=self.symbol,
            side=side,
            price=float(market_ctx["price"]),
            atr=float(market_ctx["atr"]),
            confidence=min(1.0, conf_base + max(prob_for_side - 0.5, 0.0)),
            probability=probability,
            smc_score=smc_score,
            reason=str(bias.get("reason", "cross_market_bias")),
            meta={"mctx": market_ctx, "lctx": liquidity_ctx, "cross_market": bias},
        )

    def _apply_smart_pro_signal(
        self,
        entry_sig: EntrySignal | None,
        market_ctx: dict,
        liquidity_ctx: dict,
        probability: float,
        external_context: dict,
    ) -> EntrySignal | None:
        """Use Smart Algorithm Pro as the multi-timeframe gate/advisor."""
        smart = external_context.get("smart_pro") or {}
        if not smart.get("active"):
            return entry_sig

        if not smart.get("trade_allowed", False):
            external_context["_smart_reject_reason"] = smart.get("reason", "smart_pro_filter")
            return None

        side = str(smart.get("signal") or "").upper()
        if side not in ("BUY", "SELL"):
            external_context["_smart_reject_reason"] = smart.get("reason", "smart_pro_hold")
            return None

        power = float(smart.get("power") or 0.0)
        group_agreement = int(smart.get("group_agreement") or 0)

        if entry_sig is not None:
            if entry_sig.side != side and power >= 62:
                external_context["_smart_reject_reason"] = (
                    f"smart_pro_conflict signal={side} power={power:.1f}"
                )
                return None
            if entry_sig.side == side:
                entry_sig.confidence = min(1.0, entry_sig.confidence + min(0.20, power / 500.0))
                entry_sig.reason = f"{entry_sig.reason}+smart_pro_{int(power)}"
                entry_sig.meta["smart_pro"] = {
                    "signal": side,
                    "power": power,
                    "groups": group_agreement,
                }
            return entry_sig

        # Smart-only entry is allowed only when the 6-timeframe matrix is strong
        # and at least two confluence groups agree.
        if power < 78.0 or group_agreement < 2:
            external_context["_smart_reject_reason"] = smart.get("reason", "smart_pro_wait")
            return None

        score_key = "smc_buy_score" if side == "BUY" else "smc_sell_score"
        return EntrySignal(
            symbol=self.symbol,
            side=side,
            price=float(market_ctx["price"]),
            atr=float(market_ctx["atr"]),
            confidence=min(1.0, power / 100.0),
            probability=probability,
            smc_score=int(market_ctx.get(score_key, 0)),
            reason=f"smart_pro_power_{int(power)}",
            meta={"mctx": market_ctx, "lctx": liquidity_ctx, "smart_pro": smart},
        )

    def _remember_pending_touch_prediction(self, entry_sig, atr: float):
        target = float(entry_sig.limit_price or 0.0)
        if target <= 0:
            return

        tolerance = self._touch_tolerance(target, atr)
        if any(
            p["side"] == entry_sig.side
            and abs(float(p["target"]) - target) <= max(float(p["tolerance"]), tolerance)
            for p in self._pending_touch_predictions
        ):
            return

        self._pending_touch_predictions.append({
            "id": f"P{self._bar_counter:06d}-{len(self._pending_touch_predictions) + 1}",
            "side": entry_sig.side,
            "target": target,
            "created_bar": self._bar_counter,
            "expires_bar": self._bar_counter + 50,
            "tolerance": tolerance,
            "reason": entry_sig.reason,
        })

    def _update_pending_touch_predictions(self, enriched, price: float, atr: float) -> dict:
        hits = misses = 0
        if not self._pending_touch_predictions:
            return {"hits": hits, "misses": misses}

        latest = enriched.iloc[-1]
        high = float(latest.get("high", price))
        low = float(latest.get("low", price))

        remaining = []
        for pred in self._pending_touch_predictions:
            target = float(pred["target"])
            tolerance = max(float(pred.get("tolerance", 0.0)), self._touch_tolerance(target, atr))
            touched = (low - tolerance) <= target <= (high + tolerance)

            if touched:
                hits += 1
                self.confidence.on_prediction_hit(pred["side"], target)
                self._emit("prediction_hit", {
                    "symbol": self.symbol,
                    "side": pred["side"],
                    "target": target,
                    "price": price,
                    "low": low,
                    "high": high,
                    "reason": pred.get("reason", ""),
                })
                continue

            if self._bar_counter > int(pred["expires_bar"]):
                misses += 1
                self.confidence.on_prediction_miss(pred["side"], target)
                self._emit("prediction_miss", {
                    "symbol": self.symbol,
                    "side": pred["side"],
                    "target": target,
                    "price": price,
                    "low": low,
                    "high": high,
                    "reason": pred.get("reason", ""),
                })
                continue

            remaining.append(pred)

        self._pending_touch_predictions = remaining
        return {"hits": hits, "misses": misses}

    @staticmethod
    def _touch_tolerance(target: float, atr: float) -> float:
        return max(abs(float(atr)) * 0.03, abs(float(target)) * 0.00001, 1e-9)

    # ── تسجيل الصفقة المغلقة ────────────────────────────────────────────────────

    def _record_closed(self, trade: dict, market_ctx: dict):
        try:
            pnl    = trade.get("pnl_points", 0)
            reason = trade.get("reason", "auto")
            won    = pnl > 0

            # 1. حارس الخسائر + ثقة ذاتية
            self.guard.on_trade_closed(pnl)
            if won:
                self.confidence.on_win(pnl)
            else:
                self.confidence.on_loss(pnl)

            # 2. نمط الذيل
            uw = market_ctx.get("last_upper_wick_ratio", 0)
            lw = market_ctx.get("last_lower_wick_ratio", 0)
            if trade.get("side") == "BUY" and lw > 0.1:
                self.wick.record("BUY", lw, "entry_zone", blocked=False, won=won)
            elif trade.get("side") == "SELL" and uw > 0.1:
                self.wick.record("SELL", uw, "entry_zone", blocked=False, won=won)

            # 3. سجّل في LearningEngine (مع setup_reason للتتبع الدقيق)
            self.learning.record(
                agent="smc",
                symbol=self.symbol,
                side=trade["side"],
                entry=trade["entry"],
                exit_price=trade["exit"],
                points=pnl,
                setup_reason=reason,
            )

            # 4. يوميات التعلم
            self.journal.remember_trade(
                strategy=f"smc_{self.symbol}",
                side=trade["side"],
                probability=0.5,
                smc_buy_score=market_ctx.get("smc_buy_score", 0),
                smc_sell_score=market_ctx.get("smc_sell_score", 0),
                entry_price=trade["entry"],
                exit_price=trade["exit"],
                points=pnl,
                signal_type=reason,
            )

            # 5. أخبر EntryAgent بنتيجة الإعداد (بما فيها النقاط)
            self.entry.record_outcome(reason, won, points=float(pnl))

            # 6. التعلم التكيفي: سجّل نتيجة الصفقة لإعادة التدريب التدريجي
            self.adaptive_trainer.record_exit(
                self.symbol,
                trade["side"].lower(),
                float(pnl),
            )

            # 7. بعد كل 20 صفقة: حدّث عتبات الإعداد في EntryAgent
            summary = self.learning.summary("smc", self.symbol)
            if int(summary.get("trades", 0)) % 20 == 0 and int(summary.get("trades", 0)) > 0:
                self._refresh_entry_thresholds()

        except Exception as exc:
            self.log.warning("Failed to record closed trade: %s", exc)

    def _refresh_entry_thresholds(self):
        """يُحدِّث عتبات الإعدادات في EntryAgent بناءً على أداء كل إعداد المُتعلَّم."""
        try:
            setup_perf = self.entry.setup_performance_summary()
            new_thresholds = {}

            for setup_reason, stats in setup_perf.items():
                if stats["trades"] < 10:
                    continue
                wr = stats["wr"]
                # إعدادات ممتازة (WR > 0.65): خفّف عتبة الثقة العالية
                if wr > 0.65 and "high_conf" in setup_reason:
                    current = self.entry._setup_thresholds.get("high_conf_buy", 0.72)
                    new_thresholds["high_conf_buy"]  = max(0.60, current - 0.01)
                    new_thresholds["high_conf_sell"] = min(0.40, self.entry._setup_thresholds.get("high_conf_sell", 0.28) + 0.01)
                # إعدادات ضعيفة (WR < 0.45): شدّد عتبة الاستمرار
                elif wr < 0.45 and "continuation" in setup_reason:
                    current = self.entry._setup_thresholds.get("bos_continuation_buy", 0.58)
                    new_thresholds["bos_continuation_buy"]  = min(0.75, current + 0.01)
                    new_thresholds["bos_continuation_sell"] = max(0.25, self.entry._setup_thresholds.get("bos_continuation_sell", 0.42) - 0.01)

            if new_thresholds:
                self.entry.update_setup_thresholds(new_thresholds)
                self.log.info("[%s] Updated entry setup thresholds: %s", self.symbol, new_thresholds)
        except Exception as exc:
            self.log.warning("Failed to refresh entry thresholds: %s", exc)

    # ── الحدث ────────────────────────────────────────────────────────────────────

    def _on_event(self, event: str, data: dict):
        if event == "sl_update":
            self._push_sl_update_to_executor(data)
        self._emit(event, data)

    def _emit(self, event: str, data: dict):
        if self.event_cb:
            try:
                self.event_cb(event, data)
            except Exception:
                pass

    def _push_sl_update_to_executor(self, data: dict):
        """Forward MonitorAgent trailing/BE SL updates to the demo executor."""
        modify = getattr(self.executor, "modify_position", None)
        if not callable(modify):
            return

        trade_id = data.get("trade_id")
        pos = self.monitor._positions.get(trade_id)
        if not pos:
            return

        ticket = pos.get("ticket")
        if not ticket:
            return

        new_sl = data.get("sl")
        old_sl = pos.get("_prev_sl", pos.get("sl"))

        # تجاهل تحديثات SL صغيرة جداً (noise من التقريب)
        if old_sl and new_sl and abs(float(new_sl) - float(old_sl)) < 1e-5:
            return

        pos["_prev_sl"] = old_sl   # احفظ القيمة السابقة قبل التغيير

        try:
            result = modify(
                symbol=self.symbol,
                ticket=ticket,
                sl=new_sl,
                tp=pos.get("tp"),
            )
            sent = bool(result.get("sent"))
            data["modify_sent"] = sent
            if not sent:
                retcode = result.get("retcode", 0)
                # retcode 10016 = Invalid stops — رجّع SL السابق وأضف cooldown
                pos["sl"] = old_sl
                data["sl"] = old_sl
                pos["sl_update_cooldown"] = 5
                self.log.warning(
                    "⚠️  %s  SL update rejected by MT5  kept SL=%.5f  [%s]  retcode=%s",
                    self.symbol, float(old_sl or 0), trade_id, retcode,
                )
        except Exception as exc:
            pos["sl"] = old_sl
            data["sl"] = old_sl
            pos["sl_update_cooldown"] = 5
            self.log.warning("Failed to push SL update to executor: %s", exc)

    # ── حالة النظام ──────────────────────────────────────────────────────────────

    def status(self) -> dict:
        base = {
            "symbol":           self.symbol,
            "bars_processed":   self._bar_counter,
            "trades_opened":    self._trade_counter,
            "open_positions":   self.monitor.open_positions(),
            "learning":         self.learning.summary("smc", self.symbol),
            "confidence":       self.confidence.status(),
            "adaptive_trainer": self.adaptive_trainer.status(),
            "setup_perf":       self.entry.setup_performance_summary(),
            "setup_thresholds": self.entry.get_setup_threshold_report(),
        }
        base.update(self._last_status)
        base["open_positions"] = self.monitor.open_positions()
        return base
