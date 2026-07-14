"""
DrawdownGuard — حارس الخسائر المتتالية.

يتصرف فوراً بعد كل خسارة:
  1 خسارة متتالية  → توقف 10 bars
  2 خسارة متتالية → توقف 30 bar + رفع عتبات الدخول
  3+ خسارة        → توقف 60 bar + lot أدنى إجباري

يُعاد الضبط بعد أول ربح.
"""

import logging


class DrawdownGuard:
    name = "drawdown_guard"

    # إعدادات الاستجابة لكل مستوى خسارة
    _RULES = [
        # (حد الخسائر المتتالية, bars توقف, رسالة)
        (1, 10,  "cooldown_1loss"),
        (2, 30,  "cooldown_2loss"),
        (3, 60,  "cooldown_3loss"),
    ]

    def __init__(self, symbol: str, min_lot: float = 0.01):
        self.symbol          = symbol
        self.min_lot         = min_lot
        self._consec_losses  = 0
        self._pause_bars     = 0   # bars remaining in pause
        self._force_min_lot  = False
        self._boost_thresh   = False
        self.log = logging.getLogger(f"friday.agent.{self.name}")

    # ── API ──────────────────────────────────────────────────────────────────────

    def on_trade_closed(self, pnl_points: float):
        """استدعَ بعد كل صفقة مغلقة."""
        if pnl_points > 0:
            # ربح → إعادة الضبط الكامل
            if self._consec_losses > 0:
                self.log.info("[%s] ربح — إعادة ضبط DrawdownGuard", self.symbol)
            self._consec_losses = 0
            self._pause_bars    = 0
            self._force_min_lot = False
            self._boost_thresh  = False
        else:
            # خسارة
            self._consec_losses += 1
            self._apply_rules()

    def tick(self) -> bool:
        """
        استدعَ في بداية كل bar.
        يُعيد True إذا كان الدخول مسموحاً، False إذا كانت هناك فترة توقف.
        """
        if self._pause_bars > 0:
            self._pause_bars -= 1
            remaining = self._pause_bars
            self.log.info(
                "[%s] توقف إجباري — خسائر=%d  bars_remaining=%d",
                self.symbol, self._consec_losses, remaining,
            )
            return False
        return True

    def adjust_lot(self, requested_lot: float) -> float:
        """يُعيد الـlot الفعلي — يُجبر على الحد الأدنى بعد 3+ خسائر."""
        if self._force_min_lot:
            return self.min_lot
        return requested_lot

    def adjust_thresholds(self, buy_thr: float, sell_thr: float) -> tuple[float, float]:
        """يرفع عتبات الدخول مؤقتاً بعد 2+ خسائر متتالية."""
        if self._boost_thresh:
            # رفع عتبة الشراء 5% وخفض عتبة البيع 5%
            return min(buy_thr + 0.05, 0.90), max(sell_thr - 0.05, 0.10)
        return buy_thr, sell_thr

    def status(self) -> dict:
        return {
            "symbol":          self.symbol,
            "consec_losses":   self._consec_losses,
            "pause_bars_left": self._pause_bars,
            "force_min_lot":   self._force_min_lot,
            "boost_thresh":    self._boost_thresh,
        }

    # ── داخلي ────────────────────────────────────────────────────────────────────

    def _apply_rules(self):
        pause, reason = 10, "cooldown_1loss"

        if self._consec_losses >= 3:
            pause, reason        = 60, "cooldown_3loss"
            self._force_min_lot  = True
            self._boost_thresh   = True
        elif self._consec_losses >= 2:
            pause, reason        = 30, "cooldown_2loss"
            self._boost_thresh   = True
            self._force_min_lot  = False
        else:
            self._boost_thresh   = False
            self._force_min_lot  = False

        self._pause_bars = pause
        self.log.warning(
            "[%s] %d خسارة متتالية → %s (%d bars توقف)  force_lot=%s  boost_thr=%s",
            self.symbol, self._consec_losses, reason, pause,
            self._force_min_lot, self._boost_thresh,
        )
