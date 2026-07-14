#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
حارس (Haaris) - Guard Agent
يراقب المخاطر ويتدخل عند الخطر — لا يُغلق صفقات ولا يعدّل EA
"""
import json, csv, requests, datetime
from pathlib import Path

AGENT_DIR   = Path(__file__).parent
MEMORY_FILE = AGENT_DIR / "memory.json"
REPORT_FILE = AGENT_DIR / "report.md"
LOG_FILE    = AGENT_DIR / "log.jsonl"

COMMON      = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
STATUS_JSON = COMMON / "ea_realtime_status.json"

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

RISK_RULES = {
    "max_drawdown_pct": 30.0,    # تنبيه عند 30% drawdown (حساب صغير)
    "danger_drawdown_pct": 55.0, # خطر حقيقي عند 55%
    "min_balance": 10.0,          # رصيد أدنى مطلق (حساب اختبار صغير)
    "max_floating_loss_pct": 25.0 # أقصى خسارة عائمة
}

def load_memory():
    default = {
        "agent": "حارس", "name": "Haaris", "role": "Risk Guard",
        "runs": 0, "risk_events": [],
        "peak_balance": 0,
        "drawdown_history": [],
        "risk_level": "GREEN",
        "risk_score": 0,
        "start_balance": 0
    }
    if MEMORY_FILE.exists():
        try:
            data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
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

def ask_ollama(prompt):
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 80}, "keep_alive": "10m"}, timeout=8)
        if r.ok:
            return r.json().get("response", "").strip()
    except Exception as e:
        return f"[Ollama offline: {e}]"
    return "[No response]"

def run():
    mem = load_memory()
    st  = read_status()
    mem["runs"] += 1
    now = datetime.datetime.now().isoformat()
    
    bal = float(st.get("balance", 0))
    eq  = float(st.get("equity", bal))
    positions = int(st.get("positions", 0))
    
    if mem["start_balance"] == 0 and bal > 0:
        mem["start_balance"] = bal
    if bal > mem["peak_balance"]:
        mem["peak_balance"] = bal
    
    # Calculate risks
    dd_pct = (mem["peak_balance"] - bal) / mem["peak_balance"] * 100 if mem["peak_balance"] > 0 else 0
    float_loss_pct = (bal - eq) / bal * 100 if bal > 0 else 0
    pnl_from_start = bal - mem["start_balance"] if mem["start_balance"] > 0 else 0

    # Rapid drop detection (more than 3% in one cycle)
    last_bal = mem.get("last_balance_check", bal)
    rapid_drop_pct = (last_bal - bal) / last_bal * 100 if last_bal > 0 and bal > 0 else 0
    mem["last_balance_check"] = bal

    # Risk scoring
    risk_score = 0
    risk_flags = []

    if rapid_drop_pct > 3.0:
        risk_score += 20
        risk_flags.append(f"🔴 انخفاض سريع: -{rapid_drop_pct:.1f}% من الدورة السابقة")
    
    if dd_pct > RISK_RULES["danger_drawdown_pct"]:
        risk_score += 50
        risk_flags.append(f"🔴 DANGER: Drawdown {dd_pct:.1f}% > {RISK_RULES['danger_drawdown_pct']}%")
    elif dd_pct > RISK_RULES["max_drawdown_pct"]:
        risk_score += 25
        risk_flags.append(f"🟡 WARNING: Drawdown {dd_pct:.1f}% > {RISK_RULES['max_drawdown_pct']}%")
    
    if bal < RISK_RULES["min_balance"] and bal > 0:
        risk_score += 30
        risk_flags.append(f"🔴 LOW BALANCE: {bal:.2f}$ < {RISK_RULES['min_balance']}$")
    
    if float_loss_pct > RISK_RULES["max_floating_loss_pct"]:
        risk_score += 20
        risk_flags.append(f"🟡 FLOAT LOSS: {float_loss_pct:.1f}%")
    
    risk_level = "GREEN" if risk_score == 0 else ("YELLOW" if risk_score < 30 else "RED")
    mem["risk_level"] = risk_level
    mem["risk_score"]  = risk_score
    
    if risk_flags:
        mem["risk_events"].append({"time": now, "flags": risk_flags, "score": risk_score})
        mem["risk_events"] = mem["risk_events"][-50:]
    
    mem["drawdown_history"].append({"t": now, "dd": round(dd_pct, 2), "bal": bal})
    mem["drawdown_history"] = mem["drawdown_history"][-100:]
    
    risk_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(risk_level, "⚪")
    
    prompt = f"""أنت وكيل حماية ذكي لحساب تداول ذهب. قيّم مستوى الخطر الحالي (3-4 جمل):

البيانات:
- الرصيد: {bal:.2f}$  |  Equity: {eq:.2f}$
- Drawdown: {dd_pct:.1f}%  |  Float Loss: {float_loss_pct:.1f}%
- P&L من البداية: {pnl_from_start:+.2f}$
- مستوى الخطر: {risk_level}  |  Risk Score: {risk_score}/100
- مناصب مفتوحة: {positions}

تنبيهات: {risk_flags if risk_flags else ['لا تنبيهات']}

هل الوضع آمن للاستمرار؟ وما توصيتك؟"""

    analysis = ask_ollama(prompt)
    
    report = f"""# تقرير حارس | {now}

## {risk_emoji} مستوى الخطر: {risk_level} (Score: {risk_score}/100)

| المؤشر | القيمة | الحد الأقصى |
|--------|--------|-------------|
| Drawdown | {dd_pct:.1f}% | {RISK_RULES['max_drawdown_pct']}% |
| Float Loss | {float_loss_pct:.1f}% | {RISK_RULES['max_floating_loss_pct']}% |
| الرصيد | {bal:.2f}$ | >{RISK_RULES['min_balance']}$ |
| P&L الكلي | {pnl_from_start:+.2f}$ | - |
| مناصب مفتوحة | {positions} | - |

## 🤖 تقييم الذكاء الاصطناعي
{analysis}

## 🚨 التنبيهات النشطة
{chr(10).join(risk_flags) if risk_flags else '✅ الوضع آمن'}

## 📊 آخر أحداث الخطر
{chr(10).join(f"- [{e['time'][:16]}] Score:{e['score']} | {'; '.join(e['flags'])}" for e in mem['risk_events'][-5:]) if mem['risk_events'] else '✅ لا أحداث'}
"""
    REPORT_FILE.write_text(report, encoding="utf-8")
    
    log_entry = {"time": now, "agent": "Haaris", "run": mem["runs"],
                 "risk_level": risk_level, "risk_score": risk_score,
                 "dd_pct": round(dd_pct, 2), "balance": bal, "flags": risk_flags}

    with open(LOG_FILE, "a", encoding="utf-8") as lf:
        lf.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    save_memory(mem)
    return {"agent": "guard", "risk_level": risk_level, "risk_score": risk_score,
            "dd_pct": round(dd_pct, 2), "balance": bal, "flags": risk_flags,
            "vote": 0 if risk_level == "RED" else 1}

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
