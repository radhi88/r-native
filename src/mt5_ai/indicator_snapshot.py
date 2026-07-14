"""
IndicatorSnapshot — تصوير كامل لقيم المؤشرات لحظة الإشارة.

يُحفظ مع كل صفقة (دخول وخروج) ليمكّن PatternAnalyzer من:
- تحديد نطاقات المؤشرات المرتبطة بالخسارة
- استبعادها تلقائياً من الإعدادات المستقبلية
- تعزيز الاحتمالية في الظروف التاريخية الجيدة
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.snapshot")

# ── الملف ──────────────────────────────────────────────────────────────────
_SNAPSHOT_CSV  = Path(__file__).parents[2] / "data" / "indicator_snapshots.csv"
_BLACKLIST_JSON = Path(__file__).parents[2] / "data" / "pattern_blacklist.json"

SNAPSHOT_FIELDS = [
    # identity
    "timestamp", "symbol", "agent", "side", "setup_reason",
    # price
    "price", "spread", "spread_ratio",
    # trend / EMA
    "ema_fast", "ema_mid", "ema_slow", "ema_alignment", "trend_score",
    # momentum
    "rsi", "rsi_zone", "momentum_3", "momentum_10",
    # volatility
    "atr", "atr_ratio", "volatility_regime",
    # ADX
    "adx", "adx_regime",
    # SMC flags
    "smc_buy_score", "smc_sell_score",
    "bos_up", "bos_down", "choch_up", "choch_down",
    "bullish_fvg", "bearish_fvg",
    "in_bullish_ob", "in_bearish_ob",
    "ssl_sweep", "bsl_sweep",
    "demand_zone", "supply_zone",
    "distance_to_ob",
    # time
    "hour", "day_of_week", "session",
    # outcome (filled on close)
    "outcome_won", "outcome_points",
]


@dataclass
class IndicatorSnapshot:
    """لقطة كاملة للمؤشرات لحظة إشارة الدخول."""

    # identity
    timestamp:       str   = ""
    symbol:          str   = ""
    agent:           str   = ""
    side:            str   = ""
    setup_reason:    str   = ""

    # price
    price:           float = 0.0
    spread:          float = 0.0
    spread_ratio:    float = 0.0   # spread / atr  (< 1 = tight, > 2 = wide)

    # trend / EMA
    ema_fast:        float = 0.0
    ema_mid:         float = 0.0
    ema_slow:        float = 0.0
    ema_alignment:   str   = "mixed"   # "bull_stack"|"bear_stack"|"mixed"
    trend_score:     float = 0.0       # -1 .. +1

    # momentum
    rsi:             float = 50.0
    rsi_zone:        str   = "neutral" # "overbought"|"oversold"|"neutral"
    momentum_3:      float = 0.0       # (close[0]-close[3]) / atr
    momentum_10:     float = 0.0       # (close[0]-close[10]) / atr

    # volatility
    atr:             float = 0.0
    atr_ratio:       float = 1.0       # atr / avg_atr_20
    volatility_regime: str = "normal"  # "low"|"normal"|"high"|"extreme"

    # ADX
    adx:             float = 20.0
    adx_regime:      str   = "weak"    # "weak"|"moderate"|"strong"|"very_strong"

    # SMC
    smc_buy_score:   int   = 0
    smc_sell_score:  int   = 0
    bos_up:          bool  = False
    bos_down:        bool  = False
    choch_up:        bool  = False
    choch_down:      bool  = False
    bullish_fvg:     bool  = False
    bearish_fvg:     bool  = False
    in_bullish_ob:   bool  = False
    in_bearish_ob:   bool  = False
    ssl_sweep:       bool  = False
    bsl_sweep:       bool  = False
    demand_zone:     bool  = False
    supply_zone:     bool  = False
    distance_to_ob:  float = 999.0     # distance in ATR units to nearest OB

    # time
    hour:            int   = 0
    day_of_week:     int   = 0
    session:         str   = "off"     # "tokyo"|"london"|"ny"|"overlap"|"off"

    # outcome (filled after close)
    outcome_won:     bool  = False
    outcome_points:  float = 0.0

    # ── helpers ────────────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        *,
        symbol: str,
        agent: str,
        side: str,
        setup_reason: str,
        price: float,
        spread: float,
        atr: float,
        avg_atr: float,
        ema_fast: float,
        ema_mid: float,
        ema_slow: float,
        trend_score: float,
        rsi: float,
        adx: float,
        momentum_3: float  = 0.0,
        momentum_10: float = 0.0,
        smc_ctx: dict | None = None,
        liquidity_ctx: dict | None = None,
        distance_to_ob: float = 999.0,
    ) -> "IndicatorSnapshot":
        """Factory — رتّب كل القيم المحسوبة في لقطة واحدة."""
        smc  = smc_ctx  or {}
        lctx = liquidity_ctx or {}
        now  = datetime.now(timezone.utc)

        # EMA alignment
        if ema_fast > ema_mid > ema_slow:
            ema_align = "bull_stack"
        elif ema_fast < ema_mid < ema_slow:
            ema_align = "bear_stack"
        else:
            ema_align = "mixed"

        # RSI zone
        rsi_zone = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"

        # ATR ratio / volatility regime
        avg_a = max(avg_atr, 1e-9)
        atr_r = atr / avg_a
        if atr_r < 0.6:
            vol_regime = "low"
        elif atr_r < 1.5:
            vol_regime = "normal"
        elif atr_r < 2.5:
            vol_regime = "high"
        else:
            vol_regime = "extreme"

        # ADX regime
        if adx < 20:
            adx_reg = "weak"
        elif adx < 30:
            adx_reg = "moderate"
        elif adx < 50:
            adx_reg = "strong"
        else:
            adx_reg = "very_strong"

        # Spread ratio
        spread_ratio = spread / max(atr, 1e-9)

        # Session
        h = now.hour
        if 2 <= h < 9:
            session = "tokyo"
        elif 8 <= h < 13:
            session = "london"
        elif 12 <= h < 17:
            session = "overlap"
        elif 17 <= h < 22:
            session = "ny"
        else:
            session = "off"

        return cls(
            timestamp=now.isoformat(),
            symbol=symbol, agent=agent,
            side=side, setup_reason=setup_reason,
            price=price, spread=spread, spread_ratio=round(spread_ratio, 3),
            ema_fast=ema_fast, ema_mid=ema_mid, ema_slow=ema_slow,
            ema_alignment=ema_align, trend_score=round(trend_score, 4),
            rsi=round(rsi, 2), rsi_zone=rsi_zone,
            momentum_3=round(momentum_3, 4), momentum_10=round(momentum_10, 4),
            atr=round(atr, 5), atr_ratio=round(atr_r, 3),
            volatility_regime=vol_regime,
            adx=round(adx, 2), adx_regime=adx_reg,
            smc_buy_score=smc.get("smc_buy_score", 0),
            smc_sell_score=smc.get("smc_sell_score", 0),
            bos_up=bool(smc.get("bos_up")),
            bos_down=bool(smc.get("bos_down")),
            choch_up=bool(smc.get("choch_up")),
            choch_down=bool(smc.get("choch_down")),
            bullish_fvg=bool(smc.get("bullish_fvg")),
            bearish_fvg=bool(smc.get("bearish_fvg")),
            in_bullish_ob=bool(smc.get("in_bullish_ob")),
            in_bearish_ob=bool(smc.get("in_bearish_ob")),
            ssl_sweep=bool(lctx.get("ssl_sweep_active")),
            bsl_sweep=bool(lctx.get("bsl_sweep_active")),
            demand_zone=bool(smc.get("demand_zone")),
            supply_zone=bool(smc.get("supply_zone")),
            distance_to_ob=round(distance_to_ob, 3),
            hour=h, day_of_week=now.weekday(),
            session=session,
        )

    def to_row(self) -> dict:
        d = asdict(self)
        # convert bools to int for CSV readability
        for k, v in d.items():
            if isinstance(v, bool):
                d[k] = int(v)
        return d

    def set_outcome(self, won: bool, points: float):
        self.outcome_won    = won
        self.outcome_points = points


# ── CSV helpers ────────────────────────────────────────────────────────────

def save_snapshot(snap: IndicatorSnapshot, path: str | None = None) -> str:
    """Append snapshot to CSV. Returns timestamp (record ID). path param accepted for compatibility."""
    csv_path = Path(path) if path else _SNAPSHOT_CSV
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    exists = csv_path.exists() and csv_path.stat().st_size > 0
    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SNAPSHOT_FIELDS, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(snap.to_row())
    return snap.timestamp


def load_snapshots(
    agent: str | None = None,
    symbol: str | None = None,
    min_outcome_points: float | None = None,
) -> list[dict]:
    """Load snapshots with optional filters."""
    if not _SNAPSHOT_CSV.exists():
        return []
    rows = []
    with open(_SNAPSHOT_CSV, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if agent  and r.get("agent")  != agent:  continue
            if symbol and r.get("symbol") != symbol: continue
            # only rows with outcome recorded
            if r.get("outcome_points", "") == "":     continue
            rows.append(r)
    return rows


def update_snapshot_outcome(
    symbol: str,
    side: str,
    entry_approx: float,
    won: bool,
    points: float,
    path: str | None = None,
) -> bool:
    """
    يُحدّث نتيجة أقرب snapshot لم تُسجَّل نتيجته بعد لهذه الصفقة.
    يُستدعى حين تُغلق صفقة — يربط P&L بلقطة المؤشرات الأصلية.
    Returns True if a row was updated.
    """
    csv_path = Path(path) if path else _SNAPSHOT_CSV
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False

    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    side_upper = side.upper()
    tol = max(abs(entry_approx) * 0.002, 1.0)   # 0.2% tolerance أو نقطة واحدة minimum

    updated = False
    for i in range(len(rows) - 1, -1, -1):
        r = rows[i]
        if r.get("symbol") != symbol:
            continue
        if r.get("side", "").upper() != side_upper:
            continue
        # تجاهل الصفوف التي سُجّلت نتيجتها مسبقاً
        try:
            if float(r.get("outcome_points", "0") or "0") != 0.0:
                continue
        except (ValueError, TypeError):
            pass
        # تحقق من قرب سعر الدخول
        try:
            if abs(float(r.get("price", 0) or 0) - entry_approx) > tol:
                continue
        except (ValueError, TypeError):
            continue
        rows[i]["outcome_won"]    = int(won)
        rows[i]["outcome_points"] = round(float(points), 5)
        updated = True
        break

    if updated:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=SNAPSHOT_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        log.info("[snapshot.outcome] %s %s won=%s pts=%.2f", symbol, side, won, points)

    return updated


# ══════════════════════════════════════════════════════════════════════════
# PatternAnalyzer — يحلل الـ snapshots ويبني قائمة الاستبعاد والتعزيز
# ══════════════════════════════════════════════════════════════════════════

class PatternAnalyzer:
    """
    يقسّم قيم كل مؤشر إلى نطاقات (buckets) ويحسب win-rate لكل نطاق.
    النطاقات ذات WR < 0.40 (مع >= 5 صفقات) تُضاف للـ blacklist.
    النطاقات ذات WR > 0.65 تُضاف للـ whitelist.
    """

    # تعريف نطاقات التقسيم لكل مؤشر
    _BUCKETS: dict[str, list] = {
        "rsi":          [0, 20, 30, 40, 50, 60, 70, 80, 100],
        "adx":          [0, 15, 20, 25, 30, 40, 60],
        "spread_ratio": [0, 0.5, 1.0, 1.5, 2.0, 3.0, 999],
        "atr_ratio":    [0, 0.5, 0.8, 1.2, 1.8, 2.5, 999],
        "momentum_3":   [-999, -2, -1, -0.3, 0.3, 1, 2, 999],
        "momentum_10":  [-999, -3, -1.5, -0.5, 0.5, 1.5, 3, 999],
        "hour":         [0, 7, 9, 12, 17, 21, 24],
        "distance_to_ob": [0, 0.5, 1.0, 2.0, 3.0, 999],
    }
    _MIN_TRADES    = 5
    _BAD_WR        = 0.40
    _GOOD_WR       = 0.65

    def __init__(self):
        self._blacklist: dict = self._load_blacklist()

    # ── public API ─────────────────────────────────────────────────────────

    def analyze_and_update(self, agent: str, symbol: str):
        """Full analysis — rebuild blacklist from snapshot history."""
        rows = load_snapshots(agent=agent, symbol=symbol)
        if len(rows) < self._MIN_TRADES:
            return

        new_bad:  dict[str, dict] = {}
        new_good: dict[str, dict] = {}

        for col, edges in self._BUCKETS.items():
            for i in range(len(edges) - 1):
                lo, hi = edges[i], edges[i + 1]
                bucket_rows = [
                    r for r in rows
                    if _in_bucket(r.get(col), lo, hi)
                ]
                n = len(bucket_rows)
                if n < self._MIN_TRADES:
                    continue
                wins = sum(1 for r in bucket_rows if str(r.get("outcome_won")) in ("1", "True"))
                wr = wins / n

                bucket_key = f"{col}:{lo}-{hi}"
                if wr < self._BAD_WR:
                    new_bad[bucket_key] = {
                        "col": col, "lo": lo, "hi": hi,
                        "wr": round(wr, 3), "trades": n,
                    }
                    log.info("[PatternAnalyzer] BAD bucket %s  WR=%.0f%%  n=%d",
                             bucket_key, wr * 100, n)
                elif wr > self._GOOD_WR:
                    new_good[bucket_key] = {
                        "col": col, "lo": lo, "hi": hi,
                        "wr": round(wr, 3), "trades": n,
                    }

        k = f"{agent}|{symbol}"
        self._blacklist[k] = {
            "bad_buckets":  new_bad,
            "good_buckets": new_good,
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        }
        self._save_blacklist()
        log.info("[PatternAnalyzer] %s — bad=%d good=%d buckets",
                 k, len(new_bad), len(new_good))

    def snapshot_is_excluded(self, snap: IndicatorSnapshot) -> tuple[bool, str]:
        """
        Returns (True, reason) if the snapshot matches a known bad pattern.
        Returns (False, "") if safe.
        """
        k = f"{snap.agent}|{snap.symbol}"
        data = self._blacklist.get(k, {})
        bad = data.get("bad_buckets", {})
        snap_dict = asdict(snap)

        for bk, info in bad.items():
            col, lo, hi = info["col"], info["lo"], info["hi"]
            val = snap_dict.get(col)
            if val is not None and _in_bucket(val, lo, hi):
                reason = (
                    f"blacklisted:{col}={val:.2f} in [{lo},{hi}) "
                    f"WR={info['wr']:.0%} n={info['trades']}"
                )
                return True, reason
        return False, ""

    def confidence_bonus(self, snap: IndicatorSnapshot) -> float:
        """
        Returns probability bonus (0..+0.12) if snapshot matches a good pattern.
        """
        k = f"{snap.agent}|{snap.symbol}"
        data = self._blacklist.get(k, {})
        good = data.get("good_buckets", {})
        snap_dict = asdict(snap)
        bonus = 0.0
        for bk, info in good.items():
            col, lo, hi = info["col"], info["lo"], info["hi"]
            val = snap_dict.get(col)
            if val is not None and _in_bucket(val, lo, hi):
                bonus += (info["wr"] - self._GOOD_WR) * 0.5   # max ~0.04 per match
        return min(bonus, 0.12)

    def get_worst_indicators(self, agent: str, symbol: str) -> list[str]:
        """Human-readable list of the worst indicator ranges."""
        k = f"{agent}|{symbol}"
        data = self._blacklist.get(k, {})
        return [
            f"{i['col']} in [{i['lo']},{i['hi']}) WR={i['wr']:.0%}"
            for i in sorted(data.get("bad_buckets", {}).values(),
                            key=lambda x: x["wr"])[:5]
        ]

    # ── persistence ────────────────────────────────────────────────────────

    def _load_blacklist(self) -> dict:
        if _BLACKLIST_JSON.exists():
            try:
                return json.loads(_BLACKLIST_JSON.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_blacklist(self):
        _BLACKLIST_JSON.parent.mkdir(parents=True, exist_ok=True)
        _BLACKLIST_JSON.write_text(
            json.dumps(self._blacklist, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _in_bucket(val, lo, hi) -> bool:
    try:
        v = float(val)
        return lo <= v < hi
    except (TypeError, ValueError):
        return False
