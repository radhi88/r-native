#!/usr/bin/env python3
"""مدير المخاطر (Risk Manager) — Mudir | Kelly sizing + drawdown gating"""
import json, datetime, requests
from pathlib import Path

AGENT_DIR   = Path(__file__).parent
MEMORY_FILE = AGENT_DIR / "memory.json"
REPORT_FILE = AGENT_DIR / "report.md"
LOG_FILE    = AGENT_DIR / "log.jsonl"
COMMON      = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
STATUS_JSON = COMMON / "ea_realtime_status.json"
SMC_CSV     = COMMON / "smc_decisions.csv"
OLLAMA_URL  = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

def load_memory():
    default = {"agent":"مدير المخاطر","name":"Mudir","role":"Risk Manager","runs":0,
               "peak_balance":0,"max_dd":0,"kelly_fraction":0.25,"win_count":0,"loss_count":0}
    if MEMORY_FILE.exists():
        try:
            raw = MEMORY_FILE.read_bytes().rstrip(b"\x00")
            data = json.loads(raw.decode("utf-8", errors="replace"))
            if isinstance(data, dict):
                return {**default, **data}
        except Exception:
            pass
    return default

def save_memory(m): MEMORY_FILE.write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding="utf-8")

def kelly(win_rate, avg_win, avg_loss):
    if avg_loss == 0: return 0.25
    rr = avg_win / avg_loss
    k  = win_rate - (1 - win_rate) / rr
    return max(0.05, min(0.5, k))

def ask_ollama(prompt):
    try:
        r = requests.post(OLLAMA_URL,json={"model":OLLAMA_MODEL,"prompt":prompt,"stream":False,
            "options":{"temperature":0.2,"num_predict": 80}, "keep_alive": "10m"},timeout=8)
        return r.json().get("response","").strip() if r.ok else "[Ollama offline]"
    except: return "[Ollama offline]"

def run():
    mem = load_memory()
    mem["runs"] += 1
    now = datetime.datetime.now().isoformat()
    st  = {}
    try:
        if STATUS_JSON.exists():
            st = json.loads(STATUS_JSON.read_text(encoding="utf-8"))
    except: pass

    bal = float(st.get("balance",0))
    eq  = float(st.get("equity", bal))
    if bal > mem["peak_balance"]: mem["peak_balance"] = bal
    dd  = (mem["peak_balance"] - bal) / mem["peak_balance"] * 100 if mem["peak_balance"] > 0 else 0
    mem["max_dd"] = max(mem["max_dd"], dd)

    # Kelly from decisions history
    import csv
    entries_win, entries_loss = [], []
    try:
        if SMC_CSV.exists():
            rows = list(csv.DictReader(open(SMC_CSV,encoding="utf-8")))
            balances = [float(r.get("balance",0)) for r in rows if r.get("balance","")]
            for i in range(1,len(balances)):
                diff = balances[i] - balances[i-1]
                if diff > 0: entries_win.append(diff)
                elif diff < 0: entries_loss.append(abs(diff))
    except: pass

    win_rate = len(entries_win)/(len(entries_win)+len(entries_loss)) if (entries_win or entries_loss) else 0.5
    avg_win  = sum(entries_win)/len(entries_win)   if entries_win  else 1.0
    avg_loss = sum(entries_loss)/len(entries_loss) if entries_loss else 1.0
    mem["kelly_fraction"] = kelly(win_rate, avg_win, avg_loss)

    # Small account: gate on 40% drawdown + 10$ minimum; if no balance data yet, allow through
    risk_ok = (dd < 40 and bal > 10) or (bal == 0)
    risk_level = "GREEN" if dd < 20 else ("YELLOW" if dd < 40 else "RED")
    mem["risk_level"] = risk_level  # persist so confluence can read it
    mem["max_dd"] = min(mem["max_dd"], 50)  # cap max_dd to avoid stale 100% blocking

    prompt = f"""مدير مخاطر تداول الذهب. قيّم (2 جمل):
رصيد: {bal:.2f}$ | Drawdown: {dd:.1f}% | Kelly: {mem['kelly_fraction']:.2f}
Win Rate: {win_rate:.1%} | Avg Win: {avg_win:.2f} | Avg Loss: {avg_loss:.2f}
هل يجب الاستمرار في التداول؟"""
    analysis = ask_ollama(prompt)

    report = f"""# مدير المخاطر | {now[:16]}

## ⚖️ Kelly Fraction: {mem['kelly_fraction']:.2f}
| المؤشر | القيمة |
|--------|--------|
| Drawdown | {dd:.1f}% |
| Win Rate | {win_rate:.1%} |
| Risk Level | {risk_level} |

## 🤖 {analysis}
"""
    REPORT_FILE.write_text(report, encoding="utf-8")
    with open(LOG_FILE,"a",encoding="utf-8") as f:
        f.write(json.dumps({"time":now,"dd":round(dd,2),"kelly":mem["kelly_fraction"],"risk_ok":risk_ok},ensure_ascii=False)+"\n")
    save_memory(mem)
    return {"agent":"risk_manager","time":now,"risk_level":risk_level,"kelly":mem["kelly_fraction"],"dd":round(dd,2),"vote":1 if risk_ok else 0}

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
