# -*- coding: utf-8 -*-
"""session_gate.py — بوّابة جلسة مدفوعة بالبيانات (مشتركة بين المنفّذين).

رؤية المستخدم: ندخل كل الجلسات ونتعلّمها، وكل جلسة لها أوزانها/استراتيجياتها/جيناتها/وكلاؤها —
بصمتنا في كل جلسة. هذه البوّابة تقرأ `data/r_native/session_profiles.json` (تبنيه النسخة ب:
وكيل لكل جلسة) وتقرّر: هل الجلسة الحالية مسموح لها بالدخول الحيّ (live) أم ظلّ فقط (shadow)؟

نقي/قراءة-فقط/fail-safe:
- لو الملف غائب (لم تُسلّمه النسخة ب بعد) → احتياط آمن: لندن + تداخل نيويورك فقط (08–17 UTC).
- لو فيه بصمة الجلسة الحالية → live إن قالت `live_or_shadow=="live"` فقط، وإلا منع (ظلّ).
- أي خطأ → الاحتياط الآمن (لا نُجمّد المحرّك بسبب عطل البوّابة).

مفاتيح الجلسات = نفس تقسيم deep_brain: asia(0-7) · london(7-12) · ny(12-21) · off(21-24) UTC.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

PROFILES_F = Path(r"C:\Users\Radhi\MT5\data\r_native\session_profiles.json")
_CACHE = {"mtime": 0.0, "data": None}

# 🟢 وضع الاختبار-الأمامي لكل الجلسات (طلب المستخدم الصريح: «ادخلوا صفقات، كل الجلسات، تنفيذ الآن»).
# ملفّات الجلسات (تبنيها ب) تبقى للتعلّم والتحجيم، لكنها لا تمنع الدخول في هذا الوضع — الواقع يحكم.
# الحمايات الفعلية: master_floor + سقف 2% + مانع التحوّط + قصّ الرموز النازفة. غيّره لـFalse للعودة
# للبوّابة المدفوعة بالبيانات (الجلسة المُثبتة فقط تتداول حيّاً).
FORWARD_TEST_ALL = True


def current_session(hour_utc=None):
    h = datetime.now(timezone.utc).hour if hour_utc is None else int(hour_utc)
    return "asia" if h < 7 else "london" if h < 12 else "ny" if h < 21 else "off"


def _load_profiles():
    """قراءة مُخبّأة (تُعاد فقط عند تغيّر الملف) لتفادي قراءة قرص كل دورة."""
    try:
        if not PROFILES_F.exists():
            return None
        mt = PROFILES_F.stat().st_mtime
        if mt != _CACHE["mtime"]:
            _CACHE["data"] = json.load(open(PROFILES_F, encoding="utf-8-sig"))
            _CACHE["mtime"] = mt
        return _CACHE["data"]
    except Exception:
        return None


def _fallback(h):
    # طلب المستخدم الصريح: ادخلوا كل الجلسات الآن ونتعلّمها حيّاً (forward-test؛ master_floor + 2% + مانع
    # التحوّط يحرسون). تبقى البوّابة مدفوعة بالبيانات: متى سلّمت ب session_profiles.json تُقيّد الجلسات
    # السالبة إلى ظلّ تلقائياً. حتى ذلك الحين: كل الجلسات مسموحة.
    return True


def session_allows_entry(hour_utc=None):
    """True لو يُسمح بفتح صفقة جديدة في الجلسة الحالية. إدارة/إغلاق المراكز القائمة لا تتأثّر."""
    if FORWARD_TEST_ALL:
        return True   # طلب المستخدم: كل الجلسات حيّة (اختبار أمامي؛ الحمايات تحرس)
    try:
        h = datetime.now(timezone.utc).hour if hour_utc is None else int(hour_utc)
        prof = _load_profiles()
        if not prof:
            return _fallback(h)
        sess = current_session(h)
        # الملف قد يكون {sessions:{...}} أو {asia:{...}} مباشرة
        rec = (prof.get("sessions") or prof).get(sess)
        if not isinstance(rec, dict):
            return False   # لا بصمة لهذه الجلسة بعد ⇒ ظلّ (لا دخول حيّ)
        return str(rec.get("live_or_shadow", "shadow")).lower() == "live"
    except Exception:
        try:
            return _fallback(datetime.now(timezone.utc).hour)
        except Exception:
            return False


def session_genes(hour_utc=None):
    """جينات الجلسة الحالية (stop_atr/target_atr/conf_gate) إن وُجدت — وإلا None."""
    try:
        prof = _load_profiles()
        if not prof:
            return None
        rec = (prof.get("sessions") or prof).get(current_session(hour_utc))
        return rec.get("genes") if isinstance(rec, dict) else None
    except Exception:
        return None


if __name__ == "__main__":
    h = datetime.now(timezone.utc).hour
    print("الساعة UTC:", h, "| الجلسة:", current_session(),
          "| دخول حيّ؟", session_allows_entry(), "| جينات:", session_genes(),
          "| ملف الجلسات موجود؟", PROFILES_F.exists())
