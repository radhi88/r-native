"""
LiquidityHunterAgent — صياد السيولة.

الدور:
- يرسم مستويات السيولة: EQH (قمم متساوية = BSL) و EQL (قيعان متساوية = SSL)
- يكتشف عمليات اختراق السيولة:
    BSL sweep: الشمعة تكسر EQH بالفتيلة وتغلق تحته  → إشارة بيع محتملة
    SSL sweep: الشمعة تكسر EQL بالفتيلة وتغلق فوقه  → إشارة شراء محتملة
- يحتفظ بحالة الاختراق لمدة `sweep_decay` شمعة
- لا قيود على السبريد أو الوقت أو الأخبار
"""

import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path


class LiquidityHunterAgent:
    name = "liquidity_hunter"

    def __init__(
        self,
        symbol: str,
        eq_tolerance_atr: float = 0.15,
        lookback: int = 40,
        sweep_decay: int = 10,
        state_dir: Path | None = None,
    ):
        self.symbol           = symbol
        self.eq_tolerance_atr = eq_tolerance_atr
        self.lookback         = lookback
        self.sweep_decay      = sweep_decay
        self.log = logging.getLogger(f"friday.agent.{self.name}")

        # ملف حالة خاص بكل رمز — يُحمَّل عند البدء ويُحفظ عند كل sweep
        _dir = state_dir or (Path(__file__).resolve().parents[3] / "data")
        _dir.mkdir(parents=True, exist_ok=True)
        self._state_file = _dir / f"liquidity_state_{symbol}.json"

        # تحميل الحالة المحفوظة أو البدء من صفر
        saved = self._load_state()
        self._ssl_sweep_counter: int        = saved.get("ssl_counter", 0)
        self._bsl_sweep_counter: int        = saved.get("bsl_counter", 0)
        self._last_ssl_level: float | None  = saved.get("last_ssl")
        self._last_bsl_level: float | None  = saved.get("last_bsl")

    def analyze(self, df: pd.DataFrame, atr: float) -> dict:
        """
        حلّل DataFrame وأعد سياق السيولة.
        يُستدعى كل bar بعد استدعاء add_market_structure.
        """
        if len(df) < self.lookback + 5:
            return self._empty_context()

        tolerance  = max(atr * self.eq_tolerance_atr, 0.05)
        recent     = df.tail(self.lookback + 5).reset_index(drop=True)

        eqh_levels = self._find_equal_highs(recent, tolerance)
        eql_levels = self._find_equal_lows(recent, tolerance)

        last = recent.iloc[-1]
        hi   = float(last["high"])
        lo   = float(last["low"])
        cl   = float(last["close"])
        price = cl

        # ── اكتشاف اختراق السيولة (الشمعة الحالية) ────────────────────────────
        bsl_swept        = False
        swept_bsl_level  = None
        for level in sorted(eqh_levels):
            if hi > level and cl < level:
                bsl_swept       = True
                swept_bsl_level = level
                break

        ssl_swept        = False
        swept_ssl_level  = None
        for level in sorted(eql_levels, reverse=True):
            if lo < level and cl > level:
                ssl_swept       = True
                swept_ssl_level = level
                break

        # ── تحديث عدادات الاختراق ──────────────────────────────────────────────
        if ssl_swept:
            self._ssl_sweep_counter = self.sweep_decay
            self._last_ssl_level    = swept_ssl_level
        elif self._ssl_sweep_counter > 0:
            self._ssl_sweep_counter -= 1

        if bsl_swept:
            self._bsl_sweep_counter = self.sweep_decay
            self._last_bsl_level    = swept_bsl_level
        elif self._bsl_sweep_counter > 0:
            self._bsl_sweep_counter -= 1

        # ── أقرب مستويات سيولة ───────────────────────────────────────────────
        bsl_target = next((h for h in sorted(eqh_levels) if h > price), None)
        ssl_target = next((l for l in sorted(eql_levels, reverse=True) if l < price), None)

        if bsl_swept or ssl_swept:
            self.log.info(
                "Sweep! BSL=%s @ %.5f  SSL=%s @ %.5f  price=%.5f",
                bsl_swept, swept_bsl_level or 0,
                ssl_swept, swept_ssl_level or 0,
                price,
            )
            # احفظ الحالة على الديسك فور حدوث sweep
            self._save_state()

        return {
            "eqh_levels":         eqh_levels,
            "eql_levels":         eql_levels,
            "bsl_target":         bsl_target,
            "ssl_target":         ssl_target,
            "bsl_swept":          bsl_swept,
            "ssl_swept":          ssl_swept,
            "swept_bsl_level":    swept_bsl_level,
            "swept_ssl_level":    swept_ssl_level,
            "ssl_sweep_active":   self._ssl_sweep_counter > 0,
            "bsl_sweep_active":   self._bsl_sweep_counter > 0,
            "ssl_sweep_bars_ago": self.sweep_decay - self._ssl_sweep_counter,
            "bsl_sweep_bars_ago": self.sweep_decay - self._bsl_sweep_counter,
            "last_ssl_level":     self._last_ssl_level,
            "last_bsl_level":     self._last_bsl_level,
        }

    # ── خوارزميات التجميع ──────────────────────────────────────────────────────

    def _find_equal_highs(self, df: pd.DataFrame, tolerance: float) -> list[float]:
        """
        قمم متساوية (EQH) = مستويات BSL فوق السعر.
        نجد قمم تأرجح متكتلة ضمن tolerance.
        """
        swings = []
        for i in range(1, len(df) - 1):
            h = float(df["high"].iloc[i])
            if h >= float(df["high"].iloc[i - 1]) and h >= float(df["high"].iloc[i + 1]):
                swings.append(h)

        return self._cluster_levels(swings, tolerance)

    def _find_equal_lows(self, df: pd.DataFrame, tolerance: float) -> list[float]:
        """
        قيعان متساوية (EQL) = مستويات SSL تحت السعر.
        """
        swings = []
        for i in range(1, len(df) - 1):
            l = float(df["low"].iloc[i])
            if l <= float(df["low"].iloc[i - 1]) and l <= float(df["low"].iloc[i + 1]):
                swings.append(l)

        return self._cluster_levels(swings, tolerance)

    @staticmethod
    def _cluster_levels(levels: list[float], tolerance: float) -> list[float]:
        """دمج المستويات المتقاربة ضمن tolerance وإرجاع المراكز."""
        if not levels:
            return []
        used    = [False] * len(levels)
        result  = []
        for i in range(len(levels)):
            if used[i]:
                continue
            cluster = [levels[i]]
            for j in range(i + 1, len(levels)):
                if not used[j] and abs(levels[j] - levels[i]) <= tolerance:
                    cluster.append(levels[j])
                    used[j] = True
            if len(cluster) >= 2:
                result.append(float(np.mean(cluster)))
        return sorted(result)

    def _save_state(self):
        try:
            self._state_file.write_text(json.dumps({
                "symbol":      self.symbol,
                "ssl_counter": self._ssl_sweep_counter,
                "bsl_counter": self._bsl_sweep_counter,
                "last_ssl":    self._last_ssl_level,
                "last_bsl":    self._last_bsl_level,
            }), encoding="utf-8")
        except Exception:
            pass

    def _load_state(self) -> dict:
        try:
            if self._state_file.exists():
                return json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    @staticmethod
    def _empty_context() -> dict:
        return {
            "eqh_levels": [], "eql_levels": [],
            "bsl_target": None, "ssl_target": None,
            "bsl_swept": False, "ssl_swept": False,
            "swept_bsl_level": None, "swept_ssl_level": None,
            "ssl_sweep_active": False, "bsl_sweep_active": False,
            "ssl_sweep_bars_ago": 999, "bsl_sweep_bars_ago": 999,
            "last_ssl_level": None, "last_bsl_level": None,
        }
