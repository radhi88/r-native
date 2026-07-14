# -*- coding: utf-8 -*-
import json, subprocess, sys, datetime, time, os, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

LOOP_INTERVAL = float(os.getenv("AGENTS_LOOP_SECONDS", "5"))
AGENT_TIMEOUT = float(os.getenv("AGENT_TIMEOUT_SECONDS", "60"))

BASE = Path(__file__).parent
MASTER_REPORT  = BASE / "master_report.md"
MESSAGES_BUS   = BASE / "agent_messages.json"

try:
    from pluto_brain import record_cycle
except Exception:
    record_cycle = None

AGENTS = [
    {"name": "Muraaqib",  "eng": "Muraaqib",  "disp": "muraaqib",  "path": BASE / "monitor"         / "brain.py", "emoji": "M"},
    {"name": "Muhallib",  "eng": "Muhallib",  "disp": "muhallib",   "path": BASE / "analyst"         / "brain.py", "emoji": "A"},
    {"name": "Haaris",    "eng": "Haaris",    "disp": "haaris",     "path": BASE / "guard"           / "brain.py", "emoji": "G"},
    {"name": "Mutawwir",  "eng": "Mutawwir",  "disp": "mutawwir",   "path": BASE / "optimizer"       / "brain.py", "emoji": "O"},
    {"name": "Mujalid",   "eng": "Mujalid",   "disp": "mujalid",    "path": BASE / "volume_profile"  / "brain.py", "emoji": "V"},
    {"name": "Muhaqqiq",  "eng": "Muhaqqiq",  "disp": "muhaqqiq",   "path": BASE / "llm_interrogator"/ "brain.py", "emoji": "L"},
    {"name": "Khabir",    "eng": "Khabir",    "disp": "khabir",     "path": BASE / "experience"      / "brain.py", "emoji": "E"},
    {"name": "Mudir",     "eng": "Mudir",     "disp": "mudir",      "path": BASE / "risk_manager"    / "brain.py", "emoji": "R"},
    {"name": "Musharrik", "eng": "Musharrik", "disp": "musharrik",  "path": BASE / "multi_tf"        / "brain.py", "emoji": "T"},
    {"name": "Mujammi",   "eng": "Mujammi",   "disp": "mujammi",    "path": BASE / "confluence"      / "brain.py", "emoji": "C"},
]

OLLAMA_MODEL = "qwen2.5:3b"

def check_ollama():
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=0.35)
        if r.ok:
            models = [m["name"] for m in r.json().get("models", [])]
            return True, any("llama3.2" in m or "qwen" in m for m in models)
        return False, False
    except Exception:
        return False, False

def warmup_ollama():
    """Pre-load model into memory so all agents find it hot (avoids 40s load penalty)."""
    try:
        r = requests.post("http://localhost:11434/api/generate", json={
            "model": OLLAMA_MODEL, "prompt": "ping", "stream": False,
            "keep_alive": "15m",
            "options": {"num_predict": 1}
        }, timeout=90)  # allow up to 90s for cold load
        if r.ok:
            print("Ollama warmup OK — model loaded and hot for 15min")
            return True
        return False
    except Exception as e:
        print("Ollama warmup failed: " + str(e))
        return False

def run_agent(agent):
    if not agent["path"].exists():
        return {"status": "missing_file"}
    try:
        result = subprocess.run(
            [sys.executable, str(agent["path"])],
            capture_output=True, text=True, timeout=AGENT_TIMEOUT
        )
        if result.stdout.strip():
            try:
                data = json.loads(result.stdout.strip())
                return {"status": "ok", "data": data}
            except Exception:
                return {"status": "ok", "data": {"raw": result.stdout[:200]}}
        return {"status": "no_output", "stderr": result.stderr[:200]}
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def read_report(agent):
    rpt = agent["path"].parent / "report.md"
    if not rpt.exists():
        return "no report"
    try:
        raw = rpt.read_bytes().rstrip(b"\x00")
        return raw.decode("utf-8", errors="replace")[:500]
    except Exception:
        return "report read error"

