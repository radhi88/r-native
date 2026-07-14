# -*- coding: utf-8 -*-
"""order_janitor.py — بوّاب الأوامر: وكيلٌ محليّ دائم ($0، بلا اشتراك) يُنظّف الأوامر المعلّقة غير المنطقيّة.

طلب المستخدم بعد اكتشاف 42 أمراً معلّقاً يتيماً من algory (magic 20260605 — نزّافٌ معطَّل أُحيي خلسة):
- «قائمة الإعدام»: أي أمرٍ معلّق من مجيكات معطَّلة ⇒ يُلغى فوراً.
- TTL: أوامرنا المعلّقة الأقدم من مدّةٍ معيّنة ⇒ تُلغى (لكل مجيك مدّته).
- بُعدٌ منطقيّ: أمرٌ معلّق أبعد من 3×ATR عن السعر ⇒ يُلغى (لن يُنفَّذ منطقياً).
🚫 لا يلمس أبداً: اليدويّ (magic 0) ولا EA الخارجيّة {2447,20250418,20250421,20250422,20250618}.
قراءة/إلغاء فقط — لا يفتح صفقات إطلاقاً."""
import os, sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_LOG = os.path.join(_BASE, "data", "r_native", "order_janitor.out.log")
os.makedirs(os.path.dirname(_LOG), exist_ok=True)
try:
    _lf = open(_LOG, "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

import json, time
import MetaTrader5 as mt5

try:
    import engine_lock
    engine_lock.claim("order_janitor")
except SystemExit:
    raise
except Exception:
    pass

CFG_F = os.path.join(_BASE, "data", "r_native", "order_janitor_config.json")
FEED_F = os.path.join(_BASE, "data", "r_native", "order_janitor_feed.jsonl")
STATUS_F = os.path.join(_BASE, "data", "r_native", "order_janitor_status.json")

PROTECTED = {0, 2447, 20250418, 20250421, 20250422, 20250618}   # يدويّ + خارجيّة: لا تُمسّ أبداً


def _cfg():
    d = {"enabled": True, "poll_s": 30,
         "kill_magics": [20260605, 20260600, 3627, 99792],       # معطَّلة/نزّافة: تُلغى أوامرها فوراً
         "default_ttl_min": 90,                                   # عمرٌ أقصى للأمر المعلّق
         "ttl_overrides": {"20260614": 50},                       # news_gene: سلّمه ينتهي 45د — البوّاب احتياط 50د
         "max_atr_mult": 3.0}                                      # أبعد من 3×ATR ⇒ غير منطقيّ
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        try:
            tmp = CFG_F + ".tmp"
            json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(tmp, CFG_F)
        except Exception:
            pass
    return d


def _atr(sym, n=14):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, n + 1)
    if r is None or len(r) < n + 1:
        return None
    trs = [max(float(r[i]["high"] - r[i]["low"]), abs(float(r[i]["high"] - r[i - 1]["close"])),
               abs(float(r[i]["low"] - r[i - 1]["close"]))) for i in range(1, len(r))]
    return sum(trs) / len(trs)


def _log_action(kind, o, why):
    row = {"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "kind": kind,
           "magic": o.magic, "symbol": o.symbol, "price": o.price_open, "why": why}
    try:
        with open(FEED_F, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(f"🧹 {kind}: {o.symbol} magic={o.magic} @ {o.price_open} — {why}")


def cycle(cfg):
    ords = mt5.orders_get() or []
    kill = set(int(x) for x in cfg.get("kill_magics", []))
    cancelled = 0
    atr_cache = {}
    for o in ords:
        if o.magic in PROTECTED:
            continue                                              # 🚫 يدويّ/خارجيّ
        why = None
        if o.magic in kill:
            why = "مجيك معطَّل (قائمة الإعدام)"
        else:
            ttl = float(cfg.get("ttl_overrides", {}).get(str(o.magic), cfg.get("default_ttl_min", 90)))
            age_min = (time.time() - o.time_setup) / 60.0
            if age_min > ttl:
                why = f"تجاوز العمر ({age_min:.0f}د > {ttl:.0f}د)"
            else:
                if o.symbol not in atr_cache:
                    atr_cache[o.symbol] = _atr(o.symbol)
                a = atr_cache[o.symbol]
                ti = mt5.symbol_info_tick(o.symbol)
                if a and ti and ti.bid:
                    if abs(o.price_open - ti.bid) > cfg.get("max_atr_mult", 3.0) * a:
                        why = f"بعيدٌ غير منطقيّ ({abs(o.price_open-ti.bid):.2f} > {cfg.get('max_atr_mult',3.0)}×ATR)"
        if why:
            r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
            if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                cancelled += 1
                _log_action("إلغاء", o, why)
    st = {"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
          "pending_total": len(ords), "cancelled_this_cycle": cancelled}
    try:
        tmp = STATUS_F + ".tmp"
        json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, STATUS_F)
    except Exception:
        pass


def main():
    ok = False
    for _ in range(6):
        if mt5.initialize():
            ok = True; break
        time.sleep(10)
    if not ok:
        print("[mt5] فشل الاتصال — خروج"); return
    print(f"🧹 بوّاب الأوامر بدأ {time.strftime('%Y-%m-%d %H:%M:%S')}")
    while True:
        try:
            cfg = _cfg()
            if cfg.get("enabled", True):
                cycle(cfg)
            time.sleep(max(10, int(cfg.get("poll_s", 30))))
        except Exception as e:
            print(f"cycle err: {type(e).__name__}: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
