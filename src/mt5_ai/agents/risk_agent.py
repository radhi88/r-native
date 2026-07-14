"""
RiskAgent — حساب وقف الخسارة وجني الأرباح بناءً على مستويات الهيكل.

وضع وقف الخسارة:
  شراء : أسفل حد OB الصاعد السفلي (+ buffer).  إذا لم يوجد OB → ATR × atr_sl_mult
  بيع  : أعلى حد OB الهابط العلوي (+ buffer).  إذا لم يوجد OB → ATR × atr_sl_mult

وضع جني الأرباح (الأولوية):
  شراء : 1. أقرب BSL (EQH) فوق السعر
           2. أقرب قمة تأرجح فوق السعر
           3. liquidity_high
           4. بديل ATR × 2.0
  بيع  : 1. أقرب SSL (EQL) تحت السعر
           2. أقرب قاع تأرجح تحت السعر
           3. liquidity_low
           4. بديل ATR × 2.0

الحد الأدنى لنسبة R:R = min_rr (افتراضي 1.5).
"""

import logging
from dataclasses import dataclass
from .entry_agent import EntrySignal


@dataclass
class RiskifiedSignal:
    symbol: str
    side: str
    price: float
    sl: float
    tp: float
    lot_hint: float
    risk_points: float
    reward_points: float
    rr_ratio: float
    reason: str


