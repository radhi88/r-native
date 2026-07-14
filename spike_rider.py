"""spike_rider.py — بوت راكب القفزات بنسخة المستخدم (دخول هجومي سريع على القفزة + ركوب).
حيّ على حساب DEMO، magic خاص 20260617، حدود صارمة. يتعلّم على كل جلسة (يسجّل النتيجة لكل جلسة).

⚠️ صدق: الاختبار OOS قال الحافّة المؤكّدة ضيّقة (ذهب M15 قفزة k≥2.5 = +0.38R)؛ هذه النسخة أسرع
(M5, k=2.0) فتدخل أكثر وقد تشمل صفقات بلا حافّة — لكنها DEMO وبحدود، نتعلّم بتنفيذ حقيقي ونبقي الرابح.

الحدود: سقف 2%/صفقة · لوت صغير ثابت · **مركز واحد فقط** (لا تكديس) · قفل بعد خسارتين (ضد الانتقام)
· SL هيكلي + TP=1.5R على البروكر (هو يُغلق) · كل الجلسات مع وسم الجلسة.

Run: pythonw spike_rider.py   (watchdog-managed)
"""
from __future__ import annotations
import json, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5
import portfolio_guard as pg

RN = Path(r"C:\Users\Radhi\MT5\data\r_native")
STATUS = RN / "spike_rider_status.json"
KILL_F = Path(r"C:\Users\Radhi\MT5\kill_switch.txt")   # 🛑 إيقاف طارئ: وجوده يمنع فتح صفقة جديدة فقط

PAPER = False                # 🔴 حيّ على الديمو (طلب المستخدم) — أوامر حقيقية على حساب التجربة
SYMBOL = "XAUUSDm"
TF = mt5.TIMEFRAME_M5        # أسرع من M15 → دخول أكثر
K_SPIKE = 2.0               # قفزة = |إغلاق-فتح| ≥ k×ATR
TP_R = 1.5
SL_ATR = 1.0
MAGIC = 20260617
LOT_HARD = 0.05             # سقف لوت صلب
MAX_TRADE_RISK = 2.0        # سقف خسارة صارم %2 من الحقوق
MAX_POS = 1                 # 🛑 مركز واحد فقط — لا تكديس
REVENGE_LOCK = 2            # توقّف بعد خسارتين متتاليتين
CYCLE_S = 15                # سريع


def _kill_active():
    """🛑 مفتاح الإيقاف الطارئ: يمنع فتح صفقة جديدة فقط. المركز القائم يديره البروكر تلقائياً (SL/TP)."""
    try:
        return KILL_F.exists()
    except Exception:
        return False


def _sess(hr):
    if 22 <= hr or hr < 7: return "ASIAN"
    if 7 <= hr < 12: return "LONDON"
    if 12 <= hr < 16: return "NYOVL"
    return "NYPM"


def _atr(h, l, c, n=14):
    pc = c[:-1]; tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
    return float(np.mean(tr[-n:])) if len(tr) >= n else 0.0


def _calc_lot(eq, sl_dist, info):
    tv = info.trade_tick_value; ts = info.trade_tick_size
    if tv <= 0 or ts <= 0 or sl_dist <= 0:
        return info.volume_min
    ticks = sl_dist / ts
    cap_amt = eq * MAX_TRADE_RISK / 100.0
    lot = cap_amt / (ticks * tv)
    lot = min(lot, LOT_HARD)
    step = info.volume_step or 0.01
    lot = max(info.volume_min, round(lot / step) * step)
    return float(lot)


def _recent_loss_streak():
    """قفل الانتقام: خسائر متتالية في آخر صفقات هذا المحرّك (آخر 24h)."""
    d = mt5.history_deals_get(int(time.time() - 86400), int(time.time())) or []
    closes = [(x.time, x.profit + x.commission + x.swap) for x in d if x.magic == MAGIC and x.entry == 1]
    closes.sort()
    streak = 0
    for _, pl in reversed(closes):
        if pl < 0: streak += 1
        else: break
    return streak


def _session_stats():
    """التعلّم على كل جلسة: صافي + متوسط R تقريبي لكل جلسة من تاريخ هذا المحرّك (7d)."""
    d = mt5.history_deals_get(int(time.time() - 7 * 86400), int(time.time())) or []
    bysess = {}
    for x in d:
        if x.magic == MAGIC and x.entry == 1:
            s = bysess.setdefault(_sess(datetime.fromtimestamp(x.time, timezone.utc).hour), [0, 0.0, 0])
            v = x.profit + x.commission + x.swap
            s[0] += 1; s[1] += v; s[2] += (v > 0)
    return {k: {"n": v[0], "net": round(v[1], 1), "win%": round(v[2] / v[0] * 100) if v[0] else 0}
            for k, v in bysess.items()}


