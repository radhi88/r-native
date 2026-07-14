"""edge_guard.py — المراقب اللحظي لحافّة المستخدم. يراقب اليدوي (magic-0) ويكشف *لحظة فتح أي صفقة*
ما إذا كانت تكسر بصمته الرابحة (مُستخرَجة من 3423 صفقة عبر style_miner)، فيُنبّه قبل أن يتحوّل
الانفعال إلى نزيف. لا يلمس أي صفقة — كشف + تنبيه فقط (يكتب edge_guard.json ويُلحق edge_alerts.log).

بصمة النزيف المُثبتة (توقّع سالب): انتقام بعد خسارة (6% فوز، −$48k) · لوت >0.2 (−$84/صفقة) ·
ذهب ليلاً 22-07 · سكالب <30د (الحافّة سوينغ) · الذهب عموماً (−$10/صفقة مقابل BTC +$23).

Run (watchdog-managed): pythonw edge_guard.py
"""
from __future__ import annotations
import json, time
from datetime import datetime, timezone
from pathlib import Path
import MetaTrader5 as mt5

RN = Path(r"C:\Users\Radhi\MT5\data\r_native")
STATE = RN / "edge_guard.json"
ALERTS = RN / "edge_alerts.log"
CYCLE_S = 20
BIG_LOT = 1.0                 # لوت ≥1.0 = الكارثة المُقاسة (−$93.6/صفقة، 4316 صفقة)؛ لوت 0.1-0.2 رابح (+$31k) فلا نُنذره
REVENGE_WINDOW_S = 120        # ≤2د بعد خسارة = انتقام مُقاس (−$49/صفقة)؛ النافذة الأدقّ (كان 30د فضفاضاً)
SCALP_PACE_N = 6             # >6 صفقات يدوية في 15د = نمط سكالب محموم


_LAST_ALERT = {}                 # tag -> last emit ts (dedup: one alert per pattern per window)
ALERT_COOLDOWN_S = 1200          # 20د: لا تُكرّر نفس نوع المخالفة (تجنّب إغراق الجوال)


def _alert(tag, msg):
    now = time.time()
    if now - _LAST_ALERT.get(tag, 0) < ALERT_COOLDOWN_S:
        return                   # نفس النوع نُبّه عنه قريباً — لا تُكرّر
    _LAST_ALERT[tag] = now
    line = json.dumps({"ts": now, "iso": datetime.now(timezone.utc).isoformat(),
                       "tag": tag, "msg": msg}, ensure_ascii=False)
    with open(ALERTS, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"[EDGE] {tag}: {msg}", flush=True)


def main():
    seen = set()           # tickets we've already evaluated
    seeded = False
    print("[EDGE] edge_guard live — watching your edge-fingerprint", flush=True)
    while True:
        try:
            if not (mt5.initialize() or mt5.initialize()):
                time.sleep(CYCLE_S); continue
            now = time.time()
            pos = [p for p in (mt5.positions_get() or []) if p.magic == 0]
            deals = mt5.history_deals_get(int(now - 3600), int(now)) or []
            mt5.shutdown()

            # last losing manual close (for revenge detection)
            closes = [(d.time, d.profit + d.commission + d.swap) for d in deals
                      if d.magic == 0 and d.entry == 1]
            last_loss_t = max([t for t, pl in closes if pl < 0], default=0)
            # manual opens in last 15min (scalp pace)
            recent_opens = sum(1 for d in deals if d.magic == 0 and d.entry == 0 and d.time > now - 900)

            # seed on first pass so we don't alert pre-existing positions after a restart
            if not seeded:
                seen = {p.ticket for p in pos}; seeded = True

            active = []          # current standing violations (for state)
            for p in pos:
                h = datetime.fromtimestamp(p.time, timezone.utc).hour
                v = []
                if p.volume >= BIG_LOT:
                    v.append(("BIG_LOT", f"لوت {p.volume} ≥1.0 — الكارثة المُقاسة: −$93.6/صفقة (تكبير الخاسر). صغّر."))
                if h >= 22 or h < 8:   # 🌙 الليل (22-08 UTC) على كل العملات = نزفك المُثبت (استبعاده يقلب اليدوي +$904 PF3.36)
                    v.append(("NIGHT", f"تداول ليلي ({h:02d}:00 UTC) — {p.symbol}. حافّتك نهاراً فقط (استبعاد الليل: +$904)"))
                if "XAU" in p.symbol:
                    v.append(("GOLD", "الذهب توقّعك −$10/صفقة (BTC +$23) — رمزك الأضعف"))
                for tag, msg in v:
                    active.append({"ticket": p.ticket, "sym": p.symbol, "tag": tag, "msg": msg})
                # one-time alerts at first sight of a NEW position
                if p.ticket not in seen:
                    seen.add(p.ticket)
                    if last_loss_t and (p.time - last_loss_t) <= REVENGE_WINDOW_S and p.time >= last_loss_t:
                        _alert("REVENGE", f"⚠️ صفقة بعد خسارة بـ{int((p.time-last_loss_t)/60)}د — انتقام مُقاس: −$49/صفقة (1441 صفقة). ابتعد دقائق.")
                    if p.volume >= BIG_LOT:
                        _alert("BIG_LOT", f"⚠️ فتحت لوت {p.volume} ({p.symbol}) — لوت ≥1 كارثة مُقاسة: −$93.6/صفقة. صغّر فوراً.")
                    if h == 23 or h == 0:   # 🔥 ساعتا الكارثة المركّزة (−$30.5k h00 + −$12.1k h23)
                        _alert("CATASTROPHE_HOUR", f"🔥 الساعة {h:02d}:00 UTC ({p.symbol}) — أخطر ساعتين في تاريخك (−$42k مجتمعة). أغلق هذه النافذة.")
                    if h >= 22 or h < 8:
                        _alert("NIGHT", f"⚠️ صفقة ليلية ({h:02d}:00 UTC، {p.symbol}) — نافذة نزفك على كل العملات. حافّتك نهاراً (+$904 باستبعاد الليل).")
            if recent_opens > SCALP_PACE_N:
                # alert once per burst (only when crossing)
                if not getattr(main, "_scalp_flag", False):
                    _alert("SCALP_PACE", f"⚠️ {recent_opens} صفقات يدوية في 15د — نمط سكالب. حافّتك سوينغ (>30د، +$87/صفقة). تمهّل.")
                    main._scalp_flag = True
            else:
                main._scalp_flag = False

            # discipline score: 100 minus penalties for distinct active violation tags
            tags = set(a["tag"] for a in active)
            score = max(0, 100 - 25 * len(tags) - (15 if recent_opens > SCALP_PACE_N else 0))
            STATE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({
                "ts": now, "iso": datetime.now(timezone.utc).isoformat(),
                "n_manual": len(pos), "discipline_score": score,
                "active_violations": active, "recent_opens_15m": recent_opens,
                "edge_reminder": "حافّتك المُقاسة (4316 صفقة): لوت<1.0 (≥1=−$94) · لا انتقام (≤2د=−$49) · سوينغ>120د (+$85 مقابل سكالب −$2.6) · نهار (لا 23/00) · لا overbought/ذهب → −$18k تصير +$41k",
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            import os; os.replace(tmp, STATE)
        except Exception as e:
            print(f"[EDGE] err {e}", flush=True)
        time.sleep(CYCLE_S)


if __name__ == "__main__":
    main()
