# -*- coding: utf-8 -*-
"""
agent_linreg_st.py — 6 وكلاء لطاقم Pine (LinReg + RSI + VWAP + SuperTrend + بنية HH/LL).

العقد الموحّد لكل وكيل (نفس عقد المجلس):
    def agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

يعتمد على وحدة suite_linreg_st (جذر MT5) عبر دالّتها evaluate() على شموع M1
(أو أدنى فريم متاح في ctx). الاستيراد دفاعيّ: إن غابت الوحدة أو الشموع أو أيّ
حقل ⇒ (0, 0.0, "بيانات غير كافية") — لا نكسر المجلس أبداً.

⚡ كاش: نتيجة evaluate() تُحفَظ لكلّ (رمز، بصمة آخر شمعة) في قاموس على مستوى
الوحدة، فلا يعيد الوكلاء الستّة الحساب 6 مرّات لكلّ رمز في الدورة الواحدة.
"""
import os
import sys

import numpy as np

# ─────────────────────── استيراد دفاعيّ لوحدة الطاقم ───────────────────────
_suite = None
try:
    import suite_linreg_st as _suite
except Exception:
    try:
        _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _ROOT not in sys.path:
            sys.path.insert(0, _ROOT)
        import suite_linreg_st as _suite
    except Exception:
        _suite = None

_MISS = (0, 0.0, "بيانات غير كافية")

# كاش على مستوى الوحدة: sym ⇒ (بصمة آخر شمعة, نتيجة evaluate)
_CACHE = {}


# ───────────────────────────── أدوات دفاعيّة ────────────────────────────────

def _lowest_bars(ctx):
    """أدنى فريم متاح (m1 أوّلاً) كقاموس مصفوفات numpy نظيفة، أو (None, None)."""
    for tf in ("m1", "m5", "m15", "h1"):
        d = ctx.get(tf) if isinstance(ctx, dict) else None
        if not isinstance(d, dict):
            continue
        try:
            o = np.asarray(d.get("o"), dtype=float).ravel()
            h = np.asarray(d.get("h"), dtype=float).ravel()
            l = np.asarray(d.get("l"), dtype=float).ravel()
            c = np.asarray(d.get("c"), dtype=float).ravel()
        except Exception:
            continue
        n = min(o.size, h.size, l.size, c.size)
        if n < 30 or not np.isfinite(c[-1]):
            continue
        try:
            v = np.asarray(d.get("v"), dtype=float).ravel()
            v = v[-n:] if v.size >= n else np.zeros(n)
        except Exception:
            v = np.zeros(n)
        bars = {"o": o[-n:], "h": h[-n:], "l": l[-n:], "c": c[-n:], "v": v}
        t = d.get("t")
        if t is not None:
            bars["t"] = t
        return tf, bars
    return None, None


def _fingerprint(tf, bars):
    """بصمة آخر شمعة: الوقت إن وُجد، وإلا قيم الشمعة الأخيرة (تكفي لتمييزها)."""
    try:
        t = bars.get("t")
        if t is not None:
            ta = np.asarray(t).ravel()
            if ta.size:
                return (tf, float(ta[-1]))
    except Exception:
        pass
    try:
        return (tf, int(bars["c"].size), float(bars["c"][-1]),
                float(bars["h"][-1]), float(bars["l"][-1]), float(bars["v"][-1]))
    except Exception:
        return None


