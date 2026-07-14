#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مطوّر (Mutawwir) - Optimizer Agent
يتابع تطور DNA ويقترح تحسينات المعاملات — يتطور بنفسه
"""
import json, csv, requests, datetime, math
from pathlib import Path
from collections import defaultdict

AGENT_DIR   = Path(__file__).parent
MEMORY_FILE = AGENT_DIR / "memory.json"
REPORT_FILE = AGENT_DIR / "report.md"
LOG_FILE    = AGENT_DIR / "log.jsonl"

COMMON      = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
STATUS_JSON = COMMON / "ea_realtime_status.json"
SMC_CSV     = COMMON / "smc_decisions.csv"

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

def load_memory():
    default = {
        "agent": "مطوّر", "name": "Mutawwir", "role": "Self-Improving Optimizer",
        "runs": 0,
        "generation_history": [],
        "parameter_suggestions": [],
        "performance_by_condition": {},
        "improvement_ideas": [],
        "self_eval_score": 50,
        "evolution_log": []
    }
    if MEMORY_FILE.exists():
        try:
            data = json.loads(MEMORY_FILE.read_bytes().rstrip(b"\x00").decode("utf-8", errors="replace"))
            if isinstance(data, dict):
                return {**default, **data}
        except Exception:
            pass
    return default

def save_memory(m):
    MEMORY_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

def read_status():
    try:
        if STATUS_JSON.exists():
            return json.loads(STATUS_JSON.read_text(encoding="utf-8"))
    except: pass
    return {}

def read_all_decisions():
    rows = []
    try:
        if SMC_CSV.exists():
            with open(SMC_CSV, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader: rows.append(row)
    except: pass
    return rows

def ask_ollama(prompt):
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.4, "num_predict": 80}, "keep_alive": "10m"}, timeout=8)
        if r.ok:
            return r.json().get("response", "").strip()
    except Exception as e:
        return f"[Ollama offline: {e}]"
    return "[No response]"

def analyze_conditions(rows):
    """Analyze which SMC conditions lead to best entries"""
    conditions = defaultdict(lambda: {"entries": 0, "blocked": 0})
    for r in rows:
        key = f"ob={r.get('ob_hit','?')}_fvg={r.get('fvg_hit','?')}_bias={r.get('bias','?')}"
        if "ENTRY" in r.get("decision",""):
            conditions[key]["entries"] += 1
        elif "BLOCK" in r.get("decision",""):
            conditions[key]["blocked"] += 1
    return dict(conditions)

def self_improve(mem, analysis_text):
    """Agent improves its own evaluation logic based on findings"""
    score = mem["self_eval_score"]
    
    # Simple self-improvement: adjust score based on patterns found
    if "positive" in analysis_text.lower() or "جيد" in analysis_text or "ممتاز" in analysis_text:
        score = min(100, score + 2)
    elif "negative" in analysis_text.lower() or "سيئ" in analysis_text or "خطر" in analysis_text:
        score = max(0, score - 2)
    
    mem["self_eval_score"] = score
    
    # Add evolution log entry
    mem["evolution_log"].append({
        "time": datetime.datetime.now().isoformat()[:16],
        "score": score,
        "note": analysis_text[:100]
    })
    mem["evolution_log"] = mem["evolution_log"][-50:]

def run():
    mem  = load_memory()
    st   = read_status()
    rows = read_all_decisions()
    mem["runs"] += 1
    now = datetime.datetime.now().isoformat()
    
    # Get current EA parameters from status
    gen    = st.get("generation", 0)
    bal    = float(st.get("balance", 0))
    eq     = float(st.get("equity", bal))
    smc_ob = st.get("smc_ob_count", 0)
    smc_fvg = st.get("smc_fvg_count", 0)
    smc_bias = st.get("smc_bias", "NEUTRAL")
    smc_bos  = st.get("smc_has_bos", False)
    
    # Track generation evolution
    if gen > 0:
        mem["generation_history"].append({"t": now[:16], "gen": gen, "bal": bal, "eq": eq})
        mem["generation_history"] = mem["generation_history"][-100:]
    
    # Analyze conditions
    cond_analysis = analyze_conditions(rows) if rows else {}
    
    # Find best condition
    best_cond = max(cond_analysis, key=lambda k: cond_analysis[k]["entries"]) if cond_analysis else "N/A"
    
    # Build performance summary
    gen_trend = ""
    if len(mem["generation_history"]) >= 2:
        first_gen = mem["generation_history"][0]
        last_gen  = mem["generation_history"][-1]
        gen_delta = last_gen["gen"] - first_gen["gen"]
        bal_delta = last_gen["bal"] - first_gen["bal"]
        gen_trend = f"Gen {first_gen['gen']}→{last_gen['gen']} (+{gen_delta}) | P&L: {bal_delta:+.2f}$"
    
    cond_str = "\n".join([
        f"  {k}: entries={v['entries']} blocked={v['blocked']}"
        for k, v in list(cond_analysis.items())[:8]
    ]) if cond_analysis else "  لا بيانات"
    
    prompt = f"""أنت وكيل تحسين ذاتي لنظام تداول ذهب بالذكاء الاصطناعي. حلل الأداء واقترح تحسينات محددة (5 نقاط عملية):

