#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
محرك الخبرة (Experience Engine) — Khabir
يطابق الإعداد الحالي مع أنماط من السجل التاريخي
ويرفع تحذيراً عند تكرار الأنماط الخاسرة
"""
import json, datetime, csv, requests
from pathlib import Path
from collections import defaultdict

AGENT_DIR   = Path(__file__).parent
MEMORY_FILE = AGENT_DIR / "memory.json"
REPORT_FILE = AGENT_DIR / "report.md"
LOG_FILE    = AGENT_DIR / "log.jsonl"
JOURNAL_FILE = Path(r"C:\Users\Radhi\MT5\agents\experience_journal.json")

COMMON      = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
STATUS_JSON = COMMON / "ea_realtime_status.json"
SMC_CSV     = COMMON / "smc_decisions.csv"

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

def load_memory():
    if MEMORY_FILE.exists():
        try:
            raw = MEMORY_FILE.read_bytes().rstrip(b"\x00")
            return json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            pass
    return {"agent": "محرك الخبرة", "name": "Khabir", "role": "Experience Engine",
            "runs": 0, "patterns_learned": 0, "bad_patterns_flagged": 0,
            "pattern_db": {}}

def save_memory(m): MEMORY_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

def fingerprint(row):
    """Create a hashable fingerprint of a decision row"""
    try:
        rsi_bucket = "HIGH" if float(row.get("rsi", 50)) > 65 else ("LOW" if float(row.get("rsi", 50)) < 35 else "MID")
        return f"dir={row.get('direction','?')}_ob={row.get('ob_hit','?')}_fvg={row.get('fvg_hit','?')}_bias={row.get('bias','?')}_rsi={rsi_bucket}"
    except: return "unknown"

def read_decisions():
    rows = []
    try:
        if SMC_CSV.exists():
            with open(SMC_CSV, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
    except: pass
    return rows

def ask_ollama(prompt):
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.3, "num_predict": 80}, "keep_alive": "10m"}, timeout=8)
        return r.json().get("response", "").strip() if r.ok else "[Ollama offline]"
    except: return "[Ollama offline]"

def run():
    mem  = load_memory()
    mem["runs"] += 1
    now  = datetime.datetime.now().isoformat()
    rows = read_decisions()

    if not rows:
        REPORT_FILE.write_text(f"# محرك الخبرة | {now[:16]}\n\n⏳ لا قرارات بعد\n", encoding="utf-8")
        save_memory(mem)
        return {"status": "no_data"}

    # Build/update pattern database
    pattern_db = mem["pattern_db"]
    entries = [r for r in rows if "ENTRY" in r.get("decision", "")]

    # Since we don't have actual P&L per trade (EA doesn't log it per row),
    # use balance trend as proxy: improving balance = recent entries worked
    for i in range(len(rows) - 1):
        fp = fingerprint(rows[i])
        if fp not in pattern_db:
            pattern_db[fp] = {"count": 0, "entry_count": 0, "last_seen": ""}
        pattern_db[fp]["count"] += 1
        if "ENTRY" in rows[i].get("decision", ""):
            pattern_db[fp]["entry_count"] += 1
        pattern_db[fp]["last_seen"] = rows[i].get("datetime", "")[:16]

    mem["pattern_db"]       = pattern_db
    mem["patterns_learned"] = len(pattern_db)

    # Current setup fingerprint
    try:
        st = json.loads(STATUS_JSON.read_text(encoding="utf-8")) if STATUS_JSON.exists() else {}
        rsi_b = "HIGH" if float(st.get("rsi", 50)) > 65 else ("LOW" if float(st.get("rsi", 50)) < 35 else "MID")
        current_fp = f"dir={st.get('smc_bias','?')}_ob={1 if int(st.get('smc_ob_count',0))>0 else 0}_fvg={1 if int(st.get('smc_fvg_count',0))>0 else 0}_bias={st.get('smc_bias','?')}_rsi={rsi_b}"
    except:
        current_fp = "unknown"

    # Check current pattern against history
    current_pattern = pattern_db.get(current_fp, {})
    pattern_seen = current_pattern.get("count", 0)
    pattern_entries = current_pattern.get("entry_count", 0)
    entry_rate = round(pattern_entries / pattern_seen * 100, 1) if pattern_seen > 0 else 0

    # Flag bad setups: pattern seen 3+ times with very low entry rate (<10%)
    bad_pattern = pattern_seen >= 3 and entry_rate < 10
    if bad_pattern:
        mem["bad_patterns_flagged"] += 1

    # Top patterns by entry rate
    top_patterns = sorted(
        [(fp, v) for fp, v in pattern_db.items() if v["count"] >= 2],
        key=lambda x: x[1]["entry_count"] / x[1]["count"],
        reverse=True
    )[:5]

    prompt = f"""أنت محرك الخبرة لتداول الذهب. لديك {len(pattern_db)} نمط مُسجَّل من التاريخ.

النمط الحالي: `{current_fp}`
- ظهر من قبل: {pattern_seen} مرة
- أدى لدخول: {pattern_entries} مرة ({entry_rate}%)
- تحذير: {'⚠️ نمط سيئ متكرر' if bad_pattern else '✅ لا تحذير'}

أفضل 3 أنماط تاريخياً:
{chr(10).join(f"  {fp}: دخول {v['entry_count']}/{v['count']}" for fp,v in top_patterns[:3])}

في 2-3 جمل: هل الإعداد الحالي يشبه الأنماط الناجحة؟"""

    analysis = ask_ollama(prompt)

    report = f"""# محرك الخبرة | {now[:16]}

## 📚 قاعدة المعرفة
- أنماط مُتعلَّمة: **{mem['patterns_learned']}**
- أنماط سيئة مُحذَّرة: **{mem['bad_patterns_flagged']}**

## 🔍 النمط الحالي
- البصمة: `{current_fp}`
- ظهر: {pattern_seen}x | أدى لدخول: {entry_rate}%
- التحذير: {'⚠️ نمط ضعيف' if bad_pattern else '✅ مقبول'}

## 🤖 التحليل
{analysis}

## 🏆 أفضل الأنماط التاريخية
{chr(10).join(f"- `{fp}`: {v['entry_count']}/{v['count']} دخولات" for fp,v in top_patterns[:5])}
"""
    REPORT_FILE.write_text(report, encoding="utf-8")

    result = {"agent": "experience", "time": now, "pattern": current_fp,
              "seen": pattern_seen, "entry_rate": entry_rate,
              "bad_pattern_flag": bad_pattern, "vote": 0 if bad_pattern else 1}

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": now, "pattern": current_fp, "bad": bad_pattern}, ensure_ascii=False) + "\n")
    save_memory(mem)
    return result

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
