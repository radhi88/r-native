# -*- coding: utf-8 -*-
"""peak_watch.py — راصد القمّة + مُشرّح الانهيار.

طلب المستخدم: «راقب كل شيء، تتبّع أعلى رصيد نصله، وإذا خفس بعدها ابحث عن الأسباب وعالجها
من جذورها — لأن كل ما نوصل ~80% ربح أشوفه يتعب ويهجّ معه».

ماذا يفعل (قراءة-فقط، لا يلمس صفقة أبداً):
  • يأخذ عيّنة كل 60ث: equity/balance/قمّة/سحب% + العائم مُقسّماً (يدوي/بوت/خارجي) + عدد المراكز.
  • يكتب المسار الكامل → peak_watch.jsonl (لأريك الرحلة بعد ساعتين).
  • يحفظ القمّة الحيّة → peak_watch_state.json (لا تُنسى عبر إعادة التشغيل).
  • 🔬 عند انهيار (هبوط ≥ CRASH_DD% من القمّة): يلتقط **تشريح الجذر** — مَن نزف فعلاً في
    نافذة الهبوط: مُحقَّق لكل magic + عائم لكل مصدر → peak_watch_crashes.jsonl. هذا ما يكشف
    «من أتعب الحساب»: نزيف يدوي؟ محرّك بعينه؟ ارتداد عائم؟ (يوجّه العلاج من الجذر).

حدود الأمان: قراءة-فقط تماماً. لا يلمس اليدوي/الخارجي. قفل نسخة-مفردة. windowless تحت الوصيّ.
"""
from __future__ import annotations
from engine_lock import claim
import json, time
from collections import defaultdict
from pathlib import Path
import MetaTrader5 as mt5

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
TRAIL = RN / "peak_watch.jsonl"            # مسار العيّنات (الرحلة)
STATE = RN / "peak_watch_state.json"       # القمّة الحيّة
CRASH = RN / "peak_watch_crashes.jsonl"    # تشريح الانهيارات

EXT = {2447, 20250418, 20250421, 20250422, 20250618}   # خبراء المستخدم الخارجيّون — لا نلمس، لكن نُحاسِب
POLL_S      = 60.0      # عيّنة كل دقيقة
CRASH_DD    = 4.0       # هبوط ≥ هذا % من القمّة = انهيار يستحقّ التشريح
RECRASH_MIN = 20.0      # لا تُكرّر تشريح نفس القمّة قبل هذه الدقائق (تفادي السبام)
WINDOW_MIN  = 20.0      # نافذة «مَن نزف» = آخر كم دقيقة من الصفقات المُحقَّقة


def _load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"peak": 0.0, "peak_ts": 0.0, "last_crash_ts": 0.0, "last_crash_peak": 0.0}


def _save(p, obj):
    tmp = p.with_suffix(p.suffix + ".tmp")
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    tmp.replace(p)


def _append(p, obj):
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _floating_by_source():
    """العائم الحالي مقسّماً: يدوي(0) / بوت(لنا) / خارجي(خبراء المستخدم)."""
    pos = mt5.positions_get() or []
    g = defaultdict(float); cnt = defaultdict(int)
    for p in pos:
        src = "manual" if p.magic == 0 else ("ext" if p.magic in EXT else "bot")
        g[src] += p.profit + p.swap          # العائم = ربح + سواب (العمولة مُحقَّقة سلفاً)
        cnt[src] += 1
    return {k: round(g[k], 2) for k in g}, {k: cnt[k] for k in cnt}, len(pos)


def _realized_by_magic(since_s):
    """صافي مُحقَّق لكل magic منذ since_s (يكشف مَن أغلق على خسارة في نافذة الهبوط)."""
    deals = mt5.history_deals_get(since_s, time.time()) or []
    net = defaultdict(float); n = defaultdict(int)
    for d in deals:
        if d.entry == 1:                     # إغلاق فقط (مُحقَّق)
            net[d.magic] += d.profit + d.commission + d.swap
            n[d.magic] += 1
    out = []
    for m in net:
        src = "manual" if m == 0 else ("ext" if m in EXT else "bot")
        out.append({"magic": int(m), "src": src, "net": round(net[m], 2), "n": n[m]})
    out.sort(key=lambda x: x["net"])          # الأسوأ أوّلاً
    return out


