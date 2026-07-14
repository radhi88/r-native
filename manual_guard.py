"""manual_guard.py — حارس مخاطر التداول اليدوي (magic 0).

الخلفية (تدقيق 2026-06-15، 13 وكيلاً): البوتات رابحة (+$1,070/7d) لكن التداول اليدوي نازف
(−$7,246/7d)، ≈100% منه في الذهب، بتوقيع «قطع الرابح وترك الخاسر» (متوسط ربح ~$34 مقابل خسارة
~−$147، أسوأ صفقة −$2,493). كل محرّكات التحسين/القتل تراقب البوتات (الرابحة) ولا تلمس النازف
الحقيقي (اليدوي) بحكم التصميم. هذا الحارس يسدّ تلك الفجوة الوحيدة — مع احترام القاعدة الصارمة:

  ✅ يحمي أي صفقة يدوية عارية (بلا وقف) بوقف كارثي سخيّ (أبعد من 2% أو 2.5×ATR من السعر الحالي)
     — هذا ما فوّض به المستخدم صراحةً: «احمِ أي يدوي عارٍ بوقف». لا يلمس صفقة لها وقف أصلاً.
  ✅ ينبّه: يحسب مخاطر اليدوي (عائم، تركّز، تداول ليلي، عمق الغرق) ويكتب manual_guard.json
     + سطراً صاخباً تقرؤه غرفة العمليات/الحلقة الليلية.
  🚫 لا يُغلق أي صفقة يدوية أبداً · لا يُعدّل وقف صفقة لها وقف · لا يرسل أي أمر دخول. DEMO فقط.
"""
from __future__ import annotations
import json, time
from pathlib import Path

RN = Path(r"C:\Users\Radhi\MT5\data\r_native")
OUT = RN / "manual_guard.json"
POLL = 8                    # كان 30: المستخدم يفتح يدوياً بسرعة (نظامه هجومي) — نحمي العاري أسرع
STOP_PCT = 0.02              # وقف كارثي: 2% من السعر الحالي (سخيّ — يمنع الكارثة لا يدير الصفقة)
STOP_ATR_MULT = 2.5
NIGHT_START, NIGHT_END = 22, 8   # نافذة الحظر المثبتة النزف (وقت خادم تقريبي = UTC)
POS_LOSS_ALERT = 50.0        # ننبّه على أي صفقة يدوية مفردة تخسر أكثر من هذا (أو نسبة الحقوق)
POS_LOSS_PCT = 0.025         # = أو 2.5% من الحقوق، أيّهما أكبر — لكسر نمط «اترك الخاسر يكبر»


def _atr(rates, n=14):
    if rates is None or len(rates) < n + 1:
        return 0.0
    trs = [max(float(rates[i]["high"]) - float(rates[i]["low"]),
               abs(float(rates[i]["high"]) - float(rates[i - 1]["close"])),
               abs(float(rates[i]["low"]) - float(rates[i - 1]["close"])))
           for i in range(1, len(rates))]
    return sum(trs[-n:]) / min(n, len(trs)) if trs else 0.0


def _protect_naked(mt5, p, info):
    """أضف وقفاً كارثياً لصفقة يدوية عارية فقط (sl==0) — مرجعه السعر الحالي ليبقى صالحاً ويكبح
    الخسارة من هنا فصاعداً. يرجع وصف الإجراء أو None. لا يلمس صفقة لها وقف."""
    if p.sl != 0.0:
        return None
    tick = mt5.symbol_info_tick(p.symbol)
    if not tick:
        return None
    r = mt5.copy_rates_from_pos(p.symbol, mt5.TIMEFRAME_M15, 0, 30)
    a = _atr(r)
    is_buy = p.type == 0
    ref = tick.bid if is_buy else tick.ask          # السعر الذي يُغلق عنده (جهة الخسارة)
    dist = max(STOP_PCT * ref, STOP_ATR_MULT * a)
    if dist <= 0:
        return None
    sl = round(ref - dist if is_buy else ref + dist, info.digits)
    res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol,
                          "position": p.ticket, "sl": sl, "tp": p.tp})
    ok = bool(res and res.retcode == mt5.TRADE_RETCODE_DONE)
    return f"{'✅' if ok else '❌'} حمى يدوي عارٍ {p.symbol} #{p.ticket} sl={sl}"


