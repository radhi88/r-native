# -*- coding: utf-8 -*-
"""deep_conviction.py — جسر بين العقل العميق والمنفّذين.

يقرأ قناعة العقل العميق (deep_dossier.json) لرمزٍ واتجاه، فيُعيد:
  • mult: مضاعِف قوّة الدخول (1.0 محايد · >1 ادخل أقوى/أكبر · <1 تحفّظ).
  • tier: وصف (🟢 ضوء أخضر مُثبت / 🔴 فيتو تعلّمي / محايد).
  • ok: False فقط عند فيتو تعلّمي قويّ (شرط دالّ سالب) ⇒ لا تدخل.

القناعة مدفوعة بالشروط المُثبتة فقط (Bonferroni=قوي، معنوي=ناعم) — لا حماس مؤشرات خام.
fail-open بالكامل: أي خطأ/ملفّ قديم (العقل متوقّف) ⇒ (1.0, "محايد", True) فلا يُعطّل المنفّذ أبداً.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

_DOSSIER = Path(r"C:\Users\Radhi\MT5\data\r_native\deep_dossier.json")
_CACHE = {"t": 0.0, "data": None}
_TTL = 5.0          # خبّئ القراءة ثوانٍ قليلة
_MAX_AGE = 150.0    # لو الملفّ أقدم من هذا (العقل متوقّف) ⇒ محايد


def _load():
    now = time.time()
    if _CACHE["data"] is not None and now - _CACHE["t"] < _TTL:
        return _CACHE["data"]
    try:
        if now - _DOSSIER.stat().st_mtime > _MAX_AGE:
            _CACHE.update(t=now, data=None); return None
        d = json.load(open(_DOSSIER, encoding="utf-8-sig"))
        _CACHE.update(t=now, data=d)
        return d
    except Exception:
        _CACHE.update(t=now, data=None)
        return None


def conviction(sym, side):
    """(mult, tier, ok) للرمز sym باتجاه side ('BUY'/'SELL' أو 1/-1).
    تُطبَّق فقط إذا وافق اتجاهُ العقل اتجاهَ المنفّذ (وإلا حياد)."""
    try:
        d = _load()
        if not d:
            return 1.0, "محايد", True
        sd = (d.get("symbols", {}) or {}).get(sym)
        if not sd:
            return 1.0, "محايد", True
        cv = sd.get("conviction") or {}
        want = 1 if (side in (1, "BUY", "buy", "Buy")) else -1
        bias = sd.get("bias")
        bdir = 1 if bias == "صعود" else -1 if bias == "هبوط" else 0
        if bdir == 0 or bdir != want:
            return 1.0, "محايد", True          # العقل لا يوافق الاتجاه ⇒ لا تعزيز ولا فيتو
        mult = float(cv.get("mult", 1.0))
        # القناعة تحجّم الدخول: الأخضر يكبّر (حتى ×2 دخول قويّ)، السالب يصغّر للوت الأدنى.
        # فيتو صارم (ok=False) فقط على قاعدة **حقيقية مُثبتة** (صافي صفقات منفّذة + Bonferroni) —
        # موثوقة لأنها تشمل التكلفة (مثل: لا تدخل عند التشبّع الشرائي/الذهب). لا فيتو من الظلّ الفتيّ.
        ok = not bool(cv.get("real_veto"))
        return mult, cv.get("tier", "محايد"), ok
    except Exception:
        return 1.0, "محايد", True


def green_lights():
    """قائمة الأضواء الخضراء الحاليّة (رموز ثبت شرطها الموجب) — للعرض/المراقبة."""
    try:
        d = _load()
        return (d or {}).get("green_lights", []) or []
    except Exception:
        return []