حالة النظام:
- الجيل الحالي: {gen}  |  الرصيد: {bal:.2f}$
- OB zones: {smc_ob}  |  FVG zones: {smc_fvg}
- BOS: {smc_bos}  |  Bias: {smc_bias}
- إجمالي القرارات: {len(rows)}
- تطور الأجيال: {gen_trend if gen_trend else 'لا بيانات كافية'}
- تقييم الوكيل لنفسه: {mem['self_eval_score']}/100

أداء الظروف المختلفة:
{cond_str}

اقترح:
1. تحسينات على معاملات SMC (OB lookback, FVG size, zone touch %)
2. متى يجب زيادة/تقليل الـ exposure
3. أي ظروف SMC أثبتت نجاحها أكثر
4. هل يجب تغيير bias direction الآن؟
5. توقعك للجيل القادم"""

    analysis = ask_ollama(prompt)
    
    # Self-improvement step
    self_improve(mem, analysis)
    
    # Store parameter suggestions
    mem["parameter_suggestions"].append({
        "time": now[:16],
        "gen": gen,
        "suggestion": analysis[:300],
        "score": mem["self_eval_score"]
    })
    mem["parameter_suggestions"] = mem["parameter_suggestions"][-20:]
    
    # Performance by condition
    mem["performance_by_condition"] = cond_analysis
    
    report = f"""# تقرير مطوّر | {now}

## 🧬 تطور DNA
- الجيل الحالي: **{gen}**
- تقييم الوكيل لنفسه: **{mem['self_eval_score']}/100**
- {gen_trend if gen_trend else 'جمع بيانات...'}

## 📊 أداء الظروف
```
{cond_str}
```
أفضل ظرف: `{best_cond}`

## 🤖 توصيات الذكاء الاصطناعي
{analysis}

## 📈 سجل التطور الذاتي
{chr(10).join(f"- [{e['time']}] Score:{e['score']} | {e['note']}" for e in mem['evolution_log'][-8:])}

## 💡 آخر الاقتراحات المتراكمة
{chr(10).join(f"- [{s['time']}] Gen{s['gen']}: {s['suggestion'][:150]}..." for s in mem['parameter_suggestions'][-5:])}
"""
    REPORT_FILE.write_text(report, encoding="utf-8")
    
    log_entry = {"time": now, "agent": "مطوّر", "run": mem["runs"],
                 "gen": gen, "self_score": mem["self_eval_score"],
                 "best_cond": best_cond, "total_decisions": len(rows)}
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    
    save_memory(mem)
    return {"status": "ok", "gen": gen, "self_score": mem["self_eval_score"], "analysis": analysis}

if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
