# -*- coding: utf-8 -*-
"""manual_mimic.py — مُعمّق التعلّم من دخولك اليدويّ: «حلّل دخولي وادركه وحاول تقليدي بمعايير دقيقة».

لكل دخول يدويّ جديد (magic 0) يلتقط **الحالة الكاملة لحظتها**: العقل (انحياز/قرار/التقاء/RSI/الجلسة/
المستويات من deep_dossier) + بنية SMC (M5/M15: HH-HL/LH-LL + BOS) + اتجاهك (BUY/SELL) + قرب القمة/القاع.
ثم يجمعها ويتعلّم **بروفايلك**: «دخولاتك تتجمّع حول هذه الشروط» (نسبة الاتجاه، أفضل الجلسات/الساعات،
بنية M5 الغالبة، متوسّط RSI/الالتقاء). هذه **معايير تقليدك** — أساس تنبيهٍ لاحقٍ حين تتكرّر ظروفك.

صدق: حافّتك تقديريّة؛ هذا يلتقط **سياقك المنهجيّ + انضباطك** لا حدسك. قراءة-فقط (لا يفتح صفقات).
يحترم: magic 0 فقط، يتجاهل الخبراء الخارجيّين. Windowless.  Run: pythonw manual_mimic.py
"""
from __future__ import annotations
import json, os, sys, time
from collections import Counter
from pathlib import Path
import MetaTrader5 as mt5

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    import market_structure as ms
except Exception:
    ms = None

DOSS = RN / "deep_dossier.json"
DNA = RN / "manual_entry_dna.jsonl"
PROFILE = RN / "manual_mimic_profile.json"
SEEN = RN / "manual_mimic_seen.json"
LOG = RN / "manual_mimic.log"
MAGIC = 0
EXTERNAL = {2447, 20250418, 20250421, 20250422, 20250618}
POLL_S = 60.0


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _doss(sym):
    try:
        d = json.load(open(DOSS, encoding="utf-8-sig"))
        return (d.get("symbols", {}) or {}).get(sym, {})
    except Exception:
        return {}


def _capture(d):
    """يلتقط سياق دخولٍ يدويّ. السياق الحيّ (SMC/العقل) يُلتقط فقط للدخول **الحديث** (لحظيّ) —
    أمّا التاريخيّ (backfill) فالحالة الحاليّة مضلّلة له، فنكتفي بالأساس (اتجاه/رمز/ساعة)."""
    sym = d.symbol
    fresh = (time.time() - d.time) < 300                 # حديث ≤5 دقائق ⇒ سياق حيّ دقيق
    ctx = {"ticket": d.ticket, "ts": d.time, "iso": time.strftime("%Y-%m-%dT%H:%M", time.localtime(d.time)),
           "sym": sym, "side": "BUY" if d.type == 0 else "SELL", "price": d.price, "vol": d.volume,
           "hour": time.gmtime(d.time).tm_hour, "live": fresh}
    if fresh:
        sd = _doss(sym)
        ctx.update({"bias": sd.get("bias"), "call": sd.get("call"), "confluence": sd.get("confluence"),
                    "score": sd.get("score"), "rsi_h1": sd.get("rsi_h1"), "session": sd.get("session"),
                    "near_above": sd.get("nearest_above"), "near_below": sd.get("nearest_below")})
        if ms is not None:
            for tf in ("M5", "M15"):
                try:
                    st = ms.structure(sym, tf)
                    ctx["struct_" + tf] = st.get("trend")
                    ctx["bos_" + tf] = st.get("bos")
                except Exception:
                    pass
    return ctx


def _learn():
    """يحلّل DNA المتراكم ⇒ بروفايل معايير تقليدك."""
    rows = []
    try:
        for ln in open(DNA, encoding="utf-8"):
            ln = ln.strip()
            if ln:
                rows.append(json.loads(ln))
    except Exception:
        pass
    n = len(rows)
    if n < 5:
        return {"n": n, "note": "عيّنة صغيرة — يلتقط ويتعلّم (يحتاج ≥5 دخولات)"}
    sides = Counter(r.get("side") for r in rows)
    sess = Counter(r.get("session") for r in rows if r.get("session"))
    s5 = Counter(r.get("struct_M5") for r in rows if r.get("struct_M5"))
    hours = Counter(r.get("hour") for r in rows if r.get("hour") is not None)
    syms = Counter(r.get("sym") for r in rows if r.get("sym"))
    rsis = [r["rsi_h1"] for r in rows if isinstance(r.get("rsi_h1"), (int, float))]
    confs = [r["confluence"] for r in rows if isinstance(r.get("confluence"), (int, float))]
    bos_with = sum(1 for r in rows if r.get("bos_M5") or r.get("bos_M15"))
    return {"n": n,
            "side_pct": {k: round(100 * v / n) for k, v in sides.items()},
            "top_symbols": syms.most_common(4),
            "top_sessions": sess.most_common(3),
            "struct_M5_pct": {k: round(100 * v / n) for k, v in s5.items()},
            "top_hours_utc": [h for h, _ in hours.most_common(5)],
            "avg_rsi_h1": round(sum(rsis) / len(rsis), 1) if rsis else None,
            "avg_confluence": round(sum(confs) / len(confs), 3) if confs else None,
            "entered_on_bos_pct": round(100 * bos_with / n),
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}


def main():
    mt5.initialize()
    RN.mkdir(parents=True, exist_ok=True)
    seen = set()
    try:
        seen = set(json.load(open(SEEN)))
    except Exception:
        pass
    _log("manual_mimic start — يتعلّم دخولك اليدويّ")
    while True:
        try:
            deals = mt5.history_deals_get(time.time() - 3 * 86400, time.time()) or []
            new = [d for d in deals if d.entry == 0 and d.magic == MAGIC and d.magic not in EXTERNAL
                   and d.ticket not in seen and d.symbol and d.price > 0 and d.volume > 0]
            for d in new:
                ctx = _capture(d)
                with open(DNA, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ctx, ensure_ascii=False) + "\n")
                seen.add(d.ticket)
            if new:
                json.dump(list(seen), open(SEEN, "w"))
                _log(f"التقط {len(new)} دخولاً يدويّاً")
            prof = _learn()
            tmp = PROFILE.with_suffix(".json.tmp")
            json.dump(prof, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            os.replace(tmp, PROFILE)
        except Exception as e:
            _log(f"err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    if "--once" in sys.argv:
        mt5.initialize()
        d = mt5.history_deals_get(time.time() - 3 * 86400, time.time()) or []
        man = [x for x in d if x.entry == 0 and x.magic == 0 and x.symbol and x.price > 0 and x.volume > 0]
        print(f"دخولات يدوية صالحة (3 أيام): {len(man)} — أملأ DNA…")
        seen = set()
        try:
            seen = set(json.load(open(SEEN)))
        except Exception:
            pass
        with open(DNA, "a", encoding="utf-8") as f:
            for x in man:
                if x.ticket not in seen:
                    f.write(json.dumps(_capture(x), ensure_ascii=False) + "\n")
                    seen.add(x.ticket)
        json.dump(list(seen), open(SEEN, "w"))
        print("بروفايل تقليدك:", json.dumps(_learn(), ensure_ascii=False, indent=1))
    else:
        main()
