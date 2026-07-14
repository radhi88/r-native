import MetaTrader5 as mt5, time, sys
mt5.initialize()
last = {"eq": None, "n": None, "sl": None, "fl": None}
t0 = time.time()
while time.time() - t0 < 3.5*3600:
    try:
        a = mt5.account_info()
        man = [p for p in (mt5.positions_get() or []) if p.magic == 0]
        n = len(man); sl = len([p for p in man if p.sl]); fl = sum(p.profit for p in man)
        eq = a.equity
        line = None
        if last["n"] is None:
            line = f"بدء المراقبة: {n} صفقات · حقوق ${eq:.2f} · عائم ${fl:+.2f} · بوقف {sl}/{n}"
        elif n != last["n"]:
            line = f"{'📉 أُغلقت' if n < last['n'] else '📈 فُتحت'} صفقة ⇒ الآن {n} صفقات · حقوق ${eq:.2f} · عائم ${fl:+.2f}"
        elif sl != last["sl"]:
            line = f"🔐 وقفٌ عُدّل ⇒ بوقف {sl}/{n}"
        elif last["eq"] is not None and abs(eq - last["eq"]) >= 3.0:
            line = f"{'🟢' if eq > last['eq'] else '🔴'} الحقوق ${eq:.2f} (عائم ${fl:+.2f})"
        if line:
            print(line, flush=True)
            last = {"eq": eq, "n": n, "sl": sl, "fl": fl}
        elif last["eq"] is None:
            last = {"eq": eq, "n": n, "sl": sl, "fl": fl}
    except Exception as e:
        print(f"err {type(e).__name__}", flush=True)
        time.sleep(15)
    time.sleep(5)
print("انتهت نافذة المراقبة", flush=True)
