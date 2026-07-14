#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
محقق اللغة (LLM Interrogator) — Muhaqqiq
يجبر النظام على تبرير كل دخول بلغة طبيعية ويُقيّم التماسك المنطقي
Architecture: from shared multi-agent XAUUSD framework §3.2
"""
import json, datetime, requests, csv
from pathlib import Path

AGENT_DIR   = Path(__file__).parent
MEMORY_FILE = AGENT_DIR / "memory.json"
REPORT_FILE = AGENT_DIR / "report.md"
LOG_FILE    = AGENT_DIR / "log.jsonl"

COMMON      = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
STATUS_JSON = COMMON / "ea_realtime_status.json"
SMC_CSV     = COMMON / "smc_decisions.csv"
AGENTS_DIR  = Path(__file__).parent.parent

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

COHERENCE_THRESHOLD = 6  # Score out of 10 — below this = reject

def load_memory():
    if MEMORY_FILE.exists():
        try:
            raw = MEMORY_FILE.read_bytes().rstrip(b"\x00")
            return json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            pass
    return {"agent": "محقق اللغة", "name": "Muhaqqiq", "role": "LLM Interrogator",
            "runs": 0, "avg_coherence": 0, "rejections_by_llm": 0,
            "approvals_by_llm": 0, "interrogations": []}

def save_memory(m): MEMORY_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

def read_context():
    st, last_decisions = {}, []
    try:
        if STATUS_JSON.exists():
            st = json.loads(STATUS_JSON.read_text(encoding="utf-8"))
    except: pass
    try:
        if SMC_CSV.exists():
            with open(SMC_CSV, encoding="utf-8") as f:
                last_decisions = list(csv.DictReader(f))[-10:]
    except: pass
    return st, last_decisions

def interrogate(st, decisions, confluence):
    """Force the LLM to articulate the trade setup and score coherence 0-10"""
    bal   = st.get("balance", "N/A")
    bias  = st.get("smc_bias", "NEUTRAL")
    ob    = st.get("smc_ob_count", 0)
    fvg   = st.get("smc_fvg_count", 0)
    bos   = st.get("smc_has_bos", False)
    ema   = st.get("ema_dir", "N/A")
    rsi   = st.get("rsi", "N/A")

    conf_approved = confluence.get("approved", False) if confluence else False
    conf_votes    = confluence.get("votes", 0)
    conf_dir      = confluence.get("direction", "NEUTRAL")

    last_dec = "\n".join([
        f"  {d.get('datetime','')[:16]} {d.get('direction','')} → {d.get('decision','')} | {d.get('reason','')}"
        for d in decisions[-5:]
    ]) if decisions else "  لا قرارات"

    prompt = f"""أنت محقق تداول ذكي. سأعطيك السياق الكامل وعليك:
1. تكتب سرداً منطقياً لماذا يجب/لا يجب الدخول الآن (3-4 جمل)
2. تعطي درجة تماسك المنطق من 0 إلى 10
3. تحدد نقطة ضعف واحدة في هذا الإعداد

السياق:
- الرصيد: {bal}$ | EMA: {ema} | RSI: {rsi}
- SMC: OB={ob} FVG={fvg} BOS={bos} Bias={bias}
- التقاطع: {'✅ موافق' if conf_approved else '❌ مرفوض'} ({conf_votes} أصوات) → {conf_dir}

آخر 5 قرارات:
{last_dec}

قدّم إجابتك بهذا الشكل بالضبط:
السرد: [3-4 جمل]
الدرجة: [رقم 0-10]
نقطة الضعف: [جملة واحدة]"""

    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.3, "num_predict": 80}, "keep_alive": "10m"}, timeout=8)
        response = r.json().get("response", "") if r.ok else ""

        if not response:
            # Ollama returned empty — abstain (pass-through, don't block)
            return "[Ollama: empty response — abstaining]", COHERENCE_THRESHOLD

        # Extract score
        score = COHERENCE_THRESHOLD  # default = pass-through when uncertain
        for line in response.split("\n"):
            if "الدرجة:" in line or "Score:" in line.lower():
                try:
                    parts = line.split(":")[-1].strip().split("/")[0].strip()
                    score = int(float(parts))
                    break
                except: pass

        return response, max(0, min(10, score))
    except Exception as e:
        # Ollama unreachable — abstain rather than block all signals
        return f"[Ollama offline — abstaining: {type(e).__name__}]", COHERENCE_THRESHOLD

def run():
    mem = load_memory()
    mem["runs"] += 1
    now = datetime.datetime.now().isoformat()

    st, decisions = read_context()

    # Read confluence signal if available
    confluence = {}
    try:
        cf = AGENTS_DIR / "confluence_signal.json"
        if cf.exists():
            confluence = json.loads(cf.read_text(encoding="utf-8"))
    except: pass

    narrative, score = interrogate(st, decisions, confluence)
    approved = score >= COHERENCE_THRESHOLD

    if approved:
        mem["approvals_by_llm"] += 1
    else:
        mem["rejections_by_llm"] += 1

    total = mem["approvals_by_llm"] + mem["rejections_by_llm"]
    all_scores = [i.get("score", 5) for i in mem["interrogations"]]
    all_scores.append(score)
    mem["avg_coherence"] = round(sum(all_scores) / len(all_scores), 1)

    mem["interrogations"].append({
        "t": now[:16], "score": score, "approved": approved,
        "narrative": narrative[:200]
    })
    mem["interrogations"] = mem["interrogations"][-50:]

    report = f"""# محقق اللغة | {now[:16]}

## 🧠 تقييم التماسك المنطقي
- الدرجة: **{score}/10** {'✅' if approved else '❌'}
- القرار: **{'مُوافق للمرور' if approved else 'مرفوض — تماسك منخفض'}**
- متوسط الدرجات التاريخي: {mem['avg_coherence']}/10
- رفضات LLM: {mem['rejections_by_llm']} | موافقات: {mem['approvals_by_llm']}

## 📝 السرد والتقييم
{narrative}
"""
    REPORT_FILE.write_text(report, encoding="utf-8")

    result = {"agent": "llm_interrogator", "time": now, "score": score,
              "approved": approved, "threshold": COHERENCE_THRESHOLD,
              "avg_coherence": mem["avg_coherence"]}

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": now, "score": score, "approved": approved}, ensure_ascii=False) + "\n")
    save_memory(mem)
    return result

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
