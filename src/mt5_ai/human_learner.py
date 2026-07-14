"""
HumanBehaviorLearner — يتعلم من قرارات المتداول اليدوية ويطبّقها تلقائياً.

ما يُسجَّل:
  manual_close   ← أغلق المتداول الصفقة يدوياً (قبل SL/TP)
  manual_sl_move ← حرّك المتداول الـSL يدوياً

ما يُستخلَص (بعد 3 ملاحظات+):
  preferred_exit_atr   ← عند كم ATR ربح يفضّل الإغلاق
  preferred_trail_atr  ← المسافة المُفضَّلة للـSL من الذروة (ATR)

التطبيق التلقائي:
  MonitorAgent يستدعي get_preferred_exit_atr / get_preferred_trail_atr
  ويطبّق تفضيلات المتداول بدلاً من المعاملات الثابتة.
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

from .config import JOURNAL_DIR

log = logging.getLogger("friday.human_learner")

_LOG_FILE     = JOURNAL_DIR / "human_decisions.csv"
_MIN_SAMPLES  = 3   # الحد الأدنى للملاحظات قبل التطبيق


class HumanBehaviorLearner:

    def __init__(self):
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, list[dict]] = {}  # symbol → rows

    # ── تسجيل القرارات ───────────────────────────────────────────────────────

    def on_manual_close(
        self,
        symbol: str,
        side: str,
        entry: float,
        exit_price: float,
        atr: float,
    ):
        """المتداول أغلق الصفقة يدوياً — سجّل عند أي ربح (بوحدة ATR)."""
        profit_pts = (exit_price - entry) if side == "BUY" else (entry - exit_price)
        profit_atr = profit_pts / atr if atr > 0 else 0.0

        row = {
            "type":       "manual_close",
            "symbol":     symbol,
            "side":       side,
            "profit_atr": round(profit_atr, 4),
            "profit_pts": round(profit_pts, 5),
            "atr":        round(atr, 5),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
        self._append(row)
        self._invalidate(symbol)
        log.info("[%s] manual_close: profit=%.2f×ATR (%.5f pts)", symbol, profit_atr, profit_pts)

    def on_manual_sl_move(
        self,
        symbol: str,
        side: str,
        entry: float,
        current_price: float,
        old_sl: float,
        new_sl: float,
        atr: float,
    ):
        """المتداول حرّك الـSL — سجّل المسافة الجديدة ومستوى الربح عند التحريك."""
        profit_pts = (current_price - entry) if side == "BUY" else (entry - current_price)
        profit_atr = profit_pts / atr if atr > 0 else 0.0

        sl_dist      = abs(current_price - new_sl)
        sl_atr_mult  = sl_dist / atr if atr > 0 else 0.0

        row = {
            "type":        "manual_sl_move",
            "symbol":      symbol,
            "side":        side,
            "profit_atr":  round(profit_atr, 4),
            "sl_atr_mult": round(sl_atr_mult, 4),
            "atr":         round(atr, 5),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        }
        self._append(row)
        self._invalidate(symbol)
        log.info(
            "[%s] manual_sl_move: profit=%.2f×ATR  new_SL_dist=%.2f×ATR",
            symbol, profit_atr, sl_atr_mult,
        )

    # ── استخلاص الأنماط ──────────────────────────────────────────────────────

    def preferred_exit_atr(self, symbol: str) -> float | None:
        """
        عند كم ATR ربح يُفضّل المتداول الإغلاق.
        يُعيد None إذا لا توجد بيانات كافية.
        """
        rows = [r for r in self._load(symbol) if r["type"] == "manual_close"]
        if len(rows) < _MIN_SAMPLES:
            return None
        values = [float(r["profit_atr"]) for r in rows if float(r["profit_atr"]) > 0]
        if not values:
            return None
        avg = mean(values)
        log.debug("[%s] preferred_exit = %.2f×ATR  (n=%d)", symbol, avg, len(values))
        return avg

    def preferred_trail_atr(self, symbol: str) -> float | None:
        """
        المسافة المُفضَّلة للـtrailing SL (بوحدة ATR).
        مستخلصة من تحركات الـSL اليدوية.
        """
        rows = [r for r in self._load(symbol) if r["type"] == "manual_sl_move"]
        if len(rows) < _MIN_SAMPLES:
            return None
        values = [float(r["sl_atr_mult"]) for r in rows if float(r["sl_atr_mult"]) > 0]
        if not values:
            return None
        avg = mean(values)
        log.debug("[%s] preferred_trail = %.2f×ATR  (n=%d)", symbol, avg, len(values))
        return avg

    def summary(self, symbol: str) -> dict:
        rows = self._load(symbol)
        closes = [r for r in rows if r["type"] == "manual_close"]
        moves  = [r for r in rows if r["type"] == "manual_sl_move"]
        return {
            "symbol":          symbol,
            "manual_closes":   len(closes),
            "sl_moves":        len(moves),
            "preferred_exit_atr":  self.preferred_exit_atr(symbol),
            "preferred_trail_atr": self.preferred_trail_atr(symbol),
        }

    # ── داخلي ────────────────────────────────────────────────────────────────

    def _append(self, row: dict):
        exists = _LOG_FILE.exists()
        with open(_LOG_FILE, "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
            if not exists:
                writer.writeheader()
            writer.writerow(row)

    def _load(self, symbol: str) -> list[dict]:
        if symbol in self._cache:
            return self._cache[symbol]
        if not _LOG_FILE.exists():
            return []
        rows = []
        with open(_LOG_FILE, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("symbol") == symbol:
                    rows.append(r)
        self._cache[symbol] = rows
        return rows

    def _invalidate(self, symbol: str):
        self._cache.pop(symbol, None)
