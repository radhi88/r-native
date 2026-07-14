"""web_launcher.py — J.7 — Browser-based campaign launcher.

Mountable Flask blueprint that brain_server.py can register at /r/campaign.
Lets the user trigger GA campaigns from any browser (incl. phone) without
opening the R Native desktop app.

Endpoints:
  POST /r/campaign/start   {symbol, tf, pg, gens}  → starts campaign in background
  GET  /r/campaign/status                          → live progress (SSE-ready)
  GET  /r/campaign/recent                          → last 10 campaigns + their top
  POST /r/campaign/cancel                          → stop current

Brain server integration (paste into brain_server.py):
    from r_native.web_launcher import bp as campaign_bp
    app.register_blueprint(campaign_bp)
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

from flask import Blueprint, jsonify, request

bp = Blueprint("r_campaign", __name__, url_prefix="/r/campaign")

# Global single-campaign state (one at a time per brain server)
_state = {
    "running":     False,
    "symbol":      None,
    "tf":          None,
    "phase":       None,
    "progress":    0,
    "total":       1,
    "started_at":  None,
    "completed_at": None,
    "vault_size":  0,
    "top_id":      None,
    "top_score":   0,
}
_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_cancel = threading.Event()

CAMPAIGN_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\campaigns")


def _run(symbol: str, tf: str, pg: int, gens: int):
    """Run a campaign in this thread, updating _state."""
    try:
        from r_native.genetic_engine import GeneticEngine, CampaignConfig
        from r_native.combo_fitness   import ingest_campaign
        import multiprocessing as mp

        cfg = CampaignConfig(
            symbol=symbol, timeframe=tf, bars=2000,
            pg_candidates=pg,
            tribe_a_gens=gens, tribe_b_gens=gens, war_gens=gens,
            revival_gens=max(1, gens // 2),
            retrain_gens=max(1, gens // 2),
            n_workers=max(2, mp.cpu_count() - 1),
        )

        def cb(phase, msg, done, total):
            with _lock:
                _state["phase"]    = phase
                _state["progress"] = done
                _state["total"]    = max(total, 1)
            if _cancel.is_set():
                raise InterruptedError("campaign cancelled by user")

        engine = GeneticEngine(cfg, progress_cb=cb)
        summary = engine.run_full_campaign()

        with _lock:
            _state["vault_size"]   = summary.get("vault_size", 0)
            _state["top_id"]       = summary.get("top_genome", {}).get("genome", {}).get("id")
            _state["top_score"]    = summary.get("top_score", 0)
            _state["completed_at"] = time.time()
            _state["phase"]        = "DONE"

        # Optional: feed combo_fitness
        try:
            camp_name = summary.get("campaign", "")
            vault_file = CAMPAIGN_DIR / camp_name / "vault.json"
            if vault_file.exists():
                vault = json.loads(vault_file.read_text(encoding="utf-8"))
                ingest_campaign(symbol, tf, vault)
        except Exception as e:
            print(f"[web_launcher] combo_fitness err: {e}")

    except InterruptedError:
        with _lock: _state["phase"] = "CANCELLED"
    except Exception as e:
        with _lock:
            _state["phase"] = f"ERROR: {e}"
            _state["completed_at"] = time.time()
    finally:
        with _lock: _state["running"] = False


@bp.route("/start", methods=["POST"])
def start():
    global _thread
    if _state["running"]:
        return jsonify({"ok": False, "error": "campaign already running"})
    payload = request.get_json() or {}
    symbol = payload.get("symbol", "BTCUSDm")
    tf     = payload.get("tf", "M5")
    pg     = int(payload.get("pg", 200))
    gens   = int(payload.get("gens", 3))

    with _lock:
        _state.update({
            "running": True, "symbol": symbol, "tf": tf,
            "phase": "STARTING", "progress": 0, "total": 1,
            "started_at": time.time(), "completed_at": None,
            "vault_size": 0, "top_id": None, "top_score": 0,
        })
    _cancel.clear()
    _thread = threading.Thread(target=_run, args=(symbol, tf, pg, gens), daemon=True)
    _thread.start()
    return jsonify({"ok": True, "started": True, "symbol": symbol, "tf": tf})


@bp.route("/status", methods=["GET"])
def status():
    with _lock:
        snapshot = dict(_state)
    snapshot["progress_pct"] = round(snapshot["progress"] / max(1, snapshot["total"]) * 100, 1)
    if snapshot["started_at"]:
        snapshot["elapsed_s"] = round(time.time() - snapshot["started_at"], 1)
    return jsonify(snapshot)


@bp.route("/cancel", methods=["POST"])
def cancel():
    _cancel.set()
    return jsonify({"ok": True, "cancelling": True})


@bp.route("/recent", methods=["GET"])
def recent():
    """List last 10 campaigns with their top genome."""
    if not CAMPAIGN_DIR.exists():
        return jsonify({"campaigns": []})
    out = []
    for camp in sorted(CAMPAIGN_DIR.iterdir(),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
        if not camp.is_dir(): continue
        sf = camp / "summary.json"
        if not sf.exists(): continue
        try:
            s = json.loads(sf.read_text(encoding="utf-8"))
            out.append({
                "campaign":    camp.name,
                "symbol":      s.get("symbol"),
                "tf":          s.get("timeframe"),
                "vault_size":  s.get("vault_size", 0),
                "top_score":   s.get("top_score", 0),
                "top_id":      s.get("top_genome", {}).get("genome", {}).get("id"),
                "finished_at": s.get("finished_at"),
            })
        except Exception: pass
    return jsonify({"campaigns": out})
