# -*- coding: utf-8 -*-
"""ollama_council.py — 🏛️ مجلس العقول المحليّ: كل موديل Ollama له دورٌ ويتشاركون ($0، بلا اشتراك، بلا حدود).

خطّ الأنابيب كل جولة (تسلسليّ — GPU واحدة):
 👁️ العيون (llava): يرى لقطة بثّ اليوتيوب الحيّة ويصفها ⇒ تدقيقٌ متقاطع مع قراءة OCR.
 🧠 المحلّل (qwen2.5:7b-instruct): قراءة سوقٍ عربيّة من أرقامنا الحيّة.
 🗡️ الناقد (llama3.1:8b): يهاجم قراءة المحلّل ويكشف ثغراتها.
 ⚖️ الحكم (qwen2.5:7b): يدمج القراءة والنقد ⇒ حكم المجلس + درجة اتفاق 0-100.
 🔧 المهندس (qwen2.5-coder:7b): يلخّص أعطال سجلّات المحرّكات.
 ⚡ العدّاء (qwen2.5:3b): يُثري آخر تنبيهات النظام بسطرٍ عربيّ.
 🏷️ المصنّف (qwen2.5:1.5b): يُصنّف أثر الأخبار القادمة على الذهب.
⚖️ الصدق: تأطيرٌ ووصفٌ وتدقيق — لا حافّة تنبؤيّة مقاسة. لا يُوصَل بأيّ مسار أوامر."""
import os, sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
_LOG = os.path.join(_RN, "ollama_council.out.log")
os.makedirs(_RN, exist_ok=True)
try:
    _lf = open(_LOG, "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

import json, time, base64, re, glob
import urllib.request

try:
    import engine_lock
    engine_lock.claim("ollama_council")
except SystemExit:
    raise
except Exception:
    pass

OLLAMA = "http://127.0.0.1:11434/api/generate"
CFG_F = os.path.join(_RN, "ollama_council_config.json")
OUT_F = os.path.join(_RN, "ai_council.json")
FEED_F = os.path.join(_RN, "ai_council_feed.jsonl")
FLAG_F = os.path.join(_RN, "ai_council_request.flag")
FRAME = os.path.join(_RN, "_yt_frame.png")
HONESTY = "⚖️ مجلسٌ محليّ للتأطير والوصف والتدقيق فقط — لا حافّة تنبؤيّة مقاسة، لا يوصَل بمسارات الأوامر."

ROLES_MODELS = {"eyes": "llava:latest", "analyst": "qwen2.5:7b-instruct-q4_K_M",
                "critic": "llama3.2:3b", "judge": "qwen2.5:7b",
                "ops": "qwen2.5-coder:3b", "runner": "qwen2.5:3b", "tagger": "qwen2.5:1.5b"}
FALLBACK_MODEL = "qwen2.5:3b"        # عند فشل موديل دور (500/ذاكرة GPU) نعيد المحاولة ثم ننزل للاحتياط


def _cfg():
    d = {"enabled": True, "interval_min": 15, "num_predict": 350, "models": dict(ROLES_MODELS)}
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        try:
            t = CFG_F + ".tmp"; json.dump(d, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(t, CFG_F)
        except Exception:
            pass
    return d


def _gen(model, prompt, images=None, npredict=350, timeout=240):
    """نداء توليد واحد (تسلسليّ). keep_alive قصير كي تتبادل الموديلات ذاكرة الـGPU."""
    body = {"model": model, "prompt": prompt, "stream": False,
            "keep_alive": "2m", "options": {"num_predict": int(npredict), "temperature": 0.4}}
    if images:
        body["images"] = images
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    return (r.get("response") or "").strip(), round(time.time() - t0, 1)


def _jload(name):
    try:
        return json.load(open(os.path.join(_RN, name), encoding="utf-8"))
    except Exception:
        return {}


def _context():
    """حزمة سياقٍ مضغوطة من ملفّاتنا الحيّة (~3k حرف)."""
    qd = _jload("quant_desk.json"); mp = _jload("market_pulse.json")
    g = (mp.get("symbols") or {}).get("XAUUSDm") or {}
    smc = g.get("smc") or {}
    parts = []
    gold = qd.get("gold") or {}
    parts.append(f"الذهب: السعر {g.get('price')} · نبض {g.get('score')}/100 · قراءة: {g.get('read','')}")
    parts.append(f"مكتب الحسابات: مركّب {gold.get('composite')} · {gold.get('verdict','')}")
    parts.append(f"النظام: {json.dumps(qd.get('regime',{}), ensure_ascii=False)}")
    parts.append(f"SMC: ترند {smc.get('trend')} · ملخّص: {smc.get('summary','')} · POC {smc.get('poc')}")
    # 🌍 خريطة كل العملات (لا الذهب فقط): أقوى 8 انحرافاً + قراءاتها
    others = [(s, d) for s, d in (mp.get("symbols") or {}).items() if s != "XAUUSDm" and isinstance(d, dict)]
    others.sort(key=lambda sd: -abs(float(sd[1].get("score", 50) or 50) - 50))
    if others:
        parts.append("خريطة العملات: " + " · ".join(
            f"{s}={d.get('score')}({str(d.get('read') or '')[:28]})" for s, d in others[:8]))
    yt = _jload("youtube_live_status.json")
    if yt.get("plan"):
        parts.append(f"خطّة قناة اليوتيوب: {json.dumps(yt['plan'], ensure_ascii=False)}")
    ev = _jload("news_events.json")
    evs = ev if isinstance(ev, list) else ev.get("events", [])
    if evs:
        nxt = [f"{e.get('title')}({e.get('impact')}) بعد {e.get('minutes_to','?')}د" for e in evs[:3]]
        parts.append("أخبار قادمة: " + " · ".join(nxt))
    return "\n".join(str(p) for p in parts)[:3500]


def _errors_pack():
    """يجمع آخر أسطر الأخطاء من أحدث سجلّات المحرّكات (بايثون يُرشّح — الموديل يُلخّص)."""
    out = []
    logs = sorted(glob.glob(os.path.join(_RN, "*.out.log")), key=os.path.getmtime, reverse=True)[:8]
    for lf in logs:
        try:
            lines = open(lf, encoding="utf-8", errors="ignore").readlines()[-40:]
            bad = [l.strip() for l in lines if re.search(r"Error|Traceback|err:|فشل|تعذّر", l)][-4:]
            if bad:
                out.append(os.path.basename(lf) + ": " + " | ".join(bad))
        except Exception:
            continue
    return "\n".join(out)[:2500] or "لا أخطاء مرصودة في السجلّات."


def _feeds_pack(n=3):
    rows = []
    for f in ("market_pulse_feed.jsonl", "quant_desk_feed.jsonl"):
        try:
            for ln in open(os.path.join(_RN, f), encoding="utf-8").readlines()[-n:]:
                rows.append(ln.strip()[:220])
        except Exception:
            continue
    return "\n".join(rows[-2 * n:]) or "لا تنبيهات جديدة."


PROPOSALS_F = os.path.join(_RN, "council_proposals.jsonl")
ALLOWED_KINDS = {"restart_engine", "cancel_orders", "set_config", "request_analysis", "spawn_agent"}


def _fleet_facts():
    """حقائق حراسة المشروع كاملاً (ملفّات فقط — بلا MT5): أعمار الحالة، الأخطاء، الأوامر، العمليّات."""
    facts = []
    now = time.time()
    retired = set((_jload("retired_engines.json").get("engines")) or [])   # 📋 المتقاعدون عمداً — ليسوا أعطالاً
    stats = sorted(glob.glob(os.path.join(_RN, "*_status.json")), key=os.path.getmtime, reverse=True)
    stale = [(os.path.basename(f), int((now - os.path.getmtime(f)) / 60)) for f in stats
             if not any(r in os.path.basename(f) for r in retired)]
    facts.append("أعمار ملفّات الحالة (دقائق): " + " · ".join(f"{n}={a}" for n, a in stale[:14]))
    old = [f"{n}({a}د)" for n, a in stale if a > 30]
    if old:
        facts.append("⚠️ حالات متجمّدة >30د: " + " · ".join(old[:6]))
    if retired:
        facts.append("📋 متقاعدون عمداً (لا تقترح إحياءهم أبداً): " + " · ".join(sorted(retired)))
    oj = _jload("order_janitor_status.json")
    facts.append(f"الأوامر المعلّقة: {oj.get('pending_total','?')} · أُلغي آخر دورة: {oj.get('cancelled_this_cycle','?')}")
    qd = _jload("quant_desk.json")
    acc = (qd.get("pnl") or {}).get("account") or {}
    facts.append(f"الحساب: رصيد {acc.get('balance')} · حقوق {acc.get('equity')} · هامش حر {acc.get('margin_free')}")
    try:
        import psutil
        n = len([p for p in psutil.process_iter(['name']) if 'python' in (p.info.get('name') or '').lower()])
        facts.append(f"عمليّات python: {n} (الحدّ الآمن <40) · إجمالي العمليّات: {len(list(psutil.process_iter()))} (<450)")
    except Exception:
        pass
    facts.append("أخطاء السجلّات: " + _errors_pack()[:900])
    return "\n".join(facts)[:3000]


def _guard_step(cfg, R, NP):
    """🛡️ الحارس: يقترح إجراءاتٍ (لا ينفّذ!) — الاقتراحات تذهب لموافقة Claude ثم منفّذٍ ضيّق."""
    facts = _fleet_facts()
    prompt = ("أنت حارس نظام تداول. من الحقائق أدناه اقترح 0-3 إجراءات JSON فقط بلا شرح، مصفوفة:\n"
              '[{"kind":"restart_engine|cancel_orders|set_config|request_analysis|spawn_agent|none",'
              '"target":"اسم المحرّك أو المجيك أو المفتاح","reason":"سبب من 10 كلمات",'
              '"details":{}}]\n'
              "لا تقترح شيئاً إن كان كل شيء سليماً (أعد []). الحقائق:\n" + facts)
    try:
        txt, secs = _gen(cfg.get("models", ROLES_MODELS).get("judge", "qwen2.5:7b"), prompt, npredict=260)
        R["guard"] = {"model": "qwen2.5:7b", "seconds": secs, "text": txt[:1200]}
        m = re.search(r"\[.*\]", txt, re.S)
        props = json.loads(m.group(0)) if m else []
        seen = set()
        try:
            for ln in open(PROPOSALS_F, encoding="utf-8").readlines()[-60:]:
                p = json.loads(ln)
                if time.time() - p.get("ts", 0) < 6 * 3600:
                    seen.add((p.get("kind"), str(p.get("target"))))
        except Exception:
            pass
        added = 0
        retired = set((_jload("retired_engines.json").get("engines")) or [])
        for p in props[:3]:
            kind = str(p.get("kind", "none"))
            if kind not in ALLOWED_KINDS:
                continue
            if any(r in str(p.get("target", "")) for r in retired):   # 🚫 لا إحياء للمتقاعدين — فلتر صلب
                continue
            key = (kind, str(p.get("target")))
            if key in seen:
                continue
            row = {"id": f"cp{int(time.time())}{added}", "ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                   "kind": kind, "target": p.get("target"), "reason": str(p.get("reason", ""))[:200],
                   "details": p.get("details") or {}, "status": "pending", "by": "council_guard"}
            with open(PROPOSALS_F, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            added += 1
        R["guard"]["proposals"] = added
        print(f"[guard] اقتراحات جديدة: {added}")
    except Exception as e:
        R["guard"] = {"model": "qwen2.5:7b", "seconds": 0, "error": f"{type(e).__name__}: {e}"}


def run_round(cfg, roles=None):
    """جولة مجلسٍ كاملة (تسلسليّة). roles=subset للاختبار."""
    M = cfg.get("models", ROLES_MODELS); NP = cfg.get("num_predict", 350)
    want = roles or ["eyes", "analyst", "critic", "judge", "ops", "runner", "tagger"]
    ctx = _context()
    R = {}; t_round = time.time()

    def step(key, model, prompt, images=None, npredict=NP):
        for attempt, m_ in ((1, model), (2, model), (3, FALLBACK_MODEL)):
            try:
                txt, secs = _gen(m_, prompt, images=images, npredict=npredict)
                R[key] = {"model": m_, "seconds": secs, "text": txt[:2400]}
                break
            except Exception as e:
                R[key] = {"model": m_, "seconds": 0, "error": f"{type(e).__name__}: {e}"}
                if images and attempt >= 2:
                    break                                     # الرؤية لا بديل لها
                time.sleep(5)
        print(f"[{key}] {R[key]['model']} → {R[key].get('seconds','-')}ث" + (" (خطأ)" if 'error' in R[key] else ""))

    if "eyes" in want:
        try:
            img = base64.b64encode(open(FRAME, "rb").read()).decode()
            step("eyes", M["eyes"],
                 "You see a screenshot of a live gold-trading YouTube stream. Tersely list: chart direction, "
                 "the signal panel colors (green=bull/red=bear), and any Entry/SL/TP numbers you can read.",
                 images=[img], npredict=220)
            yt = _jload("youtube_live_status.json"); plan = yt.get("plan") or {}
            txt = (R.get("eyes") or {}).get("text", "").lower()
            if plan:
                d = plan.get("direction", "")
                agree = ("bull" in txt or "up" in txt or "green" in txt) if d == "buy" else \
                        (("bear" in txt or "down" in txt or "red" in txt) if d == "sell" else None)
                R["eyes"]["cross_check"] = "متطابق مع قراءة OCR ✓" if agree else ("مختلف عن OCR ⚠️" if agree is False else "—")
        except Exception as e:
            R["eyes"] = {"model": M["eyes"], "seconds": 0, "error": str(e)}
    if "analyst" in want:
        step("analyst", M["analyst"],
             "أنت محلّل أسواقٍ محترف (كل العملات لا الذهب فقط). من الأرقام التالية فقط اكتب قراءةً "
             "عربيّةً موجزة (≤220 كلمة): الذهب أوّلاً ثم أبرز فرصتين من خريطة العملات — بلا اختلاق أرقام:\n" + ctx)
    if "critic" in want:
        step("critic", M["critic"],
             "أنت ناقدٌ صارم. هذه قراءة محلّلٍ وسياقها. اذكر حتى 3 ثغرات/تناقضات باختصارٍ عربيّ:\n"
             "== القراءة ==\n" + (R.get("analyst", {}).get("text", "") or "") + "\n== السياق ==\n" + ctx, npredict=220)
    if "judge" in want:
        step("judge", M["judge"],
             "أنت حَكَم مجلس تحليل. ادمج القراءة والنقد في حكمٍ نهائيّ عربيّ (≤120 كلمة) ثم اختم بسطرٍ أخير "
             "فيه رقمٌ فعليّ من 0 إلى 100 هكذا مثلاً: «اتفاق المجلس: 65/100»\n== القراءة ==\n" + (R.get("analyst", {}).get("text", "") or "")
             + "\n== النقد ==\n" + (R.get("critic", {}).get("text", "") or ""), npredict=260)
    if "ops" in want:
        step("ops", M["ops"],
             "You are a systems engineer. Summarize the top operational issues from these engine log excerpts "
             "in 3 short Arabic bullet lines (or say لا أعطال):\n" + _errors_pack(), npredict=180)
    if "runner" in want:
        step("runner", M["runner"],
             "لخّص كل سطرٍ من هذه التنبيهات بجملةٍ عربيّةٍ واحدة:\n" + _feeds_pack(), npredict=160)
    if "tagger" in want:
        ev = _jload("news_events.json"); evs = ev if isinstance(ev, list) else ev.get("events", [])
        nxt = json.dumps(evs[:3], ensure_ascii=False)[:800] if evs else "لا أحداث"
        step("tagger", M["tagger"],
             "صنّف أثر كل خبرٍ قادمٍ على الذهب (مرتفع/متوسّط/منخفض + سبب من 5 كلمات):\n" + nxt, npredict=140)

    if "guard" in want or roles is None:
        _guard_step(cfg, R, NP)

    verdict = (R.get("judge", {}) or {}).get("text", "") or "(لا حكم)"
    m = re.search(r"اتفاق\s*المجلس\s*[:：]?\s*(\d{1,3})", verdict)
    agreement = min(100, int(m.group(1))) if m else None
    out = {"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
           "round_seconds": round(time.time() - t_round, 1), "roles": R,
           "verdict": verdict, "agreement": agreement, "honesty": HONESTY}
    try:
        t = OUT_F + ".tmp"; json.dump(out, open(t, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(t, OUT_F)
    except Exception:
        pass
    print(f"🏛️ جولة اكتملت في {out['round_seconds']}ث · اتفاق={agreement}")
    return out


def main():
    print(f"🏛️ مجلس العقول بدأ {time.strftime('%Y-%m-%d %H:%M:%S')}")
    last = 0.0
    while True:
        try:
            cfg = _cfg()
            manual = os.path.exists(FLAG_F)
            if manual:
                try: os.remove(FLAG_F)
                except Exception: pass
            if cfg.get("enabled", True) and (manual or time.time() - last >= cfg.get("interval_min", 15) * 60):
                run_round(cfg)
                last = time.time()
        except Exception as e:
            print(f"loop err: {type(e).__name__}: {e}")
        time.sleep(10)


if __name__ == "__main__":
    main()
