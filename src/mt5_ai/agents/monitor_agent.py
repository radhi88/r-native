"""
MonitorAgent — مراقب الصفقات المفتوحة.

مراحل تأمين الأرباح (أكثر عدوانية — تعمل بجزء من الثانية):
  0. Micro-BE      — عند ربح ≥ 0.15×ATR  → SL = دخول فوراً (لا خسارة)
  1. Profit-Lock   — عند ربح ≥ 1.0×ATR   → SL يُقفل 0.25×ATR ربح مضمون
  2. Trailing عادي — بعد BE               → SL يتبع بـ 0.4×ATR
  3. Tight         — عند ربح ≥ 1.5×ATR   → SL يتبع بـ 0.22×ATR
  4. Ultra-Tight   — عند ربح ≥ 2.5×ATR   → SL يتبع بـ 0.12×ATR
  5. Lock          — عند ربح ≥ 4.0×ATR   → SL يتبع بـ 0.06×ATR

القاعدة: كلما زاد الربح كلما ضاقت المسافة وارتفع الـ SL أسرع.
يُستدعى الآن من حلقة تيك سريعة (< 1 ثانية) لا من حلقة الـ bar.
"""

import logging
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..human_learner import HumanBehaviorLearner


class MonitorAgent:
    name = "monitor"

    def __init__(
        self,
        symbol: str,
        be_atr_mult: float      = 0.40,  # BE عند 0.40×ATR — يعطي مساحة كافية فوق السبريد
        trail_atr_mult: float   = 0.50,  # trailing — مساحة تنفس أوسع
        tight_trigger: float    = 2.00,  # تفعيل trailing ضيق
        tight_trail_atr: float  = 0.30,  # trailing ضيق
        ultra_trigger: float    = 3.50,  # تفعيل ultra-tight
        ultra_trail_atr: float  = 0.18,  # ultra-tight
        lock_trigger: float     = 5.00,  # تفعيل القفل
        lock_trail_atr: float   = 0.08,  # قفل
        profit_lock_trigger: float = 1.00,  # جديد: قفل ربح جزئي
        profit_lock_min: float     = 0.25,  # جديد: أدنى ربح مُؤمَّن (×ATR)
        event_cb: Callable | None = None,
    ):
        self.symbol             = symbol
        self.be_atr_mult        = be_atr_mult
        self.trail_atr_mult     = trail_atr_mult
        self.tight_trigger      = tight_trigger
        self.tight_trail_atr    = tight_trail_atr
        self.ultra_trigger      = ultra_trigger
        self.ultra_trail_atr    = ultra_trail_atr
        self.lock_trigger       = lock_trigger
        self.lock_trail_atr     = lock_trail_atr
        self.profit_lock_trigger = profit_lock_trigger
        self.profit_lock_min     = profit_lock_min
        self.event_cb           = event_cb
        self.human_learner: "HumanBehaviorLearner | None" = None
        self.log = logging.getLogger(f"friday.agent.{self.name}")

        self._positions: dict[str, dict] = {}

    # ── API العام ─────────────────────────────────────────────────────────────

    def register(self, trade_id: str, pos: dict):
        self._positions[trade_id] = {
            **pos,
            "be_applied":         False,
            "profit_lock_applied": False,
            "max_profit":          0.0,
        }
        self.log.info(
            "Opened %s | %s @ %.5f  SL=%.5f  TP=%.5f  lot=%.2f",
            trade_id, pos["side"], pos["entry"],
            pos.get("sl", 0), pos.get("tp", 0), pos.get("lot", 0.01),
        )

    def update(self, price: float, atr: float) -> list[dict]:
        """
        تحديث كل الصفقات — يُستدعى من حلقة تيك سريعة (< 1 ثانية).
        يُعيد قائمة بالصفقات المغلقة.
        """
        closed = []

        for tid, pos in list(self._positions.items()):
            side   = pos["side"]
            entry  = pos["entry"]
            profit = (price - entry) if side == "BUY" else (entry - price)

            # تحديث أقصى ربح محقق
            if profit > pos["max_profit"]:
                pos["max_profit"] = profit

            sl_ok = True
            if pos.get("sl_update_cooldown", 0) > 0:
                pos["sl_update_cooldown"] -= 1
                sl_ok = False

            if atr > 0 and sl_ok:
                peak = (entry + pos["max_profit"]) if side == "BUY" else (entry - pos["max_profit"])

                # ── خروج مُفضَّل من تعلّم المتداول ─────────────────────────────
                if self.human_learner:
                    pref = self.human_learner.preferred_exit_atr(self.symbol)
                    if pref and profit >= atr * pref and not pos.get("pref_exit_triggered"):
                        pos["pref_exit_triggered"] = True
                        lock = (price - atr * 0.05) if side == "BUY" else (price + atr * 0.05)
                        if (side == "BUY" and lock > pos["sl"]) or (side == "SELL" and lock < pos["sl"]):
                            old_sl = pos["sl"]
                            pos["sl"] = lock
                            self._emit("sl_update", {
                                "trade_id": tid, "sl": lock, "old_sl": old_sl,
                                "reason": "human_pref_exit", "peak": peak,
                            })

                # ── المرحلة 0: Break-Even فوري (0.15×ATR) ───────────────────
                if not pos["be_applied"] and profit >= atr * self.be_atr_mult:
                    be_sl = entry
                    if (side == "BUY" and be_sl > pos["sl"]) or (side == "SELL" and be_sl < pos["sl"]):
                        old_sl = pos["sl"]
                        pos["sl"]         = be_sl
                        pos["be_applied"] = True
                        self.log.info("⚡ BE: %s %s → SL=%.5f (profit=%.4f)",
                                      tid, side, entry, profit)
                        self._emit("sl_update", {
                            "trade_id": tid, "sl": be_sl, "old_sl": old_sl,
                            "reason": "break_even",
                        })

                # ── المرحلة 1: قفل ربح جزئي (1.0×ATR) ──────────────────────
                if pos["be_applied"] and not pos["profit_lock_applied"] \
                        and pos["max_profit"] >= atr * self.profit_lock_trigger:
                    min_profit_sl = (entry + atr * self.profit_lock_min) if side == "BUY" \
                                    else (entry - atr * self.profit_lock_min)
                    if (side == "BUY" and min_profit_sl > pos["sl"]) \
                            or (side == "SELL" and min_profit_sl < pos["sl"]):
                        old_sl = pos["sl"]
                        pos["sl"]                  = min_profit_sl
                        pos["profit_lock_applied"] = True
                        self.log.info("🔒 ProfitLock: %s → SL=%.5f (+%.4f mín)",
                                      tid, min_profit_sl, atr * self.profit_lock_min)
                        self._emit("sl_update", {
                            "trade_id": tid, "sl": min_profit_sl, "old_sl": old_sl,
                            "reason": "profit_lock",
                        })

                # ── Trailing ديناميكي ────────────────────────────────────────
                if pos["be_applied"]:
                    ratio      = pos["max_profit"] / atr
                    trail_mult = self._pick_trail_mult(ratio)
                    trail_dist = trail_mult * atr
                    stage      = self._trail_stage(ratio)

                    if side == "BUY":
                        trail = peak - trail_dist
                        if trail > pos["sl"]:
                            old_sl = pos["sl"]
                            pos["sl"] = trail
                            self._emit("sl_update", {
                                "trade_id": tid, "sl": trail, "old_sl": old_sl,
                                "reason": f"trail_{stage}", "peak": peak,
                                "trail_mult": trail_mult,
                            })
                    else:
                        trail = peak + trail_dist
                        if trail < pos["sl"]:
                            old_sl = pos["sl"]
                            pos["sl"] = trail
                            self._emit("sl_update", {
                                "trade_id": tid, "sl": trail, "old_sl": old_sl,
                                "reason": f"trail_{stage}", "peak": peak,
                                "trail_mult": trail_mult,
                            })

            # ── فحص الخروج ──────────────────────────────────────────────────
            sl, tp  = pos["sl"], pos["tp"]
            reason  = None
            if side == "BUY":
                if sl and price <= sl:  reason = "sl_hit"
                elif tp and price >= tp: reason = "tp_hit"
            else:
                if sl and price >= sl:  reason = "sl_hit"
                elif tp and price <= tp: reason = "tp_hit"

            if reason:
                pnl = (price - entry) if side == "BUY" else (entry - price)
                result = {
                    "trade_id":   tid,
                    "side":       side,
                    "entry":      entry,
                    "exit":       price,
                    "sl":         pos["sl"],
                    "tp":         pos["tp"],
                    "pnl_points": pnl,
                    "won":        pnl > 0,
                    "reason":     reason,
                    "lot":        pos.get("lot", 0.01),
                }
                closed.append(result)
                del self._positions[tid]
                icon = "💰 WIN" if pnl > 0 else "💸 LOSS"
                self.log.info("Closed %s %s %s  entry=%.5f exit=%.5f  pnl=%.4f",
                              icon, tid, side, entry, price, pnl)
                self._emit("trade_closed", result)

        return closed

    def open_positions(self) -> dict:
        return dict(self._positions)

    def count(self) -> int:
        return len(self._positions)

    def has_side(self, side: str) -> bool:
        return any(p["side"] == side for p in self._positions.values())

    # ── اختيار معامل الـ Trailing ─────────────────────────────────────────────

    def _pick_trail_mult(self, ratio: float) -> float:
        if ratio >= self.lock_trigger:   return self.lock_trail_atr
        if ratio >= self.ultra_trigger:  return self.ultra_trail_atr
        if ratio >= self.tight_trigger:  return self.tight_trail_atr
        return self.trail_atr_mult

    def _trail_stage(self, ratio: float) -> str:
        if ratio >= self.lock_trigger:   return "lock"
        if ratio >= self.ultra_trigger:  return "ultra"
        if ratio >= self.tight_trigger:  return "tight"
        return "normal"

    def _emit(self, event: str, data: dict):
        if self.event_cb:
            try:
                self.event_cb(event, data)
            except Exception:
                pass
