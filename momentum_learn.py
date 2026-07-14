# -*- coding: utf-8 -*-
"""momentum_learn.py — حلقة تعلّم حقيقيّة لمحرّك الزخم (momentum_harvester, magic 20260630).

الفكرة (إغلاق الحلقة):
  • record(...)  ← يستدعيه momentum_harvester عند كل فتح: يسجّل ميزات الصفقة (قوّة الاتجاه، الجلسة،
    الساعة UTC، مجموعة الرمز، ATR) في momentum_features.jsonl.
  • measure()    ← يقرأ الصفقات **المغلقة** للماجيك 20260630 من friday.db، يربطها بالميزات المسجّلة
    (بالرمز + أقرب زمن)، ويحسب صافي التوقّع (expectancy) لكل **دلو ميزة**:
      - تيرتيل قوّة الاتجاه (ضعيف/متوسّط/قويّ)
      - جلسة UTC (Asian / London / NY)
      - مجموعة الرمز (FX-major / cross / metal)
    ثم يكتب momentum_edge.json = {by_session, by_strength, by_group, updated}.
  • edge_filter(sym, feats) ← يستدعيه الحاصد قبل الفتح ليتخطّى الدلاء التي وجدها measure() **سالبة صافياً**.
  • main()       ← حلقة بلا-نافذة تستدعي measure() كل ~10 دقائق.

النزاهة: مع عددٍ قليل من الصفقات الدلاء ضوضائيّة — لا نثق بحكم دلوٍ قبل n>=MIN_N (افتراضيّاً 20)؛
وإلا = محايد (لا نحظر). لا صفقات حيّة هنا — قياسٌ وتعلّم فقط.
"""
from __future__ import annotations
import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\Radhi\MT5")
DB = ROOT / "data" / "friday.db"
FEATURES = ROOT / "data" / "r_native" / "momentum_features.jsonl"
EDGE = ROOT / "data" / "r_native" / "momentum_edge.json"

MAGIC = 20260630
MIN_N = 20            # نزاهة: لا نثق بحكم دلوٍ قبل هذا العدد من الصفقات المغلقة (غير ذلك = محايد)
POLL_S = 600.0        # ~10 دقائق
JOIN_WINDOW_S = 1800  # نافذة الربط بين صفقة DB وميزة مسجّلة (نصف ساعة)

