"""
ConfidenceEngine — محرك الثقة الذاتية مع معيار Kelly.

يعمل مع DrawdownGuard:
  DrawdownGuard  → يُوقف ويُعاقب عند الخسارة المتتالية
  ConfidenceEngine → يكافئ عند الفوز ويرفع اللوت بناءً على Kelly Criterion

آلية حجم الصفقة:
  - أقل من 20 صفقة: حجم الأساس (لا بيانات كافية)
  - 20+ صفقة: Kelly Criterion (نصف Kelly للأمان)
    f* = (WR × b - (1-WR)) / b
    حيث b = متوسط الربح / متوسط الخسارة
  - مُقيَّد بـ MAX_LOT دائماً

صفقات إضافية:
  score ≥ 1.4 و WR ≥ 60% (20+ صفقة) → +1 صفقة
  score ≥ 1.7 و WR ≥ 65% (30+ صفقة) → +2 صفقة

النقاط تُحفظ في JSON للاستمرار بين الجلسات.
"""

import json
import logging
import numpy as np
from pathlib import Path

from .config import DATA_DIR, DEFAULT_LOT, MAX_LOT

log = logging.getLogger("friday.confidence")

_STATE_FILE = DATA_DIR / "confidence_scores.json"

WIN_BOOST  = 0.05   # الحد الأقصى للمكافأة في صفقة واحدة
LOSS_HIT   = 0.10   # الحد الأقصى للعقوبة في صفقة واحدة
MAX_SCORE  = 2.0
MIN_SCORE  = 0.2
_ROLLING_WINDOW = 30  # نافذة الأداء المتداولة


