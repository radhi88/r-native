"""continuous_evolution.py — Always-on self-evolving genome loop.

Runs in the background while R Native is open. Every `interval_hours`:
  1. Run a fast GA campaign on each tradeable symbol
  2. Compare new top genome vs currently deployed
  3. If new score > deployed + threshold → AUTO-DEPLOY the new genome
  4. Notify (UI banner + Telegram if enabled)
  5. Continue forever — your genome keeps improving while you sleep

This is what makes R Native truly "self-evolving" — the deployed genome
gets replaced automatically as the system discovers better DNA.

Settings: data/r_native/continuous_evo.json
{
  "enabled":           true,
  "interval_hours":    6,           # cycle period
  "symbols":           ["BTCUSDm", "XAUUSDm"],
  "tf":                "M5",
  "pg":                300,         # smaller PG for faster cycles
  "gens":              2,
  "auto_deploy_threshold": 3.0,     # new must beat current by this
  "max_deploys_per_day":   6,
  "min_trades_for_deploy": 5,       # don't replace based on tiny sample
  "notify_telegram":   true,
  "notify_ui":         true,
  "last_run":          null,
  "total_cycles":      0,
  "total_deploys":     0,
  "history":           []           # last 20 cycles
}
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\continuous_evo.json")
SYMBOL_CFG  = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
LOG_PATH    = Path(r"C:\Users\Radhi\MT5\data\r_native\continuous_evo.log")

DEFAULTS = {
    "enabled":                  False,
    "interval_hours":           6,
    "symbols":                  ["BTCUSDm", "XAUUSDm"],
    "tf":                       "M5",
    "pg":                       300,
    "gens":                     2,
    "auto_deploy_threshold":    3.0,
    "max_deploys_per_day":      6,
    "min_trades_for_deploy":    5,
    "notify_telegram":          True,
    "notify_ui":                True,
    "last_run":                 None,
    "next_run":                 None,
    "total_cycles":             0,
    "total_deploys":            0,
    "deploys_today":            0,
    "today":                    None,
    "history":                  [],
    "is_running_cycle":         False,
    "current_phase":            "idle",
}

_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────
def load() -> dict:
    if not CONFIG_PATH.exists():
        return DEFAULTS.copy()
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = DEFAULTS.copy()
        cfg.update(loaded)
        return cfg
    except Exception:
        return DEFAULTS.copy()


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    print(line.rstrip())


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _reset_daily_counter_if_needed(cfg: dict):
    today = _today_str()
    if cfg.get("today") != today:
        cfg["today"] = today
        cfg["deploys_today"] = 0


# ─────────────────────────────────────────────────────────────────────
def _run_campaign(symbol: str, tf: str, pg: int, gens: int) -> dict | None:
    """Run a fast GA campaign and return the summary."""
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
        return engine.run_full_campaign()
    except Exception as e:
        _log(f"campaign for {symbol} FAILED: {e}")
        return None


def _admit_to_hall_of_fame(symbol: str, tf: str, top: dict, new_score: float,
                           new_trades: int):
    """Save every campaign top genome to Hall of Fame, deployed or not.
    This way nothing is ever 'dropped' — every genome that scored well
    becomes a permanent breeding/seeding asset."""
    try:
        from r_native.hall_of_fame import admit
        entry = admit(
            genome={"id": top.get("id")},
            symbol=symbol, tf=tf, score=new_score,
            stats=top.get("stats") or {},
            all_params=top.get("genome") or top.get("all_params") or top,
            active_genes=top.get("active_genes") or top.get("genes") or [],
            archetype=top.get("archetype"),
            birth_method="ga_random",
        )
        _log(f"   🏆 admitted {entry['nickname']} to Hall of Fame")
    except Exception as e:
        _log(f"   ⚠ HoF admit failed: {e}")


def _maybe_auto_deploy(symbol: str, summary: dict, threshold: float,
                       min_trades: int) -> dict:
    """Compare new top vs deployed, auto-deploy if it wins by `threshold`.
    ALSO: every top genome is admitted to the Hall of Fame regardless of
    whether it gets deployed — so it can seed future cycles."""
    if not summary:
        return {"deployed": False, "reason": "no campaign summary"}

    top = summary.get("top_genome") or {}
    if not top:
        return {"deployed": False, "reason": "no top genome in summary"}

    new_score = float(summary.get("top_score") or 0)
    new_id    = top.get("id") or top.get("genome", {}).get("id")
    # trades count lives under top_genome.stats.trades (genetic_engine schema)
    new_trades = int(
        (top.get("stats") or {}).get("trades")
        or top.get("trades")
        or (top.get("genome") or {}).get("trades")
        or 0
    )

    if not new_id:
        return {"deployed": False, "reason": "top genome has no id"}

    # Hall of Fame admission happens BEFORE deploy gate — every viable
    # candidate is preserved forever
    if new_trades >= min_trades:
        _admit_to_hall_of_fame(symbol, summary.get("timeframe", "M5"),
                               top, new_score, new_trades)

    if new_trades < min_trades:
        return {"deployed": False,
                "reason": f"sample too small ({new_trades} < {min_trades})"}

    cfg_path = SYMBOL_CFG / f"{symbol}.json"
    cur_score = 0
    cur_id = None
    if cfg_path.exists():
        try:
            sc = json.loads(cfg_path.read_text(encoding="utf-8"))
            cur = sc.get("deployed_genome") or {}
            cur_score = float(cur.get("score") or 0)
            cur_id    = cur.get("id")
        except Exception:
            pass

    # ── Lane-aware threshold (Phase 5) ──────────────────────────
    # SMC genomes shouldn't have to beat the all-time classic king to get a
    # live test slot — only their own lane. If this genome is SMC and the
    # current deploy is classic (or vice-versa), compare against the best
    # in the candidate's OWN lane instead of the currently deployed.
    try:
        from r_native.hall_of_fame import get_elites_by_lane, _classify_lane
        new_lane = _classify_lane(top.get("active_genes") or top.get("genes") or [])
        cur_lane = "classic"
        if cur_id:
            from r_native.hall_of_fame import load_index
            cur_entry = load_index().get(cur_id) or {}
            cur_lane = cur_entry.get("lane") or _classify_lane(
                cur_entry.get("active_genes") or [])
        if new_lane != cur_lane:
            same_lane_elite = get_elites_by_lane(symbol, new_lane, n=1)
            lane_threshold_score = (same_lane_elite[0]["score"]
                                    if same_lane_elite else 0.0)
            delta_lane = new_score - lane_threshold_score
            if delta_lane >= threshold:
                _log(f"   🛣 lane-aware deploy: {new_lane} beats own-lane "
                     f"best {lane_threshold_score:.1f} by {delta_lane:.1f}")
                cur_score = lane_threshold_score
                cur_id    = (same_lane_elite[0]["id"] if same_lane_elite else None)
    except Exception as _e:
        _log(f"   ⚠ lane-aware compare failed (using global): {_e}")

    delta = new_score - cur_score
    if delta < threshold:
        return {"deployed": False,
                "reason": f"new {new_id}({new_score:.1f}) not > "
                          f"current {cur_id}({cur_score:.1f}) + {threshold}",
                "delta": delta}

    # Deploy it — pass the full genome dict so we don't need to scrape ga_strategies
    try:
        from r_native.actions import deploy_genome_to_live
        # Tag the genome with its real score so future cycles can compare
        top_with_score = dict(top)
        top_with_score["score"] = new_score
        result = deploy_genome_to_live(symbol, new_id,
                                       summary.get("timeframe", "M5"),
                                       genome_dict=top_with_score)
        if not result.get("ok"):
            return {"deployed": False,
                    "reason": f"deploy fn returned: {result.get('error')}",
                    "result": result}
        # Record deployment in Hall of Fame
        try:
            from r_native.hall_of_fame import record_deployment
            record_deployment(new_id, symbol)
        except Exception: pass
        return {"deployed": True, "id": new_id, "new_score": new_score,
                "old_score": cur_score, "old_id": cur_id, "delta": delta,
                "trades": new_trades, "result": result}
    except Exception as e:
        return {"deployed": False, "reason": f"deploy_to_live raised: {e}"}


# ─────────────────────────────────────────────────────────────────────
def run_one_cycle(reason: str = "scheduled") -> dict:
    """Run a single evolution cycle — exposed for manual triggering."""
    cfg = load()
    _reset_daily_counter_if_needed(cfg)
    cfg["is_running_cycle"] = True
    cfg["current_phase"] = "starting"
    save(cfg)

    cycle_summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "results": [],
    }
    deploys_done = []
    threshold  = float(cfg.get("auto_deploy_threshold", 3.0))
    min_trades = int(cfg.get("min_trades_for_deploy", 5))
    max_today  = int(cfg.get("max_deploys_per_day", 6))

    for sym in cfg.get("symbols") or []:
        if cfg.get("deploys_today", 0) >= max_today:
            _log(f"⛔ daily deploy cap reached ({max_today}) — skipping rest")
            cycle_summary["results"].append({
                "symbol": sym, "skipped": "daily cap reached"
            })
            continue

        cfg["current_phase"] = f"GA campaign on {sym}"
        save(cfg)
        _log(f"🧬 starting GA for {sym} (PG={cfg.get('pg')} gens={cfg.get('gens')})")
        summary = _run_campaign(sym, cfg.get("tf", "M5"),
                                int(cfg.get("pg", 300)),
                                int(cfg.get("gens", 2)))

        cfg["current_phase"] = f"evaluating {sym}"
        save(cfg)
        result = _maybe_auto_deploy(sym, summary or {}, threshold, min_trades)
        result["symbol"] = sym
        cycle_summary["results"].append(result)

        if result.get("deployed"):
            cfg["deploys_today"] = cfg.get("deploys_today", 0) + 1
            cfg["total_deploys"] = cfg.get("total_deploys", 0) + 1
            deploys_done.append(result)
            _log(f"✅ AUTO-DEPLOYED {sym}: {result['old_id']} → {result['id']} "
                 f"(+{result['delta']:.1f} pts)")
        else:
            _log(f"🟡 {sym}: {result.get('reason')}")

    cfg["last_run"] = datetime.now(timezone.utc).isoformat()
    cfg["next_run"] = (datetime.now(timezone.utc) +
                       timedelta(hours=cfg.get("interval_hours", 6))
                      ).isoformat()
    cfg["total_cycles"] = cfg.get("total_cycles", 0) + 1
    cfg["is_running_cycle"] = False
    cfg["current_phase"] = "idle"

    # Keep last 20 cycles in history
    hist = cfg.get("history", [])
    hist.append({
        "ts": cycle_summary["started_at"],
        "reason": reason,
        "deploys": len(deploys_done),
        "results": [{k: v for k, v in r.items() if k != "result"}
                    for r in cycle_summary["results"]],
    })
    cfg["history"] = hist[-20:]
    save(cfg)

    cycle_summary["deploys_done"] = len(deploys_done)
    cycle_summary["finished_at"] = datetime.now(timezone.utc).isoformat()

    # Notify
    if deploys_done:
        msg = "🤖 <b>Auto-Evolution: new genomes deployed</b>\n" + "\n".join(
            f"   📦 {d['symbol']}: {d['old_id']} → <b>{d['id']}</b> "
            f"(+{d['delta']:.1f} pts, {d['trades']} trades)"
            for d in deploys_done)
        if cfg.get("notify_telegram"):
            try:
                from r_native.telegram_bot import send
                send(msg, event="auto_deploy")
            except Exception:
                pass
        _log(msg.replace("<b>", "").replace("</b>", ""))

    return cycle_summary


# ─────────────────────────────────────────────────────────────────────
def _loop():
    _log("🚀 continuous_evolution loop started")
    while not _stop.is_set():
        cfg = load()
        if not cfg.get("enabled"):
            _stop.wait(60)
            continue

        # Determine when to fire next
        next_at_iso = cfg.get("next_run")
        try:
            next_at = (datetime.fromisoformat(next_at_iso)
                       if next_at_iso else datetime.now(timezone.utc))
        except Exception:
            next_at = datetime.now(timezone.utc)

        now = datetime.now(timezone.utc)
        wait_sec = (next_at - now).total_seconds()

        if wait_sec > 0:
            # Sleep in 15-sec chunks so toggle off responds quickly
            slept = 0
            while slept < wait_sec and not _stop.is_set():
                if not load().get("enabled"):  # toggled off mid-sleep
                    break
                time.sleep(min(15, wait_sec - slept))
                slept += 15
            continue

        try:
            run_one_cycle(reason="scheduled")
        except Exception as e:
            _log(f"❌ cycle failed: {e}")
            # Push next run forward so we don't tight-loop
            cfg = load()
            cfg["next_run"] = (datetime.now(timezone.utc) +
                               timedelta(minutes=15)).isoformat()
            save(cfg)


# ─────────────────────────────────────────────────────────────────────
def start():
    """Start the background loop. Idempotent."""
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return {"already_running": True}
        _stop.clear()
        _thread = threading.Thread(target=_loop, daemon=True,
                                   name="continuous-evolution")
        _thread.start()
        return {"started": True}


def stop():
    """Stop the background loop (next cycle won't fire)."""
    _stop.set()
    return {"stopped": True}


def toggle(enabled: bool = None) -> dict:
    """Flip enabled flag in config; loop reads it on next tick."""
    cfg = load()
    if enabled is None:
        enabled = not cfg.get("enabled", False)
    cfg["enabled"] = bool(enabled)
    if enabled and not cfg.get("next_run"):
        cfg["next_run"] = datetime.now(timezone.utc).isoformat()
    save(cfg)
    if enabled:
        start()
    return {"enabled": enabled}


def status() -> dict:
    cfg = load()
    return {
        "enabled":          cfg.get("enabled"),
        "thread_alive":     bool(_thread and _thread.is_alive()),
        "is_running_cycle": cfg.get("is_running_cycle"),
        "current_phase":    cfg.get("current_phase"),
        "interval_hours":   cfg.get("interval_hours"),
        "symbols":          cfg.get("symbols"),
        "last_run":         cfg.get("last_run"),
        "next_run":         cfg.get("next_run"),
        "total_cycles":     cfg.get("total_cycles"),
        "total_deploys":    cfg.get("total_deploys"),
        "deploys_today":    cfg.get("deploys_today"),
        "history":          (cfg.get("history") or [])[-5:],
    }


if __name__ == "__main__":
    print(json.dumps(status(), indent=2, ensure_ascii=False))