def scan(mt5):
    ai = mt5.account_info()
    pos = [p for p in (mt5.positions_get() or []) if p.magic == 0]
    actions, by_sym = [], {}
    for p in pos:
        s = by_sym.setdefault(p.symbol, [0, 0.0, 0.0])
        s[0] += 1; s[1] += p.volume; s[2] += p.profit + p.swap
        if p.sl == 0.0:
            info = mt5.symbol_info(p.symbol)
            if info:
                act = _protect_naked(mt5, p, info)
                if act:
                    actions.append(act)
    float_total = sum(p.profit + p.swap for p in pos)
    naked = sum(1 for p in pos if p.sl == 0.0)
    eq = ai.equity if ai else 0.0
    worst = min((p.profit + p.swap for p in pos), default=0.0)
    # 🔴 «اترك الخاسر يكبر» هو النمط القاتل (متوسط خسارة يدوية -$147، أسوأ -$2,493 بينما متوسط
    # الربح ~$34). نصرخ مبكراً على أي صفقة يدوية مفردة تتجاوز عتبة خسارة — قبل ما تكبر. تنبيه فقط.
    loss_thr = -max(POS_LOSS_ALERT, POS_LOSS_PCT * (eq or 1))
    losers = sorted([{"sym": p.symbol, "ticket": int(p.ticket),
                      "dir": "BUY" if p.type == 0 else "SELL", "vol": p.volume,
                      "loss": round(p.profit + p.swap, 1)}
                     for p in pos if (p.profit + p.swap) <= loss_thr],
                    key=lambda x: x["loss"])
    hour = time.gmtime().tm_hour
    night = (hour >= NIGHT_START or hour < NIGHT_END) and len(pos) > 0
    # أكبر تركّز رمز
    top_sym, top_float = (None, 0.0)
    for k, v in by_sym.items():
        if v[2] < top_float:
            top_sym, top_float = k, v[2]
    alerts = []
    if night:
        alerts.append(f"⚠️ تداول يدوي ليلي ({hour:02d}:00 UTC) — النافذة المثبتة النزف")
    if eq and float_total <= -0.05 * eq:
        alerts.append(f"⚠️ عائم اليدوي {float_total:.0f} = {float_total/eq*100:.0f}% من الحقوق")
    if top_sym and top_float <= -0.04 * (eq or 1):
        alerts.append(f"⚠️ تركّز خسارة يدوي في {top_sym} ({top_float:.0f})")
    if naked:
        alerts.append(f"⚠️ {naked} صفقة يدوية عارية — تمت حمايتها بوقف كارثي")
    for L in losers:
        alerts.append(f"🔴 صفقة يدوية خاسرة تكبر: {L['sym']} {L['dir']} #{L['ticket']} = {L['loss']}$ — اقطعها أو ضع وقفاً")
    return {"ts": time.time(), "n_manual": len(pos), "float": round(float_total, 1),
            "naked": naked, "worst": round(worst, 1), "night": night,
            "top_loss_symbol": top_sym, "top_loss_float": round(top_float, 1),
            "losers": losers,
            "by_symbol": {k: {"n": v[0], "lots": round(v[1], 2), "float": round(v[2], 1)}
                          for k, v in by_sym.items()},
            "alerts": alerts, "actions": actions}


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("[MANUAL-GUARD] mt5 init failed", flush=True); return 1
    print("[MANUAL-GUARD] 🛡️ يحرس اليدوي (magic 0): يحمي العاري + ينبّه · لا يُغلق أبداً · DEMO", flush=True)
    try:
        while True:
            try:
                out = scan(mt5)
                RN.mkdir(parents=True, exist_ok=True)
                tmp = OUT.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
                tmp.replace(OUT)
                if out["alerts"] or out["actions"]:
                    print(f"[MANUAL-GUARD] {out['n_manual']} يدوي · عائم {out['float']} · "
                          + " · ".join(out["alerts"] + out["actions"]), flush=True)
            except Exception as e:
                print(f"[MANUAL-GUARD] err {e}", flush=True)
            time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
