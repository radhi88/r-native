# -*- coding: utf-8 -*-
"""tick_recorder.py — محرّك التقاط لحظي (كل جزء من الثانية) لكل حركة سوق + حفظها فوراً.

طلب المستخدم: «نتعرّف على كل تحركاته ونحفظها لحظي، ونعرف الايدج والسبريد وأشكال الشموع
والتواقيت والمستويات السعرية والفجوات وباقي المؤشرات اللحظية.»

عمليّة واحدة كفؤة (لا أسطول — تجنّب الاختناق). حلقة ~0.3ث على رموز سائلة مركّزة (مع الذهب).
لكل رمز كل دورة: السعر/السبريد، سرعة التيك، شمعة M1 المتشكّلة + نمطها، المستويات المفتاحية +
القرب، الفجوات، الزخم/RSI، وتقدير حافّة لحظي صادق (هل الزخم يتجاوز السبريد؟ مقيس).
يكتب data/r_native/live_market.json (لقطة لحظية) + يُلحق الأحداث المهمّة في live_events.jsonl.
قراءة-فقط (لا order_send).
"""
from __future__ import annotations
import json, math, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5

RN = Path(r"C:\Users\Radhi\MT5\data\r_native")
SNAP_F = RN / "live_market.json"
EVENTS_F = RN / "live_events.jsonl"
LOG_F = RN / "tick_recorder.log"

FOCUS = ["XAUUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCADm",
         "BTCUSDm", "ETHUSDm", "US30m", "US500m", "USTECm", "USOILm"]
POLL_S = 0.3                      # كل ~ثلث ثانية (لحظي)
BARS_REFRESH_S = 3.0             # إعادة جلب الشموع كل 3ث (التيك كل دورة)
TICKHIST = 400                   # طول تاريخ التيك لكل رمز (للسرعة والإحصاء)


