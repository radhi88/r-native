# -*- coding: utf-8 -*-
"""unified_brain.py — 🧠 المخ الواحد (طلب المستخدم 2026-07-04 «تركيبهم مع بعض يكون مخ واحد، أسرع شيء»).

يصهر كل عيون المشروع في **حكمٍ واحد لكل عملة**، بأقصى سرعة: يقرأ الملفات الجاهزة الطازجة فقط
(نبض السوق · مكتب الحسابات · العقل العميق deep_dossier · مجلس العقول · المطوّر الذاتيّ) — بلا أيّ
نداء MT5 — فيدور كلّ ثانية بلا كلفة. المخرج unified_brain.json تقرؤه القمرة والمحرّك.

الأصوات لكل رمز (كلّها -1..+1، الغائب/القديم = صفر — محافظ):
  • النبض 0.30 : (score-50)/50 مع تأييد smc.trend
  • المكتب 0.25 : composite/100
  • العقل العميق 0.25 : ±score حسب bias، مضروبٌ بمحاذاة HTF
  • النبض-SMC 0.10 : اتجاه البنية + آخر BOS
  • المجلس 0.10 : اتّفاق المجلس (للذهب/العام)
الحكم = مجموع موزون ⇒ اتجاه + قناعة 0-1 + أصوات شفّافة. الأقوى ترتيباً = أفضل الفرص.

⚖️ صدق صارم: الصهر تنسيقٌ لا تنبّؤ — تجميع إشاراتٍ قِيست ~50% منفردةً لا يخلق حافّة (درس التجميع
المُثبَت). المخ الواحد = سياقٌ موحّد للعين + بوّابة تنفيذ، لا آلة ربح. قراءة فقط، بلا أوامر."""
import os, sys, json, time

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
try:
    _lf = open(os.path.join(_RN, "unified_brain.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

try:
    import engine_lock
    engine_lock.claim("unified_brain")
except SystemExit:
    raise
except Exception:
    pass

OUT_F = os.path.join(_RN, "unified_brain.json")
PULSE_F = os.path.join(_RN, "market_pulse.json")
DESK_F = os.path.join(_RN, "quant_desk.json")
DEEP_F = os.path.join(_RN, "deep_dossier.json")
COUNCIL_F = os.path.join(_RN, "ai_council.json")
EVOLVE_F = os.path.join(_RN, "self_evolver_status.json")
AGENTS_F = os.path.join(_RN, "agent_council.json")       # 🏛️ مجلس الـ90 وكيلاً (عينٌ سادسة)

# 🏛️ 2026-07-06: أُضيف «مجلس الـ90 وكيلاً» عينًا سادسة بوزن 0.20؛ أُعيد توزيع الأوزان الخمسة القديمة
# ×0.80 لتبقى القسمة = 1.00 (pulse .24 desk .20 deep .20 smc .08 council .08 agents .20).
W = {"pulse": 0.24, "desk": 0.20, "deep": 0.20, "smc": 0.08, "council": 0.08, "agents": 0.20}


def _fresh(path, max_age):
    try:
        if time.time() - os.path.getmtime(path) > max_age:
            return None
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _deep_vote(deep, sym):
    """صوت العقل العميق: ±score حسب bias، مرجّحٌ بمحاذاة HTF."""
    if not isinstance(deep, dict):
        return 0.0, None
    rec = (deep.get("high_conf_now") or {}).get(sym)
    if not isinstance(rec, dict):
        for v in deep.values():
            if isinstance(v, dict) and isinstance(v.get(sym), dict):
                rec = v.get(sym); break
    if not isinstance(rec, dict):
        return 0.0, None
    bias = str(rec.get("bias") or "")
    d = 1 if "صعود" in bias else (-1 if "هبوط" in bias else 0)
    score = float(rec.get("score") or 0)
    align = float(rec.get("align") or 1.0)
    vote = _clip(d * score * (0.5 + 0.5 * align))
    return vote, {"call": rec.get("call"), "score": round(score, 2), "align": align,
                  "with_htf": rec.get("with_htf")}


def _council_vote(council):
    """اتّفاق المجلس ⇒ ميلٌ عام (للذهب أساساً؛ يُطبَّق كوزنٍ خفيف عام)."""
    try:
        agree = float(council.get("agreement") or council.get("agree") or 0)
        # 0-100 اتّفاق: >60 قويّ لكن بلا اتجاه صريح ⇒ نستخدمه كتضخيمٍ للإجماع لا اتجاه مستقلّ
        return _clip((agree - 50) / 50.0) * 0.4
    except Exception:
        return 0.0


def _agents_vote(agents, sym):
    """صوت مجلس الـ90 وكيلاً لرمزٍ ما: dir × (agreement_pct/100) — إجماعٌ موزون قِيسَ لحظيّاً."""
    try:
        rec = (agents.get("symbols") or {}).get(sym)
        if not isinstance(rec, dict):
            return 0.0, None
        d = int(rec.get("dir", 0))
        pct = float(rec.get("agreement_pct", 0)) / 100.0
        vote = _clip(d * pct)
        return vote, {"pct": rec.get("agreement_pct"), "n": rec.get("n_voted"),
                      "gene": rec.get("gene"), "why": (rec.get("top_reasons") or [])[:2]}
    except Exception:
        return 0.0, None


def _fuse():
    pulse = _fresh(PULSE_F, 30) or {}
    desk = _fresh(DESK_F, 60) or {}
    deep = _fresh(DEEP_F, 6 * 3600)          # العقل العميق يُحدَّث بطيئاً — نقبله حتى 6س
    council = _fresh(COUNCIL_F, 1800) or {}
    agents = _fresh(AGENTS_F, 30) or {}      # 🏛️ مجلس الـ90 وكيلاً (طازج ≤30ث)
    evolve = _fresh(EVOLVE_F, 24 * 3600) or {}

    psyms = pulse.get("symbols") or {}
    dsyms = desk.get("symbols") or {}
    cvote = _council_vote(council)
    out = {}
    for sym, pd in psyms.items():
        try:
            score = (float(pd.get("score", 50)) - 50.0) / 50.0
            smc = pd.get("smc") or {}
            smc_t = float(smc.get("trend") or 0)
            bos = smc.get("bos") or []
            bos_d = float(bos[-1].get("dir", 0)) if bos else 0.0
            pulse_v = _clip(0.7 * score + 0.3 * smc_t)
            desk_v = _clip(float((dsyms.get(sym) or {}).get("composite", 0)) / 100.0)
            deep_v, deep_info = _deep_vote(deep, sym)
            smc_v = _clip(0.6 * smc_t + 0.4 * bos_d)
            agents_v, agents_info = _agents_vote(agents, sym)
            fused = (W["pulse"] * pulse_v + W["desk"] * desk_v + W["deep"] * deep_v
                     + W["smc"] * smc_v + W["council"] * cvote + W["agents"] * agents_v)
            fused = _clip(fused)
            direction = 1 if fused > 0.12 else (-1 if fused < -0.12 else 0)
            conviction = round(abs(fused), 3)
            voices = {"نبض": round(pulse_v, 2), "مكتب": round(desk_v, 2),
                      "عميق": round(deep_v, 2), "بنية": round(smc_v, 2),
                      "مجلس": round(cvote, 2), "وكلاء": round(agents_v, 2)}
            agree = sum(1 for v in (pulse_v, desk_v, deep_v, smc_v, agents_v) if v * fused > 0.05)
            verdict = ("🟢 شراء" if direction == 1 else ("🔴 بيع" if direction == -1 else "⚪ حياد"))
            if conviction >= 0.45 and agree >= 3:
                verdict += " قويّ"
            out[sym] = {"dir": direction, "conviction": conviction, "fused": round(fused, 3),
                        "agree": agree, "verdict": verdict, "voices": voices,
                        "deep": deep_info, "agents": agents_info,
                        "read": str(pd.get("read") or "")[:80]}
        except Exception:
            continue
    # أفضل الفرص: أعلى قناعةٍ باتّفاق ≥3
    ranked = sorted([(s, o) for s, o in out.items() if o["agree"] >= 3 and o["dir"] != 0],
                    key=lambda kv: -kv[1]["conviction"])[:6]
    top = [{"sym": s, "verdict": o["verdict"], "conviction": o["conviction"],
            "agree": o["agree"]} for s, o in ranked]
    # 🔁 حلقة متبادلة: المخ يقرأ حالة المنفّذ (radhi_mimic) — يعرف ما يفعله ذراعه التنفيذيّة
    mim = _fresh(os.path.join(_RN, "radhi_mimic_status.json"), 60) or {}
    executor = {"mode": mim.get("mode"), "positions": mim.get("positions"),
                "pnl_today": mim.get("pnl_today"), "frozen": bool(mim.get("frozen_until", 0)
                and mim.get("frozen_until", 0) > time.time())}
    return {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "weights": W, "symbols": out, "top": top,
            "evolver": {"candidates": evolve.get("candidates_live", 0),
                        "last_verdict": evolve.get("verdict", "—")},
            "executor": executor,
            "honesty": "الصهر تنسيقٌ لا تنبّؤ — سياقٌ موحّد وبوّابة، لا آلة ربح. قراءة فقط."}


def main():
    print(f"🧠 المخ الواحد بدأ {time.strftime('%Y-%m-%d %H:%M:%S')} — صهرٌ لحظيّ (قراءة ملفّات، بلا MT5)")
    while True:
        try:
            u = _fuse()
            t = OUT_F + ".tmp"; json.dump(u, open(t, "w", encoding="utf-8"), ensure_ascii=False)
            os.replace(t, OUT_F)
        except Exception as e:
            print(f"loop err: {type(e).__name__}: {e}")
        time.sleep(0.5)                      # ⚡⚡ صهر كل نصف ثانية — الإشارة تظهر أسرع (قراءة ملفّات خفيفة)


if __name__ == "__main__":
    main()
