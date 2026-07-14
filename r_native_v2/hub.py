"""
hub.py — R Native 2 unified front door (B2: READ-ONLY skeleton).

Approved scope (agent_bus, 2026-06-06): prove the shell with ZERO risk to the live path.
  • Local HTTP on 127.0.0.1:8800 (loopback only — no external bind, no auth needed for read).
  • GET /health  → hub liveness + heartbeat ages + per-engine state-file freshness.
  • GET /state   → consolidated read of EXISTING state files only (no engine calls).
  • GET /        → tiny index of available endpoints.

HARD RAILS (do not violate without an agent_bus REPLY):
  • NO /request routing yet. NO engine imports. NO MetaTrader5. NO order_send. EVER from the hub.
  • Read-only: opens existing JSON files; never writes, never mutates any engine.
  • DEMO. The protected gold_live.py (MAGIC 99791) remains the sole executor.
  • Fail-closed: any missing/unreadable file → reported as {ok:false} per key, never crashes the hub.

Run:  python r_native_v2/hub.py    (then: curl http://127.0.0.1:8800/health)
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"   # loopback only — never 0.0.0.0
PORT = 8800
VERSION = "0.1-ro"   # read-only skeleton
_STARTED = time.time()
ROOT = Path(__file__).resolve().parent          # .../MT5/r_native_v2
MT5 = ROOT.parent                                # .../MT5

# ── Managed-service files (single-instance + own heartbeat) ──────────────────
HUB_LOCK = ROOT / "data" / "hub.lock"           # pid + heartbeat, rewritten every cycle
HEARTBEAT_INTERVAL = 15                          # seconds between hub.lock heartbeat writes

# ── Existing state files the hub may READ (never write) ───────────────────────
STATE_FILES = {
    "decision":    ROOT / "data" / "sdk_decision.json",      # friday_decision.write_decision output
    "coordinator": ROOT / "data" / "coord_state.json",       # coordinator shared-floor state
    "gold_live":   ROOT / "data" / "gold_live_state.json",   # live scalper snapshot (account/positions)
    "scalp_proof": MT5 / "scalp_proof.json",                 # real-money performance gate
}

# ── MT5 terminal Common/Files (read-only view of the live MQL5 bridge) ───────
# The Brain EA (magic 20260600) + CLAUDE_SIGNAL indicator exchange JSON here.
# The hub only READS these for a unified per-symbol view — it never writes them.
COMMON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
COMMON_JSON = ["friday_brain_orders.json", "son_status.json"]   # execution-path bridge files
COMMON_TEXT = ["kill_switch.txt"]                                # plain-text flags

# ── Liveness sources (heartbeat updated every cycle — NOT the snapshot file) ──
# For engines whose snapshot file (above) is a base/output that may be stale even
# while the engine runs, liveness must be read from a per-cycle heartbeat instead.
# gold_live: gold_live.lock is rewritten every cycle; gold_live.out is a fallback.
LIVENESS_FILES = {
    "gold_live": [ROOT / "data" / "gold_live.lock", ROOT / "data" / "gold_live.out"],
}

# ── Direct-path live scalpers (NOT gated by Brain-EA kill_switch) ─────────────
# These call mt5.order_send directly. The hub only READS their liveness.
LIVE_TRADERS = {
    "gold_live":  {"magic": 99791, "symbol": "XAUUSDm",
                   "liveness": [ROOT / "data" / "gold_live.lock", ROOT / "data" / "gold_live.out"]},
    "btc_scalp":  {"magic": 99792, "symbol": "BTCUSDm",
                   "liveness": [ROOT / "data" / "btc_state.json", MT5 / "btc_live.out"]},
    "btc_swing":  {"magic": 99793, "symbol": "BTCUSDm",
                   "liveness": [ROOT / "data" / "btc_state_swing.json"]},
}

# ── Per-symbol persona genomes (E2: "each symbol has its own gene") ───────────
GENOME_GLOB = "live_genome__*.json"   # in ROOT/data ; excludes *.bak / *PRE_* backups

# ── Symbol universe (F2-a): single source of truth — enabled(trade) vs signals(display) ──
UNIVERSE_FILE = ROOT / "data" / "symbol_universe.json"

# ── PnL-per-magic sources (FILE-ONLY — hub never imports MetaTrader5) ─────────
# gold_live(99791): scalp_proof.json has today/last14d net/trades/pf.
# btc_live(99792): no PnL file yet (btc_state.json to be added by btc_live) → liveness only.
PNL_SOURCES = {
    "gold_live": {"magic": 99791, "file": MT5 / "scalp_proof.json"},
    "btc_scalp": {"magic": 99792, "file": ROOT / "data" / "btc_state.json"},
    "btc_swing": {"magic": 99793, "file": ROOT / "data" / "btc_state_swing.json"},
}

# ── Heartbeat files (agent_bus mutual-notify) ────────────────────────────────
HEARTBEATS = {
    "claude": ROOT / "agent_bus" / "HEARTBEAT_claude.txt",
    "vs":     ROOT / "agent_bus" / "HEARTBEAT_VS.txt",
}


def _age_s(p: Path) -> float | None:
    """Seconds since file last modified, or None if absent. Pure read."""
    try:
        return round(time.time() - p.stat().st_mtime, 1)
    except OSError:
        return None


def _liveness(name: str, snapshot: Path) -> dict:
    """Resolve an engine's liveness from its per-cycle heartbeat when one exists,
    else fall back to the snapshot file mtime. Returns {alive_source, age_s, present}."""
    candidates = LIVENESS_FILES.get(name, [snapshot])
    fresh_path, fresh_age = None, None
    for p in candidates:
        a = _age_s(p)
        if a is not None and (fresh_age is None or a < fresh_age):
            fresh_age, fresh_path = a, p
    return {
        "present": fresh_age is not None,
        "age_s": fresh_age,
        "alive_source": (fresh_path.name if fresh_path else None),
    }


def _read_json(p: Path) -> dict:
    """Fail-closed JSON read: returns {ok, ...} and NEVER raises."""
    if not p.exists():
        return {"ok": False, "reason": "absent", "path": str(p)}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {"ok": True, "age_s": _age_s(p), "data": data}
    except (OSError, ValueError) as exc:
        return {"ok": False, "reason": f"unreadable: {exc}", "path": str(p)}


def build_health() -> dict:
    return {
        "hub": "ok",
        "version": VERSION,
        "mode": "DEMO · read-only · loopback",
        "bind": f"{HOST}:{PORT}",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pid": os.getpid(),
        "hub_heartbeat_age_s": _age_s(HUB_LOCK),
        "heartbeats": {k: {"age_s": _age_s(p), "present": p.exists()} for k, p in HEARTBEATS.items()},
        "engines": {k: _liveness(k, p) for k, p in STATE_FILES.items()},
        "live_traders": build_live_traders(),
        "note": "no /request routing yet (B2 read-only skeleton)",
    }


def build_live_traders() -> dict:
    """Read-only liveness for the direct-path scalpers (gold_live 99791, btc_live 99792).
    These do NOT pass through the Brain-EA kill_switch."""
    out = {}
    for name, cfg in LIVE_TRADERS.items():
        fresh = None
        for p in cfg["liveness"]:
            a = _age_s(p)
            if a is not None and (fresh is None or a < fresh[1]):
                fresh = (p.name, a)
        out[name] = {
            "magic": cfg["magic"], "symbol": cfg["symbol"],
            "present": fresh is not None,
            "age_s": (fresh[1] if fresh else None),
            "alive_source": (fresh[0] if fresh else None),
        }
    return out


def build_pnl() -> dict:
    """Read-only PnL per magic from EXISTING files (no MT5 import).
    gold_live: scalp_proof.json today/last14d/gate. btc_live: btc_state.json if present,
    else a note (PnL writer pending)."""
    out = {}
    for name, cfg in PNL_SOURCES.items():
        p = cfg["file"]
        if not p.exists():
            out[name] = {"magic": cfg["magic"], "ok": False,
                         "reason": f"no PnL file yet ({p.name}) — liveness only"}
            continue
        j = _read_json(p)
        if not j.get("ok"):
            out[name] = {"magic": cfg["magic"], **j}
            continue
        d = j["data"]
        entry = {"magic": cfg["magic"], "ok": True, "age_s": j.get("age_s"), "source": p.name}
        # scalp_proof.json shape (gold)
        if isinstance(d, dict) and "today" in d:
            entry["today"] = d.get("today")
            entry["last14d"] = d.get("last14d")
            entry["real_money_gate"] = d.get("real_money_gate")
        else:
            entry["data"] = d   # btc_state.json (future) — pass through
        out[name] = entry
    return out


def build_universe() -> dict:
    """Read-only view of the symbol universe (F2-a): per-symbol enabled(trade)/signals(display)
    /always_open flags. Fail-closed."""
    j = _read_json(UNIVERSE_FILE)
    if not j.get("ok"):
        return {"ok": False, "reason": j.get("reason", "absent")}
    d = j["data"]
    syms = d.get("symbols", []) if isinstance(d, dict) else []
    return {
        "ok": True, "age_s": j.get("age_s"), "version": d.get("version"),
        "symbols": [
            {"symbol": s.get("symbol"), "market": s.get("market"),
             "asset_class": s.get("asset_class"),
             "enabled": s.get("enabled", False), "signals": s.get("signals", False),
             "always_open": s.get("always_open", False)}
            for s in syms
        ],
    }


def build_personas() -> dict:
    """E2: per-symbol persona from live_genome__<SYMBOL>.json (read-only).
    Surfaces name/generation + key params + a derived always_open (24/7) flag."""
    data_dir = ROOT / "data"
    personas = {}
    try:
        for p in sorted(data_dir.glob(GENOME_GLOB)):
            stem = p.stem  # live_genome__XAUUSDm  (skip backups)
            if ".PRE_" in p.name or p.name.endswith(".bak") or "__" not in stem:
                continue
            sym = stem.split("__", 1)[1]
            if not sym or "." in sym:
                continue
            g = _read_json(p)
            if not g.get("ok"):
                personas[sym] = g
                continue
            d = g["data"]
            params = d.get("params", {}) if isinstance(d, dict) else {}
            personas[sym] = {
                "ok": True, "age_s": g.get("age_s"),
                "name": d.get("name"), "generation": d.get("generation"),
                "lot": params.get("lot"), "sl_pts": params.get("sl_pts"), "tp_pts": params.get("tp_pts"),
                "session_filter": params.get("session_filter"),
                "always_open": params.get("session_filter") == [],   # [] => 24/7 (crypto)
            }
    except OSError as exc:
        personas = {"_error": str(exc)}
    return personas


def _read_text(p: Path) -> dict:
    """Fail-closed text read (for kill_switch.txt etc.). NEVER raises."""
    if not p.exists():
        return {"ok": False, "reason": "absent"}
    try:
        return {"ok": True, "age_s": _age_s(p), "text": p.read_text(encoding="utf-8").strip()[:200]}
    except OSError as exc:
        return {"ok": False, "reason": f"unreadable: {exc}"}


def build_common() -> dict:
    """Read-only view of the MT5 Common/Files MQL5 bridge: brain orders, son gate,
    kill switch, and every per-symbol signal_<SYMBOL>.json. Never writes."""
    out: dict = {"dir": str(COMMON), "present": COMMON.exists()}
    if not COMMON.exists():
        return out
    out["bridge"] = {name: _read_json(COMMON / name) for name in COMMON_JSON}
    out["flags"] = {name: _read_text(COMMON / name) for name in COMMON_TEXT}
    # Per-symbol signal files (multi-market substrate) — glob, fail-closed.
    signals = {}
    try:
        for p in sorted(COMMON.glob("signal_*.json")):
            sym = p.stem.replace("signal_", "")
            signals[sym] = _read_json(p)
    except OSError as exc:
        signals = {"_error": str(exc)}
    out["signals"] = signals
    return out


def build_state() -> dict:
    return {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": {k: _read_json(p) for k, p in STATE_FILES.items()},
        "universe": build_universe(),
        "live_traders": build_live_traders(),
        "pnl": build_pnl(),
        "personas": build_personas(),
        "common_files": build_common(),
    }


# ── C3-a: POST /request — read-only whitelist + shared secret ────────────────
# Secret: env HUB_SECRET if set, else a hub-local auto-generated file (gitignored).
# We deliberately do NOT edit the shared .env (sensitive, multi-session).
SECRET_FILE = ROOT / "data" / "hub_secret.txt"


def _load_secret() -> str:
    v = os.environ.get("HUB_SECRET")
    if v:
        return v.strip()
    try:
        if SECRET_FILE.exists():
            return SECRET_FILE.read_text(encoding="utf-8-sig").strip()
    except OSError:
        pass
    tok = secrets.token_hex(16)
    try:
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        SECRET_FILE.write_text(tok, encoding="utf-8")
    except OSError:
        pass
    return tok


HUB_SECRET = _load_secret()

# Read-only intent handlers — all read existing files; NONE call MT5 or write/execute.
def _intent_status(a):   return build_state()
def _intent_pnl(a):
    p = build_pnl(); m = a.get("magic")
    return {k: v for k, v in p.items() if v.get("magic") == m} if m else p
def _intent_persona(a):  return build_personas().get(a.get("symbol"), {"ok": False, "reason": "unknown symbol"})
def _intent_positions(a):
    out = {}
    for k, v in build_pnl().items():
        out[k] = {"magic": v.get("magic"), "open": (v.get("data") or {}).get("open")}
    return out  # file-only open counts; detailed positions need MT5 (out of hub scope)
def _intent_signal(a):   return build_common().get("signals", {}).get(a.get("symbol"), {"ok": False, "reason": "unknown symbol"})
def _intent_regime(a):
    sig = build_common().get("signals", {}).get(a.get("symbol"), {})
    return {"ok": True, "symbol": a.get("symbol"), "regime": (sig.get("data") or {}).get("regime")} \
        if sig.get("ok") else {"ok": False, "reason": "no signal for symbol"}
def _intent_decide_read(a):  # returns the LAST PERSISTED decision — never creates an order
    return _read_json(STATE_FILES["decision"])

READ_INTENTS = {
    "status": _intent_status, "pnl": _intent_pnl, "persona": _intent_persona,
    "positions": _intent_positions, "signal": _intent_signal, "regime": _intent_regime,
    "decide": _intent_decide_read,
}
# State-changing intents are NOT enabled (C3-b). trade.resume is manual-only forever.
STATE_CHANGING = {"trade.halt", "trade.resume", "evolve"}


class _HubServer(ThreadingHTTPServer):
    # allow_reuse_address MUST be False so a 2nd instance fails to bind :8800.
    # (http.server.HTTPServer defaults it to True, which on Windows lets duplicate
    # instances share the port — defeating the single-instance guard.)
    allow_reuse_address = False
    daemon_threads = True


class HubHandler(BaseHTTPRequestHandler):
    server_version = "RNativeHub/0.1-ro"

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            self._send(200, build_health())
        elif path == "/state":
            self._send(200, build_state())
        elif path == "/":
            self._send(200, {
                "service": "R Native 2 Hub (B2 read-only)",
                "endpoints": ["/health", "/state"],
                "note": "advisory/read-only; /request routing arrives in a later gated step",
            })
        else:
            self._send(404, {"ok": False, "reason": "unknown endpoint", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path != "/request":
            self._send(404, {"ok": False, "reason": "unknown endpoint"})
            return
        # Auth: shared secret header (defense-in-depth on loopback).
        if self.headers.get("X-Hub-Secret", "") != HUB_SECRET:
            self._send(401, {"ok": False, "reason": "missing/invalid X-Hub-Secret"})
            return
        # Body
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            req = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except (ValueError, OSError):
            self._send(400, {"ok": False, "reason": "bad JSON body"})
            return
        intent = req.get("intent")
        if intent in STATE_CHANGING:
            self._send(405, {"ok": False, "reason": f"state-changing intent '{intent}' disabled "
                             "(C3-b; trade.resume is manual-only forever)"})
            return
        fn = READ_INTENTS.get(intent)
        if not fn:
            self._send(404, {"ok": False, "reason": f"intent '{intent}' not in read-only whitelist"})
            return
        try:
            result = fn(req)
        except Exception as exc:  # noqa: BLE001 — never leak a stack to the client
            self._send(500, {"ok": False, "reason": f"intent error: {exc}"})
            return
        self._send(200, {"ok": True, "intent": intent, "result": result,
                         "ts": time.strftime("%Y-%m-%d %H:%M:%S")})

    def log_message(self, fmt: str, *args) -> None:  # quiet stdout; override default noisy logging
        return


def _write_lock() -> None:
    HUB_LOCK.parent.mkdir(parents=True, exist_ok=True)
    HUB_LOCK.write_text(
        json.dumps({"pid": os.getpid(), "ts": time.time(), "bind": f"{HOST}:{PORT}",
                    "version": VERSION, "started_ts": _STARTED}, ensure_ascii=False),
        encoding="utf-8",
    )


def _heartbeat_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            _write_lock()
        except OSError:
            pass
        stop.wait(HEARTBEAT_INTERVAL)


def main() -> None:
    # Single-instance guard: binding the loopback port is the authoritative lock.
    # If another hub already owns :8800, bind fails → we refuse to start (no duplicates).
    try:
        srv = _HubServer((HOST, PORT), HubHandler)
    except OSError as exc:
        print(f"[hub] refusing to start — {HOST}:{PORT} already in use "
              f"(another hub instance?). {exc}")
        raise SystemExit(1)

    stop = threading.Event()
    _write_lock()
    threading.Thread(target=_heartbeat_loop, args=(stop,), daemon=True).start()
    print(f"[hub] R Native 2 read-only hub on http://{HOST}:{PORT}  (GET /health, /state)")
    print(f"[hub] pid={os.getpid()} · heartbeat→{HUB_LOCK.name} every {HEARTBEAT_INTERVAL}s")
    print("[hub] DEMO · read-only · loopback · no order_send · no engine mutation")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[hub] stopped")
    finally:
        stop.set()
        srv.server_close()


if __name__ == "__main__":
    main()
