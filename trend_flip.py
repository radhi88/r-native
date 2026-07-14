# -*- coding: utf-8 -*-
"""trend_flip.py — كاشف الانعكاس الحاسم (READ-ONLY): «أغلق الخاسر واقلب مع الترند الجديد».

لا يتداول إطلاقاً (لا order_send، لا mt5.initialize داخل المنطق) — يُرجِع *قراراً* فقط
يتصرّف به المنادي (يمرّر mt5، وعند التنفيذ يستدعي record_flip لتثبيت التهدئة الذاتيّة). الغرض
(حرفيّ من المستخدم): حين كومتنا المفتوحة على رمزٍ **تحت الماء** والترند **تغيّر بوضوح وحَسماً
ضدّنا بلا عودة واقعيّة** ⇒ أَشِر بـ: أغلق الخواسر واقلب لدخول **مع** الترند الجديد.

«مصيريّ/حاسم جداً» (تأكيد المستخدم) ⇒ بوّابة صارمة تجمع: كسر بنية **طازج (BOS)** إلزاميّ + لا-عودة
على ATR(M5) + ≥4 من 5 عوامل قويّة (شمعة/دلتا/زخم/قوّة ADX/خبر) + جلسة عالية القناعة (شرط) +
أحمر عميق + تهدئة ذاتيّة-الإنفاذ + منع القلب العكسيّ + سقف قلبات/جلسة + فيتو العقل العميق.

سبب وجوده: إمساك الخواسر في ترندٍ أحاديّ الاتجاه هو ما سبّب انهيار −47%. هذا هو مخرج الخاسر
المفقود — مشدّد ضدّ التذبذب (whipsaw). كلّ قراءة fail-SAFE: استثناء/نقص ⇒ العامل False (لا نقلب
على بيانات ناقصة)؛ وتعذّر البنية ⇒ flip=False (البنية إلزاميّة).
"""
from __future__ import annotations
import time
import json as _json
import os as _os
from datetime import datetime, timezone

try:
    import market_structure as ms       # البنية + BOS — العامل الإلزاميّ (كسر طازج)
except Exception:
    ms = None
try:
    import candle_anatomy as ca         # تشريح آخر شمعة مكتملة
except Exception:
    ca = None
try:
    import delta_flow as dfl            # دلتا تدفّق الأوامر
except Exception:
    dfl = None
try:
    import deep_conviction as dc        # فيتو الخسارة المُثبتة (real_veto = الإيقاف الصلب)
except Exception:
    dc = None
try:
    import news_engine as ne            # خبر فعّال + اتجاهه
except Exception:
    ne = None

# ── ثوابت الوحدة (مشدّدة بعد التحقّق العدائيّ) ───────────────────────
MIN_FACTORS       = 4        # ≥4 من 5 عوامل اختياريّة (شمعة/دلتا/زخم/قوّة/خبر). الجلسة شرطٌ لا عامل
FLIP_COOLDOWN_S   = 600.0    # لا قلب خلال 10د من آخر قلب على الرمز
REFLIP_BLOCK_S    = 1800.0   # لا قلب **عكسيّ** (عودة للاتجاه الذي قلبنا منه) خلال 30د — يمنع long→short→long
MAX_FLIPS_SESSION = 2        # سقف خشن: قلبتان كحدٍّ أقصى لكل رمز في نافذة جلسة (8 ساعات)
DEEP_RED_FRAC     = 0.02     # «أحمر عميق»: netpl ≤ −max(2.0, 2% من الحقوق)
DEEP_RED_MIN_USD  = 2.0
NO_RETURN_ATR     = 2.0      # «لا عودة» على ATR(M5) (حركة حاسمة لا فتيل M1 لحظيّ)
STRENGTH_ADX_MIN  = 25.0     # مرفوع من 20: ترند ذو قوّة فعليّة
MOM_SPEED_ATR     = 0.50
DELTA_MIN_BIAS    = 15.0     # مرفوع من 8: انحياز تدفّق واضح (لا اختلال 90ث هامشيّ)

_FLIP_STATE_F = r"C:\Users\Radhi\MT5\data\r_native\trend_flip_state.json"
# {sym: {"ts": آخر قلب, "dir": اتجاه آخر قلب, "session_count": عدد, "session_win": نافذة 8س}}


def _safe(fn, default):
    """يشغّل قراءة ويبتلع أيّ استثناء ⇒ default (fail-safe)."""
    try:
        return fn()
    except Exception:
        return default