class ConfidenceEngine:

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._state = self._load_all()
        if symbol not in self._state:
            self._state[symbol] = {}
        self._ensure_symbol_state()

    # ── نتيجة صفقة ───────────────────────────────────────────────────────────

    def on_win(self, pnl_points: float = 0.0):
        s = self._state[self.symbol]
        s["wins"] += 1
        abs_pnl = abs(pnl_points)

        # تتبع النقاط الفعلية
        s["total_win_pts"] += abs_pnl
        s["rolling_wins"].append(abs_pnl)
        s["rolling_wins"] = s["rolling_wins"][-_ROLLING_WINDOW:]

        # حجم المكافأة متناسب مع P&L مقارنةً بالمتوسط المتداول
        avg_win = np.mean(s["rolling_wins"]) if s["rolling_wins"] else 1.0
        boost = min(WIN_BOOST * abs_pnl / (avg_win + 1e-9), WIN_BOOST * 2.0)
        boost = max(boost, WIN_BOOST * 0.3)  # حد أدنى
        s["score"] = min(s["score"] + boost, MAX_SCORE)

        prev = s.get("streak", 0)
        s["streak"] = max(0, prev) + 1
        self._save()
        log.info(
            "[%s] WIN +%.1f pts → confidence=%.2f  streak=%+d  kelly_mult=%.3f  extra=%d",
            self.symbol, pnl_points, s["score"],
            s["streak"], self.kelly_lot_multiplier, self.extra_positions,
        )

    def on_loss(self, pnl_points: float = 0.0):
        s = self._state[self.symbol]
        s["losses"] += 1
        abs_pnl = abs(pnl_points)

        # تتبع النقاط الفعلية
        s["total_loss_pts"] -= abs_pnl
        s["rolling_losses"].append(abs_pnl)
        s["rolling_losses"] = s["rolling_losses"][-_ROLLING_WINDOW:]

        # حجم العقوبة متناسب مع P&L
        avg_loss = np.mean(s["rolling_losses"]) if s["rolling_losses"] else 1.0
        hit = min(LOSS_HIT * abs_pnl / (avg_loss + 1e-9), LOSS_HIT * 2.0)
        hit = max(hit, LOSS_HIT * 0.3)  # حد أدنى
        s["score"] = max(s["score"] - hit, MIN_SCORE)

        prev = s.get("streak", 0)
        s["streak"] = min(0, prev) - 1
        self._save()
        log.info(
            "[%s] LOSS %.1f pts → confidence=%.2f  streak=%+d  kelly_mult=%.3f  extra=%d",
            self.symbol, pnl_points, s["score"],
            s["streak"], self.kelly_lot_multiplier, self.extra_positions,
        )

    def on_prediction_hit(self, side: str, target_price: float):
        s = self._state[self.symbol]
        s["score"] = min(s["score"] + 0.03, MAX_SCORE)
        s["touch_hits"] += 1
        self._save()
        log.info("[%s] TOUCH HIT %s %.5f → confidence=%.2f", self.symbol, side, target_price, s["score"])

    def on_prediction_miss(self, side: str, target_price: float):
        s = self._state[self.symbol]
        s["score"] = max(s["score"] - 0.01, MIN_SCORE)
        s["touch_misses"] += 1
        self._save()
        log.info("[%s] TOUCH MISS %s %.5f → confidence=%.2f", self.symbol, side, target_price, s["score"])

    # ── Kelly Criterion ───────────────────────────────────────────────────────

    @property
    def kelly_lot_multiplier(self) -> float:
        """
        نصف معيار Kelly للحجم المثالي:
          f* = (WR × b - (1-WR)) / b   حيث b = متوسط الربح / متوسط الخسارة
          نستخدم نصف Kelly (half-Kelly) للأمان.
          مُقيَّد بين 0.8 (حدّ أدنى للأمان) و2.0 (حدّ أقصى).
        """
        s = self._state[self.symbol]
        wins   = s.get("wins", 0)
        losses = s.get("losses", 0)
        n = wins + losses

        if n < 20:
            return 1.0  # غير كافٍ — استخدم الحجم الأساس

        wr = wins / n
        rw = s.get("rolling_wins", [])
        rl = s.get("rolling_losses", [])
        avg_win  = float(np.mean(rw)) if rw else 1.0
        avg_loss = float(np.mean(rl)) if rl else 1.0

        if avg_loss < 1e-9:
            return 1.0

        b = avg_win / avg_loss   # نسبة الربح/الخسارة
        kelly_f = (wr * b - (1.0 - wr)) / b
        kelly_f = max(0.0, min(kelly_f, 0.5))   # [0, 50%]
        half_kelly = kelly_f * 0.5              # نصف Kelly للأمان

        return round(max(0.8, 1.0 + half_kelly), 3)

    # ── قرارات التداول ───────────────────────────────────────────────────────

    @property
    def lot_multiplier(self) -> float:
        """ضارب score-based (يُستخدم عند n < 20)."""
        return round(self._state[self.symbol]["score"], 3)

    def apply_lot(self, base_lot: float) -> float:
        """يُطبّق Kelly Criterion عند توفر بيانات كافية، وإلا يستخدم score."""
        s = self._state[self.symbol]
        n = s.get("wins", 0) + s.get("losses", 0)
        multiplier = self.kelly_lot_multiplier if n >= 20 else self.lot_multiplier
        lot = round(base_lot * multiplier, 2)
        return max(min(lot, MAX_LOT), base_lot)  # never below base_lot, never above MAX_LOT

    @property
    def streak(self) -> int:
        return int(self._state[self.symbol].get("streak", 0))

    @property
    def extra_positions(self) -> int:
        """
        صفقات إضافية بناءً على الأداء المتداول:
          WR ≥ 65% (30+ صفقة) + score ≥ 1.7 → +2
          WR ≥ 60% (20+ صفقة) + score ≥ 1.4 → +1
        """
        s = self._state[self.symbol]
        wins   = s.get("wins", 0)
        losses = s.get("losses", 0)
        total  = wins + losses
        if total < 20:
            return 0

        wr = wins / total
        score = s["score"]

        if total >= 30 and wr >= 0.65 and score >= 1.7:
            return 2
        if total >= 20 and wr >= 0.60 and score >= 1.4:
            return 1
        return 0

    def rolling_performance(self) -> dict:
        """إحصاءات آخر 30 صفقة."""
        s = self._state[self.symbol]
        rw = s.get("rolling_wins", [])
        rl = s.get("rolling_losses", [])
        n  = len(rw) + len(rl)
        avg_win  = float(np.mean(rw)) if rw else 0.0
        avg_loss = float(np.mean(rl)) if rl else 0.0
        wr = len(rw) / n if n > 0 else 0.0
        rr = avg_win / avg_loss if avg_loss > 1e-9 else 0.0
        return {
            "rolling_trades": n,
            "rolling_wr":     round(wr, 3),
            "rolling_avg_win":  round(avg_win, 2),
            "rolling_avg_loss": round(avg_loss, 2),
            "rolling_rr":       round(rr, 3),
            "kelly_mult":       self.kelly_lot_multiplier,
        }

    def status(self) -> dict:
        s = self._state[self.symbol]
        return {
            "symbol":          self.symbol,
            "confidence":      round(s["score"], 3),
            "wins":            s["wins"],
            "losses":          s["losses"],
            "touch_hits":      s.get("touch_hits", 0),
            "touch_misses":    s.get("touch_misses", 0),
            "total_win_pts":   round(s.get("total_win_pts", 0.0), 2),
            "total_loss_pts":  round(s.get("total_loss_pts", 0.0), 2),
            "lot_mult":        self.lot_multiplier,
            "kelly_mult":      self.kelly_lot_multiplier,
            "streak":          self.streak,
            "extra_positions": self.extra_positions,
            "rolling":         self.rolling_performance(),
        }

    # ── حفظ / تحميل ──────────────────────────────────────────────────────────

    def _load_all(self) -> dict:
        if _STATE_FILE.exists():
            try:
                return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save(self):
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _ensure_symbol_state(self):
        s = self._state[self.symbol]
        s.setdefault("score",          1.0)
        s.setdefault("wins",           0)
        s.setdefault("losses",         0)
        s.setdefault("streak",         0)
        s.setdefault("touch_hits",     0)
        s.setdefault("touch_misses",   0)
        s.setdefault("total_win_pts",  0.0)
        s.setdefault("total_loss_pts", 0.0)
        s.setdefault("rolling_wins",   [])
        s.setdefault("rolling_losses", [])