def _evaluate(ctx):
    """نتيجة evaluate() لطاقم الرمز، مع كاش لكلّ (رمز، آخر شمعة). None عند العجز."""
    if _suite is None or not hasattr(_suite, "evaluate"):
        return None
    try:
        sym = str((ctx or {}).get("sym") or "?")
        tf, bars = _lowest_bars(ctx)
        if bars is None:
            return None
        key = _fingerprint(tf, bars)
        if key is not None:
            hit = _CACHE.get(sym)
            if hit is not None and hit[0] == key:
                return hit[1]
        o, h, l, c, v = bars["o"], bars["h"], bars["l"], bars["c"], bars["v"]
        res = None
        # توقيعات محتملة للدالّة — نجرّب بالترتيب ونتسامح مع TypeError فقط
        for call in (lambda: _suite.evaluate(bars),
                     lambda: _suite.evaluate(sym, bars),
                     lambda: _suite.evaluate(o=o, h=h, l=l, c=c, v=v),
                     lambda: _suite.evaluate(o, h, l, c, v),
                     lambda: _suite.evaluate(h, l, c, v)):
            try:
                res = call()
                if res is not None:
                    break
            except TypeError:
                continue
            except Exception:
                return None
        if res is None:
            return None
        if key is not None:
            if len(_CACHE) > 256:                     # سقف أمان (عمليّاً ~17 رمزاً)
                _CACHE.clear()
            _CACHE[sym] = (key, res)
        return res
    except Exception:
        return None


def _get(res, *names):
    """قراءة حقل من dict أو كائن بأسماء بديلة؛ None عند الغياب."""
    for nm in names:
        try:
            if isinstance(res, dict):
                if nm in res:
                    return res[nm]
            elif hasattr(res, nm):
                return getattr(res, nm)
        except Exception:
            continue
    return None


def _structure_dir(s):
    """يفكّ ترميز البنية: +1 (HH+HL) / -1 (LH+LL) / 0 مختلطة / None غائبة."""
    if s is None:
        return None
    try:
        if isinstance(s, str):
            t = s.strip().lower()
            if t in ("hh_hl", "hh+hl", "hhhl", "bullish", "bull", "up", "صاعد"):
                return 1
            if t in ("lh_ll", "lh+ll", "lhll", "bearish", "bear", "down", "هابط"):
                return -1
            return 0
        if isinstance(s, dict):
            hh = bool(s.get("hh")); hl = bool(s.get("hl"))
            lh = bool(s.get("lh")); ll = bool(s.get("ll"))
            if hh and hl and not (lh and ll):
                return 1
            if lh and ll and not (hh and hl):
                return -1
            return 0
        return int(np.sign(float(s)))
    except Exception:
        return None


# ────────────────────────────── الوكلاء الستّة ──────────────────────────────

def agent_linreg_signal(ctx):
    """اتجاه إشارة الانحدار الخطّي (signal_rising): صاعدة=+1 هابطة=-1، ثقة 0.55."""
    try:
        res = _evaluate(ctx)
        if res is None:
            return _MISS
        rising = _get(res, "signal_rising", "linreg_rising", "lr_rising")
        if rising is None:
            return _MISS
        if bool(rising):
            return (1, 0.55, "إشارة الانحدار الخطّي صاعدة")
        return (-1, 0.55, "إشارة الانحدار الخطّي هابطة")
    except Exception:
        return _MISS


def agent_rsi_state(ctx):
    """حالة RSI من الطاقم (rsi_bull): ثور=+1 دبّ=-1، ثقة 0.5."""
    try:
        res = _evaluate(ctx)
        if res is None:
            return _MISS
        bull = _get(res, "rsi_bull")
        if bull is None:
            return _MISS
        rsi = _get(res, "rsi", "rsi_value")
        tag = ""
        try:
            if rsi is not None and np.isfinite(float(rsi)):
                tag = f" (RSI={float(rsi):.0f})"
        except Exception:
            tag = ""
        if bool(bull):
            return (1, 0.5, "RSI في نطاقٍ صاعد" + tag)
        return (-1, 0.5, "RSI في نطاقٍ هابط" + tag)
    except Exception:
        return _MISS