def main():
    # 🔒 قفل وحيد: عدّة حُرّاس قد تُطلق نسخاً متعدّدة تركب نفس القفزة (magic 20260617) = تكديس يكسر
    # حدّ «مركز واحد» = خطر على حساب $100. ربط منفذ محلي ثابت (8716) يضمن نسخة واحدة (يتحرّر عند موت العملية).
    import socket
    _lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock.bind(("127.0.0.1", 8716)); _lock.listen(1)
        main._singleton_lock = _lock          # إبقاء المرجع حيّاً طوال عمر العملية
    except OSError:
        print("[SPIKE-RIDER] نسخة أخرى تعمل بالفعل — خروج (قفل وحيد 8716)", flush=True); return
    print(f"[SPIKE-RIDER] {'PAPER' if PAPER else 'LIVE-DEMO'} · {SYMBOL} M5 · k={K_SPIKE} ride {TP_R}R · magic {MAGIC} · مركز واحد · كل الجلسات", flush=True)
    last_bar = 0
    while True:
        try:
            if not (mt5.initialize() or mt5.initialize()):
                time.sleep(CYCLE_S); continue
            info = mt5.symbol_info(SYMBOL); tick = mt5.symbol_info_tick(SYMBOL)
            acct = mt5.account_info()
            r = mt5.copy_rates_from_pos(SYMBOL, TF, 0, 60)
            mypos = [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC]
            if r is None or len(r) < 20 or not tick or not info or not acct:
                mt5.shutdown(); time.sleep(CYCLE_S); continue
            o = np.array([x["open"] for x in r], float); h = np.array([x["high"] for x in r], float)
            l = np.array([x["low"] for x in r], float); c = np.array([x["close"] for x in r], float)
            t = [int(x["time"]) for x in r]
            atr = _atr(h, l, c)
            cur_bar = t[-1]
            opened = False
            if cur_bar != last_bar and atr > 0 and len(mypos) < MAX_POS:
                last_bar = cur_bar
                bo, bc = o[-2], c[-2]
                move = abs(bc - bo)
                hr = datetime.fromtimestamp(t[-1], timezone.utc).hour
                sess = _sess(hr)
                if move >= K_SPIKE * atr and not _kill_active() and _recent_loss_streak() < REVENGE_LOCK:
                    direction = 1 if bc > bo else -1
                    entry = tick.ask if direction == 1 else tick.bid
                    sl_dist = SL_ATR * atr
                    sl = round(entry - sl_dist if direction == 1 else entry + sl_dist, info.digits)
                    tp = round(entry + TP_R * sl_dist if direction == 1 else entry - TP_R * sl_dist, info.digits)
                    lot = _calc_lot(acct.equity, sl_dist, info)
                    if PAPER:
                        print(f"[SPIKE-RIDER] (ورق) {sess} {'BUY' if direction==1 else 'SELL'} @{entry:.2f}", flush=True)
                    else:
                        otype = mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL
                        _hedge, _hr = pg.would_hedge(mt5, SYMBOL, otype, MAGIC)   # 🚫 لا تفتح عكس محرّكٍ آخر منّا
                        if _hedge:
                            print(f"[SPIKE-RIDER] skip: {_hr}", flush=True)
                        else:
                            res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": lot,
                                                  "type": otype, "price": entry, "sl": sl, "tp": tp, "deviation": 50,
                                                  "magic": MAGIC, "comment": f"spike-{sess}", "type_filling": mt5.ORDER_FILLING_IOC})
                            rc = getattr(res, "retcode", None)
                            if rc == mt5.TRADE_RETCODE_DONE:
                                opened = True
                                print(f"[SPIKE-RIDER] ✅ LIVE {sess} {'BUY' if direction==1 else 'SELL'} {lot} @{entry:.2f} SL{sl:.2f} TP{tp:.2f} (قفزة {move/atr:.1f}ATR)", flush=True)
                            else:
                                print(f"[SPIKE-RIDER] أمر فشل rc={rc} {getattr(res,'comment','')}", flush=True)
            st = _session_stats()
            STATUS.write_text(json.dumps({"ts": time.time(), "iso": datetime.now(timezone.utc).isoformat(),
                                          "mode": "PAPER" if PAPER else "LIVE-DEMO", "open": len(mypos) + (1 if opened else 0),
                                          "magic": MAGIC, "by_session_7d": st,
                                          "spec": f"{SYMBOL} M5 k>={K_SPIKE} ride {TP_R}R · مركز واحد · سقف2% · كل الجلسات"},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
            mt5.shutdown()
        except Exception as e:
            print(f"[SPIKE-RIDER] err {e}", flush=True)
            try: mt5.shutdown()
            except Exception: pass
        time.sleep(CYCLE_S)


if __name__ == "__main__":
    main()