# ── مجموعات الرموز ──────────────────────────────────────────────────────────
_METALS = {"XAU", "XAG", "XPT", "XPD"}
_MAJORS = {"EURUSD", "USDJPY", "GBPUSD", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD"}
# ── تيرتيلات قوّة الاتجاه (|عائد|/ATR) — حدود ثابتة شفّافة ──────────────────
_STRENGTH_EDGES = (1.8, 2.6)   # < weak / mid / >= strong  (STRENGTH_MIN في الحاصد = 1.5)


# ════════════════════════════════════════════════════════════════════════════
#  مساعدات التصنيف (مشتركة بين record/measure/edge_filter لتطابق الدلاء)
# ════════════════════════════════════════════════════════════════════════════
def _base(sym: str) -> str:
    """رمز الأساس بدون لاحقة الوسيط (m)، بأحرف كبيرة."""
    return (sym or "").upper().rstrip("M")


def symbol_group(sym: str) -> str:
    b = _base(sym)
    if b[:3] in _METALS:
        return "metal"
    if b in _MAJORS:
        return "fx-major"
    return "cross"


def session_of(hour_utc: int) -> str:
    """جلسة تداول تقريبيّة بالساعة UTC. (تتداخل لندن/نيويورك؛ نعتمد التصنيف الغالب.)"""
    h = int(hour_utc) % 24
    if 0 <= h < 7:
        return "Asian"
    if 7 <= h < 12:
        return "London"
    if 12 <= h < 21:
        return "NY"
    return "Asian"            # 21-24 ⇒ عودة آسيا


def strength_tertile(strength: float) -> str:
    """دلو قوّة الاتجاه: strength = |عائد النافذة| / ATR(D1)."""
    s = float(strength or 0.0)
    lo, hi = _STRENGTH_EDGES
    if s < lo:
        return "weak"
    if s < hi:
        return "mid"
    return "strong"


# ════════════════════════════════════════════════════════════════════════════
#  (a) record — يستدعيه momentum_harvester عند كل فتح
# ════════════════════════════════════════════════════════════════════════════
def record(sym: str, direction: int, feats: dict | None = None) -> bool:
    """يُلحق صفّ ميزات لصفقة فتحٍ في momentum_features.jsonl.

    feats المتوقّعة (كلّها اختياريّة، تُملأ افتراضيّاً): strength (|عائد|/ATR), atr, hour (UTC),
    ويُشتقّ منها session/group. fail-open: لا يرمي استثناء أبداً (لا يعرقل التداول).
    """
    try:
        feats = dict(feats or {})
        ts = float(feats.get("ts") or time.time())
        hour = feats.get("hour")
        if hour is None:
            hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        hour = int(hour) % 24
        strength = float(feats.get("strength") or 0.0)
        row = {
            "ts": ts,
            "iso": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "sym": sym,
            "dir": int(direction),
            "strength": round(strength, 4),
            "hour": hour,
            "session": feats.get("session") or session_of(hour),
            "group": feats.get("group") or symbol_group(sym),
            "atr": round(float(feats.get("atr") or 0.0), 6),
        }
        # أيّ مفاتيح إضافيّة يمرّرها المتّصل (مثلاً h4_aligned)
        for k, v in feats.items():
            if k not in row and k not in ("session", "group", "hour", "ts", "strength", "atr"):
                row[k] = v
        FEATURES.parent.mkdir(parents=True, exist_ok=True)
        with open(FEATURES, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════════════════
#  قراءة الميزات المسجّلة
# ════════════════════════════════════════════════════════════════════════════
def _load_features() -> list[dict]:
    out = []
    if not FEATURES.exists():
        return out
    try:
        with open(FEATURES, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _closed_trades() -> list[dict]:
    """صفقات الماجيك 20260630 المغلقة من friday.db (closed=1)."""
    out = []
    if not DB.exists():
        return out
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        # net إن وُجد وإلا pnl؛ نأخذ closed=1 فقط (صفقة مكتملة لها نتيجة حقيقيّة)
        cur.execute(
            "SELECT symbol, ts, lots, pnl, "
            "COALESCE(net, pnl) AS net "
            "FROM trades WHERE magic=? AND closed=1 ORDER BY ts",
            (MAGIC,),
        )
        for r in cur.fetchall():
            out.append({
                "symbol": r["symbol"],
                "ts": float(r["ts"]),
                "lots": float(r["lots"] or 0.0),
                "pnl": float(r["pnl"] or 0.0),
                "net": float(r["net"] or 0.0),
            })
        con.close()
    except Exception:
        pass
    return out


def _join(trades: list[dict], feats: list[dict]) -> list[dict]:
    """يربط كل صفقة مغلقة بأقرب صفّ ميزات على نفس الرمز ضمن JOIN_WINDOW_S.

    إن لم تتوفّر ميزات مطابقة (مثلاً صفقات قديمة قبل تفعيل التسجيل) نشتقّ ما نقدر من DB ts نفسه
    (الساعة/الجلسة/المجموعة) حتى لا نخسر العيّنة — قوّة الاتجاه تبقى مجهولة (None) فتُستثنى من by_strength فقط.
    """
    by_sym: dict[str, list[dict]] = {}
    for fr in feats:
        by_sym.setdefault(_base(fr.get("sym", "")), []).append(fr)

    joined = []
    for t in trades:
        b = _base(t["symbol"])
        best = None
        best_dt = None
        for fr in by_sym.get(b, []):
            dt = abs(float(fr.get("ts", 0.0)) - t["ts"])
            if dt <= JOIN_WINDOW_S and (best_dt is None or dt < best_dt):
                best, best_dt = fr, dt
        hour = datetime.fromtimestamp(t["ts"], tz=timezone.utc).hour
        rec = {
            "symbol": t["symbol"],
            "net": t["net"],
            "group": symbol_group(t["symbol"]),
            "session": session_of(hour),
            "strength": None,
        }
        if best is not None:
            # نفضّل الساعة/الجلسة المسجّلة (لحظة الفتح الفعليّة) إن وُجدت
            if best.get("hour") is not None:
                rec["session"] = best.get("session") or session_of(int(best["hour"]))
            if best.get("group"):
                rec["group"] = best["group"]
            if best.get("strength") is not None:
                rec["strength"] = float(best["strength"])
        joined.append(rec)
    return joined


def _bucket_stats(rows: list[dict], keyfn) -> dict:
    """يجمّع الصفوف حسب keyfn ويحسب n / net_sum / expectancy / verdict.

    verdict: 'pay' (n>=MIN_N و exp>0) / 'bleed' (n>=MIN_N و exp<=0) / 'neutral' (n<MIN_N — ضوضاء).
    """
    agg: dict[str, list[float]] = {}
    for r in rows:
        k = keyfn(r)
        if k is None:
            continue
        agg.setdefault(k, []).append(float(r["net"]))
    out = {}
    for k, nets in agg.items():
        n = len(nets)
        tot = sum(nets)
        exp = tot / n if n else 0.0
        if n < MIN_N:
            verdict = "neutral"
        elif exp > 0:
            verdict = "pay"
        else:
            verdict = "bleed"
        # t تقريبيّ (للشفافيّة فقط — ليس بوّابة)
        if n > 1:
            mean = exp
            var = sum((x - mean) ** 2 for x in nets) / (n - 1)
            sd = math.sqrt(var)
            tval = (mean / (sd / math.sqrt(n))) if sd > 0 else 0.0
        else:
            tval = 0.0
        out[k] = {
            "n": n,
            "net_sum": round(tot, 4),
            "expectancy": round(exp, 4),
            "t": round(tval, 2),
            "verdict": verdict,
            "trusted": n >= MIN_N,
        }
    return out


# ════════════════════════════════════════════════════════════════════════════
#  (b) measure — يحسب الحافّة لكل دلو ويكتب momentum_edge.json
# ════════════════════════════════════════════════════════════════════════════
def measure() -> dict:
    trades = _closed_trades()
    feats = _load_features()
    rows = _join(trades, feats)

    by_session = _bucket_stats(rows, lambda r: r["session"])
    by_group = _bucket_stats(rows, lambda r: r["group"])
    by_strength = _bucket_stats(
        rows, lambda r: strength_tertile(r["strength"]) if r["strength"] is not None else None
    )

    edge = {
        "by_session": by_session,
        "by_strength": by_strength,
        "by_group": by_group,
        "n_closed": len(trades),
        "n_features": len(feats),
        "n_joined": len(rows),
        "min_n": MIN_N,
        "updated": datetime.now(tz=timezone.utc).isoformat(),
    }
    try:
        EDGE.parent.mkdir(parents=True, exist_ok=True)
        EDGE.write_text(json.dumps(edge, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return edge


# ════════════════════════════════════════════════════════════════════════════
#  (d) edge_filter — يستدعيه momentum_harvester قبل الفتح
# ════════════════════════════════════════════════════════════════════════════
def _load_edge() -> dict:
    try:
        if EDGE.exists():
            return json.loads(EDGE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def edge_filter(sym: str, feats: dict | None = None) -> bool:
    """True = اسمح بالفتح، False = تخطّ (الدلو سالبٌ صافياً وموثوقٌ بـ n>=MIN_N).

    نزاهة: نحظر فقط الدلاء التي حكمها 'bleed' (موثوق). 'neutral' (عيّنة قليلة) و'pay' ⇒ نسمح.
    أيّ دلو واحد موثوق-وسالب يكفي للتخطّي (مبدأ الحذر: لا نفتح في سياقٍ مُثبَتٍ نزيفه). fail-open.
    """
    try:
        edge = _load_edge()
        if not edge:
            return True
        feats = dict(feats or {})
        ts = float(feats.get("ts") or time.time())
        hour = feats.get("hour")
        if hour is None:
            hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        session = feats.get("session") or session_of(int(hour))
        group = feats.get("group") or symbol_group(sym)
        strength = feats.get("strength")

        def _bleeds(table: str, key) -> bool:
            b = (edge.get(table) or {}).get(key)
            return bool(b) and b.get("verdict") == "bleed" and b.get("trusted")

        if _bleeds("by_session", session):
            return False
        if _bleeds("by_group", group):
            return False
        if strength is not None and _bleeds("by_strength", strength_tertile(float(strength))):
            return False
        return True
    except Exception:
        return True


# ════════════════════════════════════════════════════════════════════════════
#  (c) main — حلقة قياس بلا-نافذة كل ~10 دقائق
# ════════════════════════════════════════════════════════════════════════════
def main():
    while True:
        try:
            edge = measure()
            print(f"[momentum_learn] measured: closed={edge['n_closed']} "
                  f"joined={edge['n_joined']} -> {EDGE}")
        except Exception as e:
            print(f"[momentum_learn] measure err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    import sys
    if "--measure" in sys.argv:
        e = measure()
        print(json.dumps(e, ensure_ascii=False, indent=2))
    else:
        main()
