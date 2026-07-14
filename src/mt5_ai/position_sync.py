"""
PositionSyncer — يقارن الصفقات المفتوحة في ذاكرة النظام بالصفقات الحقيقية في MT5.

يكتشف:
  manual_close   ← الصفقة اختفت من MT5 بدون SL/TP → المتداول أغلقها يدوياً
  manual_sl_move ← الـSL تغيّر في MT5 لكن لم نغيّره نحن → المتداول حرّكه

عند الاكتشاف:
  1. يُسجَّل في HumanBehaviorLearner
  2. يُرسل event لـOrchestrator (لتحديث الذاكرة)
  3. ConfidenceEngine و DrawdownGuard يُحدَّثان
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agents.orchestrator import FridayOrchestrator
    from .mt5_gateway import MT5Gateway
    from .human_learner import HumanBehaviorLearner

log = logging.getLogger("friday.position_sync")

# فارق السعر الأدنى لاعتبار الـSL تغيّر فعلاً (تجنّب noise من التقريب)
SL_CHANGE_THRESHOLD = 0.0001


class PositionSyncer:

    def __init__(
        self,
        gw: "MT5Gateway",
        human_learner: "HumanBehaviorLearner",
    ):
        self.gw     = gw
        self.learner = human_learner

    def sync(self, orch: "FridayOrchestrator", current_price: float, atr: float) -> list[dict]:
        """
        فحص لمرة واحدة لصفقات orchestrator واحد.
        يُعيد قائمة الأحداث المكتشفة.
        """
        events: list[dict] = []

        try:
            mt5_live = {p["ticket"]: p for p in self.gw.get_open_positions()}
        except Exception as exc:
            log.warning("PositionSyncer: failed to fetch MT5 positions: %s", exc)
            return events

        for tid, pos in list(orch.monitor._positions.items()):
            ticket = pos.get("ticket")
            if not ticket:
                continue   # صفقة بدون تذكرة (لم تُرسَل لـMT5 أو فشلت)

            mt5_pos = mt5_live.get(int(ticket))

            if mt5_pos is None:
                # ── إغلاق يدوي ─────────────────────────────────────────────
                event = self._handle_manual_close(orch, tid, pos, current_price, atr)
                events.append(event)
                del orch.monitor._positions[tid]

            else:
                if float(mt5_pos.get("sl") or 0.0) <= 0 and float(pos.get("sl") or 0.0) > 0:
                    event = self._handle_missing_broker_sl(orch, tid, pos, mt5_pos)
                    events.append(event)
                    continue

                sl_delta = abs(mt5_pos["sl"] - pos["sl"])
                # MT5 may round accepted SL values to symbol precision. Treat
                # tiny ATR-relative differences as broker rounding, not manual
                # intervention.
                sl_threshold = max(SL_CHANGE_THRESHOLD, abs(float(atr)) * 0.05)
                if sl_delta <= sl_threshold:
                    pos["sl"] = mt5_pos["sl"]
                    continue

                # ── تحريك SL يدوي ──────────────────────────────────────────
                event = self._handle_manual_sl_move(
                    orch, tid, pos, mt5_pos, current_price, atr
                )
                events.append(event)
                pos["sl"] = mt5_pos["sl"]  # تحديث الذاكرة

        return events

    def import_open_positions(self, orch: "FridayOrchestrator") -> int:
        """
        Import existing MT5 demo positions into the orchestrator monitor.

        This prevents a restarted monitor from opening another trade on a symbol
        that already has an active MT5 position.
        """
        try:
            mt5_positions = self.gw.get_open_positions()
        except Exception as exc:
            log.warning("PositionSyncer: failed to import MT5 positions: %s", exc)
            return 0

        imported = 0
        existing_tickets = {
            int(pos.get("ticket"))
            for pos in orch.monitor._positions.values()
            if pos.get("ticket")
        }

        for pos in mt5_positions:
            if pos.get("symbol") != orch.symbol:
                continue
            ticket = int(pos["ticket"])
            if ticket in existing_tickets:
                continue

            entry = float(pos["entry"])
            tp    = float(pos.get("tp") or 0.0)
            sl    = float(pos.get("sl") or 0.0)
            side  = pos["side"]
            broker_sl_missing = sl == 0.0

            # تحقق من صحة TP/SL قبل الاستيراد
            if tp != 0.0:
                if side == "BUY" and tp <= entry:
                    log.warning(
                        "import_open_positions: تجاهل MT5%d (%s BUY) — TP=%.5f ≤ entry=%.5f",
                        ticket, orch.symbol, tp, entry,
                    )
                    continue
                if side == "SELL" and tp >= entry:
                    log.warning(
                        "import_open_positions: تجاهل MT5%d (%s SELL) — TP=%.5f ≥ entry=%.5f",
                        ticket, orch.symbol, tp, entry,
                    )
                    continue

            if sl == 0.0 and tp != 0.0:
                reward = abs(tp - entry)
                risk = reward / 1.2 if reward > 0 else 0.0
                if risk > 0:
                    sl = entry - risk if side == "BUY" else entry + risk
                    try:
                        snap = self.gw.symbol_snapshot(orch.symbol)
                        point = float(snap.get("point") or 0.00001)
                        spread = float(snap.get("spread") or 10)
                        guard = max(point * max(spread, 10.0), risk * 0.25, 1e-9)
                        if side == "BUY":
                            current = float(snap.get("bid") or entry)
                            if sl >= current:
                                sl = current - guard
                        else:
                            current = float(snap.get("ask") or entry)
                            if sl <= current:
                                sl = current + guard
                    except Exception:
                        pass
                    log.warning(
                        "import_open_positions: MT5%d (%s %s) بلا SL — emergency SL=%.5f",
                        ticket, orch.symbol, side, sl,
                    )

            if broker_sl_missing and sl > 0:
                try:
                    result = self.gw.modify_demo_position_sl_tp(
                        ticket=ticket,
                        symbol=orch.symbol,
                        sl=sl,
                        tp=tp,
                    )
                    if result.get("sent"):
                        req_sl = (result.get("request") or {}).get("sl")
                        if req_sl:
                            sl = float(req_sl)
                        log.warning(
                            "import_open_positions: restored broker SL MT5%d (%s) → %.5f",
                            ticket, orch.symbol, sl,
                        )
                    else:
                        log.warning(
                            "import_open_positions: failed to restore broker SL MT5%d (%s) retcode=%s",
                            ticket, orch.symbol, result.get("retcode"),
                        )
                except Exception as exc:
                    log.warning(
                        "import_open_positions: restore broker SL error MT5%d (%s): %s",
                        ticket, orch.symbol, exc,
                    )

            trade_id = f"MT5{ticket}"
            orch.monitor.register(trade_id, {
                "side": side,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "lot": pos.get("volume", 0.01),
                "ticket": ticket,
            })
            existing_tickets.add(ticket)
            imported += 1

        return imported

    # ── معالجة الأحداث ───────────────────────────────────────────────────────

    def _handle_manual_close(
        self, orch, tid: str, pos: dict, price: float, atr: float
    ) -> dict:
        side  = pos["side"]
        entry = pos["entry"]
        sym   = orch.symbol

        profit_pts = (price - entry) if side == "BUY" else (entry - price)
        won = profit_pts > 0

        # سجّل في HumanBehaviorLearner
        self.learner.on_manual_close(
            symbol=sym, side=side,
            entry=entry, exit_price=price, atr=atr,
        )

        # حدّث ConfidenceEngine و DrawdownGuard
        orch.confidence.on_win(profit_pts) if won else orch.confidence.on_loss(profit_pts)
        orch.guard.on_trade_closed(profit_pts)

        # سجّل في LearningEngine
        try:
            orch.learning.record(
                agent="smc", symbol=sym, side=side,
                entry=entry, exit_price=price, points=profit_pts,
            )
        except Exception:
            pass

        # أطلق event
        event_data = {
            "trade_id":   tid,
            "side":       side,
            "entry":      entry,
            "exit":       price,
            "pnl_points": profit_pts,
            "won":        won,
            "reason":     "manual_close",
            "lot":        pos.get("lot", 0.01),
        }
        orch._emit("trade_closed", event_data)

        log.info(
            "[%s] MANUAL CLOSE %s %s  entry=%.5f exit=%.5f  pnl=%.5f  [%s]",
            sym, tid, side, entry, price, profit_pts,
            "WIN" if won else "LOSS",
        )
        return {"type": "manual_close", **event_data, "symbol": sym}

    def _handle_missing_broker_sl(self, orch, tid: str, pos: dict, mt5_pos: dict) -> dict:
        """MT5 reports SL=0 while the monitor still has a protective SL.

        Do not learn this as a human preference and do not overwrite the
        monitor's SL with zero. On demo execution, try to restore the broker SL.
        """
        sym = orch.symbol
        wanted_sl = float(pos.get("sl") or 0.0)
        ticket = int(pos.get("ticket") or mt5_pos.get("ticket") or 0)
        result = {"sent": False, "reason": "no_demo_modify"}

        modify = getattr(getattr(orch, "executor", None), "modify_position", None)
        if callable(modify) and ticket and wanted_sl > 0:
            try:
                result = modify(
                    symbol=sym,
                    ticket=ticket,
                    sl=wanted_sl,
                    tp=pos.get("tp"),
                )
            except Exception as exc:
                result = {"sent": False, "reason": str(exc)}

        if result.get("sent"):
            log.warning(
                "[%s] RESTORED MISSING BROKER SL %s  MT5_SL=0 → %.5f",
                sym, tid, wanted_sl,
            )
        else:
            log.warning(
                "[%s] BROKER SL MISSING %s  kept internal SL=%.5f  restore_failed=%s",
                sym, tid, wanted_sl, result.get("reason") or result.get("retcode"),
            )

        return {
            "type": "missing_broker_sl",
            "trade_id": tid,
            "symbol": sym,
            "side": pos.get("side"),
            "ticket": ticket,
            "wanted_sl": wanted_sl,
            "restore_sent": bool(result.get("sent")),
            "retcode": result.get("retcode"),
        }

    def _handle_manual_sl_move(
        self, orch, tid: str, pos: dict, mt5_pos: dict,
        current_price: float, atr: float
    ) -> dict:
        side   = pos["side"]
        entry  = pos["entry"]
        old_sl = pos["sl"]
        new_sl = mt5_pos["sl"]
        sym    = orch.symbol

        self.learner.on_manual_sl_move(
            symbol=sym, side=side,
            entry=entry, current_price=current_price,
            old_sl=old_sl, new_sl=new_sl, atr=atr,
        )

        log.info(
            "[%s] MANUAL SL MOVE %s %s  %.5f → %.5f  (price=%.5f)",
            sym, tid, side, old_sl, new_sl, current_price,
        )
        return {
            "type":    "manual_sl_move",
            "trade_id": tid,
            "symbol":  sym,
            "side":    side,
            "old_sl":  old_sl,
            "new_sl":  new_sl,
        }
