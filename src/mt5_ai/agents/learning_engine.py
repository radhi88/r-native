"""
LearningEngine — محرك التعلم المستقل لكل رمز تداول.

كل زوج (agent, symbol) له:
- عتباته الخاصة (buy/sell threshold, min_smc_score)
- سجل صفقاته المنفصل في CSV
- تكيّف تلقائي قائم على P&L-weighted win rate بعد 8 صفقات
- تتبع أداء منفصل لكل نمط إعداد (setup_reason)

مثال:
  smc|XAUUSDm  ← عتبات وصفقات الذهب
  smc|EURUSD   ← عتبات وصفقات اليورو/دولار
  scalping|XAUUSDm ← وكيل السكالبينج للذهب
"""

import csv
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..config import DATA_DIR, JOURNAL_DIR

# ── PatternAnalyzer integration (اختيارية — backward-compatible) ──────────────
try:
    from ..indicator_snapshot import PatternAnalyzer as _PatternAnalyzer
    _pattern_analyzer: Any = _PatternAnalyzer()
except ImportError:
    _PatternAnalyzer = None   # type: ignore
    _pattern_analyzer: Any = None

log = logging.getLogger("friday.learning")

_STATE_FILE       = DATA_DIR / "symbol_thresholds.json"
_SETUP_STATE_FILE = DATA_DIR / "setup_performance.json"
_TRADE_LOG        = JOURNAL_DIR / "agent_trades.csv"

# Updated fields — setup_reason added; old rows without it get "" as default
_TRADE_FIELDS = [
    "agent", "symbol", "side", "entry", "exit",
    "points", "won", "setup_reason", "timestamp",
]
_LEGACY_TRADE_FIELDS    = ["agent", "side", "entry", "exit", "points", "won", "timestamp"]
_LEGACY_TRADE_FIELDS_V2 = ["agent", "symbol", "side", "entry", "exit", "points", "won", "timestamp"]

# إعدادات افتراضية لكل وكيل
_AGENT_DEFAULTS = {
    "smc":      {"buy_threshold": 0.60, "sell_threshold": 0.40, "min_smc_score": 2, "atr_sl_mult": 1.5, "min_rr": 1.2},
    "scalping": {"buy_threshold": 0.68, "sell_threshold": 0.32, "min_smc_score": 1, "atr_sl_mult": 1.5, "min_rr": 1.2},
    "swing":    {"buy_threshold": 0.65, "sell_threshold": 0.35, "min_smc_score": 1, "atr_sl_mult": 1.5, "min_rr": 1.2},
    "pending":  {"buy_threshold": 0.67, "sell_threshold": 0.33, "min_smc_score": 1, "atr_sl_mult": 1.5, "min_rr": 1.2},
}

_BOUNDS = {
    "buy_threshold":  (0.55, 0.90),
    "sell_threshold": (0.10, 0.45),
    "min_smc_score":  (1, 5),
    "atr_sl_mult":    (1.0, 3.5),   # مسافة SL من السعر بوحدات ATR
    "min_rr":         (1.0, 3.0),   # نسبة R:R الدنيا للدخول
}

_DEFAULT_UPDATE_EVERY  = 5     # adapt thresholds every N closed trades per (agent, symbol)
_DEFAULT_HALFLIFE_BARS = 240   # idle decay: halve distance-to-baseline every 240 elapsed bars
                                # (~4h on M1) — quiet symbols drift back to baseline slowly

# Performance thresholds for setup classification
_SETUP_GOOD_WR  = 0.55   # above this → considered a good setup
_SETUP_BAD_WR   = 0.45   # below this → considered a bad setup
_SETUP_GREAT_WR = 0.65   # threshold for aggressive loosening of probability gates


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _key(agent: str, symbol: str) -> str:
    return f"{agent}|{symbol}"


def _setup_key(agent: str, symbol: str, reason: str) -> str:
    return f"{agent}|{symbol}|{reason}"