def _log(m):
    try:
        with open(LOG_F, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _event(d):
    try:
        with open(EVENTS_F, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _session(h):
    return "asia" if h < 7 else "london" if h < 12 else "ny" if h < 21 else "off"


def _bars(sym, tf, n):
    r = mt5.copy_rates_from_pos(sym, tf, 0, n)
    if r is None or len(r) < 3:
        return None
    return r


def _candle_pattern(o, h, l, c, po, pc):
    """نمط آخر شمعة مغلقة (M1) باستخدامها وسابقتها."""
    rng = h - l
    if rng <= 0:
        return "—"
    body = abs(c - o); upper = h - max(o, c); lower = min(o, c) - l
    bp = body / rng
    if bp < 0.1:
        return "دوجي"
    if lower > body * 2 and upper < body:
        return "مطرقة" + ("↑" if c >= o else "")
    if upper > body * 2 and lower < body:
        return "شهاب↓"
    if bp > 0.9:
        return "ماروبوزو" + ("↑" if c > o else "↓")
    # ابتلاع
    if c > o and pc < po and c >= po and o <= pc:
        return "ابتلاع صعودي"
    if c < o and pc > po and c <= po and o >= pc:
        return "ابتلاع هبوطي"
    return ("صعودية" if c > o else "هبوطية") + f" {bp:.0%}جسم"


def _levels(sym, d1, m5):
    out = {}
    if d1 is not None and len(d1) >= 2:
        ph, pl, pc = float(d1[-2]["high"]), float(d1[-2]["low"]), float(d1[-2]["close"])
        piv = (ph + pl + pc) / 3.0
        out["pivot"] = piv; out["R1"] = 2 * piv - pl; out["S1"] = 2 * piv - ph
        out["prev_day_high"] = ph; out["prev_day_low"] = pl; out["prev_day_close"] = pc
    if m5 is not None and len(m5) >= 10:
        hh = [float(m5[i]["high"]) for i in range(2, len(m5) - 2) if m5[i]["high"] == max(m5[i - 2:i + 3]["high"])]
        ll = [float(m5[i]["low"]) for i in range(2, len(m5) - 2) if m5[i]["low"] == min(m5[i - 2:i + 3]["low"])]
        if hh:
            out["swing_high"] = hh[-1]
        if ll:
            out["swing_low"] = ll[-1]
    return out


def _nearest(price, levels):
    above = [(k, v) for k, v in levels.items() if v > price]
    below = [(k, v) for k, v in levels.items() if v < price]
    na = min(above, key=lambda x: x[1]) if above else None
    nb = max(below, key=lambda x: x[1]) if below else None
    return na, nb


def _rsi(c, n=14):
    d = np.diff(c)
    if len(d) < n:
        return 50.0
    up = np.clip(d, 0, None)[-n:].mean(); dn = (-np.clip(d, None, 0))[-n:].mean()
    return 100.0 if dn == 0 else 100.0 - 100.0 / (1.0 + up / dn)


def main():
    if not (mt5.initialize() or mt5.initialize()):
        _log("mt5 init failed"); return
    RN.mkdir(parents=True, exist_ok=True)
    for s in FOCUS:
        if mt5.symbol_info(s) is None:
            try:
                mt5.symbol_select(s, True)
            except Exception:
                pass
    hist = {s: deque(maxlen=TICKHIST) for s in FOCUS}   # (ts, mid, spread)
    bars = {}; bars_ts = 0.0
    _log(f"tick_recorder start: {len(FOCUS)} رمز · poll {POLL_S}s")
    edge = {}                                            # تعلّم حافّة لحظي: هل zصرف الزخم يتجاوز السبريد؟
    while True:
        t0 = time.time()
        try:
            if t0 - bars_ts > BARS_REFRESH_S:
                for s in FOCUS:
                    bars[s] = {"M1": _bars(s, mt5.TIMEFRAME_M1, 60),
                               "M5": _bars(s, mt5.TIMEFRAME_M5, 40),
                               "D1": _bars(s, mt5.TIMEFRAME_D1, 5)}
                bars_ts = t0
            snap = {}
            h = datetime.now(timezone.utc).hour
            for s in FOCUS:
                tick = mt5.symbol_info_tick(s); info = mt5.symbol_info(s)
                if not tick or not info:
                    continue
                bid, ask = tick.bid, tick.ask
                mid = (bid + ask) / 2.0
                spread = ask - bid
                pt = info.point or 1e-5
                spread_pts = round(spread / pt, 1)
                spread_pct = round(spread / mid * 100, 4) if mid else 0
                hist[s].append((t0, mid, spread))
                # سرعة التيك: تغيّر السعر آخر ~2ث، وتقلّب
                vel = 0.0; ticks_per_s = 0.0
                if len(hist[s]) >= 5:
                    recent = [x for x in hist[s] if t0 - x[0] <= 2.0]
                    if len(recent) >= 2:
                        dt = recent[-1][0] - recent[0][0]
                        vel = (recent[-1][1] - recent[0][1]) / pt / max(dt, 1e-6)   # نقاط/ث
                        ticks_per_s = round(len(recent) / max(dt, 1e-6), 1)
                b = bars.get(s) or {}
                m1 = b.get("M1"); m5 = b.get("M5"); d1 = b.get("D1")
                cand = "—"; m1c = {}
                if m1 is not None and len(m1) >= 3:
                    o, hh, ll, c = float(m1[-2]["open"]), float(m1[-2]["high"]), float(m1[-2]["low"]), float(m1[-2]["close"])
                    po, pc = float(m1[-3]["open"]), float(m1[-3]["close"])
                    cand = _candle_pattern(o, hh, ll, c, po, pc)
                    fo, fh, fl, fc = float(m1[-1]["open"]), float(m1[-1]["high"]), float(m1[-1]["low"]), mid
                    m1c = {"o": round(fo, info.digits), "h": round(fh, info.digits),
                           "l": round(fl, info.digits), "c": round(fc, info.digits),
                           "dir": 1 if fc > fo else -1 if fc < fo else 0}
                lv = _levels(s, d1, m5)
                na, nb = _nearest(mid, lv)
                da = round((na[1] - mid) / pt, 1) if na else None
                db = round((mid - nb[1]) / pt, 1) if nb else None
                # فجوة: فتح M1 الحالي مقابل إغلاق السابق + فجوة يومية
                gap = 0.0
                if m1 is not None and len(m1) >= 2:
                    gap = round((float(m1[-1]["open"]) - float(m1[-2]["close"])) / pt, 1)
                day_gap = round((float(m1[0]["open"]) - lv.get("prev_day_close", mid)) / pt, 1) if (m1 is not None and "prev_day_close" in lv) else 0.0
                closes = np.array([x["close"] for x in m1]) if m1 is not None else np.array([mid])
                rsi = round(float(_rsi(closes)), 0)
                roc = round(float((closes[-1] / closes[-6] - 1) * 100), 3) if len(closes) > 6 else 0.0
                # 🎯 حافّة لحظية صادقة: هل |سرعة الزخم| تتجاوز نصف السبريد (تكلفة الدخول)؟
                cost_pts = spread_pts / 2.0
                signal = abs(vel) - cost_pts                  # >0 = حركة تتجاوز التكلفة لحظياً
                e = edge.setdefault(s, {"n": 0, "fav": 0})    # تتبّع: كم مرّة الزخم تجاوز التكلفة
                e["n"] += 1; e["fav"] += int(signal > 0)
                snap[s] = {
                    "bid": round(bid, info.digits), "ask": round(ask, info.digits), "mid": round(mid, info.digits),
                    "spread_pts": spread_pts, "spread_pct": spread_pct,
                    "vel_pps": round(vel, 1), "ticks_per_s": ticks_per_s,
                    "candle": cand, "m1": m1c, "rsi": rsi, "roc": roc,
                    "gap_pts": gap, "day_gap_pts": day_gap,
                    "near_above": ({"name": na[0], "dist_pts": da} if na else None),
                    "near_below": ({"name": nb[0], "dist_pts": db} if nb else None),
                    "edge_signal": round(signal, 1), "edge_fav_pct": round(100 * e["fav"] / e["n"], 0),
                    "session": _session(h),
                }
                # أحداث مهمّة تُحفَظ: لمسة مستوى، فجوة كبيرة، سبريد شاذّ، نمط قوي
                if (da is not None and da < 5) or (db is not None and db < 5):
                    _event({"ts": t0, "sym": s, "kind": "level_touch", "near_above": da, "near_below": db, "mid": round(mid, info.digits)})
                if abs(gap) >= 20:
                    _event({"ts": t0, "sym": s, "kind": "gap", "gap_pts": gap, "candle": cand})
                if "ابتلاع" in cand or "مطرقة" in cand or "شهاب" in cand:
                    _event({"ts": t0, "sym": s, "kind": "pattern", "pattern": cand, "rsi": rsi, "near_above": da, "near_below": db})
            out = {"updated": round(t0, 2), "iso": datetime.now(timezone.utc).isoformat(),
                   "poll_s": POLL_S, "n": len(snap), "symbols": snap}
            json.dump(out, open(SNAP_F, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as ex:
            _log(f"loop err: {type(ex).__name__}: {ex}")
        dt = time.time() - t0
        if dt < POLL_S:
            time.sleep(POLL_S - dt)


if __name__ == "__main__":
    main()
