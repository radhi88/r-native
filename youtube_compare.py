# -*- coding: utf-8 -*-
"""youtube_compare.py — مُحكّم مسابقة الدقّة: القناة مقابل تحليلي (our_trend).
لكل إشارةٍ سُجّلت في signal_compare.jsonl: نأخذ سعرها، ونرى بعد أفق زمنيّ (افتراضيّ 10د) هل تحرّك السعر
في اتجاه القناة (تصيب القناة) وفي اتجاهي (أُصيب أنا). ثمّ نُحصي دقّة كلٍّ. قراءة-فقط."""
import sys, json, time
import MetaTrader5 as mt5

RN = r"C:\Users\Radhi\MT5\data\r_native"
HORIZON = int(sys.argv[1]) * 60 if len(sys.argv) > 1 else 600   # ثوانٍ (افتراضيّ 10د)
SYM = "XAUUSDm"


def main():
    mt5.initialize()
    try:
        rows = [json.loads(l) for l in open(f"{RN}\\signal_compare.jsonl", encoding="utf-8") if l.strip()]
    except Exception:
        print("لا سجلّ مقارنة بعد."); return
    ch_ok = ch_n = me_ok = me_n = both = 0
    resolved = 0
    for e in rows:
        if time.time() - e["ts"] < HORIZON:
            continue                                    # لم يكتمل الأفق بعد
        later = mt5.copy_rates_from(SYM, mt5.TIMEFRAME_M1, e["ts"] + HORIZON, 1)
        if later is None or len(later) == 0:
            continue
        p1 = float(later[0]["close"]); p0 = e["price"]
        if abs(p1 - p0) < 0.1:
            continue                                    # حركةٌ مهملة
        move = "buy" if p1 > p0 else "sell"
        resolved += 1
        ch_n += 1; ch_ok += (e["channel"] == move)
        if e.get("mine"):
            me_n += 1; me_ok += (e["mine"] == move)
    print(f"📊 مسابقة الدقّة (أفق {HORIZON//60}د · إشارات محسومة: {resolved})")
    if ch_n:
        print(f"   🔴 القناة : {ch_ok}/{ch_n} = {ch_ok/ch_n*100:.0f}%")
    if me_n:
        print(f"   🔵 تحليلي : {me_ok}/{me_n} = {me_ok/me_n*100:.0f}%")
        winner = "القناة" if ch_ok/ch_n > me_ok/me_n else ("تحليلي" if me_ok/me_n > ch_ok/ch_n else "تعادل")
        print(f"   🏆 الأدقّ حتى الآن: {winner}")
    elif not ch_n:
        print("   لا إشارات محسومة بعد (تحتاج وقتاً لتتراكم).")
    mt5.shutdown()


if __name__ == "__main__":
    main()