class LearningEngine:
    """
    محرك تعلم مدرك للرمز.
    كل زوج (agent, symbol) مستقل تماماً — ذاكرة، عتبات، وتكيّف منفصلان.

    الميزات الجديدة:
    - P&L-weighted win rate: الصفقات الكبيرة تؤثر أكثر على التكيّف
    - تكيّف بخطوة تدريجية (gradient-based signal) بدلاً من if/elif الثابت
    - تتبع أداء منفصل لكل نمط إعداد (setup_reason)
    - واجهات best_setups / worst_setups / get_setup_thresholds
    """

    def __init__(self, update_every: int = _DEFAULT_UPDATE_EVERY,
                 halflife_bars: int = _DEFAULT_HALFLIFE_BARS):
        _TRADE_LOG.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_trade_log_schema()
        self._state: dict[str, dict] = self._load_state()
        self._setup_state: dict[str, dict] = self._load_setup_state()
        self.update_every  = max(1, int(update_every))
        self.halflife_bars = max(1, int(halflife_bars))
        # per-(agent|symbol) closed-trade counter since last actual adaptation
        self._since_update: dict[str, int] = {}

    # ── API العام ────────────────────────────────────────────────────────────────

    def thresholds(self, agent: str, symbol: str = "") -> dict:
        """أعد عتبات الوكيل الخاصة بالرمز. تُنشأ من الافتراضي عند أول استدعاء."""
        k = _key(agent, symbol) if symbol else agent
        if k not in self._state:
            base = _AGENT_DEFAULTS.get(agent, _AGENT_DEFAULTS["smc"])
            self._state[k] = dict(base)
        return self._state[k]

    def trades_since_last_update(self, agent: str, symbol: str = "") -> int:
        """عدد الصفقات المغلقة منذ آخر تكيّف فعلي لهذا الزوج (0..update_every)."""
        k = _key(agent, symbol) if symbol else agent
        return int(self._since_update.get(k, 0))

    def record(
        self,
        agent: str,
        symbol: str,
        side: str,
        entry: float,
        exit_price: float,
        points: float,
        setup_reason: str = "",
    ):
        """سجّل صفقة مغلقة وكيّف العتبات إذا تراكم عدد كافٍ."""
        row = {
            "agent":        agent,
            "symbol":       symbol,
            "side":         side,
            "entry":        entry,
            "exit":         exit_price,
            "points":       points,
            "won":          points > 0,
            "setup_reason": setup_reason,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }
        self._append_log(row)
        k = _key(agent, symbol) if symbol else agent
        self._since_update[k] = self._since_update.get(k, 0) + 1
        if self._since_update[k] >= self.update_every:
            self._since_update[k] = 0
            self._adapt(agent, symbol)
        if setup_reason:
            self.record_setup(
                agent=agent,
                symbol=symbol,
                setup_reason=setup_reason,
                side=side,
                entry=entry,
                exit_price=exit_price,
                points=points,
            )

    def summary(self, agent: str, symbol: str = "", lookback: int = 50) -> dict:
        """ملخص أداء الوكيل للرمز المحدد."""
        rows = self._load_rows(agent=agent, symbol=symbol, lookback=lookback)
        n    = len(rows)
        if n == 0:
            return {"trades": 0, "symbol": symbol, "thresholds": self.thresholds(agent, symbol)}

        wins       = sum(1 for r in rows if r.get("won") in ("True", True, 1))
        pts        = [float(r["points"]) for r in rows]
        gross_win  = sum(p for p in pts if p > 0)
        gross_loss = abs(sum(p for p in pts if p < 0)) or 1e-9
        return {
            "trades":          n,
            "symbol":          symbol,
            "win_rate":        wins / n,
            "pnl_weighted_wr": self._pnl_weighted_wr(rows),
            "profit_factor":   gross_win / gross_loss,
            "avg_r":           sum(pts) / n,
            "thresholds":      dict(self.thresholds(agent, symbol)),
        }

    def risk_params(self, agent: str, symbol: str = "") -> dict:
        """أعد معاملات المخاطرة المكتسبة (atr_sl_mult, min_rr)."""
        t = self.thresholds(agent, symbol)
        return {
            "atr_sl_mult": t.get("atr_sl_mult", 1.5),
            "min_rr":      t.get("min_rr", 1.2),
        }

    def record_snapshot(self, snap) -> None:
        """
        يحفظ IndicatorSnapshot إلى data/indicator_snapshots.csv.
        يُستدعى لحظة الدخول — النتيجة تُضاف لاحقاً عبر update_snapshot_outcome.
        """
        try:
            from ..indicator_snapshot import save_snapshot
            save_snapshot(snap)
            log.debug("[snapshot.save] %s %s %s", snap.symbol, snap.side, snap.setup_reason)
        except Exception as exc:
            log.debug("record_snapshot failed (non-fatal): %s", exc)

    # ── توافق خلفي للوكلاء القديمة (بدون symbol) ─────────────────────────────────

    def thresholds_legacy(self, agent: str) -> dict:
        return self.thresholds(agent, symbol="")

    def record_legacy(self, agent: str, side: str, entry: float, exit_price: float, points: float):
        self.record(agent=agent, symbol="", side=side,
                    entry=entry, exit_price=exit_price, points=points)

    def summary_legacy(self, agent: str, lookback: int = 50) -> dict:
        return self.summary(agent=agent, symbol="", lookback=lookback)

    # ── Setup-Level Tracking ─────────────────────────────────────────────────────

    def record_setup(
        self,
        agent: str,
        symbol: str,
        setup_reason: str,
        side: str,
        entry: float,
        exit_price: float,
        points: float,
    ):
        """
        سجّل نتيجة صفقة مرتبطة بنمط إعداد معين.

        يُخزَّن في _SETUP_STATE_FILE بمفتاح  agent|symbol|reason
        ويتتبع: trades, wins, total_pts, win_pts, loss_pts
        """
        sk = _setup_key(agent, symbol, setup_reason)
        entry_data = self._setup_state.setdefault(sk, {
            "agent":     agent,
            "symbol":    symbol,
            "reason":    setup_reason,
            "trades":    0,
            "wins":      0,
            "total_pts": 0.0,
            "win_pts":   0.0,
            "loss_pts":  0.0,
        })
        entry_data["trades"]    += 1
        entry_data["total_pts"] += points
        if points > 0:
            entry_data["wins"]    += 1
            entry_data["win_pts"] += points
        else:
            entry_data["loss_pts"] += abs(points)

        self._save_setup_state()
        log.debug("[setup] %s  pts=%.1f  trades=%d  wins=%d",
                  sk, points, entry_data["trades"], entry_data["wins"])

    def setup_summary(self, agent: str, symbol: str) -> list[dict]:
        """
        أعد قائمة مرتبة بأداء كل نمط إعداد لزوج (agent, symbol).

        الشكل:
        [{"reason": "ssl_sweep+bos_up+ob", "trades": 50, "wr": 0.62,
          "avg_pts": 15.3, "profit_factor": 1.8}, ...]
        """
        results = []
        prefix = f"{agent}|{symbol}|"
        for sk, data in self._setup_state.items():
            if not sk.startswith(prefix):
                continue
            trades = data.get("trades", 0)
            if trades == 0:
                continue
            wins      = data.get("wins", 0)
            total_pts = data.get("total_pts", 0.0)
            win_pts   = data.get("win_pts", 0.0)
            loss_pts  = data.get("loss_pts", 1e-9) or 1e-9
            results.append({
                "reason":       data.get("reason", sk.split("|", 2)[-1]),
                "trades":       trades,
                "wr":           wins / trades,
                "avg_pts":      total_pts / trades,
                "avg_pts_win":  win_pts / wins if wins else 0.0,
                "avg_pts_loss": -(loss_pts / (trades - wins)) if trades > wins else 0.0,
                "profit_factor": win_pts / loss_pts,
            })
        results.sort(key=lambda x: (x["wr"], x["avg_pts"]), reverse=True)
        return results

    def best_setups(self, agent: str, symbol: str, min_trades: int = 10) -> list[str]:
        """
        أعد قائمة بأنماط الإعداد ذات الأداء الجيد:
        WR > 0.55 وavg_pts > 0 وعدد الصفقات >= min_trades.

        تُستخدم لتوجيه وكيل الدخول نحو الأنماط المثبتة.
        """
        return [
            s["reason"]
            for s in self.setup_summary(agent, symbol)
            if s["trades"] >= min_trades
            and s["wr"] > _SETUP_GOOD_WR
            and s["avg_pts"] > 0
        ]

    def worst_setups(self, agent: str, symbol: str, min_trades: int = 10) -> list[str]:
        """
        أعد قائمة بأنماط الإعداد ذات الأداء الضعيف:
        WR < 0.45 أو avg_pts < 0 وعدد الصفقات >= min_trades.

        تُستخدم لتجنب الأنماط السيئة أو حظرها.
        """
        return [
            s["reason"]
            for s in self.setup_summary(agent, symbol)
            if s["trades"] >= min_trades
            and (s["wr"] < _SETUP_BAD_WR or s["avg_pts"] < 0)
        ]

    def get_setup_thresholds(self, setup_reason: str) -> dict:
        """
        أعد عتبات الاحتمالية المخصصة لنمط إعداد معين بناءً على أدائه التاريخي.

        - WR > 0.65 → عتبات أسهل (يستحق الدخول بثقة أقل)
        - WR < 0.50 → عتبات أصعب (يحتاج ثقة أعلى)
        - غير ذلك  → افتراضي
        """
        # Aggregate across all agent|symbol combinations for this reason
        total_trades = 0
        total_wins   = 0
        for sk, data in self._setup_state.items():
            if sk.endswith(f"|{setup_reason}"):
                total_trades += data.get("trades", 0)
                total_wins   += data.get("wins", 0)

        if total_trades == 0:
            return {"min_prob_buy": 0.60, "min_prob_sell": 0.40}

        wr = total_wins / total_trades
        if wr > _SETUP_GREAT_WR:
            return {"min_prob_buy": 0.55, "min_prob_sell": 0.45}
        if wr < 0.50:
            return {"min_prob_buy": 0.70, "min_prob_sell": 0.30}
        return {"min_prob_buy": 0.60, "min_prob_sell": 0.40}

    # ── P&L-Weighted Win Rate ────────────────────────────────────────────────────

    @staticmethod
    def _pnl_weighted_wr(rows: list) -> float:
        """
        حساب معدل الفوز المرجَّح بحجم P&L.

        كل صفقة لها "وزن" = abs(pts) / median(abs(pts)), مُقيَّد بـ 3.0.
        صفقة بـ 100 نقطة تؤثر 10× أكثر من صفقة بـ 10 نقاط.
        """
        if not rows:
            return 0.0
        pts        = [float(r["points"]) for r in rows]
        magnitudes = [abs(p) for p in pts]
        median_mag = float(np.median(magnitudes)) if magnitudes else 1.0
        weights    = [min(m / (median_mag + 1e-9), 3.0) for m in magnitudes]
        wins       = [1 if p > 0 else 0 for p in pts]
        weighted_wins = sum(w * win for w, win in zip(weights, wins))
        total_weight  = sum(weights)
        return weighted_wins / (total_weight + 1e-9)

    # ── تكيّف العتبات (gradient-based) ──────────────────────────────────────────

    def _adapt(self, agent: str, symbol: str):
        """
        تكيّف العتبات باستخدام إشارة مشتقة (gradient-based signal).

        - يحسب P&L-weighted WR وProfit Factor
        - يبني إشارة مركّبة [-1, +1]
        - حجم الخطوة يتناسب مع شدة الإشارة (خطأ أكبر → خطوة أكبر)
        - يكيّف: buy/sell threshold، atr_sl_mult، min_rr
        """
        rows = self._load_rows(agent=agent, symbol=symbol, lookback=30)
        if len(rows) < 8:
            return

        pts        = [float(r["points"]) for r in rows]
        gross_win  = sum(p for p in pts if p > 0)
        gross_loss = abs(sum(p for p in pts if p < 0)) or 1e-9
        pf         = gross_win / gross_loss

        pnl_wr = self._pnl_weighted_wr(rows)

        # Target: WR=0.55, PF=1.5 are "good performance"
        wr_gap = pnl_wr - 0.55                          # positive = doing well
        pf_gap = min(pf, 3.0) / 1.5 - 1.0              # positive = doing well

        # Combined signal: −1 (very bad) → +1 (very good)
        signal = 0.6 * wr_gap + 0.4 * _clamp(pf_gap, -1.0, 1.0)

        # Adaptive step: larger when far from target; accelerates on great performance
        base_step = 0.01 * (1.0 + abs(signal))
        if pnl_wr >= _SETUP_GREAT_WR:
            base_step *= 1.8   # accelerate learning when performing great
        step = _clamp(base_step, 0.005, 0.045)

        k = _key(agent, symbol) if symbol else agent
        t = self._state.setdefault(k, dict(_AGENT_DEFAULTS.get(agent, _AGENT_DEFAULTS["smc"])))

        if signal > 0.05:
            # Performing well → loosen thresholds to catch more trades
            t["buy_threshold"]  = _clamp(t["buy_threshold"]  - step, *_BOUNDS["buy_threshold"])
            t["sell_threshold"] = _clamp(t["sell_threshold"] + step, *_BOUNDS["sell_threshold"])
            if signal > 0.15:
                # Very well → tighten SL slightly, raise min RR
                t["atr_sl_mult"] = _clamp(t.get("atr_sl_mult", 1.5) - 0.05, *_BOUNDS["atr_sl_mult"])
                t["min_rr"]      = _clamp(t.get("min_rr", 1.2)      + 0.05, *_BOUNDS["min_rr"])
            log.info(
                "[%s|%s] PnL-WR=%.0f%% signal=+%.3f step=%.3f → loosened  "
                "buy=%.3f sell=%.3f SL_mult=%.2f RR=%.2f",
                agent, symbol, pnl_wr * 100, signal, step,
                t["buy_threshold"], t["sell_threshold"],
                t.get("atr_sl_mult", 1.5), t.get("min_rr", 1.2),
            )

        elif signal < -0.05:
            # Performing poorly → tighten thresholds
            t["buy_threshold"]  = _clamp(t["buy_threshold"]  + step, *_BOUNDS["buy_threshold"])
            t["sell_threshold"] = _clamp(t["sell_threshold"] - step, *_BOUNDS["sell_threshold"])
            if signal < -0.15:
                # Very poorly → widen SL (more breathing room), raise min RR
                t["atr_sl_mult"] = _clamp(t.get("atr_sl_mult", 1.5) + 0.10, *_BOUNDS["atr_sl_mult"])
                t["min_rr"]      = _clamp(t.get("min_rr", 1.2)      + 0.05, *_BOUNDS["min_rr"])
            log.info(
                "[%s|%s] PnL-WR=%.0f%% signal=%.3f step=%.3f → tightened  "
                "buy=%.3f sell=%.3f SL_mult=%.2f RR=%.2f",
                agent, symbol, pnl_wr * 100, signal, step,
                t["buy_threshold"], t["sell_threshold"],
                t.get("atr_sl_mult", 1.5), t.get("min_rr", 1.2),
            )

        else:
            log.debug("[%s|%s] PnL-WR=%.0f%% signal=%.3f → within target band, no change",
                      agent, symbol, pnl_wr * 100, signal)

        self._save_state()

        # ── PatternAnalyzer: أعد بناء القائمة السوداء بعد كل تكيّف ─────────────
        if _pattern_analyzer is not None:
            try:
                _pattern_analyzer.analyze_and_update(agent, symbol)   # ← fixed: was passing wrong kwargs
                log.debug("[PatternAnalyzer] blacklist rebuilt for %s|%s", agent, symbol)
            except Exception as exc:
                log.debug("PatternAnalyzer.analyze_and_update failed (non-fatal): %s", exc)

    def decay_toward_baseline(self, agent: str, symbol: str = "", bars_elapsed: int = 0) -> dict:
        """
        اسحب عتبات الزوج نحو القيمة الافتراضية (_AGENT_DEFAULTS) بمعدل نصف-عمري.
        المسافة إلى الأساس تُنصَّف كل halflife_bars شمعة. يُقاس الخمول بالشموع
        المنقضية (نشاط السوق)، لا بالساعة — فالعطلات لا تجرّ الرمز للأساس.
        """
        if bars_elapsed <= 0:
            return self.thresholds(agent, symbol)
        k    = _key(agent, symbol) if symbol else agent
        t    = self.thresholds(agent, symbol)          # seeds from defaults if new
        base = _AGENT_DEFAULTS.get(agent, _AGENT_DEFAULTS["smc"])
        # fraction of the gap that REMAINS after `bars_elapsed` bars
        keep = 0.5 ** (bars_elapsed / float(self.halflife_bars))
        for name, target in base.items():
            cur = t.get(name, target)
            new = target + (cur - target) * keep      # pull toward target by (1-keep)
            if name in _BOUNDS:
                new = _clamp(new, *_BOUNDS[name])
            # preserve int-typed thresholds (e.g. min_smc_score)
            t[name] = type(target)(round(new)) if isinstance(target, int) else new
        self._state[k] = t
        self._save_state()
        return t

    # ── استعلام الصفوف ────────────────────────────────────────────────────────────

    def _load_rows(
        self,
        agent: str | None = None,
        symbol: str | None = None,
        lookback: int | None = None,
    ) -> list:
        if not _TRADE_LOG.exists():
            return []
        self._ensure_trade_log_schema()
        rows = []
        with open(_TRADE_LOG, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if agent  is not None and r.get("agent")  != agent:              continue
                if symbol is not None and symbol != "" and r.get("symbol") != symbol: continue
                rows.append(r)
        return rows[-lookback:] if lookback else rows

    # ── تحميل / حفظ الحالة ──────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        # دعم الانتقال من الملف القديم
        for path in (_STATE_FILE, DATA_DIR / "agent_thresholds.json"):
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return {}

    def _save_state(self):
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_setup_state(self) -> dict:
        if _SETUP_STATE_FILE.exists():
            try:
                return json.loads(_SETUP_STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_setup_state(self):
        _SETUP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SETUP_STATE_FILE.write_text(
            json.dumps(self._setup_state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _append_log(self, row: dict):
        self._ensure_trade_log_schema()
        exists = _TRADE_LOG.exists() and _TRADE_LOG.stat().st_size > 0
        with open(_TRADE_LOG, "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_TRADE_FIELDS, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            writer.writerow(row)

    def _ensure_trade_log_schema(self):
        """
        Migrate agent_trades.csv to current schema.

        Handles three legacy layouts:
          V0: [agent, side, entry, exit, points, won, timestamp]         (no symbol)
          V1: [agent, symbol, side, entry, exit, points, won, timestamp] (no setup_reason)
          V2: current _TRADE_FIELDS (with setup_reason)
        """
        if not _TRADE_LOG.exists() or _TRADE_LOG.stat().st_size == 0:
            return

        with open(_TRADE_LOG, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            return

        header = rows[0]
        if header == _TRADE_FIELDS:
            return  # already current

        # Determine migration path
        if header not in (_LEGACY_TRADE_FIELDS, _LEGACY_TRADE_FIELDS_V2):
            log.warning("Unexpected agent trade log schema: %s", header)
            return

        normalized: list[dict] = []
        for raw in rows[1:]:
            if not raw or not any(cell.strip() for cell in raw):
                continue

            if header == _LEGACY_TRADE_FIELDS:
                # V0 → V2: no symbol, no setup_reason
                if len(raw) < len(_LEGACY_TRADE_FIELDS):
                    continue
                agent, side, entry, exit_price, points, won, timestamp = raw[:7]
                normalized.append({
                    "agent": agent, "symbol": "", "side": side,
                    "entry": entry, "exit": exit_price,
                    "points": points, "won": won,
                    "setup_reason": "", "timestamp": timestamp,
                })

            else:
                # V1 → V2: has symbol, missing setup_reason
                if len(raw) >= len(_TRADE_FIELDS):
                    normalized.append(dict(zip(_TRADE_FIELDS, raw[:len(_TRADE_FIELDS)])))
                elif len(raw) >= len(_LEGACY_TRADE_FIELDS_V2):
                    agent, symbol, side, entry, exit_price, points, won, timestamp = raw[:8]
                    normalized.append({
                        "agent": agent, "symbol": symbol, "side": side,
                        "entry": entry, "exit": exit_price,
                        "points": points, "won": won,
                        "setup_reason": "", "timestamp": timestamp,
                    })

        if not normalized:
            return

        stamp  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = _TRADE_LOG.with_suffix(f".csv.bak_{stamp}")
        shutil.copy2(_TRADE_LOG, backup)
        log.info("Migrated agent_trades.csv -- backup: %s", backup)

        with open(_TRADE_LOG, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_TRADE_FIELDS)
            writer.writeheader()
            writer.writerows(normalized)
