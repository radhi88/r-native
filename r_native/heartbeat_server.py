"""heartbeat_server.py - Tiny Flask server that lets the Launcher monitor this Worker.

Runs in a daemon thread inside r_native/app.py. Exposes 3 endpoints on
127.0.0.1:7711 by default. Listens loopback-only — never exposed to network.

Endpoints
---------
GET  /heartbeat   → { ok, uptime_sec, ram_mb, pid, version, vault_size, active_campaign }
POST /shutdown    → schedules graceful Qt exit, returns immediately
POST /restart     → flags worker as "wants restart"; launcher reads this on next /heartbeat

Backward-compatible: if the server fails to start, the worker keeps running
normally — it just won't be supervised.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional

# Suppress Flask's default request log (we don't want every 2s poll spamming console)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

VERSION         = "1.2.0"
DEFAULT_PORT    = 7711
HOST            = "127.0.0.1"

# H.5: auto-restart if RSS exceeds this threshold (MB).
# Worker requests own restart; launcher respawns it fresh.
# Resolution order (see resolve_rss_limit_mb):
#   1. env R_NATIVE_RSS_LIMIT_MB
#   2. data/r_native/settings.json  key "rss_limit_mb"
#   3. this default (500 — target for the slim H-architecture worker)
# NOTE: the current monolith legitimately boots ~515MB, so live deployments
# should carry rss_limit_mb in settings.json (or the env var) until the
# two-process split lands; otherwise a healthy boot triggers a restart loop.
RSS_RESTART_MB        = 500
RSS_CHECK_INTERVAL_S  = 30
RSS_GRACE_PERIOD_S    = 60   # breach → wait this long (launcher polls /heartbeat
                             # every 2s, sees wants_restart) before self-terminating
RSS_HARD_EXIT_WAIT_S  = 10   # after graceful shutdown hook, wait then os._exit
SETTINGS_JSON         = r"C:\Users\Radhi\MT5\data\r_native\settings.json"


def resolve_rss_limit_mb(default: int = RSS_RESTART_MB) -> int:
    """H.5: configurable RSS restart threshold.
    env R_NATIVE_RSS_LIMIT_MB > settings.json "rss_limit_mb" > default (500)."""
    try:
        raw = os.environ.get("R_NATIVE_RSS_LIMIT_MB", "").strip()
        if raw:
            v = int(float(raw))
            if v > 0:
                return v
    except Exception:
        pass
    try:
        import json
        with open(SETTINGS_JSON, "r", encoding="utf-8-sig") as f:
            v = int(json.load(f).get("rss_limit_mb", 0))
        if v > 0:
            return v
    except Exception:
        pass
    return default

_STARTED_AT     = time.time()
_RESTART_FLAG   = False           # set true by POST /restart; launcher reads via /heartbeat
_SHUTDOWN_HOOK: Optional[Callable[[], None]] = None
_STATE_GETTER:  Optional[Callable[[], dict]] = None
_thread: Optional[threading.Thread] = None
_rss_watchdog_thread: Optional[threading.Thread] = None


def _rss_mb() -> float:
    """Resident-set-size in MB; falls back to 0 if psutil unavailable."""
    try:
        import psutil
        return round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 1)
    except Exception:
        return 0.0


def _build_app():
    """Create the Flask app. Imported lazily so a missing Flask doesn't crash the worker."""
    from flask import Flask, jsonify

    app = Flask(__name__)
    app.logger.disabled = True

    @app.route("/heartbeat", methods=["GET"])
    def heartbeat():
        state = {}
        if _STATE_GETTER:
            try:    state = _STATE_GETTER() or {}
            except Exception as e: state = {"_state_err": str(e)}
        return jsonify({
            "ok":               True,
            "version":          VERSION,
            "pid":              os.getpid(),
            "uptime_sec":       round(time.time() - _STARTED_AT, 1),
            "ram_mb":           _rss_mb(),
            "wants_restart":    _RESTART_FLAG,
            **state,
        })

    @app.route("/shutdown", methods=["POST"])
    def shutdown():
        # Defer the actual shutdown so the response can be flushed first
        if _SHUTDOWN_HOOK:
            threading.Timer(0.2, _SHUTDOWN_HOOK).start()
        return jsonify({"ok": True, "shutting_down": True})

    @app.route("/restart", methods=["POST"])
    def restart():
        global _RESTART_FLAG
        _RESTART_FLAG = True
        # Schedule shutdown so launcher can respawn. Launcher polls /heartbeat
        # and sees wants_restart=true before the worker actually goes down.
        if _SHUTDOWN_HOOK:
            threading.Timer(0.5, _SHUTDOWN_HOOK).start()
        return jsonify({"ok": True, "restart_scheduled": True})

    return app


