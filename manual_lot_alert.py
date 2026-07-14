# -*- coding: utf-8 -*-
"""manual_lot_alert.py — التنبيه الصاخب: يحذّرك لحظة تفتح لوتاً كبيراً يدوياً (magic 0)، خاصّةً بعد ربح.

التحقيق الجنائيّ في اللوقز أثبت أنّ جذر «نوصل ربح ثم يخفس» = **تحجيمك اليدويّ**: بعد يوم رابح يقفز
لوتك ~60× (حتى 7.38 لوت) → avg-down حجم-كامل في ذهب هابط يمحو كل شيء (يدويّك magic 0 = −$88,127
على اللوت الكبير، مقابل +$56k على الصغير). هذا الحارس **قراءة-فقط**: يرصد كل مركز يدويّ جديد، فإن كان
لوته كبيراً (مخاطرة > عتبة من الحقوق، أو لوت ≥ عتبة مطلقة) ينبّه فوراً — ويُصعّد إن كنتَ **رابحاً مؤخّراً**
(نمط الكارثة بالضبط). لا يلمس صفقتك أبداً — ينبّهك لتصغّر بنفسك.

يكتب التنبيهات إلى data/r_native/manual_lot_alerts.jsonl (يرصدها مُراقبٌ ويرسلها لجوالك). ديمو/أيّ حساب،
windowless تحت الوصيّ. قفل نسخة-مفردة.
"""
from __future__ import annotations
import json, time
from pathlib import Path
import MetaTrader5 as mt5

try:
    from engine_lock import claim
except Exception:
    def claim(n): return True

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
ALERTS = RN / "manual_lot_alerts.jsonl"
LOG = RN / "manual_lot_alert.log"
SEEN = RN / "manual_lot_alert_seen.json"

MANUAL_MAGIC = 0          # اليدويّ (أنت) — مصدر الكارثة المُثبت
RISK_PCT_BIG = 3.0        # لوت يخاطر > 3% من الحقوق على حركة 1% = «كبير» ⇒ تنبيه
LOT_ABS_BIG  = 0.20       # أو لوت ≥ 0.20 مطلقاً (عتبة الكارثة المُثبتة: ≥0.2 = −$45k)
WIN_LOOKBACK_H = 6        # إن كان مُحقَّق آخر 6س موجباً (رابح) ⇒ نمط الكارثة ⇒ تصعيد
POLL_S = 2.0             # رصدٌ سريع (نُمسكه لحظة الفتح)


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _risk_pct(p, eq):
    """مخاطرة المركز على حركة 1% عكسيّة كنسبةٍ من الحقوق (نفس مقياس lot_guard)."""
    info = mt5.symbol_info(p.symbol)
    if not info or eq <= 0:
        return 0.0
    ts = info.trade_tick_size or info.point
    tv = info.trade_tick_value
    price = p.price_open or 0.0
    if not ts or not tv or price <= 0:
        return 0.0
    risk = (price * 0.01 / ts) * tv * p.volume      # خسارة على حركة 1%
    return risk / eq * 100.0


def _won_recently():
    """هل أنت رابحٌ في آخر WIN_LOOKBACK_H ساعة (يدويّ)؟ ⇒ نمط الكارثة (تكبير بعد ربح)."""
    deals = mt5.history_deals_get(time.time() - WIN_LOOKBACK_H * 3600, time.time()) or []
    net = sum(d.profit + d.commission + d.swap for d in deals if d.magic == MANUAL_MAGIC and d.entry == 1)
    return net > 0, round(net, 2)


def _load_seen():
    try:
        return set(json.load(open(SEEN, encoding="utf-8")))
    except Exception:
        return set()


def _save_seen(s):
    try:
        json.dump(sorted(s)[-500:], open(SEEN, "w", encoding="utf-8"))
    except Exception:
        pass


def _alert(p, eq, rp, won, won_net):
    """يكتب تنبيهاً صاخباً (يرصده المُراقب ويُرسله لجوالك). لا يلمس الصفقة."""
    sev = "🚨🚨 كارثة محتملة" if won else "⚠️ تنبيه"
    msg = (f"{sev}: لوت يدويّ كبير! {p.symbol} {'شراء' if p.type==0 else 'بيع'} {p.volume} لوت "
           f"= {rp:.1f}% مخاطرة من حقوقك (${eq:.0f}).")
    if won:
        msg += (f" أنت رابحٌ آخر {WIN_LOOKBACK_H}س (+${won_net}) — **هذا نمطُ الكارثة المُثبت** "
                f"(تكبير بعد ربح = −$88k). صغّر اللوت فوراً!")
    rec = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S"), "ticket": int(p.ticket),
           "symbol": p.symbol, "lot": float(p.volume), "risk_pct": round(rp, 1),
           "after_win": bool(won), "won_net": won_net, "equity": round(eq, 2), "msg": msg}
    try:
        with open(ALERTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    _log(msg)


def main():
    claim("manual_lot_alert")
    for _ in range(3):
        if mt5.initialize():
            break
        time.sleep(2)
    _log(f"manual_lot_alert start — يرصد لوتك اليدويّ الكبير (>{RISK_PCT_BIG}% أو ≥{LOT_ABS_BIG} لوت)")
    seen = _load_seen()
    while True:
        try:
            acct = mt5.account_info()
            eq = acct.equity if acct else 0.0
            for p in (mt5.positions_get() or []):
                if p.magic != MANUAL_MAGIC or p.ticket in seen:
                    continue
                seen.add(p.ticket)
                rp = _risk_pct(p, eq)
                _info = mt5.symbol_info(p.symbol)
                vmin = ((_info.volume_min if _info else 0.01) or 0.01)
                # 🎯 ننبّه على **التكبير المتعمّد** فقط (لا الحدّ الأدنى الحتميّ الذي لا يمكن تصغيره):
                #   لوت ≥ 0.2 (عتبة الكارثة)، أو تكبيرٌ واضح فوق الأدنى (>2.5×) بمخاطرةٍ عالية.
                if p.volume >= LOT_ABS_BIG or (p.volume > vmin * 2.5 and rp >= RISK_PCT_BIG):
                    won, won_net = _won_recently()
                    _alert(p, eq, rp, won, won_net)
            _save_seen(seen)
        except Exception as e:
            _log(f"loop err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
