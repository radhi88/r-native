# -*- coding: utf-8 -*-
"""perf_ladder.py — 🎚️ سُلّم الثقة المكتسبة (طلب المستخدم 2026-07-04 «يرفع اللوت وقت ما يتعلّم،
نسبة الرضا عالية، ونزيد بالتدريج حتى يصبح أفضل — يختبر ويقيس ويحلّل ويحدّد أهدافه ويثق بها»).

الفلسفة المقدّسة (درس انهيار +80%): رفع اللوت يُكتسب بالإثبات لا بالشعور. «نسبة الرضا» = ثقة
إحصائيّة مقيسة (توقّع موجب + t معنويّ عبر عيّنة حيّة كافية)، لا حماسة. أيّ سحبٍ يعيد للأرضية فوراً
— فلا يتحوّل السُّلّم إلى مارتينجال يزحف نحو الكارثة.

evaluate(magic, cfg) ⇒ dict:
  • يقرأ صفقات المحرّك المُغلقة (نافذة متدحرجة) ويحسب: n · نسبة الفوز · التوقّع (وسيط R) · t.
  • confidence 0-1 = بوابة: يتطلّب n≥min_trades و توقّع>0 و t≥t_gate؛ ويتدرّج مع t.
  • risk_pct = base_risk + (max_risk−base_risk)×confidence (يرتفع بالثقة، بالتدريج).
  • حارس السحب: حقوق < ذروة×(1−dd_reset) ⇒ confidence=0 فوراً (عودة للأرضية) + إنذار.
  • satisfaction% = مؤشّر بشريّ (0-100) يجمع الفوز+التوقّع+t. الحالة تُحفظ (ذروة الحقوق، الدرجة).

قراءة فقط + منطق — لا يرسل أوامر. يُستدعى من المنفّذ ليحجّم لوته بحسب ثقته المكتسبة."""
import os, json, time, math
from datetime import datetime, timedelta
import MetaTrader5 as mt5

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
ALARM = os.path.join(_RN, "news_alarm_feed.jsonl")


def _defaults():
    return {"window_trades": 40, "min_trades": 20, "t_gate": 1.5,
            "base_risk_pct": 0.5, "max_risk_pct": 4.0, "dd_reset_pct": 8.0,
            "step_up_max": 0.34, "_note": "سُلّم الثقة: يرفع المخاطرة (⇒ اللوت) بالثقة المقيسة فقط، "
            "بالتدريج، ويعود للأرضية عند سحب ≥dd_reset. الرضا رقمٌ لا شعور. ديمو."}


def _closed_R(magic, window):
    """آخر (window) صفقة مُغلقة للمحرّك ⇒ قائمة R (ربح/مخاطرة تقريبيّة عبر تطبيع بالوسيط المطلق)."""
    frm = datetime.now() - timedelta(days=30)
    pnls = []
    try:
        deals = mt5.history_deals_get(frm, datetime.now() + timedelta(hours=2)) or []
        outs = [d for d in deals if d.magic == magic and d.entry == 1]
        outs.sort(key=lambda d: d.time)
        pnls = [float(d.profit) + float(d.swap) + float(d.commission) for d in outs][-window:]
    except Exception:
        pass
    return pnls


def _stats(pnls):
    n = len(pnls)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "expectancy": 0.0, "t": 0.0}
    wins = sum(1 for p in pnls if p > 0)
    m = sum(pnls) / n
    var = sum((p - m) ** 2 for p in pnls) / max(1, n - 1)
    t = (m / (math.sqrt(var) / math.sqrt(n))) if var > 1e-9 and n > 2 else 0.0
    return {"n": n, "win_rate": round(100 * wins / n, 1), "expectancy": round(m, 3), "t": round(t, 2)}


def evaluate(magic, cfg=None, state_path=None):
    c = _defaults()
    c.update(cfg or {})
    state_path = state_path or os.path.join(_RN, f"perf_ladder_{magic}.json")
    try:
        st = json.load(open(state_path, encoding="utf-8"))
    except Exception:
        st = {"peak_equity": 0.0, "confidence": 0.0, "risk_pct": c["base_risk_pct"]}

    acct = mt5.account_info()
    equity = float(acct.equity) if acct else 0.0
    peak = max(float(st.get("peak_equity", 0.0)), equity)
    dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0

    s = _stats(_closed_R(magic, int(c["window_trades"])))
    # 🚨 حارس السحب: أيّ سحب ≥ العتبة ⇒ عودة فوريّة للأرضية (لا مارتينجال أبداً)
    dd_hit = dd >= float(c["dd_reset_pct"])
    if dd_hit:
        conf = 0.0
        reason = f"سحب {dd:.1f}% ≥ {c['dd_reset_pct']}% ⇒ عودة للأرضية"
        if not st.get("dd_alarmed"):
            try:
                with open(ALARM, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                                        "kind": "LADDER-RESET", "impact": "High", "currency": "ALL",
                                        "title": f"🎚️⚠️ سُلّم الثقة: سحب {dd:.1f}% — رجعتُ لوت الأرضية (حماية)"},
                                       ensure_ascii=False) + "\n")
            except Exception:
                pass
            st["dd_alarmed"] = True
    else:
        st["dd_alarmed"] = False
        # البوّابة: ثقةٌ فقط بعيّنة كافية + توقّع موجب + معنويّة
        if s["n"] >= int(c["min_trades"]) and s["expectancy"] > 0 and s["t"] >= float(c["t_gate"]):
            target = min(1.0, (s["t"] - float(c["t_gate"])) / 2.0 + 0.34)   # يتدرّج مع t فوق البوّابة
            prev = float(st.get("confidence", 0.0))
            conf = min(target, prev + float(c["step_up_max"]))              # صعودٌ تدريجيّ (درجة واحدة)
            reason = f"مُثبت: n={s['n']} توقّع {s['expectancy']:+.2f} t={s['t']} ⇒ ثقة {conf:.2f}"
        else:
            # لا حافّة مقيسة ⇒ انزل تدريجياً نحو الأرضية
            conf = max(0.0, float(st.get("confidence", 0.0)) - float(c["step_up_max"]))
            reason = (f"لا حافّة مقيسة بعد (n={s['n']}/{c['min_trades']}، t={s['t']}/{c['t_gate']}) ⇒ أرضية"
                      if conf == 0 else f"تراجعٌ نحو الأرضية (ثقة {conf:.2f})")

    risk_pct = float(c["base_risk_pct"]) + (float(c["max_risk_pct"]) - float(c["base_risk_pct"])) * conf
    # نسبة الرضا البشريّة 0-100: خليطٌ من الفوز والتوقّع والمعنويّة (للعرض فقط)
    satisfaction = round(max(0.0, min(100.0,
                    (s["win_rate"] * 0.4) + (min(100.0, s["t"] * 25.0) * 0.4)
                    + (50.0 if s["expectancy"] > 0 else 0.0) * 0.2)), 0)

    st.update({"ts": time.time(), "iso": datetime.now().isoformat(timespec="seconds"),
               "magic": magic, "peak_equity": round(peak, 2), "equity": round(equity, 2),
               "drawdown_pct": round(dd, 2), "confidence": round(conf, 3),
               "risk_pct": round(risk_pct, 2), "satisfaction": satisfaction,
               "stats": s, "reason": reason})
    try:
        t = state_path + ".tmp"; json.dump(st, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(t, state_path)
    except Exception:
        pass
    return st
