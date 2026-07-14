# -*- coding: utf-8 -*-
"""bot_feature_recorder.py — يلتقط بصمة السوق لحظة دخول كل صفقة بوت (مجيكاتنا) ويكتبها في friday.db
(جدول features) كي يرى المتعلّم الصافي (real_trade_learner: features⋈trades on ticket) **دخولات البوت**.

العطل الذي يصلحه: جدول features كان مجمّداً 13 يوماً — لا أحد يكتب ميزاتٍ لدخولات البوت (الكاتب الوحيد
كان migrate() للصفقات اليدوية فقط). فالمتعلّم الصافي كان **أعمى** عن كل صفقة بوت، يُصدر قواعد طازجة
المظهر على مدخلٍ قديم — ويغذّي بوّابة gold_scalper الحيّة. هذا يسدّ الفجوة بأمان (قراءة-فقط للسوق،
يكتب DB فقط، لا يتداول). يعيد استخدام snapshot() المُثبتة من manual_feature_recorder.

Run: pythonw bot_feature_recorder.py   (windowless تحت الوصيّ)
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import MetaTrader5 as mt5

ROOT = Path(r"C:\Users\Radhi\MT5")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from manual_feature_recorder import snapshot          # نفس بصمة الدخول السببيّة المُثبتة
from friday_db import FridayDB

OURS = {20260608, 20260618, 20260628, 20260612, 20260614, 20260616}   # مجيكاتنا فقط
EXTERNAL = {2447, 20250418, 20250421, 20250422, 20250618}             # لا نلمس خبراء المستخدم
CYCLE_S = 6.0                                                          # سريع كفايةً لالتقاط دخولات قصيرة العمر


def main():
    if not (mt5.initialize() or mt5.initialize()):
        print("[BOTFEAT] mt5 init failed", flush=True); return
    db = FridayDB()
    seen = set()
    try:
        for row in db.con.execute("SELECT ticket FROM features"):
            seen.add(int(row[0]))
    except Exception:
        pass
    print(f"[BOTFEAT] start — تلتقط ميزات دخول البوت (موجودة {len(seen)}) magics {sorted(OURS)}", flush=True)
    while True:
        try:
            for p in (mt5.positions_get() or []):
                if p.magic not in OURS or p.magic in EXTERNAL or int(p.ticket) in seen:
                    continue
                feat = snapshot(p.symbol, p.time)               # بصمة الدخول السببيّة عند وقت الفتح
                if not feat:
                    continue
                db.insert_feature(ticket=int(p.ticket), symbol=p.symbol, ts=float(p.time),
                                  features=feat, side=(1 if p.type == 0 else -1),
                                  lot=float(p.volume), src="bot")
                seen.add(int(p.ticket))
        except Exception as e:
            print(f"[BOTFEAT] err {type(e).__name__}: {e}", flush=True)
        time.sleep(CYCLE_S)


if __name__ == "__main__":
    main()
