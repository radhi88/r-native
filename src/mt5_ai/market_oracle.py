"""
market_oracle.py
----------------
محرك تنبؤ اتجاه السوق وارتباط العملات لـ FRIDAY.

المكونات:
  CorrelationMatrix — مصفوفة ارتباط ديناميكية + علاقات مسبقة معروفة
  DirectionForecast — تنبؤ الاتجاه (UP/DOWN/NEUTRAL) مع نسبة ثقة
  PredictionTracker  — تتبع دقة التنبؤات وحساب نسبة الإصابة
  MarketOracle       — الواجهة الرئيسية
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from .config import DATA_DIR

log = logging.getLogger("friday.oracle")

_ORACLE_FILE    = DATA_DIR / "oracle_predictions.json"
_CORR_FILE      = DATA_DIR / "oracle_correlations.json"
_MAX_HIST       = 500       # أقصى تاريخ سعر محفوظ لكل عملة
_PRED_EXPIRE_S  = 60 * 60   # ساعة واحدة للتحقق من التنبؤ
_CORR_WINDOW    = 100       # عدد الشمعات لحساب الارتباط


# ── علاقات مسبقة معروفة (Prior correlations) ──────────────────────────────────
# القيمة: +1 (ارتباط إيجابي), -1 (عكسي), 0 (محايد)
PRIOR_CORRELATIONS: dict[tuple[str, str], float] = {
    # الذهب والفضة: يتحركان معاً
    ("XAUUSDm", "XAGUSDm"): +0.85,
    # الذهب مقابل الدولار: عكسي
    ("XAUUSDm", "USDJPYm"): -0.65,
    # الذهب مع اليورو والجنيه: إيجابي (كلاهما ضد الدولار)
    ("XAUUSDm", "EURUSDm"): +0.55,
    ("XAUUSDm", "GBPUSDm"): +0.50,
    # النفط والذهب: إيجابي (سلع مقومة بالدولار)
    ("XAUUSDm", "USOILm"):  +0.40,
    # النفط وBTC: أصول مخاطرة
    ("USOILm",  "BTCUSDm"): +0.35,
    # اليورو والجنيه: يتحركان معاً
    ("EURUSDm", "GBPUSDm"): +0.75,
    # اليورو مقابل الين: عكسي
    ("EURUSDm", "USDJPYm"): -0.60,
    ("GBPUSDm", "USDJPYm"): -0.55,
    # BTC وGold: أحياناً إيجابي كملاذ آمن
    ("BTCUSDm", "XAUUSDm"): +0.30,
}


# ── تنبؤ واحد ─────────────────────────────────────────────────────────────────

@dataclass
class Prediction:
    symbol:       str
    direction:    str          # "UP" / "DOWN" / "NEUTRAL"
    confidence:   float        # 0-1
    price_at:     float        # السعر عند التنبؤ
    target_price: float        # السعر المستهدف
    genome_id:    str
    ts:           float = field(default_factory=time.time)
    expiry:       float = field(default_factory=lambda: time.time() + _PRED_EXPIRE_S)
    resolved:     bool  = False
    correct:      bool  = False
    actual_price: float = 0.0
    supporting:   list  = field(default_factory=list)  # الإشارات الداعمة

    def to_dict(self) -> dict:
        return {
            "symbol":       self.symbol,
            "direction":    self.direction,
            "confidence":   round(self.confidence, 3),
            "price_at":     self.price_at,
            "target_price": self.target_price,
            "genome_id":    self.genome_id[:8],
            "ts":           datetime.fromtimestamp(self.ts, timezone.utc).isoformat(),
            "resolved":     self.resolved,
            "correct":      self.correct,
            "actual_price": self.actual_price,
            "supporting":   self.supporting,
        }


# ── مصفوفة الارتباط الديناميكية ───────────────────────────────────────────────

class CorrelationMatrix:
    """
    تحسب ارتباط بيرسون بين عوائد العملات على نافذة متحركة.
    تمزج الارتباط الديناميكي مع الارتباطات المسبقة المعروفة.
    """

    def __init__(self) -> None:
        self._returns: dict[str, deque] = {}   # symbol → آخر 100 عائد نسبي
        self._lock = threading.Lock()

    def update(self, symbol: str, price: float) -> None:
        with self._lock:
            if symbol not in self._returns:
                self._returns[symbol] = deque(maxlen=_CORR_WINDOW + 1)
            self._returns[symbol].append(price)

    def correlation(self, sym_a: str, sym_b: str) -> float:
        """
        الارتباط المخلوط: 60% ديناميكي + 40% مسبق.
        إذا لم يكن هناك بيانات كافية → يعود للمسبق.
        """
        prior = PRIOR_CORRELATIONS.get(
            (sym_a, sym_b),
            PRIOR_CORRELATIONS.get((sym_b, sym_a), 0.0)
        )

        with self._lock:
            a_prices = list(self._returns.get(sym_a, []))
            b_prices = list(self._returns.get(sym_b, []))

        min_len = min(len(a_prices), len(b_prices))
        if min_len < 10:
            return prior

        n = min(min_len, _CORR_WINDOW)
        a_arr = np.array(a_prices[-n-1:])
        b_arr = np.array(b_prices[-n-1:])
        a_ret = np.diff(a_arr) / (a_arr[:-1] + 1e-9)
        b_ret = np.diff(b_arr) / (b_arr[:-1] + 1e-9)

        if np.std(a_ret) < 1e-10 or np.std(b_ret) < 1e-10:
            return prior

        try:
            dyn = float(np.corrcoef(a_ret, b_ret)[0, 1])
        except Exception:
            return prior

        if not np.isfinite(dyn):
            return prior

        return round(0.60 * dyn + 0.40 * prior, 4)

    def inter_market_bias(self, symbol: str, all_symbols: list[str]) -> float:
        """
        احسب تحيّز اتجاهي من العملات المرتبطة.
        إذا ارتفع الذهب الآن وارتباطه بالفضة 0.85 → يتوقع صعود الفضة.
        يُعيد قيمة من -1 إلى +1.
        """
        with self._lock:
            own_prices = list(self._returns.get(symbol, []))
        if len(own_prices) < 3:
            return 0.0

        total_weight = 0.0
        total_signal = 0.0

        for other in all_symbols:
            if other == symbol:
                continue
            corr = self.correlation(symbol, other)
            if abs(corr) < 0.20:
                continue  # ارتباط ضعيف جداً → تجاهل

            with self._lock:
                other_prices = list(self._returns.get(other, []))
            if len(other_prices) < 3:
                continue

            # عائد الآخر على آخر 5 شمعات
            recent_ret = (other_prices[-1] - other_prices[-6]) / (other_prices[-6] + 1e-9) if len(other_prices) >= 6 else 0.0
            signal = np.sign(recent_ret) * corr * abs(corr)  # يعزز الإشارة بمربع الارتباط

            total_weight += abs(corr)
            total_signal += signal

        if total_weight < 0.01:
            return 0.0

        return round(float(total_signal / total_weight), 4)

    def report(self, symbols: list[str]) -> list[dict]:
        """تقرير بأقوى الارتباطات للداشبورد."""
        pairs = []
        seen = set()
        for a in symbols:
            for b in symbols:
                if a == b:
                    continue
                key = tuple(sorted([a, b]))
                if key in seen:
                    continue
                seen.add(key)
                c = self.correlation(a, b)
                if abs(c) >= 0.30:
                    pairs.append({"a": a, "b": b, "corr": round(c, 3)})
        pairs.sort(key=lambda x: abs(x["corr"]), reverse=True)
        return pairs[:10]


# ── محرك التنبؤ ───────────────────────────────────────────────────────────────

class MarketOracle:
    """
    الواجهة الرئيسية لمحرك تنبؤات السوق.

    الاستخدام:
        oracle = MarketOracle(broadcast_fn=_broadcast)
        oracle.update_price("XAUUSDm", price, smc_data)
        pred  = oracle.predict("XAUUSDm", genome_id)
        hits  = oracle.check_expired()   # يُعيد التنبؤات الصحيحة
    """

    def __init__(
        self,
        broadcast_fn: Callable[[str, dict], None] | None = None,
        reward_fn:    Callable[[str, Prediction], None] | None = None,
    ) -> None:
        self._broadcast = broadcast_fn or (lambda e, d: None)
        self._reward_fn = reward_fn
        self.corr = CorrelationMatrix()
        self._prices:      dict[str, deque] = {}
        self._smc_scores:  dict[str, tuple] = {}   # symbol → (buy_score, sell_score)
        self._predictions: list[Prediction] = []
        self._accuracy:    dict[str, list]  = {}   # symbol → [True/False, ...]
        self._lock = threading.Lock()
        self._load()
        log.info("[MarketOracle] Ready")

    # ── تحديث البيانات ───────────────────────────────────────────────────────

    def update_price(self, symbol: str, price: float, smc: dict | None = None) -> None:
        """استدعيها كل شمعة جديدة."""
        with self._lock:
            if symbol not in self._prices:
                self._prices[symbol] = deque(maxlen=_MAX_HIST)
            self._prices[symbol].append(price)
            if smc:
                self._smc_scores[symbol] = (
                    float(smc.get("smc_buy_score",  0)),
                    float(smc.get("smc_sell_score", 0)),
                )
        self.corr.update(symbol, price)

    # ── التنبؤ الرئيسي ───────────────────────────────────────────────────────

    def predict(self, symbol: str, genome_id: str = "") -> Prediction | None:
        """
        ينتج تنبؤاً للاتجاه التالي:
        1. زخم السعر (momentum)
        2. نتيجة SMC للعملة نفسها
        3. التحيّز من العملات المرتبطة
        """
        with self._lock:
            prices = list(self._prices.get(symbol, []))
            smc_b, smc_s = self._smc_scores.get(symbol, (0.0, 0.0))

        if len(prices) < 20:
            return None

        all_syms = list(self._prices.keys())
        price_now = prices[-1]

        # ── 1. زخم الأسعار ────────────────────────────────────────────────────
        mom5  = (prices[-1] - prices[-6])  / (prices[-6]  + 1e-9) if len(prices) > 6  else 0.0
        mom20 = (prices[-1] - prices[-21]) / (prices[-21] + 1e-9) if len(prices) > 20 else 0.0
        momentum_signal = 0.6 * np.sign(mom5) + 0.4 * np.sign(mom20)

        # ── 2. إشارة SMC ─────────────────────────────────────────────────────
        smc_net = (smc_b - smc_s) / 5.0   # نرمّل من -1 إلى +1

        # ── 3. تحيّز العملات المرتبطة ─────────────────────────────────────────
        inter_bias = self.corr.inter_market_bias(symbol, all_syms)

        # ── تجميع الإشارات (أوزان) ────────────────────────────────────────────
        signal = 0.45 * momentum_signal + 0.35 * smc_net + 0.20 * inter_bias

        if abs(signal) < 0.15:
            direction  = "NEUTRAL"
            confidence = 0.40 + abs(signal)
        elif signal > 0:
            direction  = "UP"
            confidence = min(0.95, 0.50 + abs(signal) * 0.45)
        else:
            direction  = "DOWN"
            confidence = min(0.95, 0.50 + abs(signal) * 0.45)

        # الهدف: نقدّر حجم التحرك بناءً على ATR تقريبي
        recent_arr  = np.array(prices[-20:])
        atr_est     = float(np.mean(np.abs(np.diff(recent_arr)))) * 5
        if direction == "UP":
            target = price_now + atr_est
        elif direction == "DOWN":
            target = price_now - atr_est
        else:
            target = price_now

        supporting = []
        if abs(mom5) > 0.0002:
            supporting.append(f"mom5={'↑' if mom5>0 else '↓'}{abs(mom5)*100:.3f}%")
        if abs(smc_net) > 0.1:
            supporting.append(f"smc={'BUY' if smc_net>0 else 'SELL'}{abs(smc_net)*5:.1f}")
        if abs(inter_bias) > 0.15:
            supporting.append(f"inter={'↑' if inter_bias>0 else '↓'}{abs(inter_bias):.2f}")

        pred = Prediction(
            symbol=symbol, direction=direction, confidence=round(confidence, 3),
            price_at=price_now, target_price=round(target, 5),
            genome_id=genome_id, supporting=supporting,
        )

        with self._lock:
            self._predictions.append(pred)
            if len(self._predictions) > 500:
                self._predictions = self._predictions[-300:]

        self._broadcast("oracle_prediction", pred.to_dict())
        log.debug("[Oracle] %s → %s conf=%.2f support=%s", symbol, direction, confidence, supporting)
        return pred

    # ── فحص التنبؤات المنتهية ────────────────────────────────────────────────

    def check_expired(self) -> list[Prediction]:
        """
        يفحص التنبؤات التي انتهت صلاحيتها.
        يُعيد قائمة التنبؤات الصحيحة ويُطلق المكافآت.
        """
        now = time.time()
        correct_preds: list[Prediction] = []

        with self._lock:
            to_check = [p for p in self._predictions if not p.resolved and p.expiry <= now]

        for pred in to_check:
            with self._lock:
                prices = list(self._prices.get(pred.symbol, []))
            if not prices:
                continue

            current = prices[-1]
            pred.actual_price = current
            pred.resolved     = True

            move = current - pred.price_at
            if pred.direction == "UP":
                pred.correct = move > 0
            elif pred.direction == "DOWN":
                pred.correct = move < 0
            else:
                pred.correct = abs(move / (pred.price_at + 1e-9)) < 0.001

            with self._lock:
                if pred.symbol not in self._accuracy:
                    self._accuracy[pred.symbol] = []
                self._accuracy[pred.symbol].append(pred.correct)
                if len(self._accuracy[pred.symbol]) > 100:
                    self._accuracy[pred.symbol] = self._accuracy[pred.symbol][-100:]

            emoji = "✅" if pred.correct else "❌"
            self._broadcast("oracle_result", {
                **pred.to_dict(),
                "emoji": emoji,
                "move_pct": round(move / (pred.price_at + 1e-9) * 100, 4),
            })

            if pred.correct:
                correct_preds.append(pred)
                if self._reward_fn:
                    self._reward_fn(pred.genome_id, pred)

        self._save()
        return correct_preds

    # ── إحصاءات الدقة ────────────────────────────────────────────────────────

    def accuracy_stats(self) -> dict:
        """يُعيد دقة التنبؤ لكل عملة."""
        with self._lock:
            acc = dict(self._accuracy)
        result = {}
        for sym, results in acc.items():
            if results:
                result[sym] = {
                    "total":    len(results),
                    "correct":  sum(results),
                    "accuracy": round(sum(results) / len(results), 3),
                }
        return result

    def active_predictions(self) -> list[dict]:
        now = time.time()
        with self._lock:
            active = [p for p in self._predictions if not p.resolved and p.expiry > now]
        return [p.to_dict() for p in active[-20:]]

    def correlation_report(self) -> list[dict]:
        with self._lock:
            syms = list(self._prices.keys())
        return self.corr.report(syms)

    # ── الحفظ والتحميل ───────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            with self._lock:
                data = {
                    "predictions": [p.to_dict() for p in self._predictions[-100:]],
                    "accuracy":    {k: v[-50:] for k, v in self._accuracy.items()},
                }
            _ORACLE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load(self) -> None:
        try:
            if not _ORACLE_FILE.exists():
                return
            data = json.loads(_ORACLE_FILE.read_text(encoding="utf-8"))
            with self._lock:
                self._accuracy = {k: list(v) for k, v in data.get("accuracy", {}).items()}
        except Exception:
            pass