def _anatomy(eq, peak, dd_pct):
    """🔬 تشريح الانهيار: مَن نزف في نافذة الهبوط (مُحقَّق لكل magic + عائم لكل مصدر)."""
    fl, fl_cnt, npos = _floating_by_source()
    realized = _realized_by_magic(time.time() - WINDOW_MIN * 60)
    worst = realized[0] if realized else None
    by_src = defaultdict(float)
    for r in realized:
        by_src[r["src"]] += r["net"]
    return {
        "ts": time.time(), "kind": "CRASH",
        "peak": round(peak, 2), "equity": round(eq, 2), "dd_pct": round(dd_pct, 1),
        "drop_usd": round(peak - eq, 2),
        "realized_window_min": WINDOW_MIN,
        "realized_by_src": {k: round(by_src[k], 2) for k in by_src},
        "realized_worst_magic": worst,
        "realized_detail": realized[:8],
        "floating_now_by_src": fl, "floating_counts": fl_cnt, "n_positions": npos,
        "verdict": _verdict(by_src, fl),
    }


def _verdict(realized_by_src, floating_by_src):
    """جملة جذر واحدة: ما الذي أتعب الحساب؟"""
    r_man = realized_by_src.get("manual", 0.0); r_bot = realized_by_src.get("bot", 0.0)
    r_ext = realized_by_src.get("ext", 0.0)
    f_man = floating_by_src.get("manual", 0.0); f_bot = floating_by_src.get("bot", 0.0)
    parts = []
    if r_man < -1 or f_man < -1:
        parts.append(f"يدوي (مُحقَّق {r_man:+.0f} / عائم {f_man:+.0f}) — حارس اليدوي يُمسك الأحمر")
    if r_bot < -1 or f_bot < -1:
        parts.append(f"بوتات (مُحقَّق {r_bot:+.0f} / عائم {f_bot:+.0f}) — المايسترو يخنق النزّاف")
    if r_ext < -1:
        parts.append(f"خبراء خارجيّون (مُحقَّق {r_ext:+.0f}) — ملك المستخدم، لا نلمس")
    return "؛ ".join(parts) if parts else "ارتداد عائم بلا إغلاق خسارة — الحاصد يبنك الأخضر قبل ارتداده"


def _cycle(st):
    acct = mt5.account_info()
    if not acct:
        return st
    eq = float(acct.equity); bal = float(acct.balance)
    peak = max(float(st.get("peak", 0.0)), eq)
    new_peak = peak > float(st.get("peak", 0.0))
    st["peak"] = peak
    if new_peak:
        st["peak_ts"] = time.time()
    dd_pct = ((peak - eq) / peak * 100.0) if peak > 0 else 0.0
    fl, fl_cnt, npos = _floating_by_source()
    _append(TRAIL, {"ts": time.time(), "eq": round(eq, 2), "bal": round(bal, 2),
                    "peak": round(peak, 2), "dd": round(dd_pct, 1),
                    "fl": fl, "npos": npos, "new_peak": new_peak})
    # 🔬 كشف الانهيار
    now = time.time()
    cooled = (now - float(st.get("last_crash_ts", 0.0))) > RECRASH_MIN * 60
    fresh_peak = abs(peak - float(st.get("last_crash_peak", 0.0))) > 0.01   # قمّة جديدة منذ آخر انهيار
    if dd_pct >= CRASH_DD and peak > 0 and (cooled or fresh_peak):
        anat = _anatomy(eq, peak, dd_pct)
        _append(CRASH, anat)
        st["last_crash_ts"] = now
        st["last_crash_peak"] = peak
    _save(STATE, st)
    return st


def main():
    claim("peak_watch")                       # 🔒 قفل نسخة-مفردة
    for _ in range(3):
        if mt5.initialize():
            break
        time.sleep(2)
    st = _load_state()
    while True:
        try:
            st = _cycle(st)
        except Exception:
            pass
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
