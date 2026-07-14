"""
MarketAnalystAgent — محلل هيكل السوق SMC.

الدور: يستخرج السياق الكامل من DataFrame المُثرَّى.
لا يتداول. يوفر market_context لبقية الوكلاء.
"""

import logging
import numpy as np
import pandas as pd


class MarketAnalystAgent:
    name = "market_analyst"

    def __init__(self, symbol: str, swing_lookback: int = 5):
        self.symbol = symbol
        self.swing_lookback = swing_lookback
        self.log = logging.getLogger(f"friday.agent.{self.name}")

    def extract_context(self, enriched: pd.DataFrame) -> dict:
        """
        استخرج سياق SMC من DataFrame مُثرَّى بـ add_market_structure.
        يُعاد استدعاؤه كل bar — لا يُعيد تشغيل add_market_structure.
        """
        row = enriched.iloc[-1]

        def sf(col, default=None, row=row):
            v = row.get(col, default)
            try:
                f = float(v)
                return f if not np.isnan(f) else default
            except Exception:
                return default

        swings    = self._find_swing_points(enriched)
        price     = sf("close", 0.0)
        atr_ratio = sf("atr", 0.0)
        # ATR في market_structure مخزون كنسبة (range/close).
        # نحوّله لوحدات سعر مطلقة حتى تعمل حسابات SL/TP بشكل صحيح.
        atr_abs   = atr_ratio * price if price > 0 else atr_ratio

        context = {
            # سعر ومدى التقلب
            "price":     price,
            "atr":       atr_abs,       # وحدات USD — جاهز للـSL/TP مباشرة
            "last_high": sf("high", price),
            "last_low":  sf("low",  price),
            "spread":    sf("spread", 0.0),

            # كسور الهيكل
            "bos_up":    bool(row.get("bos_up",    0)),
            "bos_down":  bool(row.get("bos_down",  0)),
            "choch_up":  bool(row.get("choch_up",  0)),
            "choch_down":bool(row.get("choch_down",0)),

            # اختراق السيولة (الشمعة الحالية)
            "buy_side_sweep":  bool(row.get("buy_side_liquidity_sweep",  0)),
            "sell_side_sweep": bool(row.get("sell_side_liquidity_sweep", 0)),

            # الاتجاه والزخم
            "trend": sf("trend", 0.0),
            "rsi":   sf("rsi",   50.0),
            "adx":   sf("adx",   0.0),

            # بلوكات الطلب/العرض
            "in_bullish_ob":   bool(row.get("in_bullish_ob",  0)),
            "in_bearish_ob":   bool(row.get("in_bearish_ob",  0)),
            "bullish_ob_low":  sf("bullish_ob_low"),
            "bullish_ob_high": sf("bullish_ob_high"),
            "bearish_ob_low":  sf("bearish_ob_low"),
            "bearish_ob_high": sf("bearish_ob_high"),

            # فجوات القيمة العادلة
            "bullish_fvg": bool(row.get("bullish_fvg", 0)),
            "bearish_fvg": bool(row.get("bearish_fvg", 0)),
            "fvg_mid":     sf("fvg_mid"),

            # مناطق العرض والطلب المركبة
            "demand_zone": bool(row.get("demand_zone", 0)),
            "supply_zone": bool(row.get("supply_zone", 0)),

            # درجات SMC المركبة
            "smc_buy_score":  int(row.get("smc_buy_score",  0)),
            "smc_sell_score": int(row.get("smc_sell_score", 0)),
            "smc_bias":       int(row.get("smc_bias",       0)),

            # مستويات الهيكل المرجعية
            "prev_swing_high": sf("prev_swing_high"),
            "prev_swing_low":  sf("prev_swing_low"),
            "liquidity_high":  sf("liquidity_high"),
            "liquidity_low":   sf("liquidity_low"),

            # القمم والقيعان للاستهداف
            "swing_highs": swings["highs"],
            "swing_lows":  swings["lows"],
        }

        # ── ذيول آخر 3 شمعات ─────────────────────────────────────────────────
        tail3 = enriched.tail(3)
        context["upper_wick_ratios"]    = [sf("upper_wick_ratio", 0, row=r) for _, r in tail3.iterrows()]
        context["lower_wick_ratios"]    = [sf("lower_wick_ratio", 0, row=r) for _, r in tail3.iterrows()]
        context["last_upper_wick_ratio"] = context["upper_wick_ratios"][-1]
        context["last_lower_wick_ratio"] = context["lower_wick_ratios"][-1]

        self.log.debug(
            "SMC | bos_up=%s bos_down=%s choch_up=%s choch_down=%s "
            "buy=%d sell=%d  in_bull_ob=%s in_bear_ob=%s",
            context["bos_up"], context["bos_down"],
            context["choch_up"], context["choch_down"],
            context["smc_buy_score"], context["smc_sell_score"],
            context["in_bullish_ob"], context["in_bearish_ob"],
        )
        return context

    def _find_swing_points(self, df: pd.DataFrame) -> dict:
        """أهم القمم والقيعان حول السعر الحالي."""
        lb = self.swing_lookback
        n  = len(df)
        highs, lows = [], []

        for i in range(lb, n - lb):
            h = float(df["high"].iloc[i])
            l = float(df["low"].iloc[i])

            if all(h >= float(df["high"].iloc[i - j]) for j in range(1, lb + 1)) and \
               all(h >= float(df["high"].iloc[i + j]) for j in range(1, lb + 1)):
                highs.append(h)

            if all(l <= float(df["low"].iloc[i - j]) for j in range(1, lb + 1)) and \
               all(l <= float(df["low"].iloc[i + j]) for j in range(1, lb + 1)):
                lows.append(l)

        price = float(df["close"].iloc[-1])
        return {
            "highs": sorted([h for h in highs if h > price])[:5],
            "lows":  sorted([l for l in lows  if l < price], reverse=True)[:5],
        }