def run_all():
    now = datetime.datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 60)
    print("Orchestrator v3 -- " + ts)
    print("=" * 60)

    ollama_online, ollama_model = check_ollama()
    print("Ollama: " + ("ONLINE" if ollama_online else "OFFLINE") +
          " | model: " + ("ready" if ollama_model else "not ready"))

    # Warm up model BEFORE agents run so they find it hot (avoids 40s cold-load per agent)
    if ollama_online:
        warmup_ollama()

    results = {}

    def execute(agent):
        t0 = time.time()
        res = run_agent(agent)
        elapsed = round(time.time() - t0, 1)
        return agent, dict(list(res.items()) + [("elapsed_s", elapsed)])

    first_wave = [a for a in AGENTS if a["name"] != "Mujammi"]
    with ThreadPoolExecutor(max_workers=len(first_wave)) as pool:
        future_map = {pool.submit(execute, agent): agent for agent in first_wave}
        for fut in as_completed(future_map):
            agent, res = fut.result()
            results[agent["name"]] = res
            print(agent["name"] + "... " + res["status"] + " (" + str(res["elapsed_s"]) + "s)")

    confluence_agent = next((a for a in AGENTS if a["name"] == "Mujammi"), None)
    if confluence_agent is not None:
        agent, res = execute(confluence_agent)
        results[agent["name"]] = res
        print(agent["name"] + "... " + res["status"] + " (" + str(res["elapsed_s"]) + "s)")

    conf_file = BASE / "confluence_signal.json"
    confluence = {}
    try:
        if conf_file.exists():
            confluence = json.loads(conf_file.read_text(encoding="utf-8"))
    except Exception:
        pass

    conf_approved = confluence.get("approved", False)
    conf_votes    = confluence.get("votes", 0)
    conf_dir      = confluence.get("direction", "N/A")

    bus = []
    try:
        if MESSAGES_BUS.exists():
            bus = json.loads(MESSAGES_BUS.read_text(encoding="utf-8"))
    except Exception:
        pass
    bus.append({
        "time": now.isoformat(), "from": "orchestrator", "type": "cycle_complete",
        "confluence": conf_approved, "direction": conf_dir, "votes": conf_votes,
        "ollama": ollama_online, "model": ollama_model,
        "statuses": {k: v.get("status") for k, v in results.items()}
    })
    bus = bus[-200:]
    MESSAGES_BUS.write_text(json.dumps(bus, ensure_ascii=False, indent=2), encoding="utf-8")

    # Build report
    parts = ["# Master Report | " + ts, ""]
    parts.append("Ollama: " + ("ONLINE llama3.2" if ollama_model else
                               ("ONLINE no-model" if ollama_online else "OFFLINE")))
    parts.append("")
    parts.append("Confluence: " + ("APPROVED" if conf_approved else "BLOCKED") +
                 " " + str(conf_votes) + " votes | " + conf_dir)
    parts.append("")
    parts.append("| Agent | Status | Elapsed |")
    parts.append("|-------|--------|---------|")
    for a in AGENTS:
        r = results.get(a["name"], {})
        parts.append("| " + a["name"] + " | " + r.get("status", "?") +
                      " | " + str(r.get("elapsed_s", "?")) + "s |")
    parts.append("")
    parts.append("---")
    for a in AGENTS:
        parts.append("")
        parts.append("## " + a["name"])
        parts.append(read_report(a))
        parts.append("")
        parts.append("---")

    MASTER_REPORT.write_text("\n".join(parts), encoding="utf-8")

    brain_summary = {}
    if record_cycle is not None:
        try:
            brain_summary = record_cycle(AGENTS, results, confluence)
        except Exception as e:
            brain_summary = {"error": str(e)}

    status_data = {
        "last_run": now.isoformat(),
        "ollama": {"online": ollama_online, "model_ready": ollama_model},
        "confluence": {"approved": conf_approved, "votes": conf_votes, "direction": conf_dir},
        "brain": brain_summary,
        "agents": [
            {"name": a["name"], "eng": a["name"], "emoji": a["emoji"],
             "status": results.get(a["name"], {}).get("status", "?"),
             "elapsed": results.get(a["name"], {}).get("elapsed_s", 0)}
            for a in AGENTS
        ]
    }
    (BASE / "agents_status.json").write_text(
        json.dumps(status_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=" * 60)
    print(("APPROVED" if conf_approved else "BLOCKED") + " | " + str(conf_votes) + " votes | " + conf_dir)
    print("=" * 60)
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=float, default=LOOP_INTERVAL, help="Loop interval in seconds")
    args = parser.parse_args()

    if args.loop:
        print("Loop mode -- every " + str(args.interval) + "s")
        cycle = 0
        while True:
            cycle += 1
            started = time.time()
            print("\n--- Cycle #" + str(cycle) + " ---")
            run_all()
            sleep_for = max(0.05, float(args.interval) - (time.time() - started))
            print("Sleeping " + str(round(sleep_for, 3)) + "s...")
            time.sleep(sleep_for)
    else:
        run_all()
