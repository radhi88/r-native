"""
WickAgent — فلتر ذيول الشمعات.

يمنع:
  BUY  إذا كان هناك ذيل علوي كبير عند منطقة مقاومة (رفض من الأعلى)
  SELL إذا كان هناك ذيل سفلي كبير عند منطقة دعم   (دعم من الأسفل)

يتعلم:
  يسجل كل نمط ذيل + نتيجة الصفقة → يعدّل العتبة تلقائياً لكل رمز
"""

import csv
import logging
from pathlib import Path
from statistics import mean

from ..config import JOURNAL_DIR

log = logging.getLogger("friday.wick_agent")

_LOG = JOURNAL_DIR / "wick_patterns.csv"
_DEFAULT_THRESHOLD = 0.40   # ذيل > 40% من نطاق الشمعة = رفض
_MIN_SAMPLES       = 5      # الحد الأدنى قبل تعديل العتبة
_ZONE_BUFFER       = 0.5    # مضاعف ATR للقرب من المنطقة


class WickAgent:
    name = "wick"

    def __init__(self, symbol: str):
        self.symbol   = symbol
        self._cache: dict[str, float] = {}   # symbol → learned threshold
        self.log = logging.getLogger(f"friday.agent.{self.name}")
        _LOG.parent.mkdir(parents=True, exist_ok=True)

    # ── فلترة الدخول ─────────────────────────────────────────────────────────

    def should_block_buy(self, mctx: dict) -> tuple[bool, str]:
        """
        يمنع BUY إذا:
        1. ذيل علوي كبير في آخر 3 شمعات عند منطقة مقاومة
        2. السعر قرب قمة سوينج أو OB هابط وفيها ذيل
        """
        thr   = self._threshold("BUY")
        price = mctx["price"]
        atr   = mctx["atr"] or 1.0

        # ذيول آخر 3 شمعات
        recent_uw = mctx.get("upper_wick_ratios", [])
        max_uw    = max(recent_uw) if recent_uw else mctx.get("last_upper_wick_ratio", 0)

        if max_uw < thr:
            return False, ""

        # تأكد أن الذيل عند منطقة مقاومة فعلية
        near_resistance = self._near_resistance(price, atr, mctx)
        if not near_resistance:
            return False, ""

        reason = f"wick_rejection_buy uw={max_uw:.2f} thr={thr:.2f} zone={near_resistance}"
        self.log.info("[%s] BLOCK BUY — %s", self.symbol, reason)
        return True, reason

    def should_block_sell(self, mctx: dict) -> tuple[bool, str]:
        """
        يمنع SELL إذا:
        1. ذيل سفلي كبير في آخر 3 شمعات عند منطقة دعم
        """
        thr   = self._threshold("SELL")
        price = mctx["price"]
        atr   = mctx["atr"] or 1.0

        recent_lw = mctx.get("lower_wick_ratios", [])
        max_lw    = max(recent_lw) if recent_lw else mctx.get("last_lower_wick_ratio", 0)

        if max_lw < thr:
            return False, ""

        near_support = self._near_support(price, atr, mctx)
        if not near_support:
            return False, ""

        reason = f"wick_support_sell lw={max_lw:.2f} thr={thr:.2f} zone={near_support}"
        self.log.info("[%s] BLOCK SELL — %s", self.symbol, reason)
        return True, reason

    # ── تسجيل النتيجة والتعلم ────────────────────────────────────────────────

    def record(
        self,
        side: str,
        wick_ratio: float,
        zone_type: str,
        blocked: bool,
        won: bool,
    ):
        """
        يسجل نمط ذيل + نتيجته.
        blocked=True  → كان النظام سيمنع الدخول بسبب الذيل
        won=True      → الصفقة ربحت رغم الذيل (أو خسرت بدونه)
        """
        row = {
            "symbol":     self.symbol,
            "side":       side,
            "wick_ratio": round(wick_ratio, 4),
            "zone_type":  zone_type,
            "blocked":    blocked,
            "won":        won,
        }
        exists = _LOG.exists()
        with open(_LOG, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(row.keys()))
            if not exists:
                w.writeheader()
            w.writerow(row)
        self._cache.pop(self.symbol, None)
        self._adapt()

    # ── مسح تاريخي للذيول (يُشغَّل مرة عند الإقلاع) ────────────────────────

    def scan_history(self, enriched_df, lookback: int = 500):
        """
        يمسح آخر N شمعة ويسجل الأنماط التاريخية:
          ذيل علوي > DEFAULT_THRESHOLD عند قمة سوينج → نتيجة السعر بعد 5 شمعات
        """
        df = enriched_df.tail(lookback).reset_index(drop=True)
        n  = len(df)
        count = 0

        for i in range(n - 5):
            row = df.iloc[i]
            uw  = float(row.get("upper_wick_ratio", 0))
            lw  = float(row.get("lower_wick_ratio", 0))
            hi  = float(row["high"])
            lo  = float(row["low"])
            c   = float(row["close"])
            atr_r = float(row.get("atr", 0))
            atr   = atr_r * c if atr_r < 1 else atr_r   # ATR نسبي أو مطلق

            future_close = float(df.iloc[i + 5]["close"])

            # ذيل علوي عند قمة
            if uw > _DEFAULT_THRESHOLD:
                liq_h = float(row.get("liquidity_high", hi))
                if abs(hi - liq_h) < atr * _ZONE_BUFFER:
                    won_sell = future_close < c   # السعر نزل → البيع كان صح
                    self.record("SELL", uw, "swing_high", blocked=False, won=won_sell)
                    count += 1

            # ذيل سفلي عند قاع
            if lw > _DEFAULT_THRESHOLD:
                liq_l = float(row.get("liquidity_low", lo))
                if abs(lo - liq_l) < atr * _ZONE_BUFFER:
                    won_buy = future_close > c    # السعر صعد → الشراء كان صح
                    self.record("BUY", lw, "swing_low", blocked=False, won=won_buy)
                    count += 1

        log.info("[%s] scan_history: %d نمط ذيل مُسجَّل من %d شمعة", self.symbol, count, lookback)

    # ── داخلي ────────────────────────────────────────────────────────────────

    def _near_resistance(self, price: float, atr: float, mctx: dict) -> str:
        buf = atr * _ZONE_BUFFER
        checks = {
            "swing_high": mctx.get("prev_swing_high"),
            "liquidity_high": mctx.get("liquidity_high"),
            "bearish_ob_high": mctx.get("bearish_ob_high"),
        }
        for zone, level in checks.items():
            if level and abs(price - level) <= buf:
                return zone
        return ""

    def _near_support(self, price: float, atr: float, mctx: dict) -> str:
        buf = atr * _ZONE_BUFFER
        checks = {
            "swing_low":      mctx.get("prev_swing_low"),
            "liquidity_low":  mctx.get("liquidity_low"),
            "bullish_ob_low": mctx.get("bullish_ob_low"),
        }
        for zone, level in checks.items():
            if level and abs(price - level) <= buf:
                return zone
        return ""

    def _threshold(self, side: str) -> float:
        key = f"{self.symbol}_{side}"
        return self._cache.get(key, _DEFAULT_THRESHOLD)

    def _adapt(self):
        """
        يُعدِّل العتبة بناءً على التاريخ المحلي للرمز.
        منطق:
          إذا الذيل الكبير أدى لخسارة > 60% من الوقت → اخفض العتبة (أصبح أكثر حساسية)
          إذا الذيل الكبير لم يؤثر (الصفقة ربحت) > 60% → ارفع العتبة (أصبح أقل حساسية)
        """
        if not _LOG.exists():
            return
        rows = []
        with open(_LOG, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("symbol") == self.symbol:
                    rows.append(r)

        for side in ("BUY", "SELL"):
            side_rows = [r for r in rows if r["side"] == side]
            if len(side_rows) < _MIN_SAMPLES:
                continue

            blocked_correct = sum(
                1 for r in side_rows
                if r.get("blocked") in ("True", True)
                and r.get("won") in ("False", False, "0")
            )
            total_blocked = sum(1 for r in side_rows if r.get("blocked") in ("True", True)) or 1
            block_accuracy = blocked_correct / total_blocked

            key = f"{self.symbol}_{side}"
            cur = self._cache.get(key, _DEFAULT_THRESHOLD)

            if block_accuracy > 0.60:
                self._cache[key] = max(cur - 0.02, 0.25)   # أكثر حساسية
            elif block_accuracy < 0.40:
                self._cache[key] = min(cur + 0.02, 0.65)   # أقل حساسية

            log.debug(
                "[%s] %s wick_threshold=%.2f  block_accuracy=%.0f%%",
                self.symbol, side, self._cache[key], block_accuracy * 100,
            )
