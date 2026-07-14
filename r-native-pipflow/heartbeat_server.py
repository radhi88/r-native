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

VERSION         = "1.1.0"
DEFAULT_PORT    = 7711
HOST            = "127.0.0.1"

# H.5: auto-restart if RSS exceeds this threshold (MB).
# Worker requests own restart; launcher respawns it fresh.
RSS_RESTART_MB        = 500
RSS_CHECK_INTERVAL_S  = 30

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
def _rss_watchdog_loop(threshold_mb: int, interval_s: int):
    """Background loop: if RSS > threshold, set restart flag + trigger shutdown.
    Launcher sees wants_restart=true on next /heartbeat and respawns."""
    global _RESTART_FLAG
    while True:
        time.sleep(interval_s)
        rss = _rss_mb()
        if rss > 0 and rss >= threshold_mb:
            print(f"[heartbeat] RSS {rss}MB ≥ threshold {threshold_mb}MB — requesting restart")
            _RESTART_FLAG = True
            # Give launcher 5s to see the flag, then shut down ourselves
            time.sleep(5)
            if _SHUTDOWN_HOOK:
                try: _SHUTDOWN_HOOK()
                except Exception: pass
            return  # loop terminates; process exits via shutdown hook


def start_rss_watchdog(threshold_mb: int = RSS_RESTART_MB,
                       interval_s: int = RSS_CHECK_INTERVAL_S) -> bool:
    """Optional: start a background thread that auto-requests restart on RSS bloat.
    Safe to call multiple times — second call is a no-op."""
    global _rss_watchdog_thread
    if _rss_watchdog_thread and _rss_watchdog_thread.is_alive():
        return True
    _rss_watchdog_thread = threading.Thread(
        target = _rss_watchdog_loop,
        args   = (threshold_mb, interval_s),
        name   = "rnative-rss-watchdog",
        daemon = True,
    )
    _rss_watchdog_thread.start()
    print(f"[heartbeat] RSS watchdog armed: threshold={threshold_mb}MB every {interval_s}s")
    return True
