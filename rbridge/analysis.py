# -*- coding: utf-8 -*-
"""analysis.py — تحليل SMC لحظيّ احترافيّ + ربط بعقل المشروع المنفّذ. (داخل عملية الجسر، اتصال MT5 واحد.)

يجمع لكل رمز/فريم (M1 مُضاف):
  • البنية: HH/HL/LH/LL + BOS (market_structure).
  • CHoCH / CISD / IFVG (smc_structure — دوال نقيّة على OHLC).
  • FVG + صيد السيولة (sweep) + الزخم (microstructure).
  • تحليل عقل المشروع: bias/call/confluence/score/conviction/levels من deep_dossier (ما يقوده المنفّذون).
  • المركز المفتوح للرمز (هل ينفّذ المشروع صفقة عليه الآن).

كله قراءة-فقط عبر اتصال الجسر الواحد (لا اتصال جديد — درس عطل 2026-06-28).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import MetaTrader5 as mt5

_ROOT = r"C:\Users\Radhi\MT5"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    import market_structure as ms
except Exception:
    ms = None
try:
    import smc_structure as smcs        # choch / cisd / ifvg (دوال نقيّة)
except Exception:
    smcs = None
try:
    import microstructure as micro      # detect_gap (FVG) / detect_wick_rev (sweep) / detect_momentum
except Exception:
    micro = None

_DOSS = Path(_ROOT) / "data" / "r_native" / "deep_dossier.json"
_TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
       "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}


def _order_block(r):
    """Order Block: آخر شمعة معاكسة قبل اندفاع قويّ (>1.2ATR). يرجع أحدث OB طازج + هل السعر داخله."""
    import numpy as np
    if r is None or len(r) < 20:
        return None
    o, h, l, c = r["open"], r["high"], r["low"], r["close"]
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    atr = float(tr[-14:].mean()) if len(tr) >= 14 else (float(tr.mean()) if len(tr) else 0.0)
    if atr <= 0:
        return None
    cur = float(c[-1])
    for i in range(len(r) - 2, 5, -1):
        body = float(c[i] - o[i])
        if abs(body) >= 1.2 * atr:                       # اندفاع قويّ
            d = 1 if body > 0 else -1
            for j in range(i - 1, max(0, i - 6), -1):     # آخر شمعة معاكسة قبله = OB
                if (c[j] - o[j]) * d < 0:
                    lo = float(min(o[j], c[j])); hi = float(max(o[j], c[j]))
                    return {"dir": d, "lo": round(lo, 5), "hi": round(hi, 5),
                            "near": lo <= cur <= hi, "dist_atr": round(min(abs(cur - lo), abs(cur - hi)) / atr, 2)}
            break
    return None


def smc(sym, tf="M1", bars=300):
    """تحليل SMC كامل لرمز/فريم. يرجع dict مضغوط للعرض اللحظيّ."""
    out = {"tf": tf}
    try:
        r = mt5.copy_rates_from_pos(sym, _TF.get(tf, mt5.TIMEFRAME_M1), 0, bars)
        if r is None or len(r) < 60:
            return {"tf": tf, "error": "لا بيانات"}
        close, high, low = r["close"], r["high"], r["low"]
        # البنية + BOS
        if ms is not None:
            st = ms.structure(sym, tf if tf in ("M1", "M5", "M15") else "M5")
            out["trend"] = st.get("label"); out["dir"] = st.get("trend"); out["bos"] = st.get("bos")
        # CHoCH / CISD / IFVG
        if smcs is not None:
            ch = smcs.choch(close, high, low)
            out["choch"] = "CHoCH↑" if ch > 0 else "CHoCH↓" if ch < 0 else None
            ci = smcs.cisd(close, high, low)
            out["cisd"] = "CISD↑" if ci > 0 else "CISD↓" if ci < 0 else None
            iv = smcs.ifvg(close, high, low)
            out["ifvg"] = "IFVG↑" if iv > 0 else "IFVG↓" if iv < 0 else None
        # FVG + سيولة + زخم
        if micro is not None:
            g = micro.detect_gap(r)
            out["fvg"] = ("FVG↑ %.1fATR" % g[1]) if g[0] > 0 else ("FVG↓ %.1fATR" % g[1]) if g[0] < 0 else None
            w = micro.detect_wick_rev(r)        # dir = اتجاه الارتداد بعد خطف السيولة
            out["sweep"] = ("صيد سيولة → ارتداد↑" if w[0] > 0 else "صيد سيولة → ارتداد↓" if w[0] < 0 else None)
            m = micro.detect_momentum(r)
            out["momentum"] = ("زخم↑ %.1fATR" % m[1]) if m[0] > 0 else ("زخم↓ %.1fATR" % m[1]) if m[0] < 0 else None
        ob = _order_block(r)                              # Order Block
        if ob:
            tag = "OB↑" if ob["dir"] > 0 else "OB↓"
            where = "⊙داخله" if ob["near"] else (str(ob["dist_atr"]) + "ATR")
            out["ob"] = "%s %s @%s-%s" % (tag, where, ob["lo"], ob["hi"])
            out["ob_zone"] = [ob["lo"], ob["hi"], ob["dir"]]      # رقميّ لرسم المنطقة على الشارت
        # منطقة FVG (3 شموع) رقميّة للرسم
        if len(r) >= 3:
            a3, c3 = r[-3], r[-1]
            if a3["high"] < c3["low"]:
                out["fvg_zone"] = [float(a3["high"]), float(c3["low"]), 1]
            elif a3["low"] > c3["high"]:
                out["fvg_zone"] = [float(c3["high"]), float(a3["low"]), -1]
    except Exception as e:
        out["error"] = f"{type(e).__name__}"
    return out


def friday(sym):
    """تحليل عقل المشروع المنفّذ (deep_dossier) — ما يقود قرارات الدخول."""
    try:
        d = json.load(open(_DOSS, encoding="utf-8-sig"))
        sd = (d.get("symbols", {}) or {}).get(sym)
        if not sd:
            return None
        return {k: sd.get(k) for k in ("bias", "call", "gsignal", "confluence", "score",
                                       "high_conf", "rsi_h1", "conviction", "session",
                                       "nearest_above", "nearest_below")}
    except Exception:
        return None


def position(sym):
    """هل المشروع/المستخدم له مركز مفتوح على الرمز الآن؟ (مجمّع)."""
    try:
        pos = [p for p in (mt5.positions_get(symbol=sym) or [])]
        if not pos:
            return None
        net = sum(p.profit for p in pos)
        vol = sum(p.volume for p in pos)
        buys = sum(1 for p in pos if p.type == 0)
        return {"n": len(pos), "vol": round(vol, 2), "pnl": round(net, 2),
                "side": "BUY" if buys > len(pos) / 2 else "SELL" if buys < len(pos) / 2 else "MIX"}
    except Exception:
        return None


def setup(sym, tf="M5"):
    """خطّة SMC احترافية: اتجاه + منطقة ذهبية (fib 0.618-0.786) + دخول + وقف + أهداف + R:R + قائمة تحقّق.
    صدق: هذه خطّة بنيويّة للانضباط/العرض (SMC اختُبر ~50% بالمشروع) — لا حافّة مُثبتة، بل تأطير منهجيّ كالمحترفين."""
    try:
        if ms is None:
            return {"valid": False, "reason": "البنية غير متاحة"}
        r = mt5.copy_rates_from_pos(sym, _TF.get(tf, mt5.TIMEFRAME_M5), 0, 300)
        if r is None or len(r) < 60:
            return {"valid": False, "reason": "لا بيانات"}
        cur = float(r["close"][-1])
        highs, lows = ms._swings(sym, _TF.get(tf, mt5.TIMEFRAME_M5), n=300, k=2)
        if len(highs) < 1 or len(lows) < 1:
            return {"valid": False, "reason": "قمم/قيعان غير كافية"}
        st = ms.structure(sym, tf)
        trend = st.get("trend")
        sh = highs[-1]; sl = lows[-1]                      # (فهرس, سعر)
        # الاتجاه: مع البنية إن حُسمت، وإلا حسب آخر ساق
        if trend == "up":
            direction = "BUY"
        elif trend == "down":
            direction = "SELL"
        else:
            direction = "BUY" if sh[0] > sl[0] else "SELL"
        leg_hi = float(sh[1]); leg_lo = float(sl[1])
        rng = leg_hi - leg_lo
        if rng <= 0:
            return {"valid": False, "reason": "ساق غير صالحة"}
        f = lambda a, b, x: a + (b - a) * x
        if direction == "BUY":                            # ارتداد هابط للمنطقة الذهبية ثم استمرار صعود
            gz_hi = leg_hi - 0.618 * rng; gz_lo = leg_hi - 0.786 * rng
            entry = (gz_hi + gz_lo) / 2.0
            stop = leg_lo - 0.12 * rng                    # تحت قاع الساق + هامش
            tps = [leg_hi, leg_hi + 0.272 * rng, leg_hi + 0.618 * rng]
        else:                                             # ارتداد صاعد للمنطقة الذهبية ثم استمرار هبوط
            gz_lo = leg_lo + 0.618 * rng; gz_hi = leg_lo + 0.786 * rng
            entry = (gz_hi + gz_lo) / 2.0
            stop = leg_hi + 0.12 * rng
            tps = [leg_lo, leg_lo - 0.272 * rng, leg_lo - 0.618 * rng]
        risk = abs(entry - stop)
        rr = [round(abs(t - entry) / risk, 1) if risk else 0 for t in tps]
        in_zone = min(gz_lo, gz_hi) <= cur <= max(gz_lo, gz_hi)
        # قائمة التحقّق (مكوّنات الإعداد)
        sm = smc(sym, tf)
        chk = {"BOS": bool(sm.get("bos")), "CHoCH": bool(sm.get("choch")),
               "OB": bool(sm.get("ob")), "FVG": bool(sm.get("fvg")),
               "سيولة": bool(sm.get("sweep")), "منطقة ذهبية": in_zone}
        score = sum(1 for v in chk.values() if v)
        rnd = 5 if "JPY" in sym or any(x in sym for x in ("XAU", "BTC", "ETH", "US", "DE", "NAS")) else 5
        digits = 2 if any(x in sym for x in ("XAU", "BTC", "ETH", "JPY", "US30", "DE", "NAS", "US", "225")) else 5
        R = lambda v: round(v, digits)
        status = ("🟢 منطقة الدخول نشطة الآن" if in_zone
                  else "⏳ ينتظر ارتداداً للمنطقة الذهبية")
        return {"valid": True, "direction": direction, "tf": tf, "status": status,
                "golden_zone": [R(min(gz_lo, gz_hi)), R(max(gz_lo, gz_hi))],
                "entry": R(entry), "stop": R(stop), "targets": [R(t) for t in tps],
                "rr": rr, "in_zone": in_zone, "checklist": chk, "score": score,
                "leg": [R(leg_lo), R(leg_hi)], "price": R(cur)}
    except Exception as e:
        return {"valid": False, "reason": type(e).__name__}


def analyze(sym, tfs=("M1", "M5", "M15", "H1")):
    """التحليل الكامل لرمز: SMC لكل فريم + عقل المشروع + المركز المفتوح + خطط الإعداد الاحترافية."""
    return {"symbol": sym, "friday": friday(sym), "position": position(sym),
            "smc": [smc(sym, tf) for tf in tfs],
            "setups": [setup(sym, t) for t in ("M5", "M15", "H1")]}
