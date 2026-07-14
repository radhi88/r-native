# -*- coding: utf-8 -*-
"""home_extra.py — مصدر بيانات نقيّ لشاشة R Trader الرئيسية (بلا MT5).

دالّتان نقيّتان تقرآن ملفّات ``data/r_native`` فقط — لا اتصال MT5، ولا
كتابة، ولا آثار جانبيّة. أيّ خطأ قراءة/تحليل ⇒ إرجاع فارغ (fail-soft) بدل
الاستثناء، كي لا تُسقِط الواجهة. لا اختراع بيانات: إن غاب الملفّ أرجِع [].

⚖️ الصدق: قراءة فقط. لا مسار أوامر، ولا تعديل ui.py أو gateway.py.
سيربطها مهندس لاحق؛ هذا الملفّ = الوحدة النقيّة + اختبارها فقط.

المصادر:
  equity_curve()  ← data/r_native/pnl_history.json  {"curve": [[ts, equity], …]}
                    (احتياط: peak_watch.jsonl سطر-لكلّ-عيّنة {"ts", "eq", …})
  todays_trades() ← data/r_native/brain_trader_feed.jsonl  (خلاصة محرّك
                    brain_trader = المجيك 20260704؛ الخلاصة كلّها لهذا المحرّك،
                    بلا حقل magic فيها — مؤكَّد من brain_trader_status.json).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

# جذر البيانات: <MT5>/data/r_native  (هذا الملفّ في <MT5>/r_trader/)
_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data" / "r_native"

# مجيك محرّك brain_trader الذي تخصّه شاشة الرئيسية
MAGIC = 20260704

_CURVE_MAX = 120   # أقصى عدد نقاطٍ يُرجَعها منحنى الحقوق
_TRADES_MAX = 20   # أقصى عدد صفقاتٍ يُرجَعها سجلّ اليوم

# أنواع أحداث الخلاصة التي تمثّل صفقةً (فتح/إغلاق)؛ نتجاهل ضجيج الفيتو/الإدارة
_TRADE_KINDS = ("entry", "exit", "close", "open")


def _read_json(path: Path) -> Any:
    """حمّل JSON بأمان (utf-8-sig يبتلع BOM). فشل ⇒ None."""
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return None


def _iter_jsonl(path: Path):
    """مولّد كائنات JSON من ملفّ سطر-لكلّ-كائن؛ يتجاوز الأسطر التالفة بصمت."""
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except Exception:
        return


def _num(v: Any):
    """حوّل إلى float إن أمكن، وإلا None."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def equity_curve() -> list[list[float]]:
    """منحنى الحقوق: آخر ~120 نقطة ``[ts, equity]`` من ``data/r_native``.

    المصدر الأساسي ``pnl_history.json`` بصيغة ``{"curve": [[ts, eq], …]}``.
    إن غاب أو تلف، يُجرَّب احتياطٌ من ``peak_watch.jsonl`` (حقل ``eq``).
    لا مصدر صالح ⇒ ``[]`` (لا اختراع).

    كلّ نقطة: ``[float(ts), float(equity)]``؛ النقاط غير الرقميّة تُسقَط.
    """
    out: list[list[float]] = []

    # ── المصدر الأساسي: pnl_history.json → {"curve": [[ts, eq], …]} ──
    data = _read_json(_DATA / "pnl_history.json")
    if isinstance(data, dict):
        curve = data.get("curve")
        if isinstance(curve, list):
            for pt in curve:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    ts, eq = _num(pt[0]), _num(pt[1])
                    if ts is not None and eq is not None:
                        out.append([ts, eq])

    # ── احتياط: peak_watch.jsonl (سطر لكلّ عيّنة، حقل eq) ──
    if not out:
        for obj in _iter_jsonl(_DATA / "peak_watch.jsonl"):
            if not isinstance(obj, dict):
                continue
            ts, eq = _num(obj.get("ts")), _num(obj.get("eq"))
            if ts is not None and eq is not None:
                out.append([ts, eq])

    # آخر ~120 نقطة فقط
    return out[-_CURVE_MAX:]