class RiskAgent:
    name = "risk"

    def __init__(
        self,
        symbol: str,
        atr_sl_mult: float   = 1.5,   # SL = 1.5 × ATR when no structure level
        min_rr: float        = 1.5,   # ICT style: minimum 1:2 R:R
        sl_buffer_atr: float = 0.10,  # buffer beyond swept level / OB
        min_sl_atr: float    = 1.0,   # minimum SL distance = 1.0 × ATR
    ):
        self.symbol       = symbol
        self.atr_sl_mult  = atr_sl_mult
        self.min_rr       = min_rr
        self.sl_buffer    = sl_buffer_atr
        self.min_sl_atr   = min_sl_atr
        self.log = logging.getLogger(f"friday.agent.{self.name}")

    def compute(
        self,
        signal: EntrySignal,
        market_ctx: dict,
        liquidity_ctx: dict,
    ) -> RiskifiedSignal | None:
        price  = signal.price
        atr    = signal.atr
        buf    = atr * self.sl_buffer

        if signal.side == "BUY":
            return self._buy(price, atr, buf, market_ctx, liquidity_ctx, signal.reason)
        if signal.side == "SELL":
            return self._sell(price, atr, buf, market_ctx, liquidity_ctx, signal.reason)
        return None

    # ── شراء ─────────────────────────────────────────────────────────────────────

    def _buy(self, price, atr, buf, mctx, lctx, reason) -> RiskifiedSignal | None:
        # وقف الخسارة — ICT: الأولوية لمستوى السيولة المخترق (SSL swept level)
        sl = None
        # 1. أسفل مستوى السيولة المخترق (SSL = القاع الذي جرى اختراقه = stop الأمثل)
        ssl_swept = lctx.get("last_ssl_level")
        if ssl_swept and ssl_swept < price:
            sl = ssl_swept - buf
        # 2. أسفل حد OB الصاعد السفلي (إذا لم يوجد swept level)
        if sl is None:
            ob_low = mctx.get("bullish_ob_low")
            if ob_low and ob_low < price:
                sl = ob_low - buf
        # 3. بديل ATR
        if sl is None:
            sl = price - atr * self.atr_sl_mult

        # ضمان حد أدنى للمسافة — يحمي من SL ضيق جداً
        min_dist = atr * self.min_sl_atr
        sl = min(sl, price - min_dist)

        risk = price - sl
        if risk <= 0:
            return None

        # جني الأرباح
        tp = self._buy_tp(price, risk, mctx, lctx)

        reward = tp - price
        rr     = reward / risk if risk > 0 else 0.0
        if rr < self.min_rr:
            tp     = price + risk * self.min_rr
            reward = tp - price
            rr     = self.min_rr

        self.log.debug("BUY  SL=%.5f TP=%.5f R:R=%.2f  [%s]", sl, tp, rr, reason)
        return RiskifiedSignal(
            symbol=self.symbol, side="BUY",
            price=price, sl=sl, tp=tp, lot_hint=1.0,
            risk_points=risk, reward_points=reward, rr_ratio=rr,
            reason=reason,
        )

    # ── بيع ──────────────────────────────────────────────────────────────────────

    def _sell(self, price, atr, buf, mctx, lctx, reason) -> RiskifiedSignal | None:
        # وقف الخسارة — ICT: الأولوية لمستوى السيولة المخترق (BSL swept level)
        sl = None
        # 1. فوق مستوى السيولة المخترق (BSL = القمة التي جرى اختراقها)
        bsl_swept = lctx.get("last_bsl_level")
        if bsl_swept and bsl_swept > price:
            sl = bsl_swept + buf
        # 2. فوق حد OB الهابط العلوي
        if sl is None:
            ob_high = mctx.get("bearish_ob_high")
            if ob_high and ob_high > price:
                sl = ob_high + buf
        # 3. بديل ATR
        if sl is None:
            sl = price + atr * self.atr_sl_mult

        # ضمان حد أدنى للمسافة
        min_dist = atr * self.min_sl_atr
        sl = max(sl, price + min_dist)

        risk = sl - price
        if risk <= 0:
            return None

        # جني الأرباح
        tp = self._sell_tp(price, risk, mctx, lctx)

        reward = price - tp
        rr     = reward / risk if risk > 0 else 0.0
        if rr < self.min_rr:
            tp     = price - risk * self.min_rr
            reward = price - tp
            rr     = self.min_rr

        self.log.debug("SELL SL=%.5f TP=%.5f R:R=%.2f  [%s]", sl, tp, rr, reason)
        return RiskifiedSignal(
            symbol=self.symbol, side="SELL",
            price=price, sl=sl, tp=tp, lot_hint=1.0,
            risk_points=risk, reward_points=reward, rr_ratio=rr,
            reason=reason,
        )

    # ── منطق TP ──────────────────────────────────────────────────────────────────

    def _buy_tp(self, price: float, risk: float, mctx: dict, lctx: dict) -> float:
        min_tp     = price + risk * self.min_rr
        candidates = []

        # 1. أقرب سيولة شراء (EQH) فوق السعر
        bsl = lctx.get("bsl_target")
        if bsl and bsl > price:
            candidates.append(bsl)

        # 2. أقرب قمة تأرجح فوق السعر
        for h in mctx.get("swing_highs", []):
            if h > price + risk * 0.5:
                candidates.append(h)
                break

        # 3. مستوى السيولة العالي من market_structure
        liq_h = mctx.get("liquidity_high")
        if liq_h and liq_h > price:
            candidates.append(liq_h)

        valid = [c for c in candidates if c >= min_tp]
        return min(valid) if valid else price + risk * 2.0

    def _sell_tp(self, price: float, risk: float, mctx: dict, lctx: dict) -> float:
        min_tp     = price - risk * self.min_rr
        candidates = []

        # 1. أقرب سيولة بيع (EQL) تحت السعر
        ssl = lctx.get("ssl_target")
        if ssl and ssl < price:
            candidates.append(ssl)

        # 2. أقرب قاع تأرجح تحت السعر
        for l in mctx.get("swing_lows", []):
            if l < price - risk * 0.5:
                candidates.append(l)
                break

        # 3. مستوى السيولة المنخفض من market_structure
        liq_l = mctx.get("liquidity_low")
        if liq_l and liq_l < price:
            candidates.append(liq_l)

        valid = [c for c in candidates if c <= min_tp]
        return max(valid) if valid else price - risk * 2.0