def _atr_m5(mt5, sym, n=14):
    """ATR(M5) داخليّ — «لا-عودة» تُقاس عليه (أصدق من M1 على كتابٍ متعدّد-ATR)."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, n + 2)
    if r is None or len(r) < n + 1:
        return 0.0
    h, l, c = r["high"], r["low"], r["close"]
    trs = [max(float(h[i] - l[i]), abs(float(h[i] - c[i - 1])), abs(float(l[i] - c[i - 1])))
           for i in range(len(r) - n, len(r))]
    return sum(trs) / len(trs) if trs else 0.0


def _structure_break(sym, new_dir):
    """1) إلزاميّ ومُشدَّد: حدث كسرٍ **طازج (BOS)** في الاتجاه الجديد على M5 أو M15 — لا يكفي ترندٌ سابق
    قائم (الكسر الطازج هو الحدث الحاسم الذي طلبه المستخدم)."""
    if ms is None:
        return False
    want = "BOS↑" if new_dir > 0 else "BOS↓"
    for tf in ("M5", "M15"):
        st = _safe(lambda: ms.structure(sym, tf), {}) or {}
        if (st.get("bos") or "").startswith(want):
            return True
    return False


def _no_return(mt5, sym, our_dir, avg_entry, atr1):
    """2) لا-عودة: السعر تجاوز متوسّط دخولنا ضدّنا بـ ≥ NO_RETURN_ATR×ATR(M5) **و** كسر المتأرجح الذي كان
    يجب أن يصمد (last_low لِلّونغ / last_high لِلشورت). ATR(M5) لا M1 — حركة حاسمة على فريم أكبر."""
    if not avg_entry:
        return False
    atr5 = _safe(lambda: _atr_m5(mt5, sym), 0.0)
    atr_use = atr5 if atr5 > 0 else (atr1 or 0.0)
    if atr_use <= 0:
        return False
    tk = _safe(lambda: mt5.symbol_info_tick(sym), None)
    if not tk:
        return False
    price = (tk.bid + tk.ask) / 2.0
    against = (avg_entry - price) if our_dir > 0 else (price - avg_entry)
    if against < NO_RETURN_ATR * atr_use:
        return False
    st = _safe(lambda: ms.structure(sym, "M5"), {}) if ms else {}
    st = st or {}
    if our_dir > 0:
        lvl = st.get("last_low")
        return bool(lvl) and price < lvl
    lvl = st.get("last_high")
    return bool(lvl) and price > lvl


def _candle(sym, our_dir):
    """3) شمعة انعكاسيّة/استمراريّة قويّة في اتجاه الترند الجديد (ضدّنا)."""
    if ca is None:
        return False
    sig = _safe(lambda: ca.last_signal(sym), {}) or {}
    pat = sig.get("pat", "")
    if our_dir > 0:
        return pat in ("shooting_star", "marubozu_dn", "bearish_engulfing")
    return pat in ("hammer", "marubozu_up", "bullish_engulfing")


def _delta(sym, new_dir):
    """4) دلتا التدفّق تؤكّد الاتجاه الجديد بانحياز واضح (DELTA_MIN_BIAS). لا تيكات ⇒ غير مؤكَّد."""
    if dfl is None:
        return False
    f = _safe(lambda: dfl.flow(sym), None)
    if not f:
        return False
    return _safe(lambda: dfl.confirms(sym, new_dir, min_bias=DELTA_MIN_BIAS), False)


def _momentum(mt5, sym, new_dir, atr1):
    """5) زخم M1 (شمعتان) في الاتجاه الجديد بسرعة ذات معنى."""
    if atr1 <= 0:
        return False
    r = _safe(lambda: mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 4), None)
    if r is None or len(r) < 3:
        return False
    move = float(r["close"][-1] - r["close"][-3])
    mdir = 1 if move > 0 else -1
    return mdir == new_dir and (abs(move) / atr1) >= MOM_SPEED_ATR


def _strength(mt5, sym, new_dir, atr1):
    """6) قوّة الترند: ADX(M5) ≥ STRENGTH_ADX_MIN واتجاه +DI/−DI مع new_dir، وRSI(M5) يميل الاتجاه الجديد."""
    r = _safe(lambda: mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 60), None)
    if r is None or len(r) < 30:
        return False
    import numpy as np
    h, l, c = r["high"].astype(float), r["low"].astype(float), r["close"].astype(float)
    n = 14
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = tr[-n:].mean()
    if atr <= 0:
        return False
    pdi = 100.0 * plus_dm[-n:].mean() / atr
    mdi = 100.0 * minus_dm[-n:].mean() / atr
    denom = pdi + mdi
    adx = 100.0 * abs(pdi - mdi) / denom if denom > 0 else 0.0
    if adx < STRENGTH_ADX_MIN:
        return False
    di_dir = 1 if pdi > mdi else -1
    diff = np.diff(c)
    gain = np.clip(diff, 0, None)[-n:].mean()
    loss = (-np.clip(diff, None, 0))[-n:].mean()
    rsi = 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)
    rsi_dir = 1 if rsi >= 50.0 else -1
    return di_dir == new_dir and rsi_dir == new_dir


def _news(sym, new_dir):
    """7) خبر فعّال يدفع الاتجاه الجديد (veto ⇒ لا ندخل اتجاهاً جديداً الآن)."""
    if ne is None:
        return False
    res = _safe(lambda: ne.news_vote(sym), (0, 0.0, False, ""))
    nd, _w, veto, _why = res
    if veto:
        return False
    return int(nd) == new_dir


def _session():
    """شرط (لا عامل): الساعة عالية القناعة — لندن 08-13 + تداخل نيويورك 13-17 (UTC)."""
    return 8 <= datetime.now(timezone.utc).hour < 17


def _load_flip_state(sym):
    try:
        return (_json.load(open(_FLIP_STATE_F, encoding="utf-8")) or {}).get(sym, {})
    except Exception:
        return {}


def record_flip(sym, new_dir):
    """يستدعيه المنادي **بعد تنفيذ القلب فعلاً** — يثبّت الوقت/الاتجاه/عدّاد-الجلسة (تهدئة ذاتيّة-الإنفاذ)."""
    try:
        try:
            d = _json.load(open(_FLIP_STATE_F, encoding="utf-8")) or {}
        except Exception:
            d = {}
        now = time.time()
        win = datetime.now(timezone.utc).hour // 8         # نافذة جلسة 8 ساعات
        s = d.get(sym, {})
        if s.get("session_win") != win:
            s["session_count"] = 0
            s["session_win"] = win
        s["ts"] = now
        s["dir"] = int(new_dir)
        s["session_count"] = int(s.get("session_count", 0)) + 1
        d[sym] = s
        _os.makedirs(_os.path.dirname(_FLIP_STATE_F), exist_ok=True)
        json_tmp = _FLIP_STATE_F + ".tmp"
        _json.dump(d, open(json_tmp, "w", encoding="utf-8"))
        _os.replace(json_tmp, _FLIP_STATE_F)
    except Exception:
        pass


def decisive_reversal(mt5, sym, our_dir, avg_entry, netpl, eq, atr1, last_flip_ts):
    """القرار الحاسم (READ-ONLY). our_dir: +1 لونغ / −1 شورت. new_dir=−our_dir. يُرجِع
    {flip,new_dir,score,factors,reason,cooldown_ok}. التهدئة/المنع-العكسيّ/سقف-الجلسة ذاتيّة-الإنفاذ
    (من ملفّ الحالة) **بالإضافة** إلى last_flip_ts الممرَّر — أيّهما أحدث. أيّ خطأ غير متوقَّع ⇒ flip=False."""
    try:
        try:
            our_dir = 1 if (our_dir is not None and float(our_dir) >= 0) else -1
        except Exception:
            our_dir = -1
        new_dir = -our_dir
        now = time.time()

        structure_break = _safe(lambda: _structure_break(sym, new_dir), False)
        no_return       = _safe(lambda: _no_return(mt5, sym, our_dir, avg_entry, atr1), False)
        candle          = _safe(lambda: _candle(sym, our_dir), False)
        delta           = _safe(lambda: _delta(sym, new_dir), False)
        momentum        = _safe(lambda: _momentum(mt5, sym, new_dir, atr1), False)
        strength        = _safe(lambda: _strength(mt5, sym, new_dir, atr1), False)
        news            = _safe(lambda: _news(sym, new_dir), False)
        session         = _safe(_session, False)

        dc_ok = True
        if dc is not None:
            try:
                _mult, _tier, dc_ok = dc.conviction(sym, "BUY" if new_dir > 0 else "SELL")
            except Exception:
                dc_ok = True

        optional = {"candle": candle, "delta": delta, "momentum": momentum,
                    "strength": strength, "news": news}      # الجلسة شرطٌ منفصل لا عامل
        opt_count = sum(1 for v in optional.values() if v)

        deep_red_floor = max(DEEP_RED_MIN_USD, DEEP_RED_FRAC * float(eq or 0.0))
        deeply_red = (netpl is not None) and (netpl <= -deep_red_floor)

        # تهدئة/منع-عكسيّ/سقف-جلسة ذاتيّة-الإنفاذ (من الملفّ) + الممرَّر
        flip_st = _load_flip_state(sym)
        last_ts = max(float(last_flip_ts or 0.0), float(flip_st.get("ts", 0.0)))
        last_dir = int(flip_st.get("dir", 0))
        cooldown_ok = (now - last_ts) >= FLIP_COOLDOWN_S
        reflip_ok = not (new_dir == -last_dir and (now - last_ts) < REFLIP_BLOCK_S)   # لا عودة عكسيّة سريعة
        win = datetime.now(timezone.utc).hour // 8
        sc = int(flip_st.get("session_count", 0)) if flip_st.get("session_win") == win else 0
        count_ok = sc < MAX_FLIPS_SESSION

        factors = {"structure_break": structure_break, "no_return": no_return,
                   "candle": candle, "delta": delta, "momentum": momentum,
                   "strength": strength, "news": news, "session": session,
                   "deeply_red": deeply_red, "deep_conviction_ok": dc_ok,
                   "cooldown_ok": cooldown_ok, "reflip_ok": reflip_ok, "count_ok": count_ok,
                   "opt_count": opt_count}
        score = int(structure_break) + int(no_return) + opt_count + int(session)

        flip = bool(deeply_red and structure_break and no_return and session
                    and opt_count >= MIN_FACTORS and cooldown_ok and reflip_ok and count_ok and dc_ok)

        if not deeply_red:
            reason = f"كومة ليست حمراء بعمق (netpl={netpl} > −{deep_red_floor:.1f}$) — لا قلب"
        elif not structure_break:
            reason = "لا كسر بنية طازج (BOS) في الاتجاه الجديد (إلزاميّ) — لا قلب"
        elif not no_return:
            reason = "لا تأكيد «لا عودة» (لم يتجاوز الدخول بـ2×ATR(M5) ويكسر المتأرجح) — لا قلب"
        elif not session:
            reason = "خارج نافذة الجلسة عالية القناعة (08-17 UTC) — لا قلب"
        elif opt_count < MIN_FACTORS:
            on = [k for k, v in optional.items() if v]
            reason = f"عوامل غير كافية {opt_count}/{MIN_FACTORS} (المتوفّر: {on or '—'}) — لا قلب"
        elif not cooldown_ok:
            reason = f"تهدئة ({int(now - last_ts)}ث < {int(FLIP_COOLDOWN_S)}ث) — لا قلب"
        elif not reflip_ok:
            reason = "منع القلب العكسيّ (عودة لاتجاه سابق ضمن 30د) — لا قلب"
        elif not count_ok:
            reason = f"بلغ سقف القلبات للجلسة ({sc}/{MAX_FLIPS_SESSION}) — لا قلب"
        elif not dc_ok:
            reason = "فيتو العقل العميق (real_veto) على الاتجاه الجديد — لا قلب"
        else:
            nd_txt = "شراء↑" if new_dir > 0 else "بيع↓"
            reason = (f"انعكاس حاسم: BOS+لا-عودة+{opt_count} عوامل+جلسة على كومة حمراء "
                      f"${netpl:.0f} ⇒ أغلق الخواسر واقلب {nd_txt} (score={score})")

        return {"flip": flip, "new_dir": new_dir, "score": int(score),
                "factors": factors, "reason": reason, "cooldown_ok": cooldown_ok}
    except Exception as e:                                   # حارس أخير: لا يرتفع استثناء للمنادي أبداً
        return {"flip": False, "new_dir": -(1 if (our_dir or -1) >= 0 else -1), "score": 0,
                "factors": {}, "reason": f"خطأ غير متوقَّع: {type(e).__name__}", "cooldown_ok": True}


if __name__ == "__main__":
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("mt5.initialize() فشل — لا جلسة")
        raise SystemExit(1)
    MAGIC = 20260628
    for sym in ("XAUUSDm", "BTCUSDm"):
        poss = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
        atr1 = 0.0
        rr = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 16)
        if rr is not None and len(rr) >= 15:
            import numpy as _np
            h, l, c = rr["high"], rr["low"], rr["close"]
            tr = _np.maximum(h[1:] - l[1:], _np.maximum(_np.abs(h[1:] - c[:-1]), _np.abs(l[1:] - c[:-1])))
            atr1 = float(tr[-14:].mean())
        tk = mt5.symbol_info_tick(sym)
        if poss:
            vol = sum(p.volume for p in poss) or 1.0
            avg_entry = sum(p.price_open * p.volume for p in poss) / vol
            netpl = sum(p.profit for p in poss); synth = ""
        else:
            mid = ((tk.bid + tk.ask) / 2.0) if tk else 1.0
            avg_entry = mid + 3.0 * atr1; netpl = -50.0; synth = " (اصطناعيّ)"
        acc = mt5.account_info()
        eq = acc.equity if acc else 50.0
        print(f"\n=== {sym}{synth}  avg={avg_entry:.2f} netpl={netpl:.1f} atr1={atr1:.4f} eq={eq:.1f} ===")
        for our_dir in (+1, -1):
            res = decisive_reversal(mt5, sym, our_dir, avg_entry, netpl, eq, atr1, last_flip_ts=0.0)
            print(f"  our_dir={our_dir:+d} → flip={res['flip']} new_dir={res['new_dir']:+d} score={res['score']}")
            print(f"    {res['reason']}")
            print(f"    factors={res['factors']}")
    mt5.shutdown()
