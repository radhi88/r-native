# -*- coding: utf-8 -*-
"""news_straddle.py — 🎯 قوسا الأخبار بمواصفة المستخدم الحرفيّة (2026-07-02):
«قبل الخبر نضع أمرَين محدّدين فوق وتحت آخر سعر — شراء (Buy Stop) وبيع (Sell Stop) بلوت 0.1،
واللي يدخل نلغي الأمر الآخر (OCO)».

- التسليح: قبل الحدث الأحمر/البرتقاليّ (USD) بـ arm_before_s ثانية، من news_events.json.
- الإزاحة: فوق/تحت السعر بـ max(0.35×ATR(M5)، 4×السبريد الحاليّ، 1.5$) — تتجاوز توسّع سبريد الخبر.
- OCO حقيقيّ: أوّل جانبٍ يتنفّذ ⇒ يُلغى الآخر فوراً (مراقبة كل ثانيتين حول الخبر).
- وقف لكل أمر: 1.0×ATR(M5) خلف الدخول. تسوية إجباريّة بعد settle_min دقيقة (لا نبيت صفقة خبر).
- حملة واحدة لكل حدث (dedup بالحقبة). kill_switch محترم. ديمو فقط. magic 20260702.
⚠️ صدق المشروع: قياساتنا التاريخيّة لهذا النمط = لا حافّة صافية بعد الكلفة — هذا خيار المستخدم
الصريح بعينٍ مفتوحة، والحجم 0.1 على الذهب = ±10$ لكل 1$ حركة (خبر NFP يتحرّك 10-25$)."""
import os, sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
try:
    _lf = open(os.path.join(_RN, "news_straddle.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

import json, time
import MetaTrader5 as mt5

try:
    import engine_lock
    engine_lock.claim("news_straddle")
except SystemExit:
    raise
except Exception:
    pass

MAGIC = 20260702
SYM = "XAUUSDm"
CFG_F = os.path.join(_RN, "news_straddle_config.json")
ST_F = os.path.join(_RN, "news_straddle_state.json")
EV_F = os.path.join(_RN, "news_events.json")
KILL = os.path.join(_RN, "kill_switch.txt")


def _cfg():
    d = {"enabled": True, "lot": 0.10, "offset_atr": 0.35, "sl_atr": 1.0,
         "arm_before_s": 120, "settle_min": 45, "impacts": ["High", "Medium"],
         "_note": "قوسا الأخبار OCO بمواصفة المستخدم — 0.1 لوت، إلغاء الجانب الآخر فور التنفيذ. ديمو."}
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        try:
            t = CFG_F + ".tmp"; json.dump(d, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(t, CFG_F)
        except Exception:
            pass
    return d


def _st():
    try:
        return json.load(open(ST_F, encoding="utf-8"))
    except Exception:
        return {"done_events": [], "campaign": None}


def _st_save(d):
    try:
        t = ST_F + ".tmp"; json.dump(d, open(t, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(t, ST_F)
    except Exception:
        pass


def _atr_m5(n=14):
    r = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 0, n + 1)
    if r is None or len(r) < n + 1:
        return None
    trs = [max(float(r[i]["high"] - r[i]["low"]), abs(float(r[i]["high"] - r[i - 1]["close"])),
               abs(float(r[i]["low"] - r[i - 1]["close"]))) for i in range(1, len(r))]
    return sum(trs[-n:]) / n


def _next_event(cfg, st):
    try:
        d = json.load(open(EV_F, encoding="utf-8"))
        evs = d.get("events", d) if isinstance(d, dict) else d
    except Exception:
        return None
    now = time.time()
    best = None
    for e in evs or []:
        ep = float(e.get("epoch") or 0)
        if ep <= now or str(e.get("impact")) not in cfg.get("impacts", ["High"]):
            continue
        if str(e.get("currency")) not in ("USD", "ALL"):
            continue
        if int(ep) in st.get("done_events", []):
            continue
        if best is None or ep < best[0]:
            best = (ep, e.get("title", "?"))
    return best


def _pending():
    return [o for o in (mt5.orders_get() or []) if o.magic == MAGIC]


def _positions():
    return [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]


def _cancel(ticket):
    r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
    return bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)


def _arm(cfg, ep, title):
    """يضع القوسين: Buy Stop فوق + Sell Stop تحت آخر سعر."""
    tick = mt5.symbol_info_tick(SYM); si = mt5.symbol_info(SYM)
    atr = _atr_m5()
    if not (tick and si and atr):
        return False
    spread = (tick.ask - tick.bid)
    off = max(cfg.get("offset_atr", 0.35) * atr, 4.0 * spread, 1.5)
    sl_d = cfg.get("sl_atr", 1.0) * atr
    lot = float(cfg.get("lot", 0.10))
    mid = (tick.ask + tick.bid) / 2.0
    up, dn = round(mid + off, si.digits), round(mid - off, si.digits)
    exp = int(time.time() + 30 * 60)
    ok = []
    for typ, px, sl in ((mt5.ORDER_TYPE_BUY_STOP, up, round(up - sl_d, si.digits)),
                        (mt5.ORDER_TYPE_SELL_STOP, dn, round(dn + sl_d, si.digits))):
        r = mt5.order_send({"action": mt5.TRADE_ACTION_PENDING, "symbol": SYM, "volume": lot,
                            "type": typ, "price": float(px), "sl": float(sl), "tp": 0.0,
                            "magic": MAGIC, "comment": "nstraddle",
                            "type_time": mt5.ORDER_TIME_SPECIFIED, "expiration": exp})
        ok.append(bool(r and r.retcode == mt5.TRADE_RETCODE_DONE))
    print(f"🎯 قوسا {title}: شراء@{up} / بيع@{dn} (لوت {lot} · إزاحة {off:.2f} · وقف {sl_d:.2f}) ⇒ {ok}")
    return all(ok)


def main():
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print(f"🎯 قوسا الأخبار بدأ {time.strftime('%Y-%m-%d %H:%M:%S')} — OCO لوت 0.1 (مواصفة المستخدم)")
    while True:
        try:
            cfg = _cfg(); st = _st()
            if not cfg.get("enabled", True) or os.path.exists(KILL):
                time.sleep(10); continue
            # 🛡️ حاجز ديمو (تدقيق C1 2026-07-08): كان «ديمو فقط» توثيقاً بلا إنفاذ — الآن كوداً.
            _acc = mt5.account_info(); _srv = str(getattr(_acc, "server", "") or "")
            if not _acc or not ("Trial" in _srv or "Demo" in _srv):
                time.sleep(30); continue
            camp = st.get("campaign")
            now = time.time()
            if camp:                                          # حملة نشطة: OCO + تسوية
                poss = _positions(); pend = _pending()
                if poss and pend:                             # ⚡ أحدهما دخل ⇒ ألغِ الآخر فوراً (OCO)
                    for o in pend:
                        if _cancel(o.ticket):
                            print(f"✂️ OCO: أُلغي الجانب الآخر ({o.ticket}) بعد تنفيذ {('شراء' if poss[0].type==0 else 'بيع')}")
                if now > camp["ep"] + cfg.get("settle_min", 45) * 60:   # تسوية إجباريّة
                    for o in _pending():
                        _cancel(o.ticket)
                    for p in _positions():
                        tk = mt5.symbol_info_tick(SYM)
                        mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYM, "volume": p.volume,
                                        "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
                                        "position": p.ticket, "price": tk.bid if p.type == 0 else tk.ask,
                                        "deviation": 50, "magic": MAGIC, "comment": "nstraddle_settle",
                                        "type_filling": mt5.ORDER_FILLING_IOC})
                        print(f"🏁 تسوية {p.ticket} بعد {cfg.get('settle_min',45)}د (عائم ${p.profit:+.2f})")
                    st["campaign"] = None; _st_save(st)
                elif not poss and not pend and now > camp["ep"] + 600:
                    print("🏁 انتهت الحملة (لا أوامر ولا مراكز)")
                    st["campaign"] = None; _st_save(st)
                time.sleep(2); continue                        # مراقبة سريعة حول الخبر
            nxt = _next_event(cfg, st)
            if nxt and (nxt[0] - now) <= cfg.get("arm_before_s", 120):
                if _arm(cfg, nxt[0], nxt[1]):
                    st.setdefault("done_events", []).append(int(nxt[0]))
                    st["campaign"] = {"ep": nxt[0], "title": nxt[1]}
                    _st_save(st)
            time.sleep(5)
        except Exception as e:
            print(f"loop err: {type(e).__name__}: {e}")
            time.sleep(15)


if __name__ == "__main__":
    main()
