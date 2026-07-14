"""symbol_heatmap.py — J.20 — Live multi-symbol grid showing tradeability status.

For each symbol, periodically asks the gate "would you GO if I asked right now?"
Color-codes the result so user sees at-a-glance which markets are hot.

States:
  🟢 GO        — gate verdict = GO, ready to trade
  🟡 WAIT      — gate would WAIT (no signal but no blocker)
  🔴 BLOCKED   — hard blocker (regime, session, news, etc.)
  ⚫ UNKNOWN   — gate error / no data
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Callable

from r_native.asset_classes import all_supported

GATE_URL = "http://127.0.0.1:5055/api/r/trade_gate?symbol={sym}&bypass_session=1&bypass_weekend=1&bypass_friday=1"


class SymbolHeatmap:
    """Background poller that fetches gate status for every symbol every N seconds.
    Threadsafe — UI just reads .latest property."""

    def __init__(self, symbols: list[str] | None = None, poll_seconds: float = 12.0):
        self.symbols = symbols or all_supported()
        self.poll_seconds = poll_seconds
        self.latest: dict[str, dict] = {s: {"status": "UNKNOWN"} for s in self.symbols}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_update: Callable | None = None

    def set_on_update(self, cb: Callable):
        """Register a callback fired after each poll cycle (UI uses this)."""
        self._on_update = cb

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="symbol-heatmap")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            for sym in self.symbols:
                if self._stop.is_set(): break
                self.latest[sym] = self._poll_one(sym)
            if self._on_update:
                try: self._on_update(self.latest.copy())
                except Exception as e: print(f"[heatmap] callback err: {e}")
            self._stop.wait(self.poll_seconds)

    def _poll_one(self, sym: str) -> dict:
        try:
            with urllib.request.urlopen(GATE_URL.format(sym=sym), timeout=4) as r:
                d = json.loads(r.read().decode())
        except Exception as e:
            return {"status": "UNKNOWN", "reason": str(e)[:60], "ts": time.time()}

        verdict = d.get("verdict", "ERROR")
        hard    = d.get("hard_blockers", []) or []
        soft    = d.get("soft_warnings", []) or []
        deployed = d.get("deployed_genome_id")

        if verdict == "GO":
            status = "GO"
        elif verdict == "WAIT":
            status = "WAIT"
        elif verdict == "NO" or hard:
            status = "BLOCKED"
        else:
            status = "UNKNOWN"

        return {
            "status":   status,
            "verdict":  verdict,
            "side":     d.get("side"),
            "deployed": deployed,
            "blockers": hard[:3],
            "warnings": soft[:3],
            "ts":       time.time(),
            "reason":   d.get("reason_ar", "")[:80],
        }


# ── Standalone CLI (test runner) ──────────────────────────────────────
def _cli():
    hm = SymbolHeatmap(poll_seconds=10.0)
    def show(grid):
        print("\n=== SYMBOL HEATMAP ===")
        for sym, st in grid.items():
            icon = {"GO": "🟢", "WAIT": "🟡", "BLOCKED": "🔴",
                    "UNKNOWN": "⚫"}.get(st["status"], "❓")
            print(f"  {icon} {sym:10s} {st['status']:8s}  {st.get('reason','')[:50]}")
    hm.set_on_update(show)
    hm.start()
    try:
        while True: time.sleep(60)
    except KeyboardInterrupt:
        hm.stop()


if __name__ == "__main__":
    _cli()
