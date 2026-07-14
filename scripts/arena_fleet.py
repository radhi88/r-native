from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "OpenJarvis" / "frontend"
LOG_DIR = ROOT / "logs"
RUNTIME_DIR = ROOT / "runtime" / "arena_fleet"

MT5_COMMON = Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "Common" / "Files"
STATUS_FILE = MT5_COMMON / "ea_realtime_status.json"
HISTORY_FILE = MT5_COMMON / "ea_bar_history.json"
DNA_FILE = MT5_COMMON / "gold_dna_memory.csv"
BEST_DNA_JSON = MT5_COMMON / "gold_best_dna_candidate.json"
BEST_DNA_SET = MT5_COMMON / "gold_best_dna_candidate.set"

EA_MONITOR = ROOT / "ea_monitor.py"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
DATA_URL = "http://localhost:7799/data"
PING_URL = "http://localhost:7799/ping"
ARENA_URL = "http://127.0.0.1:5173/arena"

MONITOR_LOG = LOG_DIR / "ea_monitor_fleet.log"
MONITOR_ERR = LOG_DIR / "ea_monitor_fleet.err.log"
VITE_LOG = LOG_DIR / "vite_5173_fleet.log"
VITE_ERR = LOG_DIR / "vite_5173_fleet.err.log"
FLEET_LOG = LOG_DIR / "arena_fleet.log"
STATUS_OUT = RUNTIME_DIR / "status.json"
RECOMMENDATIONS = RUNTIME_DIR / "recommendations.jsonl"
DEV_QUEUE = RUNTIME_DIR / "dev_queue.md"

LOOP_SECONDS = int(os.getenv("ARENA_FLEET_LOOP_SECONDS", "5"))
STALE_SECONDS = int(os.getenv("ARENA_FLEET_STALE_SECONDS", "25"))
DNA_SECONDS = int(os.getenv("ARENA_FLEET_DNA_SECONDS", "20"))


DNA_INT_FIELDS = {
    "generation",
    "ExtraTightGapPoints",
    "ModifyStepPoints",
    "CooldownTP",
    "CooldownSL",
    "CooldownLoss",
    "WinsToRecover",
    "AtrBars",
}