def agent_vwap_side(ctx):
    """جهة السعر من VWAP الجلسة: فوق=+1 تحت=-1، ثقة 0.5."""
    try:
        res = _evaluate(ctx)
        if res is None:
            return _MISS
        above = _get(res, "above_vwap", "vwap_bull")
        if above is None:
            vwap = _get(res, "vwap", "session_vwap", "vwap_value")
            if vwap is None:
                return _MISS
            vwap = float(vwap)
            if not np.isfinite(vwap):
                return _MISS
            px = None
            try:
                px = float(ctx.get("price") or 0.0)
            except Exception:
                px = 0.0
            if not px:
                _, bars = _lowest_bars(ctx)
                if bars is None:
                    return _MISS
                px = float(bars["c"][-1])
            if px == vwap:
                return (0, 0.0, "على خطّ VWAP تماماً")
            above = px > vwap
        if bool(above):
            return (1, 0.5, "السعر فوق VWAP الجلسة")
        return (-1, 0.5, "السعر تحت VWAP الجلسة")
    except Exception:
        return _MISS


def agent_supertrend(ctx):
    """اتجاه SuperTrend من الطاقم (st_dir)، ثقة 0.6 + 0.1 إن كان الانقلاب حديثاً (≤8 شموع)."""
    try:
        res = _evaluate(ctx)
        if res is None:
            return _MISS
        st = _get(res, "st_dir", "supertrend_dir", "st_direction")
        if st is None:
            return _MISS
        d = int(np.sign(float(st)))
        if d == 0:
            return (0, 0.0, "سوبرترند متعادل")
        conf = 0.6
        fresh = ""
        flip = _get(res, "st_flip_bars", "bars_since_flip", "st_flip_age", "flip_bars")
        try:
            if flip is not None and 0 <= float(flip) <= 8:
                conf = 0.7
                fresh = f" — انقلاب حديث قبل {int(float(flip))} شمعة"
        except Exception:
            pass
        if d > 0:
            return (1, conf, "سوبرترند صاعد" + fresh)
        return (-1, conf, "سوبرترند هابط" + fresh)
    except Exception:
        return _MISS


def agent_structure_hhll(ctx):
    """بنية القمم/القيعان من الطاقم: HH+HL=+1، LH+LL=-1، مختلطة=0، ثقة 0.55."""
    try:
        res = _evaluate(ctx)
        if res is None:
            return _MISS
        d = _structure_dir(_get(res, "structure", "structure_dir", "hhll"))
        if d is None:
            return _MISS
        if d > 0:
            return (1, 0.55, "بنية صاعدة HH+HL")
        if d < 0:
            return (-1, 0.55, "بنية هابطة LH+LL")
        return (0, 0.0, "بنية مختلطة")
    except Exception:
        return _MISS


def agent_suite_alignment(ctx):
    """يصوّت فقط عند اصطفاف الزوايا الخمس كلّها (setup صاعد/هابط) بثقة 0.85."""
    try:
        res = _evaluate(ctx)
        if res is None:
            return _MISS
        setup = _get(res, "setup", "alignment", "aligned")
        if setup is not None and not isinstance(setup, str):
            try:
                setup = {1: "bullish", -1: "bearish"}.get(int(np.sign(float(setup))), "")
            except Exception:
                setup = str(setup)
        t = (setup or "").strip().lower()
        if t in ("bullish", "bull", "buy", "long", "صاعد"):
            return (1, 0.85, "اصطفاف خماسيّ صاعد (LinReg+RSI+VWAP+ST+بنية)")
        if t in ("bearish", "bear", "sell", "short", "هابط"):
            return (-1, 0.85, "اصطفاف خماسيّ هابط (LinReg+RSI+VWAP+ST+بنية)")
        return (0, 0.0, "لا اصطفاف خماسياً")
    except Exception:
        return _MISS


# ────────────────────────────── السجلّ ─────────────────────────────────────
CATEGORY = "linreg_st"

AGENTS = [
    ("linreg_signal",     CATEGORY, agent_linreg_signal,    1.0),
    ("rsi_state",         CATEGORY, agent_rsi_state,        1.0),
    ("vwap_side",         CATEGORY, agent_vwap_side,        1.0),
    ("supertrend_suite",  CATEGORY, agent_supertrend,       1.0),
    ("structure_hhll",    CATEGORY, agent_structure_hhll,   1.0),
    ("suite_alignment",   CATEGORY, agent_suite_alignment,  1.0),
]
