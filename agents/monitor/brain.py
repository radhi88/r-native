#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مراقب (Muraaqib) - Monitor Agent
يراقب حالة الـ EA ويتتبع الصحة العامة للنظام
"""
import json, csv, os, requests, datetime
from pathlib import Path

AGENT_DIR   = Path(__file__).parent
MEMORY_FILE = AGENT_DIR / "memory.json"
REPORT_FILE = AGENT_DIR / "report.md"
LOG_FILE    = AGENT_DIR / "log.jsonl"

COMMON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
STATUS_JSON = COMMON / "ea_realtime_status.json"
SMC_CSV     = COMMON / "smc_decisions.csv"

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

def load_memory():
    default = {
        "agent": "مراقب",
        "name": "Muraaqib",
        "role": "System Health Monitor",
        "scans": 0,
        "last_balance": 0,
        "max_balance": 0,
        "min_balance": 999999,
        "max_drawdown_pct": 0,
        "alerts": [],
        "balance_history": [],
        "ob_history": [],
        "fvg_history": [],
        "start_time": datetime.datetime.now().isoformat()
    }
    if MEMORY_FILE.exists():
        try:
            data = json.loads(MEMORY_FILE.read_bytes().rstrip(b"\x00").decode("utf-8", errors="replace"))
            if isinstance(data, dict):
                return {**default, **data}
        except Exception:
            pass
    return default

def save_memory(mem):
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")

def read_status():
    try:
        if STATUS_JSON.exists():
            return json.loads(STATUS_JSON.read_text(encoding="utf-8"))
    except: pass
    return {}

def read_last_decisions(n=20):
    rows = []
    try:
        if SMC_CSV.exists():
            with open(SMC_CSV, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
            return rows[-n:]
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
    st   = read_status()
    decs = read_last_decisions(20)
    
    mem["scans"] += 1
    now = datetime.datetime.now().isoformat()

    bal = float(st.get("balance", mem["last_balance"] or 0))
    eq  = float(st.get("equity",  bal))
    
    if bal > 0:
        mem["last_balance"] = bal
        mem["max_balance"]  = max(mem["max_balance"], bal)
        mem["min_balance"]  = min(mem["min_balance"], bal)
        dd_pct = (mem["max_balance"] - bal) / mem["max_balance"] * 100 if mem["max_balance"] > 0 else 0
        mem["max_drawdown_pct"] = max(mem["max_drawdown_pct"], dd_pct)
        mem["balance_history"].append({"t": now, "bal": bal, "eq": eq})
        if len(mem["balance_history"]) > 100:
            mem["balance_history"] = mem["balance_history"][-100:]

    smc_ob  = st.get("smc_ob_count", 0)
    smc_fvg = st.get("smc_fvg_count", 0)
    smc_bos = st.get("smc_has_bos", False)
    smc_bias = st.get("smc_bias", "NEUTRAL")

    # Alerts
    alerts_now = []
    if bal > 0 and eq < bal * 0.90:
        alerts_now.append(f"⚠️ DRAWDOWN ALERT: equity={eq:.2f} < 90% of balance={bal:.2f}")
    if bal < 400 and bal > 0:
        alerts_now.append(f"⚠️ LOW BALANCE: {bal:.2f}$")

    mem["alerts"] = (mem["alerts"] + alerts_now)[-20:]

    # Build context for LLM
    decisions_str = "\n".join([
        f"  [{r.get('datetime','')}] dir={r.get('direction','')} decision={r.get('decision','')} ob={r.get('ob_hit','')} fvg={r.get('fvg_hit','')} bal={r.get('balance','')}"
        for r in decs[-10:]
    ]) if decs else "  No decisions yet"

    prompt = f"""أنت وكيل مراقبة ذكي لنظام تداول ذهب. قم بتحليل الحالة الراهنة وأعطِ تقرير صحة موجز (3-5 جمل عربية):

الحالة الراهنة:
- الرصيد: {bal:.2f}$  |  Equity: {eq:.2f}$
- أقصى drawdown: {mem['max_drawdown_pct']:.1f}%
- OB zones: {smc_ob}  |  FVG zones: {smc_fvg}
- BOS: {smc_bos}  |  Bias: {smc_bias}
- إجمالي المسح: {mem['scans']}

آخر 10 قرارات:
{decisions_str}

تنبيهات: {alerts_now if alerts_now else 'لا تنبيهات'}

أعطِ تقييم صحة النظام ومدى جاهزيته للتداول."""

    analysis = ask_ollama(prompt)

    # Write report
    report = f"""# تقرير مراقب | {now}

## 📊 الحالة العامة
| المؤشر | القيمة |
|--------|--------|
| الرصيد | {bal:.2f}$ |
| Equity | {eq:.2f}$ |
| أقصى Drawdown | {mem['max_drawdown_pct']:.1f}% |
| إجمالي المسحات | {mem['scans']} |
| OB Zones | {smc_ob} |
| FVG Zones | {smc_fvg} |
| BOS | {smc_bos} |
| Bias | {smc_bias} |

## 🤖 تحليل الذكاء الاصطناعي
{analysis}

## ⚠️ التنبيهات
{chr(10).join(alerts_now) if alerts_now else '✅ لا تنبيهات'}

## 📈 آخر القرارات
{decisions_str}
"""
    REPORT_FILE.write_text(report, encoding="utf-8")
    
    # Log entry
    log_entry = {
        "time": now, "agent": "مراقب", "scan": mem["scans"],
        "balance": bal, "equity": eq, "drawdown_pct": mem.get("max_drawdown_pct", 0),
        "smc_ob": smc_ob, "smc_fvg": smc_fvg, "alerts": alerts_now,
        "ai_summary": analysis[:200]
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    
    save_memory(mem)
    return {"status": "ok", "balance": bal, "alerts": alerts_now, "analysis": analysis}

if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