DNA_TO_INPUT = {
    "ExtraTightGapPoints": "InpExtraTightGapPoints",
    "ModifyStepPoints": "InpModifyStepPoints",
    "BasketTakeProfit": "InpBasketTakeProfitMoney",
    "BasketStopLoss": "InpBasketStopLossMoney",
    "BasketLockStart": "InpBasketLockStartMoney",
    "BasketLockGiveBack": "InpBasketLockGiveBackMoney",
    "CooldownTP": "InpCooldownAfterBasketTPMinutes",
    "CooldownSL": "InpCooldownAfterBasketSLMinutes",
    "CooldownLoss": "InpCooldownAfterLargeLossMinutes",
    "LotReductionFactor": "InpLotReductionFactor",
    "MinLotFactor": "InpMinLotFactor",
    "RecoveryLotStep": "InpRecoveryLotStep",
    "GridWidenFactor": "InpGridWidenFactor",
    "MaxGridFactor": "InpMaxGridFactor",
    "RecoveryGridStep": "InpRecoveryGridStep",
    "WinsToRecover": "InpWinsToRecover",
    "AtrBars": "InpDNA_AtrBars_Candidate",
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    ensure_dirs()
    line = f"[{now()}] {message}"
    try:
        print(line, flush=True)
    except OSError:
        pass
    with FLEET_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def http_text(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return True, resp.read(2_000_000).decode("utf-8", errors="replace")
    except Exception as exc:
        return False, str(exc)


def http_json(url: str, timeout: float = 3.0) -> tuple[bool, dict[str, Any]]:
    ok, text = http_text(url, timeout)
    if not ok:
        return False, {"error": text}
    try:
        return True, json.loads(text)
    except Exception as exc:
        return False, {"error": f"bad_json: {exc}", "raw": text[:500]}


def run(args: list[str], timeout: int = 10, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def pids_on_port(port: int) -> set[int]:
    try:
        proc = run(["netstat", "-ano"], timeout=10)
    except Exception:
        return set()
    pids: set[int] = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[1]
        state = parts[3] if len(parts) >= 5 else ""
        pid_text = parts[-1]
        if not local.endswith(f":{port}") or state != "LISTENING":
            continue
        try:
            pids.add(int(pid_text))
        except ValueError:
            pass
    return pids


def kill_port(port: int) -> None:
    for pid in pids_on_port(port):
        try:
            run(["taskkill", "/PID", str(pid), "/F"], timeout=10)
            log(f"killed port {port} pid={pid}")
        except Exception as exc:
            log(f"failed to kill port {port} pid={pid}: {exc}")


def start_monitor() -> None:
    if not PYTHON.exists():
        raise FileNotFoundError(f"Python not found: {PYTHON}")
    kill_port(7799)
    with MONITOR_LOG.open("ab") as out, MONITOR_ERR.open("ab") as err:
        subprocess.Popen(
            [str(PYTHON), str(EA_MONITOR)],
            cwd=str(ROOT),
            stdout=out,
            stderr=err,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    log("started ea_monitor.py on 7799")


def start_vite() -> None:
    kill_port(5173)
    with VITE_LOG.open("ab") as out, VITE_ERR.open("ab") as err:
        subprocess.Popen(
            ["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1"],
            cwd=str(FRONTEND),
            stdout=out,
            stderr=err,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    log("started Vite on 5173")


def file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except Exception:
        return 0.0


def age_seconds(path: Path) -> float | None:
    mtime = file_mtime(path)
    if not mtime:
        return None
    return max(0.0, time.time() - mtime)


def iso_age_seconds(value: Any) -> float | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return max(0.0, (datetime.now() - dt).total_seconds())
        return max(0.0, (datetime.now(dt.tzinfo) - dt).total_seconds())
    except Exception:
        return None


def num(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except Exception:
        return default


def read_dna() -> list[dict[str, Any]]:
    if not DNA_FILE.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with DNA_FILE.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                clean: dict[str, Any] = {}
                for key, value in row.items():
                    if not key:
                        continue
                    if key in DNA_INT_FIELDS:
                        clean[key] = int(num(value))
                    else:
                        clean[key] = num(value)
                if clean:
                    records.append(clean)
    except Exception as exc:
        log(f"dna read error: {exc}")
    return records


def pick_best_dna(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None

    profitable = [r for r in records if num(r.get("net_profit")) > 0 and num(r.get("total_trades")) >= 3]
    pool = profitable or records
    return max(
        pool,
        key=lambda r: (
            num(r.get("fitness"), -999999),
            num(r.get("net_profit"), -999999),
            -num(r.get("max_drawdown_pct"), 999999),
        ),
    )


def write_best_dna(best: dict[str, Any] | None) -> None:
    if not best:
        return

    payload = {
        "updated_at": now(),
        "source": str(DNA_FILE),
        "best": best,
        "note": "Candidate only. Apply manually or through the EA inputs after a completed tester run.",
    }
    write_json(BEST_DNA_JSON, payload)

    lines = [
        "; GOLD DNA candidate generated by arena_fleet.py",
        f"; updated_at={payload['updated_at']}",
        "; Verify in Strategy Tester before using in live/demo execution.",
    ]
    for dna_key, input_key in DNA_TO_INPUT.items():
        if dna_key in best:
            lines.append(f"{input_key}={best[dna_key]}")
    BEST_DNA_SET.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze_health(endpoint: dict[str, Any], status_file: dict[str, Any], history: list[Any]) -> dict[str, Any]:
    current = endpoint.get("current") if isinstance(endpoint.get("current"), dict) else {}
    indicators = current.get("indicators") if isinstance(current.get("indicators"), dict) else {}
    metrics = endpoint.get("metrics") if isinstance(endpoint.get("metrics"), dict) else {}
    dna_memory = endpoint.get("dna_memory") if isinstance(endpoint.get("dna_memory"), dict) else {}
    best = dna_memory.get("best") if isinstance(dna_memory.get("best"), dict) else None

    balance = num(current.get("balance"), num(status_file.get("balance"), 0))
    peak_balance = num(current.get("peak_balance"), num(status_file.get("peak_balance"), balance))
    drawdown_from_peak = ((peak_balance - balance) / peak_balance * 100.0) if peak_balance > 0 else 0.0
    avoid = num(indicators.get("avoid_score"), 0)
    entry = num(indicators.get("entry_score"), 0)
    sig = num(indicators.get("sig"), 0)
    adx = num(indicators.get("adx"), 0)
    spread = num(indicators.get("spread_points"), 0)

    actions: list[str] = []
    if drawdown_from_peak >= 20:
        actions.append("DD_ALERT: peak drawdown is high; protect best DNA and consider account/equity peak lock.")
    if avoid >= 55:
        actions.append("AVOID_ALERT: current entry quality is poor; avoid new entries or widen gap/cooldown.")
    if entry >= 45 and avoid < 35:
        actions.append("ENTRY_OK: indicator regime is cleaner; collect samples before changing DNA.")
    if adx < 14 and abs(sig) < 30:
        actions.append("CHOP_ALERT: low ADX and weak SIG; stop-reverse can churn here.")
    if spread > 0 and indicators.get("atr_points") and spread > num(indicators.get("atr_points")) * 0.18:
        actions.append("SPREAD_ALERT: spread is large relative to ATR.")
    if best and num(best.get("fitness")) < 0:
        actions.append("DNA_ALERT: best recorded DNA is still negative fitness; continue training before locking.")

    return {
        "balance": balance,
        "peak_balance": peak_balance,
        "drawdown_from_peak_pct": round(drawdown_from_peak, 2),
        "bar": current.get("bar", status_file.get("bar")),
        "indicator_snapshot": indicators,
        "metrics": {
            "win_rate": metrics.get("win_rate"),
            "profit_factor": metrics.get("profit_factor"),
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "net_profit": metrics.get("net_profit"),
        },
        "history_bars": len(history) if isinstance(history, list) else 0,
        "actions": actions,
    }


def append_recommendation(health: dict[str, Any]) -> None:
    actions = health.get("actions") or []
    if not actions:
        return
    rec = {
        "time": now(),
        "bar": health.get("bar"),
        "balance": health.get("balance"),
        "drawdown_from_peak_pct": health.get("drawdown_from_peak_pct"),
        "actions": actions,
    }
    with RECOMMENDATIONS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write_dev_queue() -> None:
    content = f"""# Arena 24/7 Agent Queue

Updated: {now()}

Active local agents:
- WatchdogAgent: keeps `ea_monitor.py` on port 7799 and Vite `/arena` on port 5173 alive.
- DataAgent: compares MT5 Common Files with `/data` and restarts stale services.
- DNAAgent: reads `gold_dna_memory.csv`, exports `gold_best_dna_candidate.json` and `.set`.
- IndicatorAgent: records ATR/SIG/RSI/ADX/MACD/MFI/VoI%/Spread/D-CH/Demand/Supply stats.
- DevAdvisorAgent: writes improvement recommendations to `runtime/arena_fleet/recommendations.jsonl`.

Manual code improvements to apply after a completed test run:
- Add account peak lock to the EA so a 100 -> 990 run cannot collapse without a hard equity lock.
- Persist DNA and indicator snapshot on every bar, not only current JSON.
- Add optional entry gate inputs for `AvoidMax`, `EntryMin`, `AdxMin`, and `MaxSpreadToAtr`.
- Add a UI button to promote `gold_best_dna_candidate.set` into a tester preset.
- Add post-run report that compares peak DNA, final DNA, and worst drawdown window.
"""
    DEV_QUEUE.write_text(content, encoding="utf-8")


def main() -> int:
    ensure_dirs()
    log("arena fleet starting")
    last_dna = 0.0
    last_rec_key = ""

    while True:
        status_file = read_json(STATUS_FILE, {})
        history = read_json(HISTORY_FILE, [])
        ok_data, endpoint = http_json(DATA_URL, timeout=3.0)
        ok_ping, _ = http_text(PING_URL, timeout=2.0)
        ok_arena, arena_text = http_text(ARENA_URL, timeout=4.0)

        if not ok_ping or not ok_data:
            log(f"monitor down or invalid: ping={ok_ping} data={ok_data}")
            start_monitor()
            time.sleep(3)
            continue

        endpoint_current = endpoint.get("current") if isinstance(endpoint.get("current"), dict) else {}
        status_age = age_seconds(STATUS_FILE)
        endpoint_age = iso_age_seconds(endpoint.get("last_update"))
        if status_age is not None and endpoint_age is not None:
            if status_age < 10 and endpoint_age > STALE_SECONDS:
                log(f"monitor stale: status_age={status_age:.1f}s endpoint_age={endpoint_age:.1f}s; restarting")
                start_monitor()
                time.sleep(3)
                continue

        if not ok_arena or "root" not in arena_text:
            log(f"arena down or invalid: {arena_text[:180]}")
            start_vite()
            time.sleep(3)

        if time.time() - last_dna >= DNA_SECONDS:
            records = read_dna()
            best = pick_best_dna(records)
            write_best_dna(best)
            write_dev_queue()
            last_dna = time.time()

        health = analyze_health(endpoint, status_file, history if isinstance(history, list) else [])
        rec_key = "|".join(health.get("actions", [])) + f"|{health.get('bar')}"
        if rec_key and rec_key != last_rec_key:
            append_recommendation(health)
            last_rec_key = rec_key

        status = {
            "updated_at": now(),
            "mode": "safe_24_7_supervisor",
            "services": {
                "ea_monitor": {"ok": ok_data and ok_ping, "url": DATA_URL, "pids": sorted(pids_on_port(7799))},
                "arena": {"ok": ok_arena, "url": ARENA_URL, "pids": sorted(pids_on_port(5173))},
            },
            "files": {
                "status": {"path": str(STATUS_FILE), "age_seconds": status_age, "bar": status_file.get("bar")},
                "history": {"path": str(HISTORY_FILE), "age_seconds": age_seconds(HISTORY_FILE)},
                "dna": {"path": str(DNA_FILE), "age_seconds": age_seconds(DNA_FILE)},
            },
            "health": health,
        }
        write_json(STATUS_OUT, status)
        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("arena fleet stopped by user")
        raise SystemExit(0)
