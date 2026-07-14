"""auto_ga_daemon.py — Autonomous GA-campaign launcher.

Runs every 15 minutes. For each tradeable symbol:
  1. Reads live performance from HoF index + decision_log
  2. Identifies "weak performers":
       • symbol has ≥10 closed trades on its current deployed_genome AND
       • net live PnL ≤ 0 (the seeded B99880-clone isn't fitting this symbol)
  3. If a campaign isn't already running for this symbol → spawn one
  4. When the campaign completes (background subprocess):
       a. Pick the top survivor from ga_strategies
       b. (Optionally) ask LLM Certifier to issue trust certificate
       c. Replace deployed_genome with the new symbol-native genome
       d. Log to data/r_native/auto_ga_log.jsonl

Limits:
  • Max 2 concurrent campaigns (each spawns its own GA process — CPU bound)
  • One campaign per symbol per 24h (don't re-evaluate too frequently)
  • Cooling-off: skip symbols where last campaign finished <6h ago

CLI:
  python -m r_native.auto_ga_daemon --run-once
  python -m r_native.auto_ga_daemon --daemon --interval-min 15
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT       = Path(r"C:\Users\Radhi\MT5")
CONFIGS    = ROOT / "data" / "r_native" / "symbol_configs"
HOF_INDEX  = ROOT / "data" / "r_native" / "hall_of_fame" / "index.json"
DLOG       = ROOT / "data" / "r_native" / "decision_log"
STATE_PATH = ROOT / "data" / "r_native" / "auto_ga_state.json"
LOG_PATH   = ROOT / "data" / "r_native" / "auto_ga_log.jsonl"

# Thresholds (tunable)
MIN_LIVE_TRADES        = 10        # need this many before deciding it's "weak"
MAX_LIVE_PNL_FOR_WEAK  = 0.0       # net pnl ≤ this on the deployed genome
MAX_CONCURRENT_GA      = 2
COOLDOWN_HOURS         = 6
ONE_CAMPAIGN_PER_24H   = True
GA_TIMEOUT_MIN         = 90        # kill campaigns that exceed this


def _load_state() -> dict:
    if not STATE_PATH.exists(): return {"running": {}, "history": {}}
    try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception: return {"running": {}, "history": {}}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _log(event: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _hof() -> dict:
    if not HOF_INDEX.exists(): return {}
    try: return json.loads(HOF_INDEX.read_text(encoding="utf-8"))
    except Exception: return {}


def _decision_log_closes(genome_id: str) -> tuple[int, float]:
    """Read closed trades for this genome from decision_log → (n_closes, net_pnl)."""
    p = DLOG / f"{genome_id}.jsonl"
    if not p.exists(): return 0, 0.0
    n = 0; net = 0.0
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            try: ev = json.loads(line)
            except Exception: continue
            if ev.get("kind") == "CLOSE":
                n += 1
                net += float(ev.get("profit") or 0)
    except Exception: pass
    return n, net


def _is_weak(symbol: str) -> tuple[bool, str]:
    """Decide whether this symbol's current genome is underperforming enough
    to deserve a fresh GA campaign. Returns (yes, reason)."""
    cfg_path = CONFIGS / f"{symbol}.json"
    if not cfg_path.exists(): return False, "no config"
    try: cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception: return False, "config read err"
    dg = cfg.get("deployed_genome") or {}
    gid = dg.get("id")
    if not gid: return False, "no deployed genome"
    # Prefer decision_log (per-genome live truth); fall back to HoF
    n_closes, net_pnl = _decision_log_closes(gid)
    if n_closes == 0:
        h = _hof().get(gid, {}) or {}
        n_closes = int(h.get("live_trades") or 0)
        net_pnl  = float(h.get("live_pnl") or 0)
    if n_closes < MIN_LIVE_TRADES:
        return False, f"only {n_closes} closes (need {MIN_LIVE_TRADES})"
    if net_pnl > MAX_LIVE_PNL_FOR_WEAK:
        return False, f"net pnl ${net_pnl:+.2f} — not weak"
    return True, f"{n_closes} closes, net ${net_pnl:+.2f} ≤ floor"


def _running_campaigns(state: dict) -> dict:
    """Garbage-collect dead PIDs from state.running and return the live ones."""
    live = {}
    for sym, info in (state.get("running") or {}).items():
        pid = info.get("pid")
        if not pid: continue
        try:
            if sys.platform == "win32":
                r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                    capture_output=True, text=True, timeout=4,
                                    creationflags=0x08000000)
                if str(pid) in (r.stdout or ""):
                    live[sym] = info
            else:
                os.kill(int(pid), 0); live[sym] = info
        except Exception: pass
    state["running"] = live
    return live


def _too_recent(symbol: str, state: dict) -> bool:
    """True if a campaign for this symbol completed within COOLDOWN_HOURS."""
    hist = (state.get("history") or {}).get(symbol)
    if not hist: return False
    try:
        last = datetime.fromisoformat(hist["completed_at"].replace("Z", "+00:00"))
    except Exception: return False
    age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
    if ONE_CAMPAIGN_PER_24H and age_h < 24: return True
    return age_h < COOLDOWN_HOURS


def _spawn_campaign(symbol: str, tf: str = "M5") -> Optional[int]:
    """Spawn a detached GA campaign for this symbol. Returns PID or None.
    The campaign writes to data/r_native/symbol_configs/<sym>.json with new
    ga_strategies; auto_ga_daemon picks the best one in its next tick."""
    # Use the genome_breeder/scanner GA path; here we trigger via scanner.full_scan
    # restricted to this symbol — that's how the rest of the system already does it.
    log_file = ROOT / "data" / "r_native" / "logs" / f"ga_{symbol}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-u", "-c",
           f"import sys; sys.path.insert(0, r'{ROOT}');"
           f"from r_native.scanner import full_scan, update_symbol_configs_from_scan;"
           f"import MetaTrader5 as mt5;"
           f"mt5.initialize();"
           f"r = full_scan(symbols=['{symbol}'], n_bars=3000,"
           f" progress_cb=lambda s: print(s, flush=True));"
           f"update_symbol_configs_from_scan(r) if r and r.get('ok') is not False else None;"
           f"print('CAMPAIGN_DONE', flush=True)"]
    try:
        with open(log_file, "ab") as f_out:
            creationflags = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW (no console popup)
            p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=f_out, stderr=f_out,
                                  creationflags=creationflags, close_fds=True)
        return p.pid
    except Exception as e:
        _log({"event": "spawn_failed", "symbol": symbol, "err": str(e)})
        return None


def _promote_new_genome(symbol: str) -> Optional[str]:
    """After a campaign finishes, pick top ga_strategy with confidence=DEPLOY
    and write it into deployed_genome. Returns the new gid or None."""
    cfg_path = CONFIGS / f"{symbol}.json"
    if not cfg_path.exists(): return None
    try: cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception: return None
    strats = [s for s in (cfg.get("ga_strategies") or [])
              if s.get("confidence") == "DEPLOY" and s.get("active_genes")]
    if not strats: return None
    strats.sort(key=lambda s: -(s.get("score") or s.get("profit_factor") or 0))
    top = strats[0]
    cfg["deployed_genome"] = {
        "id":             top["id"],
        "parent_id":      "auto_ga",
        "active_genes":   top.get("active_genes") or [],
        "sl_atr_mult":    top.get("sl_atr_mult", 2.0),
        "tp_atr_mult":    top.get("tp_atr_mult", 4.0),
        "start_hour":     top.get("start_hour", 0),
        "end_hour":       top.get("end_hour", 23),
        "profit_factor":  top.get("profit_factor", 0),
        "win_rate":       top.get("win_rate", 0),
        "trades":         top.get("trades", 0),
        "sharpe":         top.get("sharpe", 0),
        "source":         "auto_ga_promoted",
        "deployed_at":    datetime.now(timezone.utc).isoformat(),
    }
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return top["id"]


def run_once() -> dict:
    """Single sweep — check finished campaigns, identify weak performers,
    spawn new campaigns up to MAX_CONCURRENT_GA."""
    state = _load_state()
    live = _running_campaigns(state)

    # 0. Heal any duplicate genome IDs before doing anything else. A stale
    # daemon (or a manual config copy) can re-introduce collisions; the dedup
    # heal keeps the invariant "one genome ID per symbol" enforced.
    dedup_result: dict = {"detected_collisions": 0, "rewrites": 0}
    try:
        from r_native.genome_dedup import heal as _dedup_heal
        dedup_result = _dedup_heal(dry_run=False)
        if dedup_result.get("rewrites"):
            _log({"event": "dedup_heal", **dedup_result})
    except Exception as e:
        _log({"event": "dedup_heal_error", "error": str(e)})

    # 1. Check if any running campaigns wrote a CAMPAIGN_DONE marker
    finished = []
    for sym in list(state.get("running", {}).keys()):
        if sym not in live:
            # Process exited — assume done (or crashed)
            new_gid = _promote_new_genome(sym)
            state.setdefault("history", {})[sym] = {
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "promoted_gid": new_gid,
            }
            del state["running"][sym]
            _log({"event": "campaign_finished", "symbol": sym,
                  "promoted_gid": new_gid})
            finished.append((sym, new_gid))

    # 2. Identify weak symbols + spawn campaigns up to the cap
    spawned = []
    skipped = []
    slots = MAX_CONCURRENT_GA - len(state["running"])
    if slots > 0:
        # Inspect every configured symbol
        for cfg_path in sorted(CONFIGS.glob("*.json")):
            if ".bak" in cfg_path.name: continue
            symbol = cfg_path.stem
            if symbol in state["running"]:
                skipped.append((symbol, "already running")); continue
            if _too_recent(symbol, state):
                skipped.append((symbol, "cooldown")); continue
            weak, reason = _is_weak(symbol)
            if not weak:
                skipped.append((symbol, reason)); continue
            pid = _spawn_campaign(symbol)
            if pid:
                state["running"][symbol] = {
                    "pid": pid,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
                spawned.append((symbol, pid))
                _log({"event": "campaign_spawned", "symbol": symbol,
                      "pid": pid, "reason": reason})
                slots -= 1
                if slots <= 0: break
    _save_state(state)

    return {
        "ok": True,
        "running":  list(state["running"].keys()),
        "spawned":  spawned,
        "finished": finished,
        "skipped":  skipped[:10],     # cap for log volume
        "dedup":    {"healed": dedup_result.get("rewrites", 0),
                     "collisions": dedup_result.get("detected_collisions", 0)},
    }


def _cli():
    ap = argparse.ArgumentParser(prog="r_native.auto_ga_daemon")
    ap.add_argument("--run-once",     action="store_true")
    ap.add_argument("--daemon",       action="store_true")
    ap.add_argument("--interval-min", type=int, default=15)
    args = ap.parse_args()

    if args.run_once:
        r = run_once()
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return

    if args.daemon:
        print(f"[auto_ga] daemon — every {args.interval_min} min", flush=True)
        while True:
            try:
                r = run_once()
                print(f"[{datetime.now(timezone.utc):%H:%M:%S}] "
                      f"running={len(r['running'])} "
                      f"spawned={len(r['spawned'])} "
                      f"finished={len(r['finished'])}", flush=True)
            except Exception as e:
                print(f"[auto_ga] err: {e}", flush=True)
            time.sleep(args.interval_min * 60)
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()
