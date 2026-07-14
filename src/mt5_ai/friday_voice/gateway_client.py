"""Thin HTTP/file client for the FRIDAY local gateway (:8799) — Phase 5.

Provides the voice assistant with access to agent dispatch jobs/patches,
autopilot control (file write), dashboard launch (subprocess), and free-form
task dispatch. All HTTP calls use a hard 5-second timeout (D-09). On any
network failure the methods return ``{"ok": False, "error": "gateway_unreachable"}``
(D-04) so the CommandRouter can speak an immediate Arabic error without an LLM call.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlencode

from .config import PROJECT_ROOT, log_event

GATEWAY_BASE = "http://127.0.0.1:8799"
AUTOPILOT_STATE = PROJECT_ROOT / "friday_autopilot_state.json"
DASHBOARD_SCRIPT = PROJECT_ROOT / "scripts" / "friday_web_dashboard.py"
DASHBOARD_PORT = 8822


class GatewayClient:
    """Thin client for the FRIDAY local gateway.

    All methods return a dict with at minimum ``{"ok": bool}``.
    On any network failure, HTTP methods return
    ``{"ok": False, "error": "gateway_unreachable"}``.
    All HTTP calls use a hard 5-second timeout (D-09).
    """

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = GATEWAY_BASE + path
        if params:
            url += "?" + urlencode(params)
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log_event("GATEWAY", f"unreachable GET {path}: {exc}")
            return {"ok": False, "error": "gateway_unreachable"}

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            GATEWAY_BASE + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log_event("GATEWAY", f"unreachable POST {path}: {exc}")
            return {"ok": False, "error": "gateway_unreachable"}

    @staticmethod
    def _port_open(host: str, port: int, timeout: float = 0.3) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def get_jobs(self, limit: int = 3) -> dict:
        """Return last N dispatch jobs from Gateway.

        On success: ``{"ok": True, "jobs": [...], "count": N}``
        On failure: ``{"ok": False, "error": "gateway_unreachable"}``
        """
        result = self._get("/dispatch/jobs", {"limit": limit})
        if result.get("error") == "gateway_unreachable":
            return result
        rows = result.get("rows") or []
        return {"ok": True, "jobs": rows, "count": len(rows)}

    def get_patches(self, status: str = "pending", limit: int = 10) -> dict:
        """Return patch proposals from Gateway (filtered client-side).

        A patch is "pending" when ``approved == 0`` AND ``applied == 0``.
        On success: ``{"ok": True, "patches": [...], "count": N}``
        On failure: ``{"ok": False, "error": "gateway_unreachable"}``
        """
        result = self._get("/dispatch/patches", {"limit": limit})
        if result.get("error") == "gateway_unreachable":
            return result
        rows = result.get("rows") or []
        if status == "pending":
            rows = [
                r for r in rows
                if int(r.get("approved") or 0) == 0 and int(r.get("applied") or 0) == 0
            ]
        return {"ok": True, "patches": rows, "count": len(rows)}

    def control_autopilot(self, action: str) -> dict:
        """Write autopilot stop/start command to friday_autopilot_state.json atomically.

        Does NOT call Gateway HTTP — writes the file directly (D-05). The autopilot
        supervisor polls this file and reads the 'mode' field. The existing file is
        read first so all other fields are preserved; only 'mode' is overwritten.

        Returns ``{"ok": True, "mode": action}`` on success,
        ``{"ok": False, "error": str}`` on I/O failure.
        """
        state_path = AUTOPILOT_STATE
        try:
            try:
                current = json.loads(state_path.read_text(encoding="utf-8"))
                if not isinstance(current, dict):
                    current = {}
            except (FileNotFoundError, json.JSONDecodeError):
                current = {}
            current["mode"] = action  # e.g. "stop"
            tmp_fd, tmp_path = tempfile.mkstemp(dir=state_path.parent, suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                    json.dump(current, fh, ensure_ascii=False, indent=2)
                os.replace(tmp_path, state_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            log_event("GATEWAY", f"autopilot mode set to '{action}'")
            return {"ok": True, "mode": action}
        except Exception as exc:
            log_event("GATEWAY", f"autopilot control_autopilot failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def launch_dashboard(self) -> dict:
        """Launch friday_web_dashboard.py via subprocess if not already on port 8822.

        Returns ``{"ok": True, "status": "already_running"}`` if port 8822 is open,
        ``{"ok": True, "status": "launched", "pid": int}`` on successful launch,
        ``{"ok": False, "error": str}`` on failure.
        """
        if self._port_open("127.0.0.1", DASHBOARD_PORT):
            return {"ok": True, "status": "already_running"}
        if not DASHBOARD_SCRIPT.exists():
            log_event("GATEWAY", f"dashboard script not found: {DASHBOARD_SCRIPT}")
            return {"ok": False, "error": "dashboard_script_not_found"}
        try:
            proc = subprocess.Popen(
                ["python", str(DASHBOARD_SCRIPT)],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log_event("GATEWAY", f"dashboard launched pid={proc.pid}")
            return {"ok": True, "status": "launched", "pid": proc.pid}
        except Exception as exc:
            log_event("GATEWAY", f"dashboard launch failed: {exc}")
            return {"ok": False, "error": str(exc)}

    def dispatch_task(self, task_text: str) -> dict:
        """POST a free-form task to Gateway /dispatch/run.

        Body: ``{"task": task_text, "max_agents": 3}`` (D-06).
        On success: passes through gateway response dict (has "status", "pid", etc.)
        with ``ok`` set to ``True`` when status == "started".
        On failure: ``{"ok": False, "error": "gateway_unreachable"}``
        """
        result = self._post("/dispatch/run", {"task": task_text, "max_agents": 3})
        if result.get("error") == "gateway_unreachable":
            return result
        result["ok"] = result.get("status") == "started"
        return result
