"""
indicator_memory.py
-------------------
ذاكرة المؤشرات الغنية لـ FRIDAY.

لكل صفقة (آلية أو يدوية) يُحفظ:
  - الـ snapshot الكامل: كل قيم المؤشرات لحظة الدخول
  - النتيجة: ربح/خسارة + المبلغ
  - المصدر: "bot" أو "human" (صفقة يدوية)
  - "السبب المُستنتَج": التركيبة المؤشراتية التي كانت نشطة

بعد كل دورة يحسب النظام:
  - أي تركيبات المؤشرات الأكثر ارتباطاً بالربح
  - الأوزان الديناميكية لكل مؤشر
  - "بطاقة السبب": لماذا كانت هذه الصفقة مربحة بالضبط
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR

log = logging.getLogger("friday.indicator_memory")

_MEMORY_FILE = DATA_DIR / "indicator_memory.json"
_MAX_RECORDS  = 500   # أقصى عدد سجلات مُخزَّنة
_MIN_SAMPLE   = 5     # الحد الأدنى لتحليل الأنماط


# ── المؤشرات التي نُتابعها ─────────────────────────────────────────────────────
TRACKED_INDICATORS = [
    # Boolean SMC
    "bos_up", "bos_down", "choch_up", "choch_down",
    "in_bullish_ob", "in_bearish_ob",
    "bullish_fvg", "bearish_fvg",
    "buy_side_liquidity_sweep", "sell_side_liquidity_sweep",
    "demand_zone", "supply_zone",
    "ifvg_bull", "ifvg_bear",
    # Continuous
    "smc_buy_score", "smc_sell_score", "smc_bias",
    "rsi", "adx", "mfi", "trend",
    "atr", "probability",
    "upper_wick_ratio", "lower_wick_ratio",
]

# الحدود الاسمية لتصنيف القيم المستمرة
_RSI_BULL  = 50    # RSI > 50 → إشارة صعودية
_RSI_BEAR  = 50
_ADX_TREND = 25    # ADX > 25 → اتجاه قوي
_PROB_HIGH = 0.65  # احتمالية عالية


# ── سجل صفقة واحدة ────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    trade_id: str            # ticket أو UUID
    symbol: str
    side: str                # "BUY" / "SELL"
    entry_price: float
    source: str              # "bot" / "human"
    genome_id: str           # الجينوم النشط وقت الدخول (فارغ للصفقات اليدوية)
    timestamp: str

    # لقطة المؤشرات الكاملة لحظة الدخول
    snapshot: dict[str, Any] = field(default_factory=dict)

    # تُملأ عند الإغلاق
    pnl: float | None = None
    won: bool | None = None
    closed_at: str | None = None

    # تحليل السبب (يُملأ بعد الإغلاق)
    why_won: list[str] = field(default_factory=list)    # المؤشرات التي ساهمت في الربح
    why_lost: list[str] = field(default_factory=list)   # المؤشرات التي أوحت خطأ

    def close(self, pnl: float, pattern_library: "PatternLibrary | None" = None) -> None:
        self.pnl = float(pnl)
        self.won = pnl > 0
        self.closed_at = datetime.now(timezone.utc).isoformat()
        if pattern_library:
            self.why_won, self.why_lost = pattern_library.explain(self)

    def active_conditions(self) -> list[str]:
        """أعد قائمة الشروط المنطقية النشطة في لحظة الدخول."""
        result = []
        snap = self.snapshot
        bool_flags = [
            "bos_up", "bos_down", "choch_up", "choch_down",
            "in_bullish_ob", "in_bearish_ob",
            "bullish_fvg", "bearish_fvg",
            "buy_side_liquidity_sweep", "sell_side_liquidity_sweep",
            "demand_zone", "supply_zone",
            "ifvg_bull", "ifvg_bear",
        ]
        for k in bool_flags:
            if snap.get(k):
                result.append(k)

        # قيم مستمرة → تصنيف رمزي
        rsi  = snap.get("rsi", 50)
        adx  = snap.get("adx", 0)
        prob = snap.get("probability", 0.5)
        smc_buy  = snap.get("smc_buy_score", 0)
        smc_sell = snap.get("smc_sell_score", 0)

        if rsi  > 55: result.append("rsi_bull")
        elif rsi < 45: result.append("rsi_bear")
        if adx  > _ADX_TREND: result.append("adx_trending")
        if prob > _PROB_HIGH: result.append("high_prob")
        if smc_buy  >= 3: result.append("smc_buy_strong")
        if smc_sell >= 3: result.append("smc_sell_strong")
        if snap.get("trend", 0) > 0: result.append("trend_bull")
        elif snap.get("trend", 0) < 0: result.append("trend_bear")

        return result

    def to_dict(self) -> dict:
        return {
            "trade_id":   self.trade_id,
            "symbol":     self.symbol,
            "side":       self.side,
            "entry_price":self.entry_price,
            "source":     self.source,
            "genome_id":  self.genome_id,
            "timestamp":  self.timestamp,
            "snapshot":   self.snapshot,
            "pnl":        self.pnl,
            "won":        self.won,
            "closed_at":  self.closed_at,
            "why_won":    self.why_won,
            "why_lost":   self.why_lost,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TradeRecord":
        r = cls(
            trade_id    = d.get("trade_id", ""),
            symbol      = d.get("symbol", ""),
            side        = d.get("side", ""),
            entry_price = float(d.get("entry_price", 0)),
            source      = d.get("source", "bot"),
            genome_id   = d.get("genome_id", ""),
            timestamp   = d.get("timestamp", ""),
            snapshot    = d.get("snapshot", {}),
            pnl         = d.get("pnl"),
            won         = d.get("won"),
            closed_at   = d.get("closed_at"),
            why_won     = d.get("why_won", []),
            why_lost    = d.get("why_lost", []),
        )
        return r


# ── مكتبة الأنماط ─────────────────────────────────────────────────────────────

class PatternLibrary:
    """
    يحسب ارتباط كل مؤشر بالربح عبر جميع السجلات المُكتملة.

    لكل مؤشر يحتفظ بـ:
        wins_with[indicator]   — عدد الصفقات الرابحة التي كان المؤشر نشطاً فيها
        total_with[indicator]  — إجمالي الصفقات التي كان نشطاً فيها

    معدل فوز مرجَّح = wins_with / total_with
    """

    def __init__(self) -> None:
        self._wins_with:  dict[str, int] = {}
        self._total_with: dict[str, int] = {}
        self._wins_without:  dict[str, int] = {}
        self._total_without: dict[str, int] = {}
        self._total_trades = 0
        self._total_wins   = 0

    def update(self, record: TradeRecord) -> None:
        if record.won is None:
            return
        active = set(record.active_conditions())
        self._total_trades += 1
        if record.won:
            self._total_wins += 1

        # جميع الشروط الممكنة
        all_conds = set(TRACKED_INDICATORS + [
            "rsi_bull","rsi_bear","adx_trending","high_prob",
            "smc_buy_strong","smc_sell_strong","trend_bull","trend_bear"
        ])
        for cond in all_conds:
            if cond in active:
                self._total_with[cond] = self._total_with.get(cond, 0) + 1
                if record.won:
                    self._wins_with[cond] = self._wins_with.get(cond, 0) + 1
            else:
                self._total_without[cond] = self._total_without.get(cond, 0) + 1
                if record.won:
                    self._wins_without[cond] = self._wins_without.get(cond, 0) + 1

    def win_rate_with(self, cond: str) -> float:
        t = self._total_with.get(cond, 0)
        if t == 0:
            return 0.0
        return self._wins_with.get(cond, 0) / t

    def win_rate_without(self, cond: str) -> float:
        t = self._total_without.get(cond, 0)
        if t == 0:
            return 0.0
        return self._wins_without.get(cond, 0) / t

    def indicator_importance(self, min_sample: int = _MIN_SAMPLE) -> list[dict]:
        """
        أعد قائمة المؤشرات مرتبة حسب "قوة الارتباط بالربح".

        القوة = (WR_مع - WR_بدون)  →  كلما أكبر كلما كان المؤشر أكثر ارتباطاً بالربح.
        """
        results = []
        for cond in self._total_with:
            t = self._total_with.get(cond, 0)
            if t < min_sample:
                continue
            wr_with    = self.win_rate_with(cond)
            wr_without = self.win_rate_without(cond)
            lift = wr_with - wr_without  # مقياس "الرفع"
            results.append({
                "indicator":   cond,
                "wr_with":     round(wr_with, 3),
                "wr_without":  round(wr_without, 3),
                "lift":        round(lift, 3),
                "total_with":  t,
                "profitable":  lift > 0.05,
            })
        results.sort(key=lambda x: -x["lift"])
        return results

    def explain(self, record: TradeRecord) -> tuple[list[str], list[str]]:
        """
        اشرح لماذا الصفقة ربحت أو خسرت بناءً على المكتبة الحالية.
        يُعيد (why_won, why_lost).
        """
        active  = record.active_conditions()
        why_won  = []
        why_lost = []
        for cond in active:
            wr = self.win_rate_with(cond)
            t  = self._total_with.get(cond, 0)
            if t < _MIN_SAMPLE:
                continue
            if wr > 0.55:
                why_won.append(f"{cond}(WR={wr:.0%})")
            elif wr < 0.45:
                why_lost.append(f"{cond}(WR={wr:.0%})")
        return why_won, why_lost

    def top_profitable_conditions(self, top_n: int = 10, min_sample: int = _MIN_SAMPLE) -> list[str]:
        """أعد أسماء أكثر المؤشرات ارتباطاً بالربح."""
        return [
            r["indicator"]
            for r in self.indicator_importance(min_sample)[:top_n]
            if r["profitable"]
        ]

    def to_dict(self) -> dict:
        return {
            "wins_with":    self._wins_with,
            "total_with":   self._total_with,
            "wins_without": self._wins_without,
            "total_without":self._total_without,
            "total_trades": self._total_trades,
            "total_wins":   self._total_wins,
        }

    def from_dict(self, d: dict) -> None:
        self._wins_with     = {k: int(v) for k, v in d.get("wins_with", {}).items()}
        self._total_with    = {k: int(v) for k, v in d.get("total_with", {}).items()}
        self._wins_without  = {k: int(v) for k, v in d.get("wins_without", {}).items()}
        self._total_without = {k: int(v) for k, v in d.get("total_without", {}).items()}
        self._total_trades  = int(d.get("total_trades", 0))
        self._total_wins    = int(d.get("total_wins", 0))


# ── مدير الذاكرة الرئيسي ─────────────────────────────────────────────────────

class IndicatorMemory:
    """
    يدير دورة حياة سجلات الصفقات ومكتبة الأنماط.

    الاستخدام:
        memory = IndicatorMemory()
        memory.record_entry(ticket, symbol, side, price, snapshot, genome_id, source)
        memory.record_exit(ticket, pnl)
        top = memory.top_profitable_conditions()
        importance = memory.importance_report()
    """

    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._records: dict[str, TradeRecord] = {}   # trade_id → record
        self._library = PatternLibrary()
        self._closed_records: list[TradeRecord] = []
        self._load()

    # ── API ───────────────────────────────────────────────────────────────────

    def record_entry(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        snapshot: dict,
        genome_id: str = "",
        source: str = "bot",
    ) -> None:
        rec = TradeRecord(
            trade_id    = str(trade_id),
            symbol      = symbol,
            side        = side,
            entry_price = float(entry_price),
            source      = source,
            genome_id   = genome_id,
            timestamp   = datetime.now(timezone.utc).isoformat(),
            snapshot    = dict(snapshot),
        )
        with self._lock:
            self._records[str(trade_id)] = rec
        log.debug("[IndicatorMemory] Entry recorded: %s %s %s source=%s", trade_id, symbol, side, source)

    def record_exit(self, trade_id: str, pnl: float) -> TradeRecord | None:
        tid = str(trade_id)
        with self._lock:
            rec = self._records.pop(tid, None)

        if not rec:
            log.debug("[IndicatorMemory] No entry found for %s", tid)
            return None

        rec.close(pnl, self._library)
        self._library.update(rec)

        with self._lock:
            self._closed_records.append(rec)
            if len(self._closed_records) > _MAX_RECORDS:
                self._closed_records = self._closed_records[-_MAX_RECORDS:]

        self._save()

        log.info(
            "[IndicatorMemory] Closed %s %s pnl=%.2f won=%s why_won=%s why_lost=%s",
            tid, rec.symbol, pnl, rec.won, rec.why_won[:3], rec.why_lost[:2],
        )
        return rec

    def top_profitable_conditions(self, top_n: int = 10) -> list[str]:
        return self._library.top_profitable_conditions(top_n)

    def importance_report(self) -> list[dict]:
        return self._library.indicator_importance()

    def human_trades_summary(self) -> dict:
        """ملخص الصفقات اليدوية فقط."""
        with self._lock:
            human = [r for r in self._closed_records if r.source == "human"]
        if not human:
            return {"count": 0, "wins": 0, "total_pnl": 0.0, "win_rate": 0.0, "top_conditions": []}
        wins  = sum(1 for r in human if r.won)
        pnl   = sum(r.pnl for r in human if r.pnl is not None)
        # أكثر الشروط المشتركة في الصفقات اليدوية الرابحة
        cond_wins: dict[str, int] = {}
        cond_total: dict[str, int] = {}
        for r in human:
            for c in r.active_conditions():
                cond_total[c] = cond_total.get(c, 0) + 1
                if r.won:
                    cond_wins[c] = cond_wins.get(c, 0) + 1
        top = sorted(
            [(c, cond_wins.get(c, 0) / max(t, 1), t)
             for c, t in cond_total.items() if t >= 2],
            key=lambda x: -x[1]
        )
        return {
            "count":          len(human),
            "wins":           wins,
            "total_pnl":      round(pnl, 2),
            "win_rate":       round(wins / len(human), 3),
            "top_conditions": [{"cond": c, "wr": round(w, 3), "total": t} for c, w, t in top[:5]],
        }

    def get_open_entry(self, trade_id: str) -> TradeRecord | None:
        with self._lock:
            return self._records.get(str(trade_id))

    def recent_closed(self, n: int = 20) -> list[dict]:
        with self._lock:
            recs = self._closed_records[-n:]
        return [r.to_dict() for r in reversed(recs)]

    # ── التخزين والاسترجاع ────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            _MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = {
                    "library":  self._library.to_dict(),
                    "closed":   [r.to_dict() for r in self._closed_records[-_MAX_RECORDS:]],
                    "open":     {k: v.to_dict() for k, v in self._records.items()},
                }
            _MEMORY_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("[IndicatorMemory] Save failed: %s", exc)

    def _load(self) -> None:
        try:
            if not _MEMORY_FILE.exists():
                return
            data = json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
            self._library.from_dict(data.get("library", {}))
            for d in data.get("closed", []):
                try:
                    self._closed_records.append(TradeRecord.from_dict(d))
                except Exception:
                    pass
            for k, d in data.get("open", {}).items():
                try:
                    self._records[k] = TradeRecord.from_dict(d)
                except Exception:
                    pass
            log.info(
                "[IndicatorMemory] Loaded: %d closed, %d open",
                len(self._closed_records), len(self._records),
            )
        except Exception as exc:
            log.warning("[IndicatorMemory] Load failed: %s", exc)
