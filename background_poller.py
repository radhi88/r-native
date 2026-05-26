"""background_poller.py — keep the Qt UI alive while brain is slow.

THE problem: r_native.app, brain_server, r_executor, and 5 agents now run
in ONE process (since 83d34a9). Brilliant for deployment but creates a
GIL contention hazard: every 3 seconds the Qt main thread does ~5 HTTP
calls to localhost:5055 (account, agents, auto_evo, advisors, services).
If brain is doing anything slow inside the same process — Ollama LLM
call (90s), GA campaign worker join, MT5 reconnect, breeder backtest —
the urllib request waits, the Qt event loop blocks, Windows shows
"(Not Responding)".

Solution: ONE background QThread polls all HTTP endpoints + caches
results. The Qt main thread's tick reads from the cache (instant, no
I/O) and only updates widgets. The UI can NEVER freeze on brain
slowness because it never blocks on the network.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Optional, Any

from PySide6.QtCore import QThread, Signal


# Hard cap on any single HTTP call to brain. Anything beyond this means
# brain is too busy — we drop the result, the UI keeps last-known value.
HTTP_HARD_TIMEOUT_S = 1.0

# How often the poller wakes up to refresh its cache.
POLL_INTERVAL_S = 3.0


def _safe_get_json(url: str, timeout: float = HTTP_HARD_TIMEOUT_S) -> Optional[dict]:
    """Single-attempt GET with hard timeout. Returns dict on success,
    None on any failure. Never raises."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


class BackgroundPoller(QThread):
    """Background thread that keeps a fresh snapshot of brain state.

    Emits `updated` (no args) after each full refresh — UI slots read
    from .cache directly (thread-safe via _lock).
    """
    updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # Cache shape — pre-populated with empty values so UI never gets None
        self._cache: dict[str, Any] = {
            "agents":          [],
            "auto_evo":        {},
            "services":        {},   # from r_native.embedded_services
            "account":         {},
            "executor":        {},
            "hof_summary":     {},
            "trade_gate_btc":  {},
            "advisor_insights": [],
            "strategist_state": {},
            "last_refresh_ts": 0,
            "last_refresh_ms": 0,
            "fail_streak":     0,
        }

    # ── Public API for UI ─────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        """Thread-safe read of a cached value."""
        with self._lock:
            return self._cache.get(key, default)

    def all(self) -> dict:
        """Snapshot copy of the whole cache."""
        with self._lock:
            return dict(self._cache)

    def stop(self):
        self._stop.set()

    # ── Worker loop ────────────────────────────────────────────
    def run(self):
        """Qt thread entry. Polls all endpoints + updates cache."""
        while not self._stop.is_set():
            t0 = time.time()
            new = {}

            # Brain endpoints (each independent, single-attempt)
            new["agents"]     = (_safe_get_json("http://127.0.0.1:5055/api/r/agents/list") or {}).get("agents", [])
            new["auto_evo"]   = _safe_get_json("http://127.0.0.1:5055/api/r/auto_evo/status") or {}
            new["account"]    = _safe_get_json("http://127.0.0.1:5055/api/account") or {}
            new["executor"]   = _safe_get_json("http://127.0.0.1:5055/api/r/executor") or {}
            new["hof_summary"]= _safe_get_json("http://127.0.0.1:5055/api/r/hof/summary") or {}
            new["trade_gate_btc"] = _safe_get_json("http://127.0.0.1:5055/api/r/trade_gate?symbol=BTCUSDm") or {}
            new["advisor_insights"] = (_safe_get_json("http://127.0.0.1:5055/api/r/agents/insights?n=80") or {}).get("insights", [])

            # Local file: strategist state (no HTTP needed)
            try:
                from pathlib import Path
                p = Path(r"C:\Users\Radhi\MT5\data\r_native\agents\strategist_state.json")
                if p.exists():
                    new["strategist_state"] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

            # Embedded services status (in-process, no HTTP)
            try:
                from r_native.embedded_services import services_status
                new["services"] = services_status()
            except Exception:
                pass

            # Direct MT5 polls (also off Qt main thread).
            # account_info, positions, today's deals — formerly in _on_tick,
            # they were blocking the Qt event loop for 100-2000ms each.
            try:
                import MetaTrader5 as mt5
                from datetime import datetime, timedelta
                if not mt5.initialize():
                    mt5.initialize()
                info = mt5.account_info()
                if info:
                    new["mt5_account"] = {
                        "balance": float(info.balance),
                        "equity":  float(info.equity),
                        "margin":  float(info.margin),
                        "free":    float(info.margin_free),
                    }
                positions = mt5.positions_get() or []
                new["mt5_r_positions"] = [
                    {"ticket": p.ticket, "symbol": p.symbol,
                     "type":   "BUY" if p.type == 0 else "SELL",
                     "volume": float(p.volume),
                     "price_open":    float(p.price_open),
                     "price_current": float(p.price_current),
                     "sl": float(p.sl), "tp": float(p.tp),
                     "profit":  float(p.profit),
                     "magic":   int(p.magic),
                     "comment": p.comment or ""}
                    for p in positions if p.magic == 20260605
                ]
                # Last 24h deals — heaviest call, kept here so UI never blocks
                deals = mt5.history_deals_get(
                    datetime.now() - timedelta(hours=24),
                    datetime.now()) or []
                r_closed = [d for d in deals
                            if d.magic == 20260605 and d.entry == 1]
                new["mt5_today_pl"]      = sum(
                    d.profit + d.swap + d.commission for d in r_closed)
                new["mt5_today_trades"]  = len(r_closed)
                new["mt5_today_wins"]    = sum(1 for d in r_closed if d.profit > 0)
                # Recent deals for activity stream (last 4h, both entry kinds)
                recent_cutoff = datetime.now() - timedelta(hours=4)
                recent = mt5.history_deals_get(recent_cutoff,
                                                datetime.now()) or []
                new["mt5_recent_deals"] = [
                    {"ticket": d.ticket, "time": int(d.time),
                     "symbol": d.symbol, "magic": int(d.magic),
                     "entry":  int(d.entry),
                     "type":   int(d.type),
                     "price":  float(d.price),
                     "profit": float(d.profit),
                     "swap":   float(d.swap),
                     "commission": float(d.commission)}
                    for d in sorted(recent, key=lambda x: x.time,
                                    reverse=True)[:20]
                    if int(d.magic) == 20260605 and int(d.entry) in (0, 1)
                ]
            except Exception as _me:
                # MT5 hiccup — UI keeps last-known values
                pass

            elapsed_ms = int((time.time() - t0) * 1000)
            failed = sum(1 for k in ("agents","auto_evo","account","executor")
                          if not new.get(k))
            new["last_refresh_ts"] = time.time()
            new["last_refresh_ms"] = elapsed_ms

            with self._lock:
                self._cache.update(new)
                if failed >= 3:
                    self._cache["fail_streak"] += 1
                else:
                    self._cache["fail_streak"] = 0

            # Notify Qt slots — they read from cache, never block
            try:
                self.updated.emit()
            except Exception:
                pass

            # Sleep in small chunks so stop() is responsive
            slept = 0.0
            while slept < POLL_INTERVAL_S and not self._stop.is_set():
                time.sleep(0.2)
                slept += 0.2
