#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
محلل (Muhallib) - Analyst Agent
يحلل قرارات SMC ويتعلم الأنماط الرابحة والخاسرة
"""
import json, csv, os, requests, datetime
from pathlib import Path
from collections import defaultdict

AGENT_DIR   = Path(__file__).parent
MEMORY_FILE = AGENT_DIR / "memory.json"
REPORT_FILE = AGENT_DIR / "report.md"
LOG_FILE    = AGENT_DIR / "log.jsonl"

COMMON  = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
SMC_CSV = COMMON / "smc_decisions.csv"

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

def load_memory():
    default = {
        "agent": "محلل", "name": "Muhallib", "role": "SMC Pattern Analyst",
        "runs": 0, "total_decisions": 0,
        "patterns": {
            "ob_hit_rate": 0, "fvg_hit_rate": 0,
            "buy_count": 0, "sell_count": 0,
            "blocked_count": 0, "entry_count": 0,
            "best_hour": 0, "worst_hour": 0,
            "hourly_entries": {}
        },
        "insights": [],
        "last_row_count": 0
    }
    if MEMORY_FILE.exists():
        try:
            data = json.loads(MEMORY_FILE.read_bytes().rstrip(b"\x00").decode("utf-8", errors="replace"))
            if isinstance(data, dict):
                merged = {**default, **data}
                merged["patterns"] = {**default["patterns"], **merged.get("patterns", {})}
                return merged
        except Exception:
            pass
    return default

def save_memory(m):
    MEMORY_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

def read_all_decisions():
    rows = []
    try:
        if SMC_CSV.exists():
            with open(SMC_CSV, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
    except: pass
    return rows

def ask_ollama(prompt):
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 80}, "keep_alive": "10m"}, timeout=8)
        if r.ok:
            return r.json().get("response", "").strip()
    except Exception as e:
        return f"[Ollama offline: {e}]"
    return "[No response]"

def run():
    mem  = load_memory()
    rows = read_all_decisions()
    mem["runs"] += 1
    now = datetime.datetime.now().isoformat()
    
    if not rows:
        mem["insights"].append(f"{now}: No decisions yet — EA hasn't reached SMC filter")
        save_memory(mem)
        REPORT_FILE.write_text(f"# محلل | {now}\n\n⏳ لا قرارات بعد — SMC فلتر لم يُفعَّل بعد\n", encoding="utf-8")
        return {"status": "no_data"}

    mem["total_decisions"] = len(rows)
    
    # Count patterns
    ob_hits = sum(1 for r in rows if r.get("ob_hit","0") == "1")
    fvg_hits = sum(1 for r in rows if r.get("fvg_hit","0") == "1")
    buys     = sum(1 for r in rows if r.get("direction","") == "BUY")
    sells    = sum(1 for r in rows if r.get("direction","") == "SELL")
    entries  = sum(1 for r in rows if "ENTRY" in r.get("decision",""))
    blocked  = sum(1 for r in rows if "BLOCK" in r.get("decision",""))
    
    # Hourly distribution
    hourly = defaultdict(int)
    for r in rows:
        try:
            h = r.get("datetime","")[:13].split(" ")[-1].split(":")[0]
            if "ENTRY" in r.get("decision",""):
                hourly[h] += 1
        except: pass

    best_hour = max(hourly, key=hourly.get) if hourly else "N/A"
    
    # New data since last run
    new_rows = rows[mem["last_row_count"]:]
    mem["last_row_count"] = len(rows)
    
    p = mem["patterns"]
    p["ob_hit_rate"]   = round(ob_hits / len(rows) * 100, 1)
    p["fvg_hit_rate"]  = round(fvg_hits / len(rows) * 100, 1)
    p["buy_count"]     = buys
    p["sell_count"]    = sells
    p["entry_count"]   = entries
    p["blocked_count"] = blocked
    p["best_hour"]     = best_hour
    p["hourly_entries"] = dict(hourly)
    
    # Sample data for LLM
    sample = "\n".join([
        f"  {r.get('datetime','')[:16]} | {r.get('direction','')} | {r.get('decision','')} | OB:{r.get('ob_hit','')} FVG:{r.get('fvg_hit','')} | bias:{r.get('bias','')} | {r.get('reason','')}"
        for r in rows[-15:]
    ])
    
    prompt = f"""أنت وكيل تحليل ذكي لنظام SMC تداول ذهب. حلل الأنماط التالية واستخلص insights مفيدة (4-6 نقاط عربية):

إحصاءات شاملة ({len(rows)} قرار):
- OB hit rate: {p['ob_hit_rate']}%
- FVG hit rate: {p['fvg_hit_rate']}%
- BUY signals: {buys}  |  SELL signals: {sells}
- Entries: {entries}  |  Blocked: {blocked}
- أفضل ساعة للدخول: {best_hour}:00
- توزيع الساعات: {dict(list(hourly.items())[:5])}

آخر 15 قرار:
{sample}

ما هي أبرز الأنماط التي تلاحظها؟ وما توصياتك لتحسين الأداء؟"""

    analysis = ask_ollama(prompt)
    
    if new_rows:
        mem["insights"].append(f"{now[:16]}: +{len(new_rows)} قرارات جديدة | entries={entries} blocked={blocked}")
    mem["insights"] = mem["insights"][-30:]

    report = f"""# تقرير محلل | {now}

## 📊 إحصاءات SMC ({len(rows)} قرار إجمالي)
| المؤشر | القيمة |
|--------|--------|
| OB Hit Rate | {p['ob_hit_rate']}% |
| FVG Hit Rate | {p['fvg_hit_rate']}% |
| BUY signals | {buys} |
| SELL signals | {sells} |
| Entries (فعلية) | {entries} |
| Blocked (محجوبة) | {blocked} |
| نسبة الدخول | {round(entries/len(rows)*100,1) if rows else 0}% |
| أفضل ساعة | {best_hour}:00 |

## 🤖 تحليل الذكاء الاصطناعي
{analysis}

## 💡 الـ Insights المتراكمة
{chr(10).join(f'- {i}' for i in mem['insights'][-10:])}

## 📅 توزيع الدخول بالساعات
{chr(10).join(f'- {h}:00 → {c} دخول' for h,c in sorted(hourly.items()))}
"""
    REPORT_FILE.write_text(report, encoding="utf-8")
    
    log_entry = {"time": now, "agent": "محلل", "run": mem["runs"],
                 "total_rows": len(rows), "entries": entries, "blocked": blocked,
                 "ob_hit_rate": p["ob_hit_rate"], "fvg_hit_rate": p["fvg_hit_rate"]}
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    
    save_memory(mem)
    return {"status": "ok", "total": len(rows), "entries": entries, "analysis": analysis}

if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