def _local_today() -> str:
    """تاريخ اليوم المحلّي بصيغة ISO (YYYY-MM-DD)، لمطابقة حقل iso في الخلاصة."""
    return date.today().isoformat()


def _event_is_today(obj: dict, today: str) -> bool:
    """هل حدثُ الخلاصة من اليوم؟ نعتمد بادئة حقل iso، وإلا نحوّل ts."""
    iso = obj.get("iso")
    if isinstance(iso, str) and iso[:10]:
        return iso[:10] == today
    ts = _num(obj.get("ts"))
    if ts is not None:
        try:
            return datetime.fromtimestamp(ts).date().isoformat() == today
        except (OverflowError, OSError, ValueError):
            return False
    return False


def todays_trades() -> list[dict]:
    """آخر 20 حدث صفقة (فتح/إغلاق) لليوم من محرّك المجيك 20260704.

    يقرأ ``brain_trader_feed.jsonl`` — خلاصة محرّك brain_trader بأكملها
    (بلا حقل magic؛ المحرّك كلّه هو المجيك 20260704). يستخرج أحداث
    ``entry/exit/close/open`` فقط (يتجاهل veto/trail/tighten/ladder…)،
    مرشَّحةً على iso اليوم، ويُرجِع آخر 20 بالترتيب الزمنيّ.

    كلّ عنصر (حقول متاحة فقط، لا اختراع):
      ``{"ts", "iso", "sym", "type", "dir", "px", "lot"}``
      حيث ``type`` = نوع الحدث (entry/exit/…) و``dir`` = buy/sell إن وُجد.
    """
    today = _local_today()
    rows: list[dict] = []

    for obj in _iter_jsonl(_DATA / "brain_trader_feed.jsonl"):
        if not isinstance(obj, dict):
            continue
        kind = obj.get("kind")
        if kind not in _TRADE_KINDS:
            continue
        if not _event_is_today(obj, today):
            continue

        row: dict[str, Any] = {
            "ts": _num(obj.get("ts")),
            "iso": obj.get("iso"),
            "sym": obj.get("sym"),
            "type": kind,
        }
        # حقول اختياريّة — تُضاف فقط إن وُجدت في الحدث الأصلي (لا اختراع)
        if "dir" in obj:
            row["dir"] = obj.get("dir")
        px = _num(obj.get("px"))
        if px is not None:
            row["px"] = px
        lot = _num(obj.get("lot"))
        if lot is not None:
            row["lot"] = lot
        rows.append(row)

    # الترتيب الزمنيّ ثمّ آخر 20 (الملفّ مُلحَق ترتيباً، لكن نضمن بالطابع الزمنيّ)
    rows.sort(key=lambda r: (r.get("ts") is None, r.get("ts") or 0.0))
    return rows[-_TRADES_MAX:]


if __name__ == "__main__":
    # اختبار دخانيّ: يطبع أطوال المخرجات + معاينةً موجزة. لا MT5، لا كتابة.
    ec = equity_curve()
    tt = todays_trades()

    print(f"[home_extra] data dir      : {_DATA}")
    print(f"[home_extra] equity_curve  : {len(ec)} point(s)")
    if ec:
        print(f"             first / last : {ec[0]}  ->  {ec[-1]}")
    print(f"[home_extra] todays_trades : {len(tt)} trade(s) for magic {MAGIC}")
    if tt:
        last = tt[-1]
        print(f"             last trade   : {last}")

    # فحص نوعي بسيط — لا يرمي إن كانت المخرجات فارغة (بيئة بلا بيانات)
    assert isinstance(ec, list), "equity_curve must return a list"
    assert all(isinstance(p, list) and len(p) == 2 for p in ec), "curve points must be [ts, eq]"
    assert isinstance(tt, list), "todays_trades must return a list"
    assert len(tt) <= _TRADES_MAX, "todays_trades must be capped at 20"
    assert len(ec) <= _CURVE_MAX, "equity_curve must be capped at 120"
    print("[home_extra] self-test OK")
