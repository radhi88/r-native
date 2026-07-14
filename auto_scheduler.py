"""auto_scheduler.py — J.4 — Weekly auto-evolution loop.

Every Sunday night UTC: run a fresh GA campaign on each tradeable symbol.
If the new top genome scores higher than the current deployed by N points,
auto-deploy it. Notify via Telegram.

Settings: data/r_native/auto_scheduler.json
{
  "enabled":            false,
  "schedule_day":       "sunday",   // sunday/monday/...
  "schedule_hour_utc":  22,
  "symbols":            ["BTCUSDm", "XAUUSDm", "EURUSDm"],
  "tf":                 "M5",
  "pg":                 400,
  "gens":               3,
  "auto_deploy_threshold":  5.0,    // new_top.score - current.score > this
  "max_auto_deploys_per_week": 3,
  "notify_telegram":    true
}
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\auto_scheduler.json")
SYMBOL_CFG  = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")

DEFAULTS = {
    "enabled":                  False,
    "schedule_day":             "sunday",
    "schedule_hour_utc":        22,
    "symbols":                  ["BTCUSDm", "XAUUSDm", "EURUSDm"],
    "tf":                       "M5",
    "pg":                       400,
    "gens":                     3,
    "auto_deploy_threshold":    5.0,
    "max_auto_deploys_per_week": 3,
    "notify_telegram":          True,
    "last_run":                 None,
    "deploys_this_week":        0,
    "week_started":             None,
}

DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6}

_stop = threading.Event()
_thread: threading.Thread | None = None


def load() -> dict:
    if not CONFIG_PATH.exists(): return DEFAULTS.copy()
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = DEFAULTS.copy(); cfg.update(loaded); return cfg
    except Exception:
        return DEFAULTS.copy()


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _next_run_at(cfg: dict) -> datetime:
    """Calculate when the next scheduled run should fire."""
    now = datetime.now(timezone.utc)
    target_dow = DAYS.get(cfg.get("schedule_day", "sunday").lower(), 6)
    target_h   = int(cfg.get("schedule_hour_utc", 22))
    # Find next target day at target hour
    days_ahead = (target_dow - now.weekday()) % 7
    candidate = now.replace(hour=target_h, minute=0, second=0, microsecond=0) \
                   + timedelta(days=days_ahead)
    if candidate <= now: candidate += timedelta(days=7)
    return candidate


def _run_one_campaign(symbol: str, tf: str, pg: int, gens: int) -> dict | None:
    """Run a GA campaign + check if new top justifies auto-deploy."""
    try:
        from r_native.genetic_engine import GeneticEngine, CampaignConfig
        import multiprocessing as mp
        cfg = CampaignConfig(
            symbol=symbol, timeframe=tf, bars=2000,
            pg_candidates=pg,
            tribe_a_gens=gens, tribe_b_gens=gens, war_gens=gens,
            revival_gens=max(1, gens // 2),
            retrain_gens=max(1, gens // 2),
            n_workers=max(2, mp.cpu_count() - 1),
        )
        engine = GeneticEngine(cfg)
        summary = engine.run_full_campaign()
        return summary
    except Exception as e:
        print(f"[auto_scheduler] campaign for {symbol} failed: {e}")
        return None


def _maybe_auto_deploy(symbol: str, summary: dict, threshold: float) -> dict | None:
    """If new top score beats current deployed by `threshold`, deploy it."""
    if not summary: return None
    top = summary.get("top_genome", {})
    if not top: return None
    new_score = summary.get("top_score", 0)
    new_id    = top.get("genome", {}).get("id")
    if not new_id: return None

    # Check current deployed
    cfg_path = SYMBOL_CFG / f"{symbol}.json"
    if not cfg_path.exists(): return None
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cur = cfg.get("deployed_genome") or {}
    cur_score = cur.get("score", 0) or 0
    if new_score - cur_score < threshold:
        return {"deployed": False, "reason": f"new={new_score:.1f} not > current+{threshold}",
                "current": cur.get("id")}

    # Deploy
    try:
        from r_native.actions import deploy_genome_to_live
        result = deploy_genome_to_live(symbol, new_id, summary.get("timeframe", "M5"))
        return {"deployed": True, "id": new_id, "new_score": new_score,
                "old_score": cur_score, "old_id": cur.get("id"),
                "result": result}
    except Exception as e:
        return {"deployed": False, "reason": str(e)}


def _scheduler_loop():
    print(f"[auto_scheduler] started")
    while not _stop.is_set():
        cfg = load()
        if not cfg.get("enabled"):
            _stop.wait(300); continue   # check every 5 min when disabled

        next_run = _next_run_at(cfg)
        wait_sec = (next_run - datetime.now(timezone.utc)).total_seconds()
        if wait_sec > 0:
            print(f"[auto_scheduler] next run: {next_run:%Y-%m-%d %H:%M UTC} "
                  f"(in {wait_sec/3600:.1f}h)")
            # Sleep in chunks so we can be stopped
            for _ in range(int(wait_sec / 30)):
                if _stop.is_set(): return
                time.sleep(30)

        # Reset weekly counter if a new week started
        now = datetime.now(timezone.utc)
        week_start = now - timedelta(days=now.weekday())
        if cfg.get("week_started") != week_start.date().isoformat():
            cfg["week_started"]     = week_start.date().isoformat()
            cfg["deploys_this_week"] = 0
            save(cfg)

        # Run campaigns
        print(f"[auto_scheduler] firing weekly campaigns on {cfg['symbols']}")
        max_deploys = int(cfg.get("max_auto_deploys_per_week", 3))
        threshold   = float(cfg.get("auto_deploy_threshold", 5.0))
        deploys_done = []
        for sym in cfg.get("symbols", []):
            if cfg.get("deploys_this_week", 0) >= max_deploys:
                print(f"[auto_scheduler] hit weekly cap, stopping")
                break
            summary = _run_one_campaign(sym, cfg.get("tf", "M5"),
                                        int(cfg.get("pg", 400)),
                                        int(cfg.get("gens", 3)))
            result = _maybe_auto_deploy(sym, summary, threshold)
            if result and result.get("deployed"):
                cfg["deploys_this_week"] = cfg.get("deploys_this_week", 0) + 1
                deploys_done.append(f"{sym}: {result['old_id']} → {result['id']} "
                                    f"(+{result['new_score']-result['old_score']:.1f})")

        cfg["last_run"] = now.isoformat()
        save(cfg)

        # Telegram notification
        if cfg.get("notify_telegram") and deploys_done:
            try:
                from r_native.telegram_bot import send
                send(f"🤖 <b>Weekly auto-evolution complete</b>\n" +
                     "\n".join(f"   📦 {d}" for d in deploys_done),
                     event="daily_summary")
            except Exception: pass


def start_scheduler():
    global _thread
    if _thread and _thread.is_alive(): return
    _stop.clear()
    _thread = threading.Thread(target=_scheduler_loop, daemon=True,
                               name="auto-scheduler")
    _thread.start()


def stop_scheduler():
    _stop.set()


def status() -> dict:
    cfg = load()
    return {
        "enabled":  cfg.get("enabled"),
        "running":  bool(_thread and _thread.is_alive()),
        "next_run": _next_run_at(cfg).isoformat() if cfg.get("enabled") else None,
        "last_run": cfg.get("last_run"),
        "deploys_this_week": cfg.get("deploys_this_week", 0),
    }


if __name__ == "__main__":
    print(json.dumps(status(), indent=2))
