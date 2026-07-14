"""
FRIDAY Voice — Self-Healing HealthMonitor (Phase 7).

A daemon thread that probes Ollama / Gateway / MT5 every interval, announces
failures and recoveries in Arabic via VoiceOutput.speak_async(), dispatches
repair agents for Ollama and Gateway via GatewayClient.dispatch_task(), and
appends every event to logs/friday_voice/health_repairs.log.

Implements locked decisions D-01 through D-08 and D-12 from 07-CONTEXT.md:
  HEAL-01 (probe + announce), HEAL-02 (dispatch repair),
  HEAL-03 (recovery announce + event log).

Design notes:
  - D-07: re-check the service directly each interval; recovery = service
    responds OK again. No job-status polling.
  - D-12: MT5 is announce-only — never dispatch a repair agent for it.
  - Task strings are hardcoded module constants (never interpolated from
    external input) per the phase threat model.
"""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from .config import LOG_DIR, FridayVoiceConfig, log_event
from .gateway_client import GatewayClient
from .mt5_tools import MT5Tools
from .voice_output import VoiceOutput


# ── Hardcoded announcements (never interpolated from external input) ──────────
_ANNOUNCEMENTS = {
    "ollama": {
        "down": "أولاما مش شغال، بعت وكيل يصلحه",
        "task": "أولاما مش شغال. تحقق من عملية ollama serve وأعد تشغيلها إذا لزم. الملف: friday_local_gateway.py",
    },
    "gateway": {
        "down": "البوابة مش شغالة، بعت وكيل يصلحها",
        "task": "البوابة على بورت 8799 مش شغالة. تحقق من عملية friday_local_gateway.py وأعد تشغيلها.",
    },
    "mt5": {"down": "MT5 مش متصل، حاول تشغله مجدداً"},
}
_RECOVERY_MSG = "الخدمة رجعت شغالة"


class HealthMonitor:
    """Background daemon that watches local services and self-heals on failure.

    Per-service state machine (D-03):
        last_known_up : last observed up/down state (init True per Pitfall 1)
        fail_since    : float epoch of first failure, or None
        repair_dispatched : whether a repair was successfully dispatched this outage
    """

    def __init__(
        self,
        config: FridayVoiceConfig,
        voice: VoiceOutput,
        gateway_client: GatewayClient,
        mt5_tools: MT5Tools,
    ) -> None:
        # D-01 constructor; mt5_tools added as 4th param (resolves Open Question #1)
        self._config = config
        self._voice = voice
        self._gateway = gateway_client
        self._mt5_tools = mt5_tools
        # Floor the interval at 5s so a hostile/garbage value cannot busy-spin (Pitfall 5)
        self._interval = max(5, int(config.health_interval_s))
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="friday-health", daemon=True
        )
        # D-03: per-service state, init last_known_up True (Pitfall 1)
        self._service_state = {
            service: {"last_known_up": True, "fail_since": None, "repair_dispatched": False}
            for service in ("ollama", "gateway", "mt5")
        }

    # ── lifecycle (D-11) ─────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        # D-07: Event.wait (not time.sleep) so stop() interrupts immediately
        while not self._stop.wait(timeout=self._interval):
            self._check_services()

    # ── probes (D-02) ────────────────────────────────────────────────────────
    def _check_services(self) -> None:
        self._check("ollama", self._probe_ollama)
        self._check("gateway", self._probe_gateway)
        self._check("mt5", self._probe_mt5)

    def _probe_ollama(self) -> bool:
        try:
            resp = urllib.request.urlopen(
                "http://127.0.0.1:11434/api/tags", timeout=3
            )
            return resp.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            # urllib.error.HTTPError subclasses URLError, so a 404 -> False (acceptable)
            return False

    def _probe_gateway(self) -> bool:
        try:
            resp = urllib.request.urlopen(
                "http://127.0.0.1:8799/health", timeout=3
            )
            return resp.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def _probe_mt5(self) -> bool:
        # initialize() is thread-safe (internal RLock) and fast-paths on cached state
        return bool(self._mt5_tools.initialize())

    # ── state machine (D-04, D-05, D-06, D-12) ───────────────────────────────
    def _check(self, service: str, probe_fn) -> None:
        state = self._service_state[service]
        is_up = probe_fn()

        if not is_up and state["last_known_up"]:
            # up -> down (D-04): record, announce, log, then dispatch repair
            state["last_known_up"] = False
            state["fail_since"] = time.time()
            state["repair_dispatched"] = False
            self._voice.speak_async(_ANNOUNCEMENTS[service]["down"])
            self._log_health(service, "DOWN", "announcing failure")
            # D-05 + D-12: only ollama/gateway dispatch a repair; mt5 never does
            if service in ("ollama", "gateway") and not state["repair_dispatched"]:
                result = self._gateway.dispatch_task(_ANNOUNCEMENTS[service]["task"])
                if result.get("ok"):
                    state["repair_dispatched"] = True
                    self._log_health(
                        service, "REPAIR_DISPATCHED", f"ok={result.get('ok')}"
                    )
                else:
                    # Leave repair_dispatched False so next cycle retries (Pitfall 3)
                    self._log_health(
                        service,
                        "REPAIR_DISPATCH_FAILED",
                        str(result.get("error", "unknown")),
                    )

        elif is_up and not state["last_known_up"]:
            # down -> up (D-06): announce recovery once, reset state
            state["last_known_up"] = True
            state["fail_since"] = None
            state["repair_dispatched"] = False
            self._voice.speak_async(_RECOVERY_MSG)
            self._log_health(service, "RECOVERED", "")
        # else: no transition — do nothing

    # ── event log (D-08) ─────────────────────────────────────────────────────
    def _log_health(self, service: str, event: str, detail: str) -> None:
        ts = datetime.now().isoformat(timespec="seconds")
        line = f"[{ts}] [{service.upper()}] {event} {detail}".strip()
        log_event("HEALTH", f"{service} {event}")
        try:
            with (LOG_DIR / "health_repairs.log").open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            # A logging failure must never crash the monitor thread
            pass