def start(port: int = DEFAULT_PORT,
          shutdown_hook: Optional[Callable[[], None]] = None,
          state_getter:  Optional[Callable[[], dict]] = None) -> bool:
    """Start the heartbeat server in a daemon thread.

    Args:
        port:          TCP port (default 7711). Loopback only.
        shutdown_hook: Called on POST /shutdown — should trigger Qt app.quit().
        state_getter:  Optional callable returning extra state dict (vault_size, etc.).

    Returns True if the thread started, False if Flask wasn't available.
    """
    global _SHUTDOWN_HOOK, _STATE_GETTER, _thread
    _SHUTDOWN_HOOK = shutdown_hook
    _STATE_GETTER  = state_getter

    if _thread and _thread.is_alive():
        return True  # already running

    try:
        app = _build_app()
    except ImportError as e:
        print(f"[heartbeat] Flask unavailable — supervision disabled: {e}")
        return False

    def _serve():
        try:
            # use_reloader=False is critical — reloader spawns a child process
            # which would double everything; threaded=True so concurrent polls work.
            app.run(host=HOST, port=port, debug=False,
                    use_reloader=False, threaded=True)
        except OSError as e:
            # Port already taken — non-fatal. Most likely another worker is running.
            print(f"[heartbeat] could not bind {HOST}:{port} — {e}")

    _thread = threading.Thread(target=_serve, name="rnative-heartbeat",
                               daemon=True)
    _thread.start()
    print(f"[heartbeat] serving on http://{HOST}:{port}")
    return True


def is_restart_requested() -> bool:
    """Worker code can poll this to short-circuit long ops if a restart was requested."""
    return _RESTART_FLAG


# ─── H.5: RSS watchdog ────────────────────────────────────────────────
def _rss_watchdog_loop(threshold_mb: int, interval_s: float,
                       grace_s: float = RSS_GRACE_PERIOD_S,
                       hard_wait_s: float = RSS_HARD_EXIT_WAIT_S,
                       hard_exit: bool = True,
                       max_checks: Optional[int] = None,
                       rss_getter: Callable[[], float] = None):
    """Background loop: if RSS ≥ threshold, set wants_restart + self-terminate.

    Sequence on breach (H.5 DOD):
      1. wants_restart=true — launcher polls /heartbeat every 2s and respawns
      2. wait `grace_s` (60s) so in-flight work / the launcher can react
      3. graceful shutdown via _SHUTDOWN_HOOK (Qt app.quit())
      4. if still alive `hard_wait_s` later → os._exit(0)  (hard fallback)

    `max_checks`, `hard_exit` and `rss_getter` exist for offline unit tests.
    """
    global _RESTART_FLAG
    get_rss = rss_getter or _rss_mb
    checks = 0
    while True:
        time.sleep(interval_s)
        rss = get_rss()
        if rss > 0 and rss >= threshold_mb:
            print(f"[heartbeat] RSS {rss}MB ≥ threshold {threshold_mb}MB — "
                  f"requesting restart (grace {grace_s}s)", flush=True)
            _RESTART_FLAG = True
            # Grace period: launcher sees wants_restart on next /heartbeat poll
            time.sleep(grace_s)
            if _SHUTDOWN_HOOK:
                try: _SHUTDOWN_HOOK()
                except Exception: pass
            if hard_exit:
                # Graceful path should have exited us by now; force it if not.
                time.sleep(hard_wait_s)
                print("[heartbeat] graceful shutdown did not exit — os._exit(0)",
                      flush=True)
                os._exit(0)
            return  # (tests) loop terminates without killing the process
        checks += 1
        if max_checks is not None and checks >= max_checks:
            return  # (tests) bounded run, no breach observed


def start_rss_watchdog(threshold_mb: Optional[int] = None,
                       interval_s: int = RSS_CHECK_INTERVAL_S) -> bool:
    """Optional: start a background thread that auto-requests restart on RSS bloat.
    threshold_mb=None → resolve_rss_limit_mb() (env R_NATIVE_RSS_LIMIT_MB >
    settings.json "rss_limit_mb" > 500). Safe to call twice — second is a no-op."""
    global _rss_watchdog_thread
    if threshold_mb is None:
        threshold_mb = resolve_rss_limit_mb()
    if _rss_watchdog_thread and _rss_watchdog_thread.is_alive():
        return True
    _rss_watchdog_thread = threading.Thread(
        target = _rss_watchdog_loop,
        args   = (threshold_mb, interval_s),
        name   = "rnative-rss-watchdog",
        daemon = True,
    )
    _rss_watchdog_thread.start()
    print(f"[heartbeat] RSS watchdog armed: threshold={threshold_mb}MB every {interval_s}s"
          f" (grace {RSS_GRACE_PERIOD_S}s → graceful exit)")
    return True
