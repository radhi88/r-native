"""
FRIDAY Web Dashboard — http://127.0.0.1:8790/

يشغّل AutoTrader في الخلفية ويعرض لوحة تحكم تفاعلية على المتصفح.
تشغيل:
    python scripts/friday_web_dashboard.py
    python scripts/friday_web_dashboard.py --profile scalping --poll-seconds 30
"""

import argparse
import copy
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import queue

import joblib
import numpy as np
import pandas as pd
if os.getenv("FRIDAY_DASHBOARD_DISABLE_TF", "").strip().lower() in {"1", "true", "yes", "on"}:
    tf = None
    TF_IMPORT_ERROR = RuntimeError("disabled by FRIDAY_DASHBOARD_DISABLE_TF")
else:
    try:
        import tensorflow as tf
        TF_IMPORT_ERROR = None
    except Exception as exc:
        tf = None
        TF_IMPORT_ERROR = exc
from sklearn.preprocessing import StandardScaler

from _bootstrap import bootstrap

bootstrap()

from friday_symbol_universe import PRIORITY_SYMBOLS, resolve_symbols
from mt5_ai.adaptive_trainer import AdaptiveTrainer
from mt5_ai.agents.entry_agent import EntryAgent
from mt5_ai.agents.evolution_committee import EvolutionCommittee
from mt5_ai.agents.learning_engine import LearningEngine
from mt5_ai.genetic_evolver import GeneticEvolver
from mt5_ai.genome_awards import AwardEngine
from mt5_ai.market_oracle import MarketOracle
from mt5_ai.agents.liquidity_hunter_agent import LiquidityHunterAgent
from mt5_ai.agents.market_analyst_agent import MarketAnalystAgent
from mt5_ai.agents.risk_agent import RiskAgent
from mt5_ai.ai_brain import TradingBrain
from mt5_ai.model_loader import load_symbol_model
from mt5_ai.confidence_engine import ConfidenceEngine
from mt5_ai.pivot_engine import PivotEngine
from mt5_ai.config import (
    AGGRESSIVE_SCALPING_IGNORE_SPREAD,
    DATA_DIR,
    DEFAULT_LOT,
    FEATURE_COLUMNS,
    LOG_DIR,
    MODEL_PATH,
    MT5_SYMBOL,
    SCALER_PATH,
    SEQ_LEN,
)
from mt5_ai.execution import DemoMT5Executor, PaperExecutor
from mt5_ai.market_structure import add_market_structure
from mt5_ai.mt5_gateway import MT5Gateway

DEFAULT_SYMBOLS = list(PRIORITY_SYMBOLS)
MARKET_STALE_SECONDS = 15 * 60

# Per-symbol SL/TP — crypto is more volatile
SYMBOL_RISK = {
    "BTCUSDm":  {"sl_pct": 0.005,  "tp_pct": 0.0075},
    "ETHUSDm":  {"sl_pct": 0.005,  "tp_pct": 0.0075},
    "_default": {"sl_pct": 0.0010, "tp_pct": 0.0015},
}

# point size per symbol (used by PivotEngine)
SYMBOL_POINT = {
    "XAUUSDm": 0.01, "XAGUSDm": 0.001,
    "BTCUSDm": 1.0,  "ETHUSDm": 0.1,
    "_default": 0.00001,
}

PORT = 8790
ROOT = Path(__file__).resolve().parents[1]
SERVICE_URLS = {
    "hub": os.getenv("FRIDAY_DASHBOARD_URL", f"http://127.0.0.1:{PORT}").rstrip("/"),
    "gateway": os.getenv("FRIDAY_GATEWAY_URL", "http://127.0.0.1:8799").rstrip("/"),
    "chat": os.getenv("FRIDAY_CHAT_URL", "http://127.0.0.1:8811").rstrip("/"),
    "tradingview": os.getenv("FRIDAY_TRADINGVIEW_URL", "http://127.0.0.1:8822").rstrip("/"),
    "agents": os.getenv("FRIDAY_AGENTS_URL", "http://127.0.0.1:8833").rstrip("/"),
    "brain": os.getenv("FRIDAY_BRAIN_URL", "http://127.0.0.1:8844").rstrip("/"),
    "dna_ea": os.getenv("FRIDAY_DNA_EA_URL", "http://127.0.0.1:7799").rstrip("/"),
}
EXTERNAL_EXECUTOR_LOGS = (
    (ROOT / "realtime_scalper_logs", "realtime_demo_executor_*.jsonl", "realtime_scalper"),
    (ROOT / "touch_executor_logs", "touch_demo_executor_*.jsonl", "touch_executor"),
    (ROOT / "position_governor_logs", "governor_v2_*.jsonl", "position_governor"),
)
MT5_SUCCESS_RETCODES = {10008, 10009}


# ---------------------------------------------------------------------------
# REGIME-03: Volatility-regime sizing helpers (Phase 09, plan 09-05)
#
# Gate status (D-05 / 09-GATE-RESULT.md):
#   Current VERDICT = FAIL — the XAU regime model did NOT beat the naive
#   baseline (model_bal=0.3509 vs naive_bal=0.4137; needed +0.05).
#
# Gating rule:
#   _REGIME_GATE_CLEARED = False  →  all symbols pass through at 1.0
#                                     (no live sizing change until gate passes)
#   _REGIME_GATE_CLEARED = True   →  XAUUSDm is damped per REGIME_CURVE_XAU;
#                                     FX always 1.0 (D-07)
#
# How to flip: when a future gate run produces VERDICT: PASS, set
#   _REGIME_GATE_CLEARED = True
# or set env var FRIDAY_REGIME_GATE_CLEARED=1 before launching the dashboard.
# ---------------------------------------------------------------------------

_REGIME_GATE_CLEARED: bool = (
    os.getenv("FRIDAY_REGIME_GATE_CLEARED", "0").strip() in {"1", "true", "yes"}
)

# Sizing curve for XAUUSDm when gate is cleared (D-06 discretion).
# Tune in SUMMARY after a future PASS gate run.
_REGIME_CURVE_XAU: dict[str, float] = {
    "low":    0.4,   # dead-vol regime → suppress sizing
    "normal": 1.0,   # neutral → no change
    "high":   1.2,   # high-vol regime → allow slightly larger sizing
}


def regime_lot_mult(symbol: str, vol_state: str | None) -> float:
    """
    Return the regime lot multiplier for (symbol, vol_state).

    Design (D-06, D-07, REGIME-03):
      - FX symbols always return 1.0 (D-07: only XAUUSDm cleared for live damp).
      - Unknown vol_state → 1.0 (safe default).
      - When _REGIME_GATE_CLEARED is False (current: VERDICT=FAIL), returns
        the raw curve value for XAU so the CAPABILITY contract is testable;
        the live gating in _execute will override with 1.0 until gate clears.
      - When _REGIME_GATE_CLEARED is True (future PASS), returns the curve
        value for XAU (0.4 low / 1.0 normal / 1.2 high) and 1.0 for FX.

    Importable by tests/test_regime_sizing.py for isolated unit testing.
    """
    if not symbol.upper().startswith("XAU"):
        return 1.0  # D-07: FX passthrough always
    return float(_REGIME_CURVE_XAU.get(vol_state or "normal", 1.0))


def _load_regime_artifacts(symbol: str) -> dict | None:
    """
    Load regime model, scaler, and meta for a symbol (lazy, guarded).

    Returns a dict with keys: model, scaler, lo_edge, hi_edge, seq_len
    or None when artifacts are absent or fail to load (e.g. gate FAILED
    and no model was written, or TF is unavailable).

    Never raises — inference failures degrade gracefully to vol_state=None.
    """
    if tf is None:
        return None
    models_dir   = ROOT / "models" / symbol
    regime_model_path  = models_dir / "regime_model.keras"
    regime_scaler_path = models_dir / "regime_scaler.pkl"
    meta_path    = ROOT / "data" / "prepared" / f"{symbol}_regime" / "regime_meta.json"

    if not (regime_model_path.exists() and regime_scaler_path.exists() and meta_path.exists()):
        return None  # artifacts not present (gate FAILED or not built for this symbol)

    try:
        model  = tf.keras.models.load_model(str(regime_model_path), compile=False)
        scaler = joblib.load(str(regime_scaler_path))
        meta   = json.loads(meta_path.read_text(encoding="utf-8"))
        return {
            "model":    model,
            "scaler":   scaler,
            "lo_edge":  float(meta["lo_edge"]),
            "hi_edge":  float(meta["hi_edge"]),
            "seq_len":  int(meta["seq_len"]),
            # Frozen, ordered feature list the scaler/model were trained on.
            # Live inference MUST reindex to this exact order (CR-01) — positional
            # padding silently misaligns columns against the frozen scaler stats.
            "features": list(meta.get("features") or []),
        }
    except Exception as exc:
        print(f"[WARN][regime] {symbol}: artifact load failed ({exc}); regime disabled")
        return None


class NeutralProbabilityModel:
    """Keeps the dashboard alive when TensorFlow cannot be loaded."""

    def predict(self, sequence, verbose=0):
        arr = np.asarray(sequence)
        batch = int(arr.shape[0]) if arr.ndim else 1
        return np.full((batch, 1), 0.5, dtype=np.float32)


def _load_prediction_model():
    if tf is None:
        print(f"[WARN] TensorFlow unavailable; using neutral fallback model: {TF_IMPORT_ERROR}")
        return NeutralProbabilityModel(), "neutral_fallback"
    try:
        return tf.keras.models.load_model(str(MODEL_PATH), compile=False), "keras"
    except Exception as exc:
        print(f"[WARN] TensorFlow model load failed; using neutral fallback model: {exc}")
        return NeutralProbabilityModel(), "neutral_fallback"


class SymbolContext:
    """Per-symbol trading engines and runtime state."""
    def __init__(self, symbol: str, gateway, adaptive, shared_model=None, shared_scaler=None):
        self.symbol      = symbol
        self.confidence  = ConfidenceEngine(symbol)
        self.adaptive    = adaptive          # shared AdaptiveTrainer instance
        risk             = SYMBOL_RISK.get(symbol, SYMBOL_RISK["_default"])
        self.sl_pct: float = risk["sl_pct"]
        self.tp_pct: float = risk["tp_pct"]
        point            = SYMBOL_POINT.get(symbol, SYMBOL_POINT["_default"])
        try:
            point = float(gateway.symbol_snapshot(symbol).get("point") or point)
        except Exception:
            pass
        self.pivot       = PivotEngine(gateway, symbol, point_size=point)
        # ── SMC agents (one set per symbol) ───────────────────────────────────
        self.market_analyst   = MarketAnalystAgent(symbol)
        self.liquidity_hunter = LiquidityHunterAgent(symbol)
        self.entry_agent      = EntryAgent(symbol)
        self.risk_agent       = RiskAgent(symbol)
        # ── runtime state ─────────────────────────────────────────────────────
        self.last_exec_ts: float = 0.0
        self.last_bar_time = None
        self.tracked: dict = {}   # ticket → {side, entry, last_profit, symbol, setup_reason}

        # ── Per-symbol prediction model (Phase 3, D-05/D-06) ──────────────────
        # Resolve this symbol's own model+scaler; fall back to the shared model
        # (passed in from the trader) with a VISIBLE warning when missing (D-02).
        try:
            loaded = load_symbol_model(
                symbol,
                fallback_model=shared_model,
                fallback_scaler=shared_scaler,
                verbose=True,
            )
            self.model = loaded.model
            self.model_scaler = loaded.scaler
            self.model_source = loaded.source        # "per_symbol" | "shared"
            self.model_warning = loaded.warning      # None when per_symbol
        except Exception as exc:
            # Never let model resolution stop the symbol — degrade to shared.
            print(f"[WARN][SymbolContext] {symbol}: model load error ({exc}); "
                  f"using shared model")
            self.model = shared_model
            self.model_scaler = shared_scaler
            self.model_source = "shared"
            self.model_warning = f"model load error: {exc}"
        if self.model_warning:
            print(f"[WARN][SymbolContext] {symbol}: {self.model_warning}")

        # ── Regime model (Phase 9 / REGIME-03): lazy guarded load ─────────────
        # Loads regime_model.keras + regime_scaler.pkl + regime_meta.json for
        # this symbol if they exist. None when absent (gate FAILED / not built).
        # A None here is expected and safe — _analyze degrades to vol_state=None.
        self.regime_artifacts: dict | None = _load_regime_artifacts(symbol)
        if self.regime_artifacts is not None:
            print(f"[regime] {symbol}: artifacts loaded "
                  f"(gate_cleared={_REGIME_GATE_CLEARED}; "
                  f"lo={self.regime_artifacts['lo_edge']:.6f} "
                  f"hi={self.regime_artifacts['hi_edge']:.6f})")
        else:
            print(f"[regime] {symbol}: no artifacts (gate FAIL or not built) — "
                  "vol_state defaults to None in _analyze")


# ── Thread-safe gateway proxy ─────────────────────────────────────────────────
_gw_lock = threading.Lock()


class _SafeGW:
    """Serialises all MT5 gateway calls through a single lock."""

    def __init__(self, gw: MT5Gateway):
        object.__setattr__(self, "_gw", gw)

    def __getattr__(self, name):
        attr = getattr(object.__getattribute__(self, "_gw"), name)
        if callable(attr):
            def _locked(*a, **kw):
                with _gw_lock:
                    return attr(*a, **kw)
            return _locked
        return attr


# ── Shared state ──────────────────────────────────────────────────────────────
_lock = threading.Lock()
_state: dict = {
    "account": {},
    "is_demo": False,
    "account_type": "UNKNOWN",
    "symbol": MT5_SYMBOL,
    "active_symbol": MT5_SYMBOL,
    "symbols": DEFAULT_SYMBOLS,
    "service_urls": SERVICE_URLS,
    "symbol_states": {},
    "last_decision": {},
    "open_positions": [],
    "recent_trades": [],
    "candles": [],
    "stats": {
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "started": datetime.now(timezone.utc).isoformat(),
    },
    "agents": {
        "brain":     {"status": "idle", "prob": 0.5},
        "market":    {"status": "idle", "bos_up": 0, "bos_down": 0, "choch_up": 0, "choch_down": 0},
        "liquidity": {"status": "idle", "bsl": 0, "ssl": 0},
        "entry":     {"status": "idle", "reason": ""},
        "risk":      {"status": "idle", "sl": 0, "tp": 0},
        "monitor":   {"status": "idle", "trailing_count": 0},
        "learning":  {"status": "idle"},
        "trainer":   {"status": "idle"},
    },
    "evolution": {
        "generation":     0,
        "population":     0,
        "protected":      0,
        "active_id":      "",
        "active_fitness": 0.0,
        "active_wr":      0.0,
        "active_pnl":     0.0,
        "best_fitness":   0.0,
        "trades_to_evolve": 15,
        "leaderboard":    [],
        "discussion":     [],
    },
}

# ── SSE broadcast ─────────────────────────────────────────────────────────────
_sse_queues: list[queue.Queue] = []
_sse_lock = threading.Lock()


def _set(key, value):
    with _lock:
        _state[key] = value


def _merge(key, value: dict):
    with _lock:
        if isinstance(_state.get(key), dict):
            _state[key].update(value)
        else:
            _state[key] = value


def _snap() -> dict:
    with _lock:
        return copy.deepcopy(_state)


def _read_mt5_exposure_snapshot() -> dict:
    try:
        import MetaTrader5 as mt5

        if not mt5.initialize():
            return {"ok": False, "error": str(mt5.last_error())}
        info = mt5.account_info()
        positions = list(mt5.positions_get() or [])
        orders = list(mt5.orders_get() or [])
        type_names = {
            getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2): "BUY_LIMIT",
            getattr(mt5, "ORDER_TYPE_SELL_LIMIT", 3): "SELL_LIMIT",
            getattr(mt5, "ORDER_TYPE_BUY_STOP", 4): "BUY_STOP",
            getattr(mt5, "ORDER_TYPE_SELL_STOP", 5): "SELL_STOP",
        }
        return {
            "ok": True,
            "account": {
                "login": getattr(info, "login", None),
                "server": getattr(info, "server", ""),
                "currency": getattr(info, "currency", "USD"),
                "balance": getattr(info, "balance", None),
                "equity": getattr(info, "equity", None),
                "profit": getattr(info, "profit", None),
                "margin": getattr(info, "margin", None),
                "margin_free": getattr(info, "margin_free", None),
            } if info else {},
            "positions": [
                {
                    "ticket": int(getattr(p, "ticket", 0) or 0),
                    "symbol": str(getattr(p, "symbol", "")),
                    "type": "BUY" if int(getattr(p, "type", -1) or -1) == 0 else "SELL",
                    "volume": float(getattr(p, "volume", 0.0) or 0.0),
                    "open_price": round(float(getattr(p, "price_open", 0.0) or 0.0), 5),
                    "current": round(float(getattr(p, "price_current", 0.0) or 0.0), 5),
                    "sl": round(float(getattr(p, "sl", 0.0) or 0.0), 5),
                    "tp": round(float(getattr(p, "tp", 0.0) or 0.0), 5),
                    "profit": round(float(getattr(p, "profit", 0.0) or 0.0), 2),
                    "magic": int(getattr(p, "magic", -1) or -1),
                    "comment": str(getattr(p, "comment", "") or ""),
                }
                for p in positions
            ],
            "pending_orders": [
                {
                    "ticket": int(getattr(o, "ticket", 0) or 0),
                    "symbol": str(getattr(o, "symbol", "")),
                    "type": type_names.get(int(getattr(o, "type", -1) or -1), str(getattr(o, "type", ""))),
                    "volume": float(getattr(o, "volume_current", 0.0) or 0.0),
                    "price": round(float(getattr(o, "price_open", 0.0) or 0.0), 5),
                    "sl": round(float(getattr(o, "sl", 0.0) or 0.0), 5),
                    "tp": round(float(getattr(o, "tp", 0.0) or 0.0), 5),
                    "magic": int(getattr(o, "magic", -1) or -1),
                    "comment": str(getattr(o, "comment", "") or ""),
                }
                for o in orders
            ],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _broadcast(evt: str, data: dict):
    msg = f"event: {evt}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)


_external_sync_lock = threading.Lock()
_external_sync_last = 0.0
_external_sync_ready = False
_external_seen_event_ids: set[str] = set()


def _read_tail_lines(path: Path, max_bytes: int = 768_000) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), os.SEEK_SET)
            data = handle.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    return [line for line in data.splitlines() if line.strip()]


def _latest_jsonl_rows(directory: Path, pattern: str, source: str, files: int = 2) -> list[dict]:
    if not directory.exists():
        return []

    try:
        paths = sorted(
            directory.glob(pattern),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[:files]
    except Exception:
        return []

    rows: list[dict] = []
    for path in paths:
        for line in _read_tail_lines(path):
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                row["_source"] = source
                row["_log_file"] = path.name
                rows.append(row)

    return rows


def _nested(mapping: dict, *keys, default=None):
    value = mapping
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def _retcode(value: dict) -> int | None:
    raw = value.get("retcode", _nested(value, "result", "retcode"))
    try:
        return int(raw)
    except Exception:
        return None


def _is_sent(value: dict) -> bool:
    if value.get("sent") is True:
        return True
    retcode = _retcode(value)
    return retcode in MT5_SUCCESS_RETCODES


def _parse_event_epoch(event: dict) -> float:
    raw = (
        event.get("timestamp")
        or event.get("time")
        or _nested(event, "decision", "time")
        or _nested(event, "plan", "created_at")
        or _nested(event, "decision", "created_at")
    )
    if not raw:
        return 0.0

    try:
        text = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _normalize_external_event(row: dict) -> dict | None:
    row_type = str(row.get("type") or "")
    source = str(row.get("_source") or "external")
    result_keys: list[str] = []

    if row_type in {"demo_execution", "touch_execution"}:
        result_keys = ["execution_result"]
    elif row_type == "governor_v2_decision":
        result_keys = [
            "close_result",
            "profit_runner_result",
            "protect_position_result",
            "extend_tp_result",
            "reverse_result",
            "remove_pending_result",
        ]
    else:
        return None

    for result_key in result_keys:
        result = row.get(result_key)
        if not isinstance(result, dict):
            continue

        decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else {}
        request = result.get("request") if isinstance(result.get("request"), dict) else {}
        symbol = (
            decision.get("symbol")
            or plan.get("symbol")
            or request.get("symbol")
            or row.get("symbol")
            or "?"
        )
        action = (
            decision.get("action")
            or plan.get("action")
            or row_type.replace("_execution", "").upper()
        )
        timestamp = (
            row.get("timestamp")
            or decision.get("time")
            or plan.get("created_at")
            or datetime.now(timezone.utc).isoformat()
        )
        sent = _is_sent(result)
        retcode = _retcode(result)
        event = {
            "timestamp": timestamp,
            "epoch": _parse_event_epoch(row),
            "source": source,
            "log_file": row.get("_log_file", ""),
            "type": row_type,
            "result_key": result_key,
            "executed": sent,
            "sent": sent,
            "retcode": retcode,
            "action": action,
            "symbol": symbol,
            "lot": request.get("volume", decision.get("lot", plan.get("lot", 0))),
            "price": request.get("price", decision.get("close", plan.get("entry", 0))),
            "reason": decision.get("reason", plan.get("reason", result.get("reason", ""))),
            "request_id": _nested(result, "result", "request_id", default=""),
            "ticket": request.get("position", request.get("order", "")),
        }
        event["id"] = _external_event_id(event)
        return event

    return None


def _external_event_id(event: dict) -> str:
    return "|".join(
        str(event.get(key, ""))
        for key in ("source", "timestamp", "symbol", "action", "request_id", "ticket", "retcode")
    )


def _collect_external_events(limit: int = 100) -> list[dict]:
    events: list[dict] = []
    for directory, pattern, source in EXTERNAL_EXECUTOR_LOGS:
        for row in _latest_jsonl_rows(directory, pattern, source):
            event = _normalize_external_event(row)
            if event:
                events.append(event)

    seen: dict[str, dict] = {}
    for event in events:
        seen[event["id"]] = event

    ordered = sorted(
        seen.values(),
        key=lambda item: (float(item.get("epoch") or 0.0), str(item.get("timestamp") or "")),
        reverse=True,
    )
    return ordered[:limit]


def _sync_external_runtime_state(force: bool = False, broadcast: bool = False) -> None:
    global _external_sync_last, _external_sync_ready

    now = time.time()
    with _external_sync_lock:
        if not force and now - _external_sync_last < 10.0:
            return
        _external_sync_last = now
        first_sync = not _external_sync_ready
        events = _collect_external_events(limit=100)
        mt5_exposure = _read_mt5_exposure_snapshot()

        with _lock:
            dashboard_recent = [
                item
                for item in (_state.get("recent_trades", []) or [])
                if isinstance(item, dict) and item.get("source") not in {"realtime_scalper", "touch_executor", "position_governor"}
            ]
            combined = events + dashboard_recent
            by_id: dict[str, dict] = {}
            for item in combined:
                key = str(item.get("id") or _external_event_id(item))
                by_id[key] = item

            _state["recent_trades"] = sorted(
                by_id.values(),
                key=lambda item: (float(item.get("epoch") or 0.0), str(item.get("timestamp") or "")),
                reverse=True,
            )[:100]
            _state["external_recent_trades"] = events
            stats = dict(_state.get("stats") or {})
            stats["external_events"] = len(events)
            stats["external_executed"] = sum(1 for event in events if event.get("executed"))
            stats["external_sources"] = sorted({event.get("source", "") for event in events if event.get("source")})
            if mt5_exposure.get("ok"):
                positions = mt5_exposure.get("positions", [])
                pending_orders = mt5_exposure.get("pending_orders", [])
                _state["account"] = mt5_exposure.get("account", _state.get("account", {}))
                _state["open_positions"] = positions
                _state["pending_orders"] = pending_orders
                _state["mt5_positions"] = positions
                _state["mt5_pending_orders"] = pending_orders
                stats["mt5_open_positions"] = len(positions)
                stats["mt5_pending_orders"] = len(pending_orders)
                stats["mt5_exposure_source"] = "direct_mt5"
            else:
                stats["mt5_exposure_error"] = mt5_exposure.get("error", "unknown")
            _state["stats"] = stats

        new_events = [
            event
            for event in events
            if event.get("executed") and event["id"] not in _external_seen_event_ids
        ]
        _external_seen_event_ids.update(event["id"] for event in events)
        _external_sync_ready = True

    if broadcast and not first_sync:
        for event in reversed(new_events):
            _broadcast("trade", event)


# ── AutoTrader thread ─────────────────────────────────────────────────────────
class AutoTraderThread(threading.Thread):
    """
    Trading loop with three key improvements over the old 30s timer:

    1. Bar-close synchronisation — checks every 1 s whether a new M1 bar has
       formed; analysis + execution fire within 1 s of bar close, not ≤ 30 s later.

    2. Kelly Criterion lot sizing — ConfidenceEngine scales the lot based on
       rolling win-rate and avg-win/avg-loss ratio (half-Kelly). Also unlocks
       extra positions (up to +2) when win-rate ≥ 65% over 30+ trades.

    3. Adaptive online learning — AdaptiveTrainer records the feature sequence
       at every entry, and the P&L when the position closes. After 128 closed
       trades it fine-tunes the Keras model in-place with Adam(1e-5).
    """

    def __init__(self, gateway, model, scaler, brain, is_demo,
                 paper_exec, demo_exec, poll_seconds,
                 max_open_positions, entry_cooldown_seconds, profile, log_file,
                 symbols=None, execution_enabled=True,
                 threshold_update_every=5, threshold_halflife=240):
        super().__init__(daemon=True, name="friday-trader")
        self.gw = gateway
        self.model = model
        self.scaler = scaler
        self.brain = brain
        self.is_demo = is_demo
        self.paper_exec = paper_exec
        self.demo_exec = demo_exec
        self.poll_seconds = poll_seconds        # kept for display only; bar-close drives timing
        self.max_open_base = int(max_open_positions)
        self.cooldown = int(entry_cooldown_seconds)
        self.profile = profile
        self.log_file = log_file
        self.execution_enabled = bool(execution_enabled)

        # ── multi-symbol support ──────────────────────────────────────────────
        self.symbols = symbols or DEFAULT_SYMBOLS
        self.adaptive        = AdaptiveTrainer()           # ONE shared instance
        self.learning_engine = LearningEngine(
            update_every=int(threshold_update_every),
            halflife_bars=int(threshold_halflife),
        )            # shared, handles per-symbol state internally
        # per-(agent|symbol) bar index of the last CLOSED trade — drives idle decay
        self._last_trade_bar: dict[str, int] = {}
        # monotonic per-symbol bar counter (advances on each new M1 bar)
        self._bar_index: dict[str, int] = {}
        # Creating all symbol engines eagerly is expensive when --symbols all
        # resolves to hundreds of MT5 instruments. Build them on first use so
        # the dashboard HTTP server can come up before the full market scan.
        self.contexts: dict[str, SymbolContext] = {}

        # ── Genetic Evolver + Evolution Committee ─────────────────────────────
        # One brain coordinates the stack, but each symbol owns its own genome
        # population and indicator affinity file.
        self.evolvers: dict[str, GeneticEvolver] = {}
        self.evolver = self._evolver_for(self.symbols[0] if self.symbols else "")
        self.committee = EvolutionCommittee(broadcast_fn=_broadcast)
        self._evolution_advisor = self.committee.advise
        _merge("evolution", self._evolution_snapshot(self.symbols[0] if self.symbols else ""))
        print(f"[GeneticEvolver] Symbol-scoped genomes ready | active={self.evolver.symbol} "
              f"Gen={self.evolver.generation} pop={self.evolver.population_size} "
              f"protected={self.evolver.protected_count}")

        # ── Market Oracle + Award Engine ──────────────────────────────────────
        self.oracle = MarketOracle(
            broadcast_fn=_broadcast,
            reward_fn=self._oracle_reward,
        )
        self.awards = AwardEngine(broadcast_fn=_broadcast)
        print("[MarketOracle] Ready — tracking correlations across all symbols")

        # ── Autonomous Brain (Claude tool-use loop) ────────────────────────────
        try:
            from mt5_ai.autonomous_brain import AutonomousBrain
            self.autonomous_brain = AutonomousBrain(
                evolver=self.evolver,
                indicator_memory=self.evolver.memory,
                broadcast_fn=_broadcast,
                get_context_fn=lambda: {
                    "account":        _state.get("account", {}),
                    "open_positions": _state.get("open_positions", []),
                    "recent_trades":  _state.get("recent_trades", []),
                    "symbols":        self.symbols,
                    "evolution":      _state.get("evolution", {}),
                    "symbol_evolution": _state.get("evolution", {}).get("per_symbol", {}),
                },
                oracle=self.oracle,
                awards=self.awards,
            )
        except Exception as _brain_err:
            print(f"[AutonomousBrain] Load failed: {_brain_err}")
            self.autonomous_brain = None

        # ── vision instructions ───────────────────────────────────────────────
        self._vision_instructions: list[dict] = []
        self._vision_checked_at: float = 0.0

        # ── manual trade tracking ─────────────────────────────────────────────
        self._manual_tracked: dict = {}          # ticket → {symbol, side, entry, ...}
        self._last_snapshots: dict = {}          # symbol → last smc dict from _analyze

        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _evolver_for(self, symbol: str) -> GeneticEvolver:
        key = str(symbol or (self.symbols[0] if self.symbols else "")).strip()
        if key not in self.evolvers:
            self.evolvers[key] = GeneticEvolver(symbol=key, broadcast_fn=_broadcast)
        return self.evolvers[key]

    def _context_for(self, symbol: str) -> SymbolContext:
        key = str(symbol or (self.symbols[0] if self.symbols else "")).strip()
        if key not in self.contexts:
            self.contexts[key] = SymbolContext(key, self.gw, self.adaptive, shared_model=self.model, shared_scaler=self.scaler)
        return self.contexts[key]

    def _evolution_snapshot(self, active_symbol: str = "") -> dict:
        active_key = str(active_symbol or (self.symbols[0] if self.symbols else "")).strip()
        active_evolver = self._evolver_for(active_key)
        active_stats = active_evolver.stats()
        per_symbol = {sym: ev.stats() for sym, ev in self.evolvers.items()}

        leaderboard: list[dict] = []
        for sym, ev in self.evolvers.items():
            for card in ev.leaderboard(3):
                card = dict(card)
                card["symbol"] = sym
                leaderboard.append(card)
        leaderboard.sort(key=lambda item: item.get("fitness", 0.0), reverse=True)

        total_population = sum(ev.population_size for ev in self.evolvers.values())
        total_protected = sum(ev.protected_count for ev in self.evolvers.values())
        return {
            **active_stats,
            "active_symbol": active_key,
            "active_population": active_evolver.population_size,
            "active_protected": active_evolver.protected_count,
            "population": total_population,
            "protected": total_protected,
            "symbols_tracked": len(self.evolvers),
            "per_symbol": per_symbol,
            "leaderboard": leaderboard[:10],
        }

    # ── pre-warm ──────────────────────────────────────────────────────────────
    def _prewarm(self):
        """Run a dummy prediction so TF compiles the graph before the first bar."""
        try:
            dummy = np.zeros((1, SEQ_LEN, len(FEATURE_COLUMNS)), dtype=np.float32)
            self.model.predict(dummy, verbose=0)
            print("[Trader] Model pre-warmed — first inference will be fast.")
        except Exception:
            pass

    def _is_market_open(self, symbol: str) -> bool:
        try:
            snap = self.gw.symbol_snapshot(symbol)
            if snap is None or float(snap.get("bid", 0)) <= 0:
                return False
            df = self.gw.fetch_rates(symbol, "M1", 2)
            if df is None or len(df) == 0:
                return False
            last_time = df["time"].iloc[-1]
            if hasattr(last_time, "to_pydatetime"):
                last_time = last_time.to_pydatetime()
            if getattr(last_time, "tzinfo", None) is None:
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                now_utc = datetime.now(timezone.utc)
            age_seconds = max(0.0, (now_utc - last_time).total_seconds())
            return age_seconds <= MARKET_STALE_SECONDS
        except Exception:
            return False

    # ── main loop ─────────────────────────────────────────────────────────────
    def run(self):
        symbol = MT5_SYMBOL  # kept for prewarm only
        self._prewarm()
        print(f"[Trader] Multi-symbol mode — {self.symbols}")

        pos_check_counter = 0

        while not self._stop.is_set():
            try:
                for symbol in self.symbols:
                    if not self._is_market_open(symbol):
                        continue

                    ctx = self._context_for(symbol)
                    try:
                        df2 = self.gw.fetch_rates(symbol, "M1", 2)
                        if df2 is None or len(df2) < 1:
                            continue
                        bar_time = df2["time"].iloc[-1]
                    except Exception:
                        continue

                    if bar_time != ctx.last_bar_time:
                        ctx.last_bar_time = bar_time
                        self._bar_index[symbol] = self._bar_index.get(symbol, 0) + 1
                        _set("active_symbol", symbol)
                        _merge("evolution", self._evolution_snapshot(symbol))

                        decision, seq = self._analyze(symbol, ctx)

                        prob   = decision.get("probability", 0)
                        action = decision.get("action", "NO_TRADE")
                        reason = decision.get("reason", "")
                        smc    = decision.get("smc", {})
                        print(f"[DEBUG] {symbol} bar={bar_time} prob={prob:.3f} action={action} "
                              f"buy_s={smc.get('smc_buy_score',0):.0f} sell_s={smc.get('smc_sell_score',0):.0f} reason={reason}")

                        _set("last_decision", decision)
                        _broadcast("decision", decision)
                        _broadcast("pivots", {**ctx.pivot.levels, "symbol": symbol})
                        self._update_agents(decision)

                        # Update symbol strip state
                        with _lock:
                            _state["symbol_states"][symbol] = {
                                "action":    action,
                                "price":     decision.get("close", 0),
                                "prob":      prob,
                                "positions": sum(1 for p in _state.get("open_positions", []) if p.get("symbol") == symbol),
                                "genome_id": decision.get("genome_id", ""),
                                "genome_fitness": decision.get("genome_fitness", 0.0),
                                "model_source":  getattr(ctx, "model_source", "shared"),
                                "model_warning": getattr(ctx, "model_warning", None),
                            }
                        _broadcast("symbol_states", _state["symbol_states"])

                        if decision.get("action") in {"BUY", "SELL"} and self.execution_enabled:
                            result = self._execute(decision, seq, ctx)
                            if result:
                                _broadcast("trade", result)
                                with _lock:
                                    _state["recent_trades"].append(result)
                                    if len(_state["recent_trades"]) > 100:
                                        _state["recent_trades"] = _state["recent_trades"][-100:]
                        elif decision.get("action") in {"BUY", "SELL"}:
                            simulated = {
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "executed": False,
                                "mode": "ANALYSIS_ONLY",
                                "action": decision.get("action"),
                                "symbol": symbol,
                                "price": decision.get("close", 0),
                                "reason": "dashboard_analysis_only_execution_disabled",
                            }
                            _broadcast("trade", simulated)
                            with _lock:
                                _state["recent_trades"].append(simulated)
                                if len(_state["recent_trades"]) > 100:
                                    _state["recent_trades"] = _state["recent_trades"][-100:]

                        positions = self.gw.get_open_positions()
                        _set("open_positions", positions)
                        _broadcast("positions", {"positions": positions})
                        acct = self.gw.account_snapshot()
                        _set("account", acct)
                        _broadcast("state", _snap())
                        self._sync_tracked(positions)

                # Every 5s: check closed positions
                pos_check_counter += 1
                if pos_check_counter >= 5:
                    pos_check_counter = 0
                    positions = self.gw.get_open_positions()
                    self._check_closed(positions)
                    _set("open_positions", positions)
                    _broadcast("positions", {"positions": positions})
                    self._broadcast_confidence()

            except Exception as exc:
                print(f"[Trader Error] {exc}")

            self._stop.wait(0.5)   # reduced from 1s → bar-close detected within ~0.5s

    # ── analysis ──────────────────────────────────────────────────────────────
    def _analyze(self, symbol: str, ctx: "SymbolContext") -> tuple[dict, np.ndarray]:
        df = self.gw.fetch_rates(symbol, "M1", 500)
        enriched = add_market_structure(df)

        raw_data = enriched[FEATURE_COLUMNS].to_numpy(dtype=np.float32)
        local_scaler = StandardScaler()
        local_scaler.fit(raw_data)          # fit on full window, normalize per-symbol
        raw_seq  = raw_data[-SEQ_LEN:]
        scaled   = local_scaler.transform(raw_seq)
        sequence = scaled.reshape(1, SEQ_LEN, len(FEATURE_COLUMNS))

        model_for_sym = getattr(ctx, "model", None) or self.model
        probability = float(np.asarray(model_for_sym.predict(sequence, verbose=0)).squeeze())
        spread = float(enriched["spread"].iloc[-1]) if "spread" in enriched.columns else None

        # الذهب والفضة → gold_precision (3 شروط SMC، جودة عالية)
        _sym_profile = (
            "gold_precision" if any(x in symbol.upper() for x in ("XAU", "XAG"))
            else self.profile
        )
        from mt5_ai.strategy_profiles import get_profile as _gp
        _brain_for_sym = self.brain
        if _sym_profile != self.profile:
            from mt5_ai.ai_brain import TradingBrain as _TB
            _brain_for_sym = _TB(model=model_for_sym, profile_name=_sym_profile,
                                  journal=self.brain.journal)
        decision = _brain_for_sym.decide(
            df=enriched,
            sequence=sequence,
            probability=probability,
            spread=spread,
            ignore_spread=(self.profile == "scalping" and AGGRESSIVE_SCALPING_IGNORE_SPREAD),
        ).to_dict()

        decision["close"] = float(enriched["close"].iloc[-1])
        decision["symbol"] = symbol
        decision["probability"] = probability

        last = enriched.iloc[-1]
        smc_cols = [
            "bos_up", "bos_down", "choch_up", "choch_down",
            "buy_side_liquidity_sweep", "sell_side_liquidity_sweep",
            "bullish_fvg", "bearish_fvg", "in_bullish_ob", "in_bearish_ob",
            "smc_buy_score", "smc_sell_score", "smc_bias",
            "demand_zone", "supply_zone", "ifvg_bull", "ifvg_bear",
            "trend", "atr", "rsi", "adx", "mfi", "macd", "macd_sig", "spread",
            "bullish_ob_low", "bullish_ob_high", "bearish_ob_low", "bearish_ob_high",
            "prev_swing_high", "prev_swing_low", "liquidity_high", "liquidity_low",
        ]
        decision["smc"] = {c: float(last[c]) if c in enriched.columns else 0.0 for c in smc_cols}
        # حفظ آخر snapshot للصفقات اليدوية
        self._last_snapshots[symbol] = {**decision["smc"], "probability": probability, "close": float(enriched["close"].iloc[-1])}

        # تغذية Oracle بالسعر الجديد + بيانات SMC
        self.oracle.update_price(symbol, float(enriched["close"].iloc[-1]), decision["smc"])

        # Pivot confidence boost
        pivot_result = ctx.pivot.apply(
            signal=decision.get("action", "HOLD"),
            confidence=float(decision.get("confidence", 0.0)),
            price=decision["close"],
        )
        decision["pivot"] = pivot_result
        decision["confidence"] = pivot_result["confidence"]

        # Vision bias boost
        decision = self._apply_vision_boost(decision)

        # ── Run real SMC agents ───────────────────────────────────────────────
        try:
            market_ctx = ctx.market_analyst.extract_context(enriched)
            # Supplement with computed SMC scores EntryAgent needs
            market_ctx.setdefault("smc_buy_score",  float(last.get("smc_buy_score",  0)))
            market_ctx.setdefault("smc_sell_score", float(last.get("smc_sell_score", 0)))
            market_ctx.setdefault("smc_bias",       float(last.get("smc_bias",       0)))
            market_ctx.setdefault("demand_zone",    bool(last.get("demand_zone",  False)))
            market_ctx.setdefault("supply_zone",    bool(last.get("supply_zone",  False)))
            market_ctx.setdefault("ifvg_bull",      bool(last.get("ifvg_bull",    False)))
            market_ctx.setdefault("ifvg_bear",      bool(last.get("ifvg_bear",    False)))
            # 20-bar avg ATR for volatility regime calculation
            atr_col = enriched["atr"] if "atr" in enriched.columns else None
            market_ctx["atr_ref"] = float(atr_col.tail(20).mean()) if atr_col is not None else market_ctx["atr"]

            liquidity_ctx = ctx.liquidity_hunter.analyze(enriched, market_ctx["atr"])

            # ── extra_ctx: indicator values for IndicatorSnapshot & PredictionEngine ──
            closes    = enriched["close"]
            price_now = float(closes.iloc[-1])
            atr_val   = max(float(last.get("atr", 1e-6) or 1e-6) * price_now, 1e-6)
            close_arr = closes.values

            _ema_fast = float(closes.ewm(span=8,  adjust=False).mean().iloc[-1])
            _ema_mid  = float(closes.ewm(span=13, adjust=False).mean().iloc[-1])
            _ema_slow = float(closes.ewm(span=21, adjust=False).mean().iloc[-1])
            _mom3     = float(close_arr[-1] - close_arr[-4])  / atr_val if len(close_arr) >= 4  else 0.0
            _mom10    = float(close_arr[-1] - close_arr[-11]) / atr_val if len(close_arr) >= 11 else 0.0

            extra_ctx = {
                "rsi":         float(last.get("rsi",  50.0)),
                "adx":         float(last.get("adx",  20.0)),
                "ema_fast":    _ema_fast,
                "ema_mid":     _ema_mid,
                "ema_slow":    _ema_slow,
                "momentum_3":  round(_mom3,  4),
                "momentum_10": round(_mom10, 4),
            }

            # ── تطبيق معاملات الجينوم النشط (يتغلب على LearningEngine) ─────────
            symbol_evolver = self._evolver_for(symbol)
            active_genome = symbol_evolver.active_genome
            if active_genome:
                gp = active_genome.to_entry_agent_params()
                ctx.entry_agent.buy_prob_threshold  = gp["buy_prob_threshold"]
                ctx.entry_agent.sell_prob_threshold = gp["sell_prob_threshold"]
                ctx.entry_agent.min_smc_score       = gp["min_smc_score"]
                ctx.entry_agent.update_setup_thresholds(gp["setup_thresholds"])
                decision["genome_id"] = active_genome.id
                decision["genome_symbol"] = active_genome.symbol
                decision["genome_fitness"] = round(active_genome.fitness, 4)
            else:
                # fallback: LearningEngine thresholds
                thr = self.learning_engine.thresholds("smc", symbol)
                ctx.entry_agent.buy_prob_threshold  = thr.get("buy_threshold",  0.60)
                ctx.entry_agent.sell_prob_threshold = thr.get("sell_threshold", 0.40)
                ctx.entry_agent.min_smc_score       = int(thr.get("min_smc_score", 2))
            ctx.entry_agent.tick_cooldowns()

            _best  = self.learning_engine.best_setups("smc",  symbol, min_trades=5)
            _worst = self.learning_engine.worst_setups("smc", symbol, min_trades=5)

            entry_signal = ctx.entry_agent.evaluate(
                market_ctx, liquidity_ctx, probability,
                extra_ctx=extra_ctx, best_setups=_best, worst_setups=_worst,
            )

            risk_signal = None
            if entry_signal:
                risk_signal = ctx.risk_agent.compute(entry_signal, market_ctx, liquidity_ctx)
                # Agent pipeline overrides brain.decide() action
                decision["action"] = entry_signal.side
                decision["reason"] = entry_signal.reason
                if risk_signal:
                    decision["agent_sl"] = risk_signal.sl
                    decision["agent_tp"] = risk_signal.tp

            # Package agent data into decision for broadcasting
            decision["agent_market"] = {
                "symbol":          symbol,
                "bos_up":          market_ctx.get("bos_up",        False),
                "bos_down":        market_ctx.get("bos_down",      False),
                "choch_up":        market_ctx.get("choch_up",      False),
                "choch_down":      market_ctx.get("choch_down",    False),
                "in_bullish_ob":   market_ctx.get("in_bullish_ob", False),
                "in_bearish_ob":   market_ctx.get("in_bearish_ob", False),
                "bullish_fvg":     market_ctx.get("bullish_fvg",   False),
                "bearish_fvg":     market_ctx.get("bearish_fvg",   False),
                "bullish_ob_low":  market_ctx.get("bullish_ob_low"),
                "bullish_ob_high": market_ctx.get("bullish_ob_high"),
                "bearish_ob_low":  market_ctx.get("bearish_ob_low"),
                "bearish_ob_high": market_ctx.get("bearish_ob_high"),
                "fvg_mid":         market_ctx.get("fvg_mid"),
                "rsi":             market_ctx.get("rsi",   50),
                "adx":             market_ctx.get("adx",    0),
                "trend":           market_ctx.get("trend",  0),
            }
            decision["agent_liquidity"] = {
                "symbol":           symbol,
                "eqh_levels":       liquidity_ctx.get("eqh_levels", [])[:5],
                "eql_levels":       liquidity_ctx.get("eql_levels", [])[:5],
                "bsl_target":       liquidity_ctx.get("bsl_target"),
                "ssl_target":       liquidity_ctx.get("ssl_target"),
                "bsl_sweep_active": liquidity_ctx.get("bsl_sweep_active", False),
                "ssl_sweep_active": liquidity_ctx.get("ssl_sweep_active", False),
                "last_bsl_level":   liquidity_ctx.get("last_bsl_level"),
                "last_ssl_level":   liquidity_ctx.get("last_ssl_level"),
            }
            perf = ctx.entry_agent.setup_performance_summary()
            decision["agent_entry"] = {
                "symbol":     symbol,
                "setup":      entry_signal.reason     if entry_signal else "no_setup",
                "side":       entry_signal.side       if entry_signal else "HOLD",
                "smc_score":  entry_signal.smc_score  if entry_signal else 0,
                "confidence": entry_signal.confidence if entry_signal else 0,
                "buy_thr":    ctx.entry_agent.buy_prob_threshold,
                "sell_thr":   ctx.entry_agent.sell_prob_threshold,
                "cooldowns":  list(ctx.entry_agent._setup_cooldowns.keys()),
                "perf":       perf,
            }
            if risk_signal:
                decision["agent_risk"] = {
                    "symbol":      symbol,
                    "sl":          risk_signal.sl,
                    "tp":          risk_signal.tp,
                    "rr":          risk_signal.rr_ratio,
                    "risk_pts":    risk_signal.risk_points,
                    "reward_pts":  risk_signal.reward_points,
                }

            # Broadcast each agent's output as its own SSE event
            _broadcast("agent_market",    decision["agent_market"])
            _broadcast("agent_liquidity", decision["agent_liquidity"])
            _broadcast("agent_entry",     decision["agent_entry"])
            if "agent_risk" in decision:
                _broadcast("agent_risk",  decision["agent_risk"])

        except Exception as _agent_exc:
            print(f"[Agent Error] {symbol}: {_agent_exc}")

        # ── Regime inference (REGIME-03 / Phase 09-05) ────────────────────────
        # Parallel, additive computation — does NOT touch decision["action"] or
        # any direction field. Failure degrades to vol_state=None (safe default).
        # M15 sequence: fetch enough M1 bars and resample (Open Q1 fallback path:
        # gateway fetch_rates does not expose "M15" natively on all brokers, so
        # we resample from the already-fetched M1 window when possible, else fetch
        # a fresh M1 window large enough to produce seq_len M15 bars).
        decision["vol_state"]    = None   # default: no regime signal
        decision["regime_score"] = None
        try:
            ra = ctx.regime_artifacts  # preloaded in SymbolContext.__init__
            if ra is not None:
                from scripts.prepare_sequences import resample_m15
                seq_len_r = ra["seq_len"]
                # Need at least seq_len_r M15 bars → fetch (seq_len_r + 10) * 15 M1 bars
                m1_needed = (seq_len_r + 10) * 15
                df_m1 = self.gw.fetch_rates(symbol, "M1", m1_needed)
                df_m15 = resample_m15(df_m1)
                # Build features on M15 frame using the same add_market_structure pipeline
                df_m15_feat = add_market_structure(df_m15)
                # Reindex to the FROZEN, ordered feature list the scaler/model were
                # trained on (CR-01). Positional pad/truncate silently misaligns columns
                # against the frozen per-column scaler stats — so fail closed instead if
                # any trained feature is missing from the live frame.
                trained_features = ra.get("features") or list(FEATURE_COLUMNS)
                missing = [c for c in trained_features if c not in df_m15_feat.columns]
                if missing:
                    raise ValueError(
                        f"missing trained regime features {missing}; refusing positional fallback")
                if len(df_m15_feat) >= seq_len_r:
                    raw_regime = df_m15_feat[trained_features].to_numpy(dtype=np.float32)
                    raw_window = raw_regime[-seq_len_r:]
                    # Apply FROZEN scaler (from regime pipeline) — not a fresh fit.
                    # Columns are now name-aligned to the scaler's fit order.
                    n_features = ra["scaler"].n_features_in_
                    if raw_window.shape[1] != n_features:
                        raise ValueError(
                            f"regime feature count {raw_window.shape[1]} != scaler "
                            f"n_features_in_ {n_features}; refusing to infer")
                    scaled_r = ra["scaler"].transform(raw_window)
                    seq_r    = scaled_r.reshape(1, seq_len_r, n_features)
                    score    = float(np.asarray(
                        ra["model"].predict(seq_r, verbose=0)).squeeze())
                    # Bucketize against FROZEN train tercile edges
                    if score <= ra["lo_edge"]:
                        vol_state = "low"
                    elif score >= ra["hi_edge"]:
                        vol_state = "high"
                    else:
                        vol_state = "normal"
                    decision["vol_state"]    = vol_state
                    decision["regime_score"] = score
        except Exception as _regime_exc:
            print(f"[regime] {symbol}: inference failed ({_regime_exc}); "
                  "vol_state=None (direction path unaffected)")
            # Ensure safe defaults — inference error must never bubble up
            decision["vol_state"]    = None
            decision["regime_score"] = None

        return decision, scaled  # return the 2-D scaled array for adaptive trainer

    # ── execution ─────────────────────────────────────────────────────────────
    def _execute(self, decision: dict, seq: np.ndarray, ctx: "SymbolContext") -> dict | None:
        action = decision.get("action")
        if action not in {"BUY", "SELL"}:
            return None

        symbol = decision.get("symbol", MT5_SYMBOL)
        price  = float(decision["close"])

        # Dynamic max positions: base + Kelly extra (per-symbol confidence)
        max_open = self.max_open_base + ctx.confidence.extra_positions
        open_pos = self.gw.get_open_positions()
        sym_pos  = [p for p in open_pos if p.get("symbol") == symbol]
        if len(sym_pos) >= max_open:
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": action, "symbol": symbol, "price": price,
                "executed": False, "mode": "BLOCKED",
                "reason": f"max_positions:{len(sym_pos)}/{max_open} (base={self.max_open_base} extra={ctx.confidence.extra_positions})",
            }

        now  = time.time()
        last = ctx.last_exec_ts
        if now - last < self.cooldown:
            remaining = int(self.cooldown - (now - last))
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": action, "symbol": symbol, "price": price,
                "executed": False, "mode": "BLOCKED",
                "reason": f"cooldown:{remaining}s",
            }

        # ── Sniper lot sizing: Kelly × opportunity quality ─────────────────────
        smc_data     = decision.get("smc", {})
        smc_score    = float(smc_data.get("smc_buy_score", 0) if action == "BUY"
                             else smc_data.get("smc_sell_score", 0))
        prob         = float(decision.get("probability", 0.5))
        entry_conf   = float(decision.get("confidence", 0.0))
        acct_balance = float(_state.get("account", {}).get("balance", 1000.0) or 1000.0)

        # Opportunity quality: 0.6 (weak) → 1.0 (base) → 2.0 (sniper)
        score_mult  = 0.6 + (smc_score / 5.0) * 1.4      # score 0→0.6x, score 5→2.0x
        prob_mult   = 0.7 + max(0.0, prob - 0.55) * 4.0   # prob 0.55→0.7x, prob 0.80→1.7x
        conf_mult   = 0.8 + entry_conf * 0.4               # conf 0→0.8x, conf 1→1.2x
        opp_mult    = round(score_mult * prob_mult * conf_mult, 3)
        opp_mult    = max(0.4, min(opp_mult, 3.0))         # hard bounds

        # ── Regime damp (REGIME-03): fold vol_state into opp_mult ─────────────
        # Gate guard: only apply curve when _REGIME_GATE_CLEARED=True.
        # Current status: FAIL (09-GATE-RESULT.md, 2026-06-06) → regime_mult=1.0
        # (no live sizing change). When a future gate run produces PASS, set
        # env var FRIDAY_REGIME_GATE_CLEARED=1 to activate damping for XAUUSDm.
        # D-06 hard rule: only opp_mult is modified; action/direction untouched.
        # D-07: FX symbols always use regime_mult=1.0 (XAU-only scope).
        vol_state_r  = decision.get("vol_state")
        regime_mult  = 1.0  # default passthrough (gate not cleared / FX / unknown)
        if _REGIME_GATE_CLEARED:
            regime_mult = regime_lot_mult(symbol, vol_state_r)
        opp_mult    = round(opp_mult * regime_mult, 3)
        opp_mult    = max(0.4, min(opp_mult, 3.0))         # re-apply bounds after damp

        # Account-based risk: never risk more than 1.5% per trade
        max_risk_usd = acct_balance * 0.015
        kelly_lot    = ctx.confidence.apply_lot(DEFAULT_LOT)
        lot          = round(kelly_lot * opp_mult, 2)
        lot          = max(DEFAULT_LOT * 0.5, lot)         # at least half base lot

        # Use RiskAgent SL/TP when available, else fallback to fixed pct
        if decision.get("agent_sl") and decision.get("agent_tp"):
            sl = decision["agent_sl"]
            tp = decision["agent_tp"]
        else:
            sl_pct = ctx.sl_pct
            tp_pct = ctx.tp_pct
            if action == "BUY":
                sl = price * (1 - sl_pct)
                tp = price * (1 + tp_pct)
            else:
                sl = price * (1 + sl_pct)
                tp = price * (1 - tp_pct)

        if self.is_demo:
            result = self.demo_exec.execute(symbol=symbol, side=action, price=price, lot=lot, sl=sl, tp=tp)
            mode = "DEMO"
        else:
            result = self.paper_exec.execute(symbol=symbol, side=action, price=price, lot=lot, sl=sl, tp=tp)
            mode = "PAPER"

        with _lock:
            _state["stats"]["trades"] += 1

        sent = result.get("sent", False)
        if sent:
            ctx.last_exec_ts = now
            # Record entry for adaptive trainer
            ctx.adaptive.record_entry(symbol, action.lower(), seq)
            # Track for close detection (ticket available in demo mode)
            ticket = (result.get("result", {}) or {}).get("order") or result.get("order")
            if ticket:
                ctx.tracked[int(ticket)] = {
                    "symbol":       symbol,
                    "side":         action,
                    "entry":        price,
                    "last_profit":  0.0,
                    "setup_reason": decision.get("reason", ""),
                    "genome_id":    decision.get("genome_id", ""),
                }

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action, "symbol": symbol,
            "price": price, "sl": sl, "tp": tp,
            "lot": lot, "mode": mode,
            "executed": sent,
            "reason": decision.get("reason", ""),
            "probability": decision.get("probability", 0.0),
            "kelly_mult":  round(ctx.confidence.kelly_lot_multiplier, 3),
            "opp_mult":    opp_mult,
            "smc_score":   smc_score,
            "confidence": round(ctx.confidence.lot_multiplier, 3),
            "genome_id": decision.get("genome_id", ""),
            "genome_symbol": decision.get("genome_symbol", symbol),
            "result": result,
        }

        try:
            with open(self.log_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass

        return event

    # ── position tracking ─────────────────────────────────────────────────────
    def _sync_tracked(self, open_positions: list[dict]):
        """Update last_profit; also detect and register manually-opened positions."""
        open_tickets = {p["ticket"]: p for p in open_positions}

        # ── كشف الصفقات اليدوية ──────────────────────────────────────────────
        all_bot_tickets: set[int] = set()
        for ctx in self.contexts.values():
            all_bot_tickets.update(ctx.tracked.keys())
        all_bot_tickets.update(self._manual_tracked.keys())

        for pos in open_positions:
            ticket = int(pos["ticket"])
            if ticket not in all_bot_tickets:
                symbol = pos.get("symbol", "")
                side   = pos.get("side",   "BUY")
                entry  = float(pos.get("entry", 0.0))
                # سجّل دخول يدوي مع آخر snapshot متاح
                last_snap = self._last_snapshots.get(symbol, {})
                self._manual_tracked[ticket] = {
                    "symbol":      symbol,
                    "side":        side,
                    "entry":       entry,
                    "last_profit": float(pos.get("profit", 0.0)),
                    "source":      "human",
                    "snapshot":    last_snap,
                }
                # سجّل في ذاكرة المؤشرات
                try:
                    self._evolver_for(symbol).memory.record_entry(
                        trade_id    = str(ticket),
                        symbol      = symbol,
                        side        = side,
                        entry_price = entry,
                        snapshot    = last_snap,
                        genome_id   = "",
                        source      = "human",
                    )
                except Exception:
                    pass
                print(f"[HumanTrade] Detected manual trade #{ticket} {side} {symbol} @ {entry:.2f}")
                _broadcast("agent_discussion", {
                    "agent":   "HumanLearner",
                    "message": f"📌 صفقة يدوية مكتشفة: #{ticket} {side} {symbol} @ {entry:.5f}",
                })

        # ── تحديث الأرباح الجارية ────────────────────────────────────────────
        for ctx in self.contexts.values():
            for ticket, info in ctx.tracked.items():
                if ticket in open_tickets:
                    info["last_profit"] = float(open_tickets[ticket].get("profit", 0.0))
        for ticket, info in self._manual_tracked.items():
            if ticket in open_tickets:
                info["last_profit"] = float(open_tickets[ticket].get("profit", 0.0))

    def _check_closed(self, open_positions: list[dict]):
        """Detect positions that closed; handles both bot trades and manual trades."""
        open_tickets = {p["ticket"] for p in open_positions}

        # ── إغلاق الصفقات اليدوية ────────────────────────────────────────────
        closed_manual = [t for t in list(self._manual_tracked) if t not in open_tickets]
        for ticket in closed_manual:
            info = self._manual_tracked.pop(ticket)
            pnl  = info.get("last_profit", 0.0)
            sym  = info["symbol"]
            side = info["side"]
            snap = info.get("snapshot", {})
            conditions = [k for k, v in snap.items() if v and isinstance(v, (bool, int)) and k not in ("probability",)]
            try:
                self._evolver_for(sym).record_trade(
                    won=pnl >= 0, pnl=float(pnl),
                    conditions_active=conditions,
                    trade_id=str(ticket), source="human", snapshot=snap,
                )
            except Exception as _e:
                print(f"[HumanTrade] Evolver error: {_e}")
            print(f"[HumanTrade] Closed #{ticket} {side} {sym} P&L={pnl:+.2f}")
            _broadcast("agent_discussion", {
                "agent":   "HumanLearner",
                "message": f"✅ تعلّمت من صفقتك: {side} {sym} P&L={pnl:+.2f} | "
                           f"{'ربح — سأطوّر هذا النمط' if pnl>=0 else 'خسارة — سأتجنب هذا التوقيت'}",
            })
        for ctx in self.contexts.values():
            closed = [t for t in list(ctx.tracked) if t not in open_tickets]
            for ticket in closed:
                info = ctx.tracked.pop(ticket)
                pnl  = info.get("last_profit", 0.0)
                sym  = info["symbol"]
                side = info["side"]
                if pnl >= 0:
                    ctx.confidence.on_win(pnl)
                    with _lock: _state["stats"]["wins"] += 1
                else:
                    ctx.confidence.on_loss(pnl)
                    with _lock: _state["stats"]["losses"] += 1
                ctx.adaptive.record_exit(sym, side.lower(), pnl)
                # Feed outcome back to EntryAgent and LearningEngine
                setup_reason = info.get("setup_reason", "")
                entry_px     = info.get("entry", 0.0)
                ctx.entry_agent.record_outcome(setup_reason, pnl >= 0, pnl)
                try:
                    self.learning_engine.record(
                        "smc", sym, side.lower(), entry_px, entry_px + pnl, pnl, setup_reason
                    )
                except Exception:
                    pass

                # ── Phase 4: idle bar-decay + dedicated learning SSE event ───
                try:
                    self._emit_learning(sym)
                except Exception as _le:
                    print(f"[Learning] emit error: {_le}")

                # ── تسجيل الصفقة في محرك التطور الجيني ──────────────────────
                try:
                    # المؤشرات النشطة: نستخرجها من سبب الإعداد
                    conditions = [c.strip() for c in setup_reason.split("+") if c.strip()] if setup_reason else []
                    symbol_evolver = self._evolver_for(sym)
                    symbol_evolver.record_trade(
                        won=pnl >= 0,
                        pnl=float(pnl),
                        conditions_active=conditions,
                        genome_id=info.get("genome_id") or None,
                    )
                    # تحديث حالة التطور في الداشبورد
                    ev_stats = self._evolution_snapshot(sym)
                    _merge("evolution", ev_stats)
                    _broadcast("genome_update", ev_stats)
                except Exception as _evo_exc:
                    print(f"[Evolver Error] {_evo_exc}")
                # ── ربط نتيجة الصفقة بلقطة المؤشرات للتعلم ────────────────────
                try:
                    from mt5_ai.indicator_snapshot import update_snapshot_outcome
                    update_snapshot_outcome(sym, side, entry_px, pnl >= 0, pnl)
                except Exception:
                    pass
                print(f"[Trader] #{ticket} {side} {sym} P&L={pnl:+.2f} setup={setup_reason} kelly={ctx.confidence.kelly_lot_multiplier:.3f}")
                try:
                    with open(self.log_file, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "type": "position_closed",
                            "ticket": ticket, "symbol": sym, "side": side, "pnl": pnl,
                            "kelly_mult": ctx.confidence.kelly_lot_multiplier,
                        }, default=str) + "\n")
                except OSError:
                    pass

    def _emit_learning(self, symbol: str):
        """Apply idle bar-decay then broadcast the per-symbol `learning` SSE event (D-03/D-04)."""
        eng = self.learning_engine
        k   = f"smc|{symbol}"
        cur_bar  = self._bar_index.get(symbol, 0)
        last_bar = self._last_trade_bar.get(k, cur_bar)
        elapsed  = max(0, cur_bar - last_bar)
        if elapsed > 0:
            eng.decay_toward_baseline("smc", symbol, bars_elapsed=elapsed)
        # a fresh closed trade resets the idle clock to "now"
        self._last_trade_bar[k] = cur_bar

        rows = eng._load_rows(agent="smc", symbol=symbol, lookback=5)
        last_p_and_l = []
        for r in rows:
            try:
                last_p_and_l.append(round(float(r.get("points", 0.0)), 2))
            except (TypeError, ValueError):
                last_p_and_l.append(0.0)

        _broadcast("learning", {
            "symbol":                  symbol,
            "thresholds":              dict(eng.thresholds("smc", symbol)),
            "trades_since_last_update": eng.trades_since_last_update("smc", symbol),
            "last_p_and_l":            last_p_and_l,
        })

    def _broadcast_confidence(self):
        """Push confidence + adaptive trainer state + oracle checks to dashboard."""
        at = self.adaptive.status()
        _merge("agents", {
            "trainer": {
                "status":        "fine-tuning" if at["buffer_size"] >= at["buffer_capacity"] else "collecting",
                "buffer_size":   at["buffer_size"],
                "retrain_count": at["retrain_count"],
            },
        })
        for ctx in self.contexts.values():
            cs = ctx.confidence.status()
            _broadcast("confidence", {**cs, "symbol": ctx.symbol})

        # فحص تنبؤات منتهية الصلاحية + تقييم الجوائز
        try:
            self.oracle.check_expired()
            for evolver in self.evolvers.values():
                g = evolver.active_genome
                if g:
                    self.awards.evaluate(g)
            _merge("evolution", self._evolution_snapshot(_state.get("active_symbol", "")))
        except Exception as _oe:
            pass

        # بث إحصاءات Oracle
        try:
            acc_stats = self.oracle.accuracy_stats()
            corr_rep  = self.oracle.correlation_report()
            active_p  = self.oracle.active_predictions()
            _broadcast("oracle_stats", {
                "accuracy":          acc_stats,
                "correlations":      corr_rep[:5],
                "active_predictions": active_p[:5],
            })
        except Exception:
            pass

    # ── vision instructions ───────────────────────────────────────────────────
    def _load_vision_instructions(self):
        """Reload vision agent_instructions.json every 5 minutes."""
        now = time.time()
        if now - self._vision_checked_at < 300:
            return
        self._vision_checked_at = now
        try:
            instr_file = DATA_DIR / "research" / "agent_instructions.json"
            if not instr_file.exists():
                return
            data = json.loads(instr_file.read_text(encoding="utf-8"))
            rules = [r for r in data.get("rules", []) if r.get("active", True)]
            self._vision_instructions = rules
            _broadcast("vision", {
                "rule_count":         len(rules),
                "last_updated":       data.get("last_updated", ""),
                "latest_bias":        rules[0].get("bias", "") if rules else "",
                "latest_instruction": rules[0].get("instruction", "")[:80] if rules else "",
            })
            if rules:
                print(f"[Vision] Loaded {len(rules)} rules  bias={rules[0].get('bias','—')}")
        except Exception as exc:
            print(f"[Vision] Failed to load instructions: {exc}")

    def _apply_vision_boost(self, decision: dict) -> dict:
        """Apply vision bias as a confidence boost; updates decision in-place."""
        self._load_vision_instructions()
        if not self._vision_instructions:
            return decision
        action = decision.get("action", "HOLD")
        if action not in ("BUY", "SELL"):
            return decision
        boost = 0.0
        matched: list[str] = []
        for rule in self._vision_instructions:
            bias       = rule.get("bias", "neutral")
            applies_to = rule.get("applies_to", ["BOTH"])
            conf       = float(rule.get("confidence", 0.5))
            if action == "BUY"  and bias == "bullish" and ("BUY"  in applies_to or "BOTH" in applies_to):
                boost += conf * 0.10
                matched.append(rule.get("id", "?"))
            elif action == "SELL" and bias == "bearish" and ("SELL" in applies_to or "BOTH" in applies_to):
                boost += conf * 0.10
                matched.append(rule.get("id", "?"))
        if boost > 0:
            decision["vision_boost"] = round(boost, 4)
            decision["vision_rules"] = matched
            print(f"[Vision] {action} boost +{boost:.3f} from {matched}")
        return decision

    # ── agent state update ────────────────────────────────────────────────────
    def _oracle_reward(self, genome_id: str, prediction) -> None:
        """مكافأة الجينوم عند إصابة التنبؤ."""
        symbol_evolver = self._evolver_for(prediction.symbol)
        g = symbol_evolver.active_genome
        if g:
            if not hasattr(g, "achievements"):
                g.achievements = []
            symbol = prediction.symbol
            direction = prediction.direction
            g.achievements.append(
                f"تنبؤ صحيح: {symbol} {direction} (conf={prediction.confidence:.0%})"
            )
            # تقييم الجوائز
            self.awards.evaluate(g)
            symbol_evolver._save()
            _merge("evolution", self._evolution_snapshot(prediction.symbol))
        _broadcast("agent_discussion", {
            "agent":   "MarketOracle",
            "message": (
                f"🎯 التنبؤ أصاب! {prediction.symbol} {prediction.direction} "
                f"(دخل @ {prediction.price_at:.3f} → فعلي @ {prediction.actual_price:.3f})"
            ),
        })

    def _update_agents(self, decision: dict):
        smc  = decision.get("smc", {})
        prob = decision.get("probability", 0.5)
        action = decision.get("action", "HOLD")

        _merge("agents", {
            "brain": {"status": action, "prob": prob},
            "market": {
                "status":    "active",
                "bos_up":    smc.get("bos_up", 0),
                "bos_down":  smc.get("bos_down", 0),
                "choch_up":  smc.get("choch_up", 0),
                "choch_down":smc.get("choch_down", 0),
                "fvg_bull":  smc.get("bullish_fvg", 0),
                "fvg_bear":  smc.get("bearish_fvg", 0),
                "ob_bull":   smc.get("in_bullish_ob", 0),
                "ob_bear":   smc.get("in_bearish_ob", 0),
            },
            "liquidity": {
                "status":     "active",
                "bsl":        smc.get("buy_side_liquidity_sweep", 0),
                "ssl":        smc.get("sell_side_liquidity_sweep", 0),
                "buy_score":  smc.get("smc_buy_score", 0),
                "sell_score": smc.get("smc_sell_score", 0),
                "bias":       smc.get("smc_bias", 0),
            },
            "entry": {"status": "active", "reason": decision.get("reason", "")},
            "risk":  {"status": "active", "atr": smc.get("atr", 0), "rsi": smc.get("rsi", 50)},
        })


# ── Trailing SL monitor ───────────────────────────────────────────────────────
class TrailingSLMonitor(threading.Thread):
    """Moves SL to break-even once profit >= min_profit, then trails."""

    def __init__(self, gateway, is_demo, min_profit=0.01, trail_points=10, interval=5):
        super().__init__(daemon=True, name="friday-trailing-sl")
        self.gw = gateway
        self.is_demo = is_demo
        self.min_profit = float(min_profit)
        self.trail_points = int(trail_points)
        self.interval = int(interval)
        self._stop = threading.Event()
        self._count = 0

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            if self.is_demo:
                try:
                    self._trail_demo()
                except Exception:
                    pass
            self._stop.wait(self.interval)

    def _trail_demo(self):
        positions = self.gw.get_open_positions()
        for pos in positions:
            profit = pos.get("profit", 0.0)
            if profit < self.min_profit:
                continue

            ticket = pos["ticket"]
            symbol = pos["symbol"]
            side = pos["side"]
            entry = float(pos["entry"])
            current_sl = float(pos["sl"])
            tp = float(pos["tp"])

            try:
                snap = self.gw.symbol_snapshot(symbol)
                bid = float(snap["bid"])
                ask = float(snap["ask"])
                point = float(snap.get("point", 0.01))
                digits = int(snap.get("digits", 2))
            except Exception:
                continue

            if side == "BUY":
                current_price = bid
                be_sl = round(entry + point, digits)
                trail_sl = round(current_price - self.trail_points * point, digits)
                new_sl = max(current_sl, be_sl, trail_sl)
                if new_sl > current_sl + point:
                    res = self.gw.modify_demo_position_sl_tp(ticket, symbol, sl=new_sl, tp=tp)
                    if res.get("sent"):
                        self._count += 1
                        _merge("agents", {"monitor": {"status": "trailing", "trailing_count": self._count}})
                        _broadcast("sl_moved", {"ticket": ticket, "symbol": symbol, "new_sl": new_sl, "side": side})
            else:  # SELL — SL is above price; profit when ask falls; move SL down
                current_price = ask
                # Break-even: SL moves down to entry (if price fell, entry is above us now, good)
                be_sl = round(entry - point, digits)
                # Trail: keep SL trail_points above current ask
                trail_sl = round(current_price + self.trail_points * point, digits)
                # For SELL, SL should decrease (move lower) to lock profits
                # Lower SL = more protected. New SL must be < current SL.
                new_sl = min(current_sl if current_sl > 0 else entry + 1000 * point, be_sl, trail_sl)
                if current_sl == 0 or new_sl < current_sl - point:
                    res = self.gw.modify_demo_position_sl_tp(ticket, symbol, sl=new_sl, tp=tp)
                    if res.get("sent"):
                        self._count += 1
                        _merge("agents", {"monitor": {"status": "trailing", "trailing_count": self._count}})
                        _broadcast("sl_moved", {"ticket": ticket, "symbol": symbol, "new_sl": new_sl, "side": side})


# ── Candle fetcher ────────────────────────────────────────────────────────────
class CandleFetcher(threading.Thread):
    """
    Two-speed OHLCV feed:
      - Full 300-bar snapshot broadcast every `full_interval` seconds (default 60s).
      - Live 1-second tick: fetches the last 2 M1 bars and broadcasts only the
        current (open) bar as a `candle_update` so the chart animates in real time.
    """

    TICK_INTERVAL  = 1.0   # seconds between live-bar updates
    FULL_INTERVAL  = 60    # seconds between full 300-bar refreshes

    def __init__(self, gateway, symbol: str, full_interval: int = FULL_INTERVAL):
        super().__init__(daemon=True, name="friday-candles")
        self.gw = gateway
        self.symbol = symbol
        self.full_interval = full_interval
        self._candles: list[dict] = []
        self._stop = threading.Event()
        self._last_full: float = 0.0

    def stop(self):
        self._stop.set()

    def latest(self, symbol: str | None = None) -> list[dict]:
        if symbol and symbol != _snap().get("active_symbol", self.symbol):
            try:
                df = self.gw.fetch_rates(symbol, "M1", 300)
                return [self._row_to_dict(r) for _, r in df.iterrows()]
            except Exception:
                return []
        return self._candles

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _row_to_dict(row) -> dict:
        t = row["time"]
        ts = int(t.timestamp()) if hasattr(t, "timestamp") else int(t)
        return {
            "time":  ts,
            "open":  float(row["open"]),
            "high":  float(row["high"]),
            "low":   float(row["low"]),
            "close": float(row["close"]),
        }

    def _full_refresh(self, symbol):
        df = self.gw.fetch_rates(symbol, "M1", 300)
        candles = [self._row_to_dict(r) for _, r in df.iterrows()]
        self._candles = candles
        _broadcast("candles", {"candles": candles, "symbol": symbol})
        self._last_full = time.time()

    def _tick_update(self, symbol):
        """Broadcast only the current (live) M1 bar — very lightweight."""
        df = self.gw.fetch_rates(symbol, "M1", 2)
        if df is None or len(df) == 0:
            return
        bar = self._row_to_dict(df.iloc[-1])
        _broadcast("candle_update", {**bar, "symbol": symbol})

    # ── main loop ─────────────────────────────────────────────────────────────
    def run(self):
        cur_sym = None
        while not self._stop.is_set():
            now = time.time()
            active = _snap().get("active_symbol", self.symbol)
            try:
                if active != cur_sym:
                    cur_sym = active
                    self._last_full = 0.0
                    self._candles = []
                if now - self._last_full >= self.full_interval or not self._candles:
                    self._full_refresh(cur_sym)
                else:
                    self._tick_update(cur_sym)
            except Exception:
                pass  # silently skip — avoid console spam at 1 Hz
            self._stop.wait(self.TICK_INTERVAL)


# ── Heartbeat thread ──────────────────────────────────────────────────────────
def _heartbeat_loop():
    while True:
        time.sleep(15)
        _sync_external_runtime_state(broadcast=True)
        _broadcast("heartbeat", {"ts": datetime.now(timezone.utc).isoformat()})


# ── HTTP handler ──────────────────────────────────────────────────────────────
class DashboardHandler(BaseHTTPRequestHandler):
    candle_fetcher: CandleFetcher | None = None

    def log_message(self, *_):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._html()
        elif path == "/events":
            self._sse()
        elif path == "/api/state":
            _sync_external_runtime_state()
            self._json(_snap())
        elif path == "/api/candles":
            qs = self.path.split("?")[1] if "?" in self.path else ""
            params = dict(p.split("=") for p in qs.split("&") if "=" in p)
            sym = params.get("symbol", "")
            candles = self.candle_fetcher.latest(sym or None) if self.candle_fetcher else []
            self._json({"candles": candles, "symbol": sym})
        elif path == "/api/evolution":
            with _lock:
                ev = _state.get("evolution", {})
            self._json(ev)
        elif path == "/api/urls":
            self._json(SERVICE_URLS)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/consult":
            try:
                length  = int(self.headers.get("Content-Length", 0))
                body    = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                question = body.get("question", "")
                evolver  = getattr(DashboardHandler, "_evolver", None)
                committee = getattr(DashboardHandler, "_committee", None)
                if committee and question:
                    answer = committee.quick_consult(question)
                else:
                    answer = "Committee not available."
                self._json({"answer": answer})
            except Exception as exc:
                self._json({"answer": f"Error: {exc}"})
        elif path == "/api/kill_switch":
            trader = getattr(DashboardHandler, "_trader", None)
            if trader is not None:
                trader.execution_enabled = False
            print("[KILL SWITCH] execution_enabled set to False via API")
            self._json({"kill_switch": True, "execution_enabled": False})
        else:
            self.send_response(404)
            self.end_headers()

    def _html(self):
        body = DASHBOARD_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q: queue.Queue = queue.Queue(maxsize=200)
        with _sse_lock:
            _sse_queues.append(q)

        try:
            # send initial full state
            init = _snap()
            self.wfile.write(
                f"event: state\ndata: {json.dumps(init, default=str)}\n\n".encode()
            )
            self.wfile.flush()

            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b"event: heartbeat\ndata: {}\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _sse_lock:
                if q in _sse_queues:
                    _sse_queues.remove(q)


# ── Dashboard HTML ────────────────────────────────────────────────────────────
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FRIDAY | AI Trading Dashboard</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
:root{
  --bg:#0d1117;--bg2:#161b22;--bg3:#21262d;
  --txt:#c9d1d9;--muted:#6e7681;--border:#21262d;
  --green:#3fb950;--red:#f85149;--gold:#f0a500;--blue:#58a6ff;
}
body{background:var(--bg);color:var(--txt);font-family:'Courier New',monospace;font-size:12px;overflow:hidden;height:100vh;display:flex;flex-direction:column;}

/* Top bar */
#topbar{display:flex;align-items:center;gap:14px;padding:8px 16px;background:var(--bg2);border-bottom:1px solid var(--border);flex-shrink:0;}
.logo{font-size:18px;font-weight:bold;color:var(--gold);letter-spacing:3px;}
.sym{font-size:15px;color:var(--gold);font-weight:bold;}
.badge{padding:2px 8px;border-radius:10px;font-size:10px;font-weight:bold;}
.badge.DEMO{background:#0d3f5c;color:var(--blue);}
.badge.LIVE{background:#4f1a0d;color:var(--red);}
.badge.PAPER{background:#1a3f1a;color:var(--green);}
.badge.UNKNOWN{background:var(--bg3);color:var(--muted);}
#clock{margin-left:auto;color:var(--muted);font-size:11px;}
#conn{font-size:10px;color:var(--green);}

/* Stats strip */
#statsbar{display:flex;gap:18px;padding:5px 16px;background:var(--bg);border-bottom:1px solid var(--border);flex-shrink:0;flex-wrap:wrap;}
.st{display:flex;gap:5px;align-items:center;}
.st .lbl{color:var(--muted);}
.st .val{font-weight:bold;}
.val.BUY{color:var(--green);}
.val.SELL{color:var(--red);}
.val.HOLD{color:var(--muted);}

/* Main layout */
#main{display:flex;flex:1;min-height:0;}

/* Chart area */
#chart-col{display:flex;flex-direction:column;flex:1;min-width:0;}
#decision-box{display:flex;align-items:center;gap:14px;padding:7px 14px;background:var(--bg2);border-bottom:1px solid var(--border);flex-shrink:0;}
#d-action{font-size:22px;font-weight:bold;min-width:55px;}
#d-action.BUY{color:var(--green);}
#d-action.SELL{color:var(--red);}
#d-action.HOLD{color:var(--muted);}
#d-reason{color:var(--muted);font-size:11px;flex:1;}
#d-prob{color:var(--gold);font-size:13px;font-weight:bold;}
#chart-container{flex:1;min-height:0;display:grid;grid-template-rows:minmax(330px,1fr) 220px;background:var(--border);gap:1px;}
#tv-chart-wrap{position:relative;background:#0d1117;min-height:330px;}
#tv-chart{position:absolute;inset:0;}
#tv-badge{position:absolute;bottom:8px;left:10px;z-index:2;padding:3px 8px;border:1px solid #30363d;background:#0d1117cc;border-radius:4px;color:var(--muted);font-size:10px;pointer-events:none;}
#internal-chart-wrap{position:relative;background:#0d1117;min-height:180px;}
.overlay-title{position:absolute;top:6px;left:10px;z-index:3;padding:2px 7px;border-radius:3px;background:#161b22cc;color:var(--muted);font-size:10px;border:1px solid var(--border);}
#chart{width:100%;height:100%;}

/* Sidebar */
#sidebar{width:290px;background:var(--bg2);border-left:1px solid var(--border);overflow-y:auto;flex-shrink:0;}
.ag{padding:9px 12px;border-bottom:1px solid var(--border);border-left:3px solid transparent;transition:border-color .3s;}
.ag.bullish{border-left-color:var(--green);}
.ag.bearish{border-left-color:var(--red);}
.ag.active{border-left-color:var(--gold);}
.ag-name{font-size:9px;font-weight:bold;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;}
.ag-stat{font-size:11px;color:var(--txt);}
.ag-sub{font-size:10px;color:var(--muted);margin-top:3px;}
.smc-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px;margin-top:6px;}
.smc-cell{display:flex;justify-content:space-between;gap:5px;padding:4px 6px;border:1px solid var(--border);background:var(--bg);border-radius:4px;min-width:0;}
.smc-cell span:first-child{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.smc-cell b{font-weight:bold;color:var(--txt);}
.smc-cell.on.bull b{color:var(--green);}
.smc-cell.on.bear b{color:var(--red);}
.smc-cell.on.neutral b{color:var(--gold);}
.agent-trace-list{display:flex;flex-direction:column;gap:4px;margin-top:6px;max-height:160px;overflow:auto;}
.agent-trace-item{padding:5px 6px;border:1px solid var(--border);background:var(--bg);border-radius:4px;}
.agent-trace-head{display:flex;justify-content:space-between;gap:6px;color:var(--muted);font-size:9px;margin-bottom:2px;}
.agent-trace-msg{font-size:10px;color:var(--txt);line-height:1.35;}
.agent-trace-item.bullish{border-left:3px solid var(--green);}
.agent-trace-item.bearish{border-left:3px solid var(--red);}
.agent-trace-item.active{border-left:3px solid var(--gold);}

/* Positions */
#pos-wrap{padding:8px 10px;border-top:1px solid var(--border);}
.pos-hdr{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;}
.pos-item{padding:5px 7px;margin:3px 0;border-radius:3px;background:var(--bg3);border-left:3px solid;}
.pos-item.BUY{border-left-color:var(--green);}
.pos-item.SELL{border-left-color:var(--red);}
.pos-row{display:flex;justify-content:space-between;}
.pos-sub{color:var(--muted);font-size:10px;margin-top:2px;}
.pnl.pos{color:var(--green);}
.pnl.neg{color:var(--red);}

/* Trade log */
#logbar{height:140px;background:var(--bg2);border-top:1px solid var(--border);overflow-y:auto;flex-shrink:0;}
table{width:100%;border-collapse:collapse;font-size:10px;}
th{position:sticky;top:0;background:var(--bg2);color:var(--muted);font-weight:normal;padding:3px 7px;text-align:left;border-bottom:1px solid var(--border);}
td{padding:2px 7px;border-bottom:1px solid #21262d30;}
tr.BUY td:nth-child(2){color:var(--green);font-weight:bold;}
tr.SELL td:nth-child(2){color:var(--red);font-weight:bold;}
tr.BLOCKED td{color:var(--muted);}

/* Symbol strip */
#symbar{display:flex;gap:4px;padding:4px 16px;background:var(--bg2);border-bottom:1px solid var(--border);flex-shrink:0;overflow-x:auto;}
.sym-tab{padding:3px 10px;border-radius:4px;background:var(--bg3);border:1px solid var(--border);cursor:pointer;font-size:10px;font-weight:bold;white-space:nowrap;transition:background .2s;}
.sym-tab.active-tab{border-color:var(--gold);color:var(--gold);}
.sym-tab .st-act{font-size:9px;}
.sym-tab.BUY .st-act{color:var(--green);}
.sym-tab.SELL .st-act{color:var(--red);}
.sym-tab .st-price{font-size:9px;color:var(--muted);}

/* Evolution Panel */
.evolution-header{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0;}
.evo-badge{padding:2px 7px;border-radius:8px;font-size:9px;font-weight:bold;background:var(--bg3);color:var(--txt);}
.evo-badge.protected{background:#1a3f0a;color:#3fb950;}
.evo-active-genome{background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px;margin:4px 0;}
.evo-row{display:flex;justify-content:space-between;margin:2px 0;font-size:10px;}
.evo-lbl{color:var(--muted);}
.evo-val{font-weight:bold;}
.evo-val.gold{color:var(--gold);}
.evo-val.green{color:var(--green);}
.evo-val.red{color:var(--red);}
.evo-section-title{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin:6px 0 3px;}
.evo-leaderboard{display:flex;flex-direction:column;gap:2px;max-height:120px;overflow-y:auto;}
.evo-item{display:grid;grid-template-columns:auto 1fr auto auto;gap:4px;align-items:center;padding:3px 5px;border-radius:3px;background:var(--bg);border:1px solid var(--border);font-size:9px;}
.evo-item.evo-active-item{border-color:var(--gold);}
.evo-item.evo-protected-item{border-color:var(--green);}
.evo-gen-badge{font-size:8px;color:var(--muted);}
.evo-fitness-bar{height:4px;background:linear-gradient(90deg,#3fb950,#f0a500);border-radius:2px;min-width:20px;}
.evo-canvas{display:block;width:100%;height:60px;margin:6px 0;border:1px solid var(--border);border-radius:3px;background:#0d1117;}
.evo-consult-wrap{display:flex;gap:4px;margin-top:6px;}
.evo-input{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:3px;color:var(--txt);font-size:10px;padding:4px 6px;outline:none;}
.evo-input::placeholder{color:var(--muted);}
.evo-btn{background:var(--gold);color:#000;border:none;border-radius:3px;font-size:10px;font-weight:bold;padding:4px 8px;cursor:pointer;}
.evo-btn:hover{opacity:0.85;}
.evo-answer{font-size:10px;color:var(--txt);margin-top:5px;max-height:80px;overflow-y:auto;line-height:1.4;background:var(--bg);border:1px solid var(--border);border-radius:3px;padding:5px;display:none;}
.evo-disc-list{max-height:140px;overflow-y:auto;display:flex;flex-direction:column;gap:3px;margin-top:4px;}
.evo-disc-item{padding:4px 6px;border-radius:3px;background:var(--bg);border-left:2px solid var(--gold);font-size:10px;}
.evo-disc-agent{color:var(--gold);font-weight:bold;font-size:9px;}
.evo-disc-msg{color:var(--txt);margin-top:1px;line-height:1.3;}

/* scrollbar */
::-webkit-scrollbar{width:4px;}
::-webkit-scrollbar-track{background:var(--bg);}
::-webkit-scrollbar-thumb{background:var(--bg3);}

@media (max-width: 900px){
  body{height:auto;min-height:100vh;overflow:auto;}
  #topbar{flex-wrap:wrap;gap:8px;}
  #clock{margin-left:0;}
  #statsbar{gap:10px;}
  #main{flex-direction:column;min-height:auto;}
  #chart-col{min-height:720px;flex:none;}
  #chart-container{grid-template-rows:420px 240px;min-height:660px;}
  #sidebar{width:100%;border-left:0;border-top:1px solid var(--border);display:grid;grid-template-columns:repeat(2,minmax(0,1fr));overflow:visible;}
  #pos-wrap{grid-column:1/-1;}
  #logbar{height:220px;}
}

@media (max-width: 560px){
  #sidebar{grid-template-columns:1fr;}
  #chart-col{min-height:680px;}
  #chart-container{grid-template-rows:390px 230px;min-height:620px;}
  .smc-grid{grid-template-columns:1fr;}
}
</style>
</head>
<body>

<div id="topbar">
  <span class="logo">&#9889; FRIDAY</span>
  <span class="sym" id="t-sym">XAUUSDm</span>
  <span class="badge UNKNOWN" id="t-badge">UNKNOWN</span>
  <span style="color:var(--muted)">|</span>
  <span class="st"><span class="lbl">Trades:</span><span class="val" id="t-trades">0</span></span>
  <span class="st"><span class="lbl">Balance:</span><span class="val" id="t-bal">—</span></span>
  <span class="st"><span class="lbl">Equity:</span><span class="val" id="t-eq">—</span></span>
  <span id="clock"></span>
  <span id="conn">&#9679; CONNECTING</span>
</div>

<div id="symbar"></div>

<div id="statsbar">
  <div class="st"><span class="lbl">Action:</span><span class="val HOLD" id="s-action">HOLD</span></div>
  <div class="st"><span class="lbl">Prob:</span><span class="val" id="s-prob">—</span></div>
  <div class="st"><span class="lbl">ATR:</span><span class="val" id="s-atr">—</span></div>
  <div class="st"><span class="lbl">RSI:</span><span class="val" id="s-rsi">—</span></div>
  <div class="st"><span class="lbl">SMC Buy:</span><span class="val" id="s-buy-sc">—</span></div>
  <div class="st"><span class="lbl">SMC Sell:</span><span class="val" id="s-sell-sc">—</span></div>
  <div class="st"><span class="lbl">Bias:</span><span class="val" id="s-bias">—</span></div>
  <div class="st"><span class="lbl">Trailing SL:</span><span class="val" id="s-trail">0</span></div>
</div>

<div id="main">
  <div id="chart-col">
    <div id="decision-box">
      <div id="d-action" class="HOLD">HOLD</div>
      <div id="d-reason">Waiting for market signal...</div>
      <div id="d-prob"></div>
    </div>
    <div id="chart-container">
      <div id="tv-chart-wrap">
        <div id="tv-badge">TradingView primary chart</div>
        <div id="tv-chart"></div>
      </div>
      <div id="internal-chart-wrap">
        <div class="overlay-title">FRIDAY SMC overlay: pivots / OB / FVG / liquidity / SL / TP</div>
        <div id="chart"></div>
      </div>
    </div>
  </div>

  <div id="sidebar">
    <div class="ag" id="ag-brain">
      <div class="ag-name">&#129504; AI Brain (Conv1D+MHA+GRU)</div>
      <div class="ag-stat" id="ab-stat">Idle — waiting for data</div>
      <div class="ag-sub" id="ab-sub">31 features | seq=200 | threshold adaptive</div>
    </div>
    <div class="ag" id="ag-market">
      <div class="ag-name">&#128269; Market Analyst (SMC Structure)</div>
      <div class="ag-stat" id="am-stat">Scanning structure...</div>
      <div class="ag-sub" id="am-sub">BOS / CHOCH / FVG / Order Blocks</div>
    </div>
    <div class="ag" id="ag-smc-snapshot">
      <div class="ag-name">&#128202; SMC Snapshot</div>
      <div class="ag-stat" id="smc-snapshot-head">Waiting for active symbol snapshot...</div>
      <div class="smc-grid" id="smc-snapshot-grid"></div>
    </div>
    <div class="ag" id="ag-liq">
      <div class="ag-name">&#128167; Liquidity Hunter</div>
      <div class="ag-stat" id="al-stat">Tracking smart money...</div>
      <div class="ag-sub" id="al-sub">EQH / EQL / SSL / BSL sweeps</div>
    </div>
    <div class="ag" id="ag-entry">
      <div class="ag-name">&#127919; Entry Agent (8 SMC Setups)</div>
      <div class="ag-stat" id="ae-stat">Analyzing entry conditions...</div>
      <div class="ag-sub" id="ae-sub">Adaptive thresholds / P&L-weighted</div>
    </div>
    <div class="ag" id="ag-risk">
      <div class="ag-name">&#128737; Risk Agent</div>
      <div class="ag-stat" id="ar-stat">SL/TP management active</div>
      <div class="ag-sub" id="ar-sub">ATR-based stops | min R:R 1.5</div>
    </div>
    <div class="ag" id="ag-monitor">
      <div class="ag-name">&#128065; Monitor (Trailing SL)</div>
      <div class="ag-stat" id="amo-stat">Peak-Lock trailing ready</div>
      <div class="ag-sub" id="amo-sub">Activates at profit ≥ $0.01</div>
    </div>
    <div class="ag" id="ag-learn">
      <div class="ag-name">&#128218; Learning Engine</div>
      <div class="ag-stat" id="ale-stat">P&L-weighted threshold adaptation</div>
      <div class="ag-sub" id="ale-sub">Per-setup tracking | gradient updates</div>
    </div>
    <div class="ag" id="ag-train">
      <div class="ag-name">&#128260; Adaptive Trainer</div>
      <div class="ag-stat" id="atr-stat">Online fine-tuning — buffer: 0</div>
      <div class="ag-sub" id="atr-sub">Keras buffer 128 · thresholds adapt every 5 trades</div>
    </div>
    <div class="ag" id="ag-confidence">
      <div class="ag-name">&#128200; Confidence Engine (Kelly)</div>
      <div class="ag-stat" id="ace-stat">Collecting trades...</div>
      <div class="ag-sub" id="ace-sub">kelly=1.00x | streak=0 | WR=—</div>
    </div>
    <div class="ag" id="ag-pivot">
      <div class="ag-name">&#127919; Pivot Engine (Daily)</div>
      <div class="ag-stat" id="apv-stat">Loading pivot levels...</div>
      <div class="ag-sub" id="apv-sub">PP=— | R1=— | S1=—</div>
    </div>
    <div class="ag" id="ag-vision">
      <div class="ag-name">&#128065; Vision Researcher</div>
      <div class="ag-stat" id="avs-stat">No vision rules loaded</div>
      <div class="ag-sub" id="avs-sub">Drop images in data/research/inbox/</div>
    </div>
    <!-- ── Evolution Panel ────────────────────────────────────────────────── -->
    <div class="ag active" id="ag-evolution">
      <div class="ag-name">&#129516; Genetic Evolver — Strategy Evolution</div>
      <div class="evolution-header" id="evo-header">
        <span class="evo-badge protected" id="evo-gen">Gen 0</span>
        <span class="evo-badge" id="evo-pop">Pop: 0</span>
        <span class="evo-badge protected" id="evo-prot">Protected: 0</span>
        <span class="evo-badge" id="evo-next">Next: 15</span>
      </div>
      <div class="evo-active-genome" id="evo-active">
        <div class="evo-row"><span class="evo-lbl">Active Genome:</span><span class="evo-val" id="evo-active-id">—</span></div>
        <div class="evo-row"><span class="evo-lbl">Fitness:</span><span class="evo-val gold" id="evo-fitness">0.000</span></div>
        <div class="evo-row"><span class="evo-lbl">Win Rate:</span><span class="evo-val green" id="evo-wr">0%</span></div>
        <div class="evo-row"><span class="evo-lbl">P&L:</span><span class="evo-val" id="evo-pnl">0.00</span></div>
      </div>
      <!-- Leaderboard -->
      <div class="evo-section-title">Top Genomes</div>
      <div class="evo-leaderboard" id="evo-leaderboard"></div>
      <!-- Fitness chart (mini canvas) -->
      <canvas id="evo-canvas" class="evo-canvas" width="260" height="60"></canvas>
      <!-- Consult box -->
      <div class="evo-consult-wrap">
        <input id="evo-question" class="evo-input" type="text" placeholder="Ask Claude about strategy..." />
        <button class="evo-btn" onclick="consultClaude()">Ask</button>
      </div>
      <div class="evo-answer" id="evo-answer"></div>
    </div>

    <!-- ── Market Oracle & Correlation Panel ────────────────────────────────── -->
    <div class="ag active" style="border-color:#6e40c9;">
      <div class="ag-name" style="color:#a371f7;">🔮 Market Oracle — تنبؤات الاتجاه</div>
      <div class="evo-row"><span class="evo-lbl">أدق عملة:</span><span class="evo-val" id="oracle-acc-best" style="color:#a371f7;">—</span></div>
      <div style="font-size:10px;color:#8b949e;margin:4px 0 2px;">آخر التنبؤات (UP/DOWN/NEUTRAL):</div>
      <div id="oracle-pred-list"></div>
      <div style="font-size:10px;color:#8b949e;margin:6px 0 2px;">ارتباطات العملات:</div>
      <div id="oracle-corr-list"></div>
    </div>

    <!-- ── Agent Discussion Log ─────────────────────────────────────────────── -->
    <div class="ag active" id="ag-discussion">
      <div class="ag-name">&#129302; Agent Discussion (Real-time)</div>
      <div class="evo-disc-list" id="evo-disc-list"></div>
    </div>

    <div class="ag active" id="ag-agent-trace">
      <div class="ag-name">&#9881; Agent Trace</div>
      <div class="ag-stat">Live output from working agents</div>
      <div class="agent-trace-list" id="agent-trace-list"></div>
    </div>

    <div id="pos-wrap">
      <div class="pos-hdr">&#128200; Open Positions</div>
      <div id="pos-list"><span style="color:var(--muted)">No open positions</span></div>
    </div>
  </div>
</div>

<div id="logbar">
  <table>
    <thead><tr>
      <th>Time</th><th>Action</th><th>Symbol</th><th>Price</th>
      <th>SL</th><th>TP</th><th>Mode</th><th>Reason</th>
    </tr></thead>
    <tbody id="log-body"></tbody>
  </table>
</div>

<script>
// ── Chart ────────────────────────────────────────────────────────────────────
const chartEl = document.getElementById('chart');
const chart = LightweightCharts.createChart(chartEl, {
  layout:{background:{color:'#0d1117'},textColor:'#c9d1d9'},
  grid:{vertLines:{color:'#161b22'},horzLines:{color:'#161b22'}},
  crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
  rightPriceScale:{borderColor:'#21262d'},
  timeScale:{borderColor:'#21262d',timeVisible:true,secondsVisible:false},
  width:chartEl.clientWidth,
  height:chartEl.clientHeight||400,
});

const candles = chart.addCandlestickSeries({
  upColor:'#26a69a',downColor:'#ef5350',
  borderVisible:false,
  wickUpColor:'#26a69a',wickDownColor:'#ef5350',
});

let markers = [];
let slPriceLine = null, tpPriceLine = null, bePriceLine = null;
let pivotLines = [];
let obLines    = [];   // OB + FVG price lines
let liqLines   = [];   // EQH/EQL + BSL/SSL target lines
let activeSymbol = 'XAUUSDm';
const LEARN_UPDATE_EVERY = 5;   // matches --threshold-update-every default (Phase 4)
let symbolList = [];
let currentTradingViewSymbol = '';
const TV_SYMBOLS = {
  XAUUSDm:'OANDA:XAUUSD',
  XAGUSDm:'OANDA:XAGUSD',
  BTCUSDm:'BINANCE:BTCUSDT',
  ETHUSDm:'BINANCE:ETHUSDT',
  EURUSDm:'FX:EURUSD',
  GBPUSDm:'FX:GBPUSD',
  USDJPYm:'FX:USDJPY',
  USOILm:'TVC:USOIL',
  UKOILm:'TVC:UKOIL',
};

function tvSymbol(sym){
  if(TV_SYMBOLS[sym]) return TV_SYMBOLS[sym];
  const clean = String(sym||'').replace(/m$/,'');
  if(/^[A-Z]{6}$/.test(clean)) return `FX:${clean}`;
  return clean || 'OANDA:XAUUSD';
}

function renderTradingView(sym){
  const mapped = tvSymbol(sym);
  if(mapped === currentTradingViewSymbol) return;
  currentTradingViewSymbol = mapped;
  const host = document.getElementById('tv-chart');
  const badge = document.getElementById('tv-badge');
  if(!host) return;
  badge.textContent = `TradingView ${mapped} | FRIDAY symbol ${sym}`;
  host.innerHTML = '';
  const container = document.createElement('div');
  container.className = 'tradingview-widget-container';
  container.style.cssText = 'height:100%;width:100%;';
  const widget = document.createElement('div');
  widget.className = 'tradingview-widget-container__widget';
  widget.style.cssText = 'height:100%;width:100%;';
  const script = document.createElement('script');
  script.type = 'text/javascript';
  script.async = true;
  script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
  script.innerHTML = JSON.stringify({
    autosize: true,
    symbol: mapped,
    interval: '1',
    timezone: 'Etc/UTC',
    theme: 'dark',
    style: '1',
    locale: 'en',
    backgroundColor: 'rgba(13, 17, 23, 1)',
    gridColor: 'rgba(33, 38, 45, 0.7)',
    withdateranges: true,
    hide_side_toolbar: false,
    allow_symbol_change: true,
    save_image: false,
    studies: ['MASimple@tv-basicstudies','ROC@tv-basicstudies','StochasticRSI@tv-basicstudies'],
    show_popup_button: true,
    popup_width: '1100',
    popup_height: '700',
    calendar: false,
    support_host: 'https://www.tradingview.com'
  });
  container.appendChild(widget);
  container.appendChild(script);
  host.appendChild(container);
  traceAgent('TradingView', `Loaded ${mapped} for ${sym}`, 'active');
}

function fmt(v, digits=2){
  if(v===undefined || v===null || Number.isNaN(Number(v))) return '—';
  const n=Number(v);
  if(Math.abs(n)>=100) return n.toFixed(2);
  if(Math.abs(n)>=10) return n.toFixed(3);
  if(Math.abs(n)>=1) return n.toFixed(5);
  return n.toFixed(digits+3);
}

function flagValue(v){
  if(v===true) return 'ON';
  if(v===false || v===undefined || v===null) return '—';
  if(typeof v === 'number'){
    if(Math.abs(v) <= 0) return '—';
    if(Number.isInteger(v) && Math.abs(v) <= 20) return String(v);
    return fmt(v,2);
  }
  return String(v);
}

function renderSmcSnapshot(d){
  const smc = d.smc || {};
  const pv = d.pivot || {};
  const rows = [
    ['BOS ↑', smc.bos_up, 'bull'],
    ['BOS ↓', smc.bos_down, 'bear'],
    ['CHOCH ↑', smc.choch_up, 'bull'],
    ['CHOCH ↓', smc.choch_down, 'bear'],
    ['FVG ↑', smc.bullish_fvg || smc.ifvg_bull, 'bull'],
    ['FVG ↓', smc.bearish_fvg || smc.ifvg_bear, 'bear'],
    ['OB ↑', smc.in_bullish_ob, 'bull'],
    ['OB ↓', smc.in_bearish_ob, 'bear'],
    ['Demand', smc.demand_zone, 'bull'],
    ['Supply', smc.supply_zone, 'bear'],
    ['BSL sweep', smc.buy_side_liquidity_sweep, 'bear'],
    ['SSL sweep', smc.sell_side_liquidity_sweep, 'bull'],
    ['Buy score', smc.smc_buy_score, 'bull'],
    ['Sell score', smc.smc_sell_score, 'bear'],
    ['Bias', smc.smc_bias, Number(smc.smc_bias||0)>0?'bull':Number(smc.smc_bias||0)<0?'bear':'neutral'],
    ['Trend', smc.trend, Number(smc.trend||0)>0?'bull':Number(smc.trend||0)<0?'bear':'neutral'],
    ['ATR', smc.atr, 'neutral'],
    ['RSI', smc.rsi, Number(smc.rsi||50)>55?'bull':Number(smc.rsi||50)<45?'bear':'neutral'],
    ['ADX', smc.adx, 'neutral'],
    ['MFI', smc.mfi, Number(smc.mfi||50)>55?'bull':Number(smc.mfi||50)<45?'bear':'neutral'],
    ['Pivot zone', pv.pivot_zone || 'neutral', pv.pivot_zone==='support'?'bull':pv.pivot_zone==='resistance'?'bear':'neutral'],
    ['Near pivot', (pv.near_levels||[]).join(',') || pv.nearest_pivot || '—', 'neutral'],
  ];
  const grid = document.getElementById('smc-snapshot-grid');
  if(!grid) return;
  grid.innerHTML = rows.map(([label,value,tone])=>{
    const on = value && value !== 'neutral' && value !== '—' && value !== 0;
    return `<div class="smc-cell ${on?'on':''} ${tone}"><span>${label}</span><b>${flagValue(value)}</b></div>`;
  }).join('');
  document.getElementById('smc-snapshot-head').textContent =
    `${d.symbol || activeSymbol} | ${d.action || 'HOLD'} | ${d.reason || 'waiting'}`;
  const box = document.getElementById('ag-smc-snapshot');
  const bias = Number(smc.smc_bias || 0);
  box.className = 'ag ' + (bias>0?'bullish':bias<0?'bearish':'active');
}

function traceAgent(name, message, tone='active'){
  const list = document.getElementById('agent-trace-list');
  if(!list) return;
  const item = document.createElement('div');
  item.className = `agent-trace-item ${tone}`;
  item.innerHTML = `<div class="agent-trace-head"><span>${name}</span><span>${new Date().toLocaleTimeString()}</span></div><div class="agent-trace-msg">${String(message||'').slice(0,140)}</div>`;
  list.insertBefore(item, list.firstChild);
  while(list.children.length > 18) list.removeChild(list.lastChild);
}

renderTradingView(activeSymbol);
renderSmcSnapshot({symbol:activeSymbol, action:'HOLD', reason:'waiting for SMC data', smc:{}, pivot:{}});

// resize
const ro = new ResizeObserver(()=>{
  chart.applyOptions({width:chartEl.clientWidth,height:chartEl.clientHeight});
});
ro.observe(chartEl);

// ── SSE ──────────────────────────────────────────────────────────────────────
let es = null;
function connect(){
  es = new EventSource('/events');
  es.onopen = ()=>{ setConn(true); };
  es.onerror = ()=>{ setConn(false); es.close(); setTimeout(connect,3000); };
  es.addEventListener('state',      e=>onState(JSON.parse(e.data)));
  es.addEventListener('decision',   e=>onDecision(JSON.parse(e.data)));
  es.addEventListener('trade',      e=>onTrade(JSON.parse(e.data)));
  es.addEventListener('positions',  e=>onPositions(JSON.parse(e.data).positions));
  es.addEventListener('candles',        e=>{ const d=JSON.parse(e.data); if(!d.symbol||d.symbol===activeSymbol) onCandles(d.candles); });
  es.addEventListener('candle_update',  e=>{ const d=JSON.parse(e.data); if(!d.symbol||d.symbol===activeSymbol) candles.update(d); });
  es.addEventListener('sl_moved',       e=>onSlMoved(JSON.parse(e.data)));
  es.addEventListener('confidence',     e=>onConfidence(JSON.parse(e.data)));
  es.addEventListener('pivots',         e=>onPivots(JSON.parse(e.data)));
  es.addEventListener('vision',         e=>onVision(JSON.parse(e.data)));
  es.addEventListener('symbol_states',  e=>onSymbolStates(JSON.parse(e.data)));
  es.addEventListener('learning',       e=>onLearning(JSON.parse(e.data)));
  es.addEventListener('agent_market',   e=>onAgentMarket(JSON.parse(e.data)));
  es.addEventListener('agent_liquidity',e=>onAgentLiquidity(JSON.parse(e.data)));
  es.addEventListener('agent_entry',    e=>onAgentEntry(JSON.parse(e.data)));
  es.addEventListener('agent_risk',       e=>onAgentRisk(JSON.parse(e.data)));
  es.addEventListener('genome_update',       e=>onGenomeUpdate(JSON.parse(e.data)));
  es.addEventListener('evolution_cycle',     e=>onEvolutionCycle(JSON.parse(e.data)));
  es.addEventListener('genome_born',         e=>onGenomeBorn(JSON.parse(e.data)));
  es.addEventListener('agent_discussion',    e=>onAgentDiscussion(JSON.parse(e.data)));
  es.addEventListener('oracle_prediction',   e=>onOraclePrediction(JSON.parse(e.data)));
  es.addEventListener('oracle_result',       e=>onOracleResult(JSON.parse(e.data)));
  es.addEventListener('oracle_stats',        e=>onOracleStats(JSON.parse(e.data)));
  es.addEventListener('genome_award',        e=>onGenomeAward(JSON.parse(e.data)));
  es.addEventListener('heartbeat',()=>{});
}
connect();

// ── Evolution handlers ────────────────────────────────────────────────────────
let _evoFitnessHistory = [];

function onGenomeUpdate(d){
  const $ = id => document.getElementById(id);
  $('evo-gen').textContent  = `Gen ${d.generation||0}`;
  $('evo-pop').textContent  = `Pop: ${d.population||0}`;
  $('evo-prot').textContent = `Protected: ${d.protected||0}`;
  $('evo-next').textContent = `Next evolve: ${d.trades_to_evolve||0} trades`;
  $('evo-active-id').textContent = (d.active_id||'—').slice(0,8);
  const fit = d.active_fitness||0;
  $('evo-fitness').textContent = fit.toFixed(4);
  $('evo-fitness').className = 'evo-val ' + (fit>0.6?'gold':fit>0.4?'green':'');
  const wr = (d.active_wr||0)*100;
  $('evo-wr').textContent = wr.toFixed(1)+'%';
  $('evo-wr').className = 'evo-val ' + (wr>=55?'green':wr>0?'':'red');
  const pnl = d.active_pnl||0;
  $('evo-pnl').textContent = (pnl>=0?'+':'')+pnl.toFixed(2);
  $('evo-pnl').className = 'evo-val '+(pnl>=0?'green':'red');

  // Update fitness history for canvas
  _evoFitnessHistory.push(fit);
  if(_evoFitnessHistory.length > 80) _evoFitnessHistory.shift();
  drawEvoCanvas();
}

function onEvolutionCycle(d){
  onGenomeUpdate(d);
  if(d.leaderboard) renderLeaderboard(d.leaderboard);
  traceAgent('GeneticEvolver', `Gen ${d.generation} — ${d.new_children?.length||0} new genomes | protected=${d.protected}`, 'active');
}

function onGenomeBorn(d){
  traceAgent('GenomeBorn', `New genome ${(d.id||'').slice(0,8)} — ${d.source||''} | note: ${(d.advisor_note||d.dna?.note||'').slice(0,60)}`, 'bullish');
}

function onAgentDiscussion(d){
  const list = document.getElementById('evo-disc-list');
  if(!list) return;
  const item = document.createElement('div');
  item.className = 'evo-disc-item';
  item.innerHTML = `<div class="evo-disc-agent">${d.agent||'Agent'} <small style="color:var(--muted)">${new Date().toLocaleTimeString()}</small></div><div class="evo-disc-msg">${String(d.message||'').slice(0,180)}</div>`;
  list.insertBefore(item, list.firstChild);
  while(list.children.length > 30) list.removeChild(list.lastChild);
}

function renderLeaderboard(items){
  const el = document.getElementById('evo-leaderboard');
  if(!el) return;
  el.innerHTML = (items||[]).map(g=>{
    const cls = g.is_active?'evo-active-item':g.is_protected?'evo-protected-item':'';
    const barW = Math.round((g.fitness||0)*100);
    const pnl = g.total_pnl||0;
    const pnlStr = (pnl>=0?'+':'')+pnl.toFixed(1);
    return `<div class="evo-item ${cls}">
      <span class="evo-gen-badge">G${g.gen} ${g.is_protected?'🔒':g.is_active?'★':''}</span>
      <span title="${g.id}">${(g.id||'').slice(0,8)} <span style="color:var(--muted)">WR:${((g.win_rate||0)*100).toFixed(0)}% PF:${(g.profit_factor||0).toFixed(1)} T:${g.trades||0}</span></span>
      <div class="evo-fitness-bar" style="width:${barW}px"></div>
      <span style="color:${pnl>=0?'var(--green)':'var(--red)'}">${pnlStr}</span>
    </div>`;
  }).join('');
}

function drawEvoCanvas(){
  const canvas = document.getElementById('evo-canvas');
  if(!canvas||!_evoFitnessHistory.length) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0,0,w,h);
  ctx.fillStyle='#0d1117';
  ctx.fillRect(0,0,w,h);
  const pts = _evoFitnessHistory;
  const max = Math.max(...pts, 0.01);
  ctx.strokeStyle='#f0a500';
  ctx.lineWidth=1.5;
  ctx.beginPath();
  pts.forEach((v,i)=>{
    const x = (i/(pts.length-1||1))*w;
    const y = h - (v/max)*(h-6)-3;
    i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
  });
  ctx.stroke();
  // Label latest value
  ctx.fillStyle='#f0a500';
  ctx.font='9px Courier New';
  ctx.fillText('Fitness: '+pts[pts.length-1].toFixed(4), 4, 11);
}

async function consultClaude(){
  const q = document.getElementById('evo-question').value.trim();
  if(!q) return;
  const ans = document.getElementById('evo-answer');
  ans.style.display='block';
  ans.textContent='Asking Claude...';
  try{
    const r = await fetch('/api/consult',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({question:q})
    });
    const d = await r.json();
    ans.textContent = d.answer||'No response.';
  } catch(e){
    ans.textContent = 'Error: '+e.message;
  }
}

// Load initial evolution state
fetch('/api/evolution').then(r=>r.json()).then(d=>{
  if(d && d.generation !== undefined){
    onGenomeUpdate(d);
    if(d.leaderboard) renderLeaderboard(d.leaderboard);
    if(d.discussion) d.discussion.forEach(m=>onAgentDiscussion(m));
  }
});

function setConn(ok){
  const el=document.getElementById('conn');
  el.textContent = ok ? '● CONNECTED' : '● DISCONNECTED';
  el.style.color = ok ? 'var(--green)' : 'var(--red)';
}

// ── Event handlers ────────────────────────────────────────────────────────────
function onState(s){
  if(s.account){
    const a=s.account;
    document.getElementById('t-bal').textContent = a.balance ? `${a.balance} ${a.currency||'USD'}` : '—';
    document.getElementById('t-eq').textContent  = a.equity  ? `${a.equity}`  : '—';
  }
  if(s.stats){
    document.getElementById('t-trades').textContent = s.stats.trades||0;
  }
  if(s.account_type){
    const b=document.getElementById('t-badge');
    b.textContent=s.account_type;
    b.className='badge '+s.account_type;
  }
  if(s.analysis_only !== undefined){
    window.analysisOnly = !!s.analysis_only;
    if(window.analysisOnly){
      document.getElementById('amo-stat').textContent = 'Analysis only';
      document.getElementById('amo-sub').textContent = 'Execution and trailing SL disabled in dashboard';
    }
  }
  if(s.active_symbol){
    const prev = activeSymbol;
    activeSymbol = s.active_symbol;
    document.getElementById('t-sym').textContent = s.active_symbol;
    if(prev !== activeSymbol) renderTradingView(activeSymbol);
  }
  if(s.symbols && !symbolList.length) symbolList = s.symbols;
  if(s.symbol_states) onSymbolStates(s.symbol_states);
  if(s.last_decision) onDecision(s.last_decision);
  if(s.open_positions) onPositions(s.open_positions);
  if(s.recent_trades){
    document.getElementById('log-body').innerHTML='';
    [...s.recent_trades].reverse().slice(0,30).forEach(t=>addLogRow(t));
  }
  if(s.agents) updateAgents(s.agents);
}

function onDecision(d){
  const dSym = d.symbol || activeSymbol;
  // Update symbol tab for this symbol
  const tab = document.querySelector(`.sym-tab[data-sym="${dSym}"]`);
  if(tab){
    const act = d.action||'HOLD';
    tab.className = `sym-tab ${act}` + (dSym===activeSymbol?' active-tab':'');
    tab.querySelector('.st-act').textContent = act;
    tab.querySelector('.st-price').textContent = d.close ? d.close.toFixed(2) : '—';
  }
  if(dSym !== activeSymbol) return;  // only update main chart UI for active symbol
  renderTradingView(dSym);
  const action = d.action||'HOLD';
  const prob   = d.probability||0;
  const smc    = d.smc||{};
  renderSmcSnapshot(d);
  traceAgent('AI Brain', `${dSym} ${action} prob=${(prob*100).toFixed(1)}% ${d.reason||''}`, action==='BUY'?'bullish':action==='SELL'?'bearish':'active');

  // decision box
  const el=document.getElementById('d-action');
  el.textContent=action; el.className=action;
  document.getElementById('d-reason').textContent = d.reason||'';
  document.getElementById('d-prob').textContent   = prob ? `${(prob*100).toFixed(1)}%` : '';

  // stats bar
  const sv=document.getElementById('s-action');
  sv.textContent=action; sv.className='val '+action;
  document.getElementById('s-prob').textContent    = prob ? `${(prob*100).toFixed(1)}%` : '—';
  document.getElementById('s-atr').textContent     = smc.atr  ? smc.atr.toFixed(2)  : '—';
  document.getElementById('s-rsi').textContent     = smc.rsi  ? smc.rsi.toFixed(1)  : '—';
  document.getElementById('s-buy-sc').textContent  = smc.smc_buy_score  !== undefined ? smc.smc_buy_score  : '—';
  document.getElementById('s-sell-sc').textContent = smc.smc_sell_score !== undefined ? smc.smc_sell_score : '—';
  document.getElementById('s-bias').textContent    = smc.smc_bias !== undefined ? smc.smc_bias.toFixed(2) : '—';

  // agent panels
  // Brain
  const bEl=document.getElementById('ag-brain');
  bEl.className='ag '+(action==='BUY'?'bullish':action==='SELL'?'bearish':'');
  document.getElementById('ab-stat').textContent = `Prob: ${(prob*100).toFixed(1)}%  →  ${action}`;

  // Market
  const bos_u=smc.bos_up||0, bos_d=smc.bos_down||0;
  const ch_u=smc.choch_up||0, ch_d=smc.choch_down||0;
  document.getElementById('am-stat').textContent = `BOS↑${bos_u} BOS↓${bos_d} | CHOCH↑${ch_u} CHOCH↓${ch_d}`;
  document.getElementById('am-sub').textContent  = `FVG Bull:${smc.bullish_fvg||0} Bear:${smc.bearish_fvg||0} | OB Bull:${smc.in_bullish_ob||0} Bear:${smc.in_bearish_ob||0}`;
  document.getElementById('ag-market').className = 'ag '+(bos_u||ch_u?'bullish':bos_d||ch_d?'bearish':'');

  // Liquidity
  const bsl=smc.buy_side_liquidity_sweep||0, ssl=smc.sell_side_liquidity_sweep||0;
  document.getElementById('al-stat').textContent = `BSL Sweep:${bsl>0?'✓ ACTIVE':'—'}  SSL Sweep:${ssl>0?'✓ ACTIVE':'—'}`;
  document.getElementById('al-sub').textContent  = `Buy Score:${(smc.smc_buy_score||0).toFixed(1)}  Sell Score:${(smc.smc_sell_score||0).toFixed(1)}  Bias:${(smc.smc_bias||0).toFixed(2)}`;
  document.getElementById('ag-liq').className = 'ag '+(bsl>0?'bullish':ssl>0?'bearish':'');

  // Entry
  document.getElementById('ae-stat').textContent = d.reason ? `Setup: ${d.reason}` : 'No valid setup';
  document.getElementById('ag-entry').className  = 'ag '+(action==='BUY'?'bullish':action==='SELL'?'bearish':'');

  // Risk
  document.getElementById('ar-stat').textContent = `ATR:${smc.atr?smc.atr.toFixed(2):'—'}  RSI:${smc.rsi?smc.rsi.toFixed(1):'—'}`;

  // Pivot card (updated with zone info from decision)
  if(d.pivot){
    const pv=d.pivot;
    const zone=pv.pivot_zone||'neutral';
    const near=(pv.near_levels||[]).join(',')||'—';
    const abovePP=pv.above_pp;
    document.getElementById('apv-stat').textContent=`Zone:${zone} | Near:${near} | ${abovePP?'↑ Above PP':'↓ Below PP'}`;
    document.getElementById('apv-sub').textContent=pv.pivot_reason||'no pivot boost';
    document.getElementById('ag-pivot').className='ag '+(zone==='support'?'bullish':zone==='resistance'?'bearish':'active');
  }

  // Vision card (updated when decision has vision boost info)
  if(d.vision_boost){
    const boost=(d.vision_boost*100).toFixed(1);
    const rules=(d.vision_rules||[]).join(', ');
    document.getElementById('avs-stat').textContent=`Bias boost: +${boost}% | Rules: ${rules}`;
    document.getElementById('ag-vision').className='ag active';
  }
}

function renderSymbolTabs(states){
  const bar = document.getElementById('symbar');
  if(!bar) return;
  symbolList = Object.keys(states);
  bar.innerHTML = '';
  symbolList.forEach(sym => {
    const s = states[sym] || {};
    const act = s.action || 'HOLD';
    const tab = document.createElement('div');
    tab.className = `sym-tab ${act}` + (sym === activeSymbol ? ' active-tab' : '');
    tab.dataset.sym = sym;
    tab.innerHTML = `<div>${sym}</div><div class="st-act">${act}</div><div class="st-price">${s.price ? s.price.toFixed(2) : '—'}</div>`;
    tab.onclick = () => switchSymbol(sym);
    bar.appendChild(tab);
  });
}

function switchSymbol(sym){
  activeSymbol = sym;
  document.getElementById('t-sym').textContent = sym;
  renderTradingView(sym);
  // Clear current chart data and fetch new symbol's candles
  candles.setData([]);
  markers = [];
  [pivotLines, obLines, liqLines].forEach(arr=>{
    arr.forEach(pl=>{try{candles.removePriceLine(pl);}catch(e){}});
  });
  pivotLines=[]; obLines=[]; liqLines=[];
  fetch(`/api/candles?symbol=${sym}`).then(r=>r.json()).then(d=>{
    if(d.candles&&d.candles.length){ candles.setData(d.candles); chart.timeScale().fitContent(); }
  });
  // Re-render tabs to update active-tab class
  const bar = document.getElementById('symbar');
  if(bar) bar.querySelectorAll('.sym-tab').forEach(t=>{
    const tSym = t.dataset.sym;
    const tAct = t.querySelector('.st-act') ? t.querySelector('.st-act').textContent : 'HOLD';
    t.className = `sym-tab ${tAct}` + (tSym === activeSymbol ? ' active-tab' : '');
  });
}

function onSymbolStates(states){
  renderSymbolTabs(states);
}

function onConfidence(cs){
  const kelly=(cs.kelly_mult!==undefined?cs.kelly_mult.toFixed(2):'1.00');
  const streak=cs.streak||0;
  const wr=cs.rolling&&cs.rolling.rolling_wr!==undefined?`${(cs.rolling.rolling_wr*100).toFixed(0)}%`:'—';
  const extra=cs.extra_positions||0;
  const wins=cs.wins||0;
  const losses=cs.losses||0;
  document.getElementById('ace-stat').textContent=`Kelly:${kelly}x | Extra:+${extra} | ${wins}W/${losses}L`;
  document.getElementById('ace-sub').textContent=`Streak:${streak>=0?'+':''}${streak} | WR:${wr}`;
  document.getElementById('ag-confidence').className='ag '+(streak>1?'bullish':streak<-1?'bearish':'active');
}

function onPivots(levels){
  if(levels.symbol && levels.symbol !== activeSymbol) return;
  // Remove old lines
  pivotLines.forEach(pl=>{ try{candles.removePriceLine(pl);}catch(e){} });
  pivotLines=[];
  if(!levels||!Object.keys(levels).length) return;

  const cfgs={
    PP: {color:'#f0a500',  lineWidth:1, lineStyle:LightweightCharts.LineStyle.Dotted,  title:'PP'},
    R1: {color:'#ef535099',lineWidth:1, lineStyle:LightweightCharts.LineStyle.Dashed,  title:'R1'},
    R2: {color:'#ef535066',lineWidth:1, lineStyle:LightweightCharts.LineStyle.Dashed,  title:'R2'},
    S1: {color:'#3fb95099',lineWidth:1, lineStyle:LightweightCharts.LineStyle.Dashed,  title:'S1'},
    S2: {color:'#3fb95066',lineWidth:1, lineStyle:LightweightCharts.LineStyle.Dashed,  title:'S2'},
    M1: {color:'#3fb95044',lineWidth:1, lineStyle:LightweightCharts.LineStyle.SparseDotted, title:'M1'},
    M2: {color:'#3fb95044',lineWidth:1, lineStyle:LightweightCharts.LineStyle.SparseDotted, title:'M2'},
    M3: {color:'#ef535044',lineWidth:1, lineStyle:LightweightCharts.LineStyle.SparseDotted, title:'M3'},
    M4: {color:'#ef535044',lineWidth:1, lineStyle:LightweightCharts.LineStyle.SparseDotted, title:'M4'},
  };
  for(const [k,price] of Object.entries(levels)){
    if(!cfgs[k]||!price) continue;
    const c=cfgs[k];
    try{
      const pl=candles.createPriceLine({price,color:c.color,lineWidth:c.lineWidth,lineStyle:c.lineStyle,axisLabelVisible:true,title:c.title});
      pivotLines.push(pl);
    }catch(e){}
  }
  // Update pivot card header
  document.getElementById('apv-sub').textContent=`PP:${levels.PP?.toFixed(2)||'—'} R1:${levels.R1?.toFixed(2)||'—'} R2:${levels.R2?.toFixed(2)||'—'} S1:${levels.S1?.toFixed(2)||'—'} S2:${levels.S2?.toFixed(2)||'—'}`;
  traceAgent('Pivot Engine', `${levels.symbol||activeSymbol} PP:${levels.PP?.toFixed(5)||'—'} R1:${levels.R1?.toFixed(5)||'—'} S1:${levels.S1?.toFixed(5)||'—'}`, 'active');
}

function onVision(v){
  const count=v.rule_count||0;
  const bias=v.latest_bias||'—';
  const instr=v.latest_instruction||'No instructions yet';
  document.getElementById('avs-stat').textContent=`${count} rules | Bias:${bias}`;
  document.getElementById('avs-sub').textContent=instr.substring(0,60);
  document.getElementById('ag-vision').className='ag '+(count>0?'active':'');
  traceAgent('Vision Researcher', `${count} rules | Bias:${bias}`, count>0?'active':'');
}

// ── Real agent handlers ───────────────────────────────────────────────────────
function onAgentMarket(m){
  if(m.symbol && m.symbol!==activeSymbol) return;
  const bU=m.bos_up?'✓':'—', bD=m.bos_down?'✓':'—';
  const cU=m.choch_up?'✓':'—', cD=m.choch_down?'✓':'—';
  document.getElementById('am-stat').textContent=`BOS↑${bU} BOS↓${bD} | CHOCH↑${cU} CHOCH↓${cD}`;
  document.getElementById('am-sub').textContent=
    `FVG Bull:${m.bullish_fvg?'✓':'—'} Bear:${m.bearish_fvg?'✓':'—'} | OB Bull:${m.in_bullish_ob?'✓':'—'} Bear:${m.in_bearish_ob?'✓':'—'} | RSI:${m.rsi?m.rsi.toFixed(0):'—'}`;
  document.getElementById('ag-market').className='ag '+(m.bos_up||m.choch_up?'bullish':m.bos_down||m.choch_down?'bearish':'active');
  traceAgent('Market Analyst', `BOS↑${bU} BOS↓${bD} CHOCH↑${cU} CHOCH↓${cD} RSI:${m.rsi?m.rsi.toFixed(0):'—'}`, m.bos_up||m.choch_up?'bullish':m.bos_down||m.choch_down?'bearish':'active');
  // Draw OB + FVG zones on chart
  obLines.forEach(l=>{try{candles.removePriceLine(l);}catch(e){}});
  obLines=[];
  if(m.in_bullish_ob&&m.bullish_ob_high){
    obLines.push(candles.createPriceLine({price:m.bullish_ob_high,color:'#3fb95088',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'OB↑H'}));
    if(m.bullish_ob_low) obLines.push(candles.createPriceLine({price:m.bullish_ob_low,color:'#3fb95088',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'OB↑L'}));
  }
  if(m.in_bearish_ob&&m.bearish_ob_high){
    obLines.push(candles.createPriceLine({price:m.bearish_ob_high,color:'#ef535088',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'OB↓H'}));
    if(m.bearish_ob_low) obLines.push(candles.createPriceLine({price:m.bearish_ob_low,color:'#ef535088',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'OB↓L'}));
  }
  if(m.fvg_mid) obLines.push(candles.createPriceLine({price:m.fvg_mid,color:'#58a6ff55',lineWidth:1,lineStyle:3,axisLabelVisible:true,title:'FVG'}));
}

function onAgentLiquidity(l){
  if(l.symbol && l.symbol!==activeSymbol) return;
  const bA=l.bsl_sweep_active, sA=l.ssl_sweep_active;
  document.getElementById('al-stat').textContent=
    `BSL:${bA?'★ SWEPT':'—'}  SSL:${sA?'★ SWEPT':'—'}`;
  const bT=l.bsl_target?l.bsl_target.toFixed(2):'—';
  const sT=l.ssl_target?l.ssl_target.toFixed(2):'—';
  document.getElementById('al-sub').textContent=`BSL Target:${bT}  |  SSL Target:${sT}`;
  document.getElementById('ag-liq').className='ag '+(sA?'bullish':bA?'bearish':'active');
  traceAgent('Liquidity Hunter', `BSL:${bA?'swept':'—'} SSL:${sA?'swept':'—'} targets ${bT}/${sT}`, sA?'bullish':bA?'bearish':'active');
  // Draw EQH/EQL + targets on chart
  liqLines.forEach(l2=>{try{candles.removePriceLine(l2);}catch(e){}});
  liqLines=[];
  (l.eqh_levels||[]).slice(0,3).forEach((v,i)=>{
    liqLines.push(candles.createPriceLine({price:v,color:'#f0a50066',lineWidth:1,lineStyle:3,axisLabelVisible:true,title:`EQH${i+1}`}));
  });
  (l.eql_levels||[]).slice(0,3).forEach((v,i)=>{
    liqLines.push(candles.createPriceLine({price:v,color:'#58a6ff66',lineWidth:1,lineStyle:3,axisLabelVisible:true,title:`EQL${i+1}`}));
  });
  if(l.bsl_target) liqLines.push(candles.createPriceLine({price:l.bsl_target,color:'#f0a500',lineWidth:1,lineStyle:1,axisLabelVisible:true,title:'BSL↑'}));
  if(l.ssl_target) liqLines.push(candles.createPriceLine({price:l.ssl_target,color:'#58a6ff',lineWidth:1,lineStyle:1,axisLabelVisible:true,title:'SSL↓'}));
}

function onAgentEntry(e){
  if(e.symbol && e.symbol!==activeSymbol) return;
  const side=e.side||'HOLD';
  const hasSetup=e.setup&&e.setup!=='no_setup';
  document.getElementById('ae-stat').textContent=hasSetup
    ?`▶ ${e.setup} | SMC:${e.smc_score} | Conf:${(e.confidence*100).toFixed(0)}%`
    :'No valid setup this bar';
  document.getElementById('ae-sub').textContent=
    `Buy≥${(e.buy_thr*100).toFixed(0)}% Sell≤${(e.sell_thr*100).toFixed(0)}% | Blocked:${(e.cooldowns||[]).join(',')||'none'}`;
  document.getElementById('ag-entry').className='ag '+(side==='BUY'?'bullish':side==='SELL'?'bearish':'');
  traceAgent('Entry Agent', hasSetup ? `${side} ${e.setup} SMC:${e.smc_score} Conf:${(e.confidence*100).toFixed(0)}%` : 'No setup on active bar', side==='BUY'?'bullish':side==='SELL'?'bearish':'active');
  // Best setup performance in Learning card
  const perf=e.perf||{};
  const entries=Object.entries(perf);
  if(entries.length){
    const best=entries.sort((a,b)=>b[1].wr-a[1].wr)[0];
    document.getElementById('ale-stat').textContent=
      `Best: ${best[0]} WR:${(best[1].wr*100).toFixed(0)}% (${best[1].trades}t avg:${best[1].avg_pts.toFixed(1)}pts)`;
    const worst=entries.sort((a,b)=>a[1].wr-b[1].wr)[0];
    document.getElementById('ale-sub').textContent=`Worst: ${worst[0]} WR:${(worst[1].wr*100).toFixed(0)}%`;
  }
}

function onLearning(e){
  if(e.symbol && e.symbol!==activeSymbol) return;
  const t = e.thresholds || {};
  const buy  = (t.buy_threshold  != null) ? (t.buy_threshold *100).toFixed(0) : '—';
  const sell = (t.sell_threshold != null) ? (t.sell_threshold*100).toFixed(0) : '—';
  const n    = (e.trades_since_last_update != null) ? e.trades_since_last_update : 0;
  document.getElementById('ale-stat').textContent =
    `Buy≥${buy}% Sell≤${sell}% | adapt in ${n}/${LEARN_UPDATE_EVERY}`;
  const pnl = (e.last_p_and_l || []);
  const cells = pnl.length
    ? pnl.map(p => (p>=0?'+':'')+Number(p).toFixed(1)).join('  ')
    : 'no closed trades yet';
  document.getElementById('ale-sub').textContent = `Last 5 P&L: ${cells}`;
  document.getElementById('ag-learn').className =
    'ag '+(pnl.length && pnl[pnl.length-1]>=0 ? 'bullish' : pnl.length ? 'bearish' : '');
}

function onAgentRisk(r){
  if(r.symbol && r.symbol!==activeSymbol) return;
  document.getElementById('ar-stat').textContent=
    `SL:${r.sl?r.sl.toFixed(2):'—'}  TP:${r.tp?r.tp.toFixed(2):'—'}  R:R ${r.rr?r.rr.toFixed(2):'—'}`;
  document.getElementById('ar-sub').textContent=
    `Risk:${r.risk_pts?r.risk_pts.toFixed(1):'—'}pts  Reward:${r.reward_pts?r.reward_pts.toFixed(1):'—'}pts`;
  document.getElementById('ag-risk').className='ag active';
  traceAgent('Risk Agent', `SL:${r.sl?r.sl.toFixed(5):'—'} TP:${r.tp?r.tp.toFixed(5):'—'} RR:${r.rr?r.rr.toFixed(2):'—'}`, 'active');
}

function onTrade(t){
  if(!t||!t.price) return;
  // Add marker to chart
  if(t.action==='BUY'||t.action==='SELL'){
    const ts = Math.floor(new Date(t.timestamp).getTime()/1000/60)*60;
    markers.push({
      time:ts,
      position: t.action==='BUY'?'belowBar':'aboveBar',
      color:     t.action==='BUY'?'#26a69a':'#ef5350',
      shape:     t.action==='BUY'?'arrowUp':'arrowDown',
      text:      `${t.action} ${t.price.toFixed(2)}`,
      size:1.5,
    });
    markers.sort((a,b)=>a.time-b.time);
    candles.setMarkers(markers);

    // Draw SL/TP price lines
    if(t.sl) drawSLTP(t.sl, t.tp);
  }
  addLogRow(t);
}

function onPositions(positions){
  const list = document.getElementById('pos-list');
  if(!positions||!positions.length){
    list.innerHTML='<span style="color:var(--muted)">No open positions</span>';
    clearSLTPLines();
    return;
  }
  list.innerHTML='';
  positions.forEach(p=>{
    const pnlCls = p.profit>=0?'pos':'neg';
    const div=document.createElement('div');
    div.className=`pos-item ${p.side}`;
    div.innerHTML=`
      <div class="pos-row">
        <span><b>${p.side}</b> ${p.symbol} #${p.ticket}</span>
        <span class="pnl ${pnlCls}">${p.profit>=0?'+':''}${p.profit.toFixed(2)}</span>
      </div>
      <div class="pos-sub">Entry:${p.entry.toFixed(2)} SL:${p.sl?p.sl.toFixed(2):'—'} TP:${p.tp?p.tp.toFixed(2):'—'}</div>
    `;
    list.appendChild(div);
    drawSLTP(p.sl, p.tp);
  });
}

function onCandles(data){
  if(!data||!data.length) return;
  candles.setData(data);
  chart.timeScale().scrollToPosition(5, false);
}

function onSlMoved(e){
  document.getElementById('amo-stat').textContent = `Trailing SL → ${e.new_sl.toFixed(2)} (${e.symbol} ${e.side})`;
  const cnt=parseInt(document.getElementById('s-trail').textContent||'0')+1;
  document.getElementById('s-trail').textContent=cnt;
  // update SL line
  if(slPriceLine) candles.removePriceLine(slPriceLine);
  slPriceLine = candles.createPriceLine({
    price:e.new_sl, color:'#ef5350', lineWidth:1,
    lineStyle:LightweightCharts.LineStyle.Dashed,
    axisLabelVisible:true, title:'SL (trailing)',
  });
}

function updateAgents(ag){
  if(window.analysisOnly){
    document.getElementById('amo-stat').textContent = 'Analysis only';
    document.getElementById('amo-sub').textContent = 'Execution and trailing SL disabled in dashboard';
    document.getElementById('s-trail').textContent = '0';
  } else
  if(ag.monitor){
    const cnt=ag.monitor.trailing_count||0;
    document.getElementById('amo-stat').textContent = cnt>0 ? `Trailing active — ${cnt} moves` : 'Peak-Lock trailing ready';
    document.getElementById('s-trail').textContent = cnt;
  }
  if(ag.trainer){
    const buf=ag.trainer.buffer_size||0;
    const rc=ag.trainer.retrain_count||0;
    document.getElementById('atr-stat').textContent = `Buffer:${buf}/128 | Retrains:${rc}`;
  }
  if(ag.confidence) onConfidence(ag.confidence);
}

// ── Chart helpers ─────────────────────────────────────────────────────────────
function drawSLTP(sl, tp){
  if(slPriceLine){ try{candles.removePriceLine(slPriceLine);}catch(e){} slPriceLine=null; }
  if(tpPriceLine){ try{candles.removePriceLine(tpPriceLine);}catch(e){} tpPriceLine=null; }
  if(sl&&sl>0){
    slPriceLine=candles.createPriceLine({
      price:sl,color:'#ef5350',lineWidth:1,
      lineStyle:LightweightCharts.LineStyle.Dashed,
      axisLabelVisible:true,title:'SL',
    });
  }
  if(tp&&tp>0){
    tpPriceLine=candles.createPriceLine({
      price:tp,color:'#3fb950',lineWidth:1,
      lineStyle:LightweightCharts.LineStyle.Dashed,
      axisLabelVisible:true,title:'TP',
    });
  }
}

function clearSLTPLines(){
  if(slPriceLine){ try{candles.removePriceLine(slPriceLine);}catch(e){} slPriceLine=null; }
  if(tpPriceLine){ try{candles.removePriceLine(tpPriceLine);}catch(e){} tpPriceLine=null; }
}

// ── Trade log ─────────────────────────────────────────────────────────────────
function addLogRow(t){
  const tbody=document.getElementById('log-body');
  const tr=document.createElement('tr');
  const time=t.timestamp?new Date(t.timestamp).toLocaleTimeString():'';
  const action=t.action||'—';
  const cls=t.executed===false?'BLOCKED':action;
  tr.className=cls;
  tr.innerHTML=`
    <td>${time}</td>
    <td>${action}</td>
    <td>${t.symbol||'—'}</td>
    <td>${t.price?t.price.toFixed(2):'—'}</td>
    <td>${t.sl?t.sl.toFixed(2):'—'}</td>
    <td>${t.tp?t.tp.toFixed(2):'—'}</td>
    <td>${(t.mode||'').substring(0,10)}</td>
    <td>${(t.reason||'').substring(0,25)}</td>
  `;
  tbody.insertBefore(tr, tbody.firstChild);
  while(tbody.rows.length>60) tbody.deleteRow(-1);
}

// ── Clock ─────────────────────────────────────────────────────────────────────
setInterval(()=>{
  document.getElementById('clock').textContent=new Date().toLocaleTimeString();
},1000);

// ── Initial load ──────────────────────────────────────────────────────────────
// ── Market Oracle & Awards handlers ──────────────────────────────────────────
const _oracleDir = {UP:'🟢↑',DOWN:'🔴↓',NEUTRAL:'⚪─'};
let _oraclePreds = [];
let _corrPairs   = [];

function onOraclePrediction(p){
  _oraclePreds.unshift(p);
  if(_oraclePreds.length>20) _oraclePreds.pop();
  renderOraclePanel();
  const dir = _oracleDir[p.direction] || '—';
  traceAgent('MarketOracle', `${p.symbol} ${dir} conf=${(p.confidence*100).toFixed(0)}% | ${(p.supporting||[]).join(', ')}`,
    p.direction==='UP'?'bullish':p.direction==='DOWN'?'bearish':'active');
}

function onOracleResult(r){
  const emoji = r.emoji || (r.correct?'✅':'❌');
  traceAgent('OracleVerify', `${emoji} ${r.symbol} ${r.direction} | move=${r.move_pct>0?'+':''}${r.move_pct}%`, r.correct?'bullish':'bearish');
  renderOraclePanel();
}

function onOracleStats(s){
  const acc = s.accuracy||{};
  const corr = s.correlations||[];
  _corrPairs = corr;
  const symList = Object.keys(acc);
  if(symList.length){
    const best = symList.reduce((a,b)=>(acc[a]?.accuracy||0)>(acc[b]?.accuracy||0)?a:b);
    const el = document.getElementById('oracle-acc-best');
    if(el) el.textContent = `${best} ${(acc[best].accuracy*100).toFixed(0)}% (${acc[best].correct}/${acc[best].total})`;
  }
  renderCorrPanel(corr);
}

function onGenomeAward(a){
  const el = document.getElementById('evo-active-id');
  if(el) el.textContent = `${a.medal_emoji} ${a.name || a.genome_id}`;
  // Show toast
  const toast = document.createElement('div');
  toast.style.cssText='position:fixed;top:70px;right:24px;z-index:9999;background:#1e3a2f;border:1px solid #3fb950;color:#3fb950;padding:12px 20px;border-radius:8px;font-size:13px;max-width:320px;';
  toast.textContent = `${a.medal_emoji} ${a.name} — ${a.medal_name}`;
  document.body.appendChild(toast);
  setTimeout(()=>toast.remove(), 6000);
  traceAgent('GenomeChronicler', `${a.medal_emoji} «${a.name}» — وسام ${a.medal_name}`, 'bullish');
}

function renderOraclePanel(){
  const el = document.getElementById('oracle-pred-list');
  if(!el) return;
  el.innerHTML = _oraclePreds.slice(0,8).map(p=>{
    const dir = _oracleDir[p.direction]||'—';
    const cls = p.direction==='UP'?'color:#3fb950':p.direction==='DOWN'?'color:#ef5350':'color:#8b949e';
    const resolved = p.resolved ? (p.correct?'✅':'❌') : '';
    return `<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:11px;">
      <span style="color:#8b949e">${p.symbol}</span>
      <span style="${cls}">${dir} ${(p.confidence*100).toFixed(0)}%</span>
      <span>${resolved}</span>
    </div>`;
  }).join('');
}

function renderCorrPanel(pairs){
  const el = document.getElementById('oracle-corr-list');
  if(!el) return;
  el.innerHTML = pairs.slice(0,6).map(r=>{
    const c = r.corr;
    const bar = `<span style="display:inline-block;width:${Math.abs(c)*40}px;height:6px;background:${c>0?'#3fb950':'#ef5350'};border-radius:3px;vertical-align:middle;"></span>`;
    return `<div style="display:flex;align-items:center;gap:6px;padding:2px 0;font-size:11px;">
      <span style="color:#8b949e;width:90px;overflow:hidden">${r.a.replace('m','')}↔${r.b.replace('m','')}</span>
      ${bar}
      <span style="color:${c>0?'#3fb950':'#ef5350'}">${c>0?'+':''}${c.toFixed(2)}</span>
    </div>`;
  }).join('');
}

// ── Genome + Evolution handlers ───────────────────────────────────────────────
function onGenomeUpdate(ev){
  const el = id => document.getElementById(id);
  if(el('evo-gen'))    el('evo-gen').textContent    = `Gen: ${ev.generation||0}`;
  if(el('evo-pop'))    el('evo-pop').textContent    = `Pop: ${ev.population||0}`;
  if(el('evo-prot'))   el('evo-prot').textContent   = `Protected: ${ev.protected||0}`;
  if(el('evo-next'))   el('evo-next').textContent   = `Next: ${ev.trades_to_evolve||15}`;
  if(el('evo-fitness'))el('evo-fitness').textContent= (ev.active_fitness||0).toFixed(4);
  if(el('evo-wr'))     el('evo-wr').textContent     = `${((ev.active_wr||0)*100).toFixed(0)}%`;
  if(el('evo-pnl'))    el('evo-pnl').textContent    = `$${(ev.active_pnl||0).toFixed(2)}`;
  const name   = ev.active_name  || ev.active_id || '—';
  const medals = ev.active_medals|| [];
  if(el('evo-active-id')) el('evo-active-id').textContent = `${medals.slice(-1)[0]||''} ${name}`.trim() || name;
  if(ev.leaderboard) renderLeaderboard(ev.leaderboard);
}

function onEvolutionCycle(ev){
  traceAgent('GeneticEvolver', `Gen ${ev.generation} — ${ev.new_genomes||0} new children, pop=${ev.population}`, 'active');
  if(ev.leaderboard) renderLeaderboard(ev.leaderboard);
}

function onGenomeBorn(ev){
  traceAgent('GeneticEvolver', `🧬 New genome born: ${ev.genome_id||''} gen=${ev.generation}`, 'bullish');
}

function onAgentDiscussion(ev){
  const list = document.getElementById('evo-disc-list');
  if(!list) return;
  const div = document.createElement('div');
  div.style.cssText = 'padding:3px 0;border-bottom:1px solid #21262d;font-size:11px;';
  const agColor = ev.agent && ev.agent.includes('Brain')   ? '#a371f7' :
                  ev.agent && ev.agent.includes('Risk')    ? '#ef5350'  :
                  ev.agent && ev.agent.includes('Oracle')  ? '#d2a8ff'  :
                  ev.agent && ev.agent.includes('Human')   ? '#f0a500'  :
                  ev.agent && ev.agent.includes('Chroni')  ? '#58a6ff'  : '#8b949e';
  div.innerHTML = `<span style="color:${agColor};font-weight:600">${ev.agent||'?'}</span>
    <span style="color:#8b949e;margin-left:6px;">${String(ev.message||'').slice(0,160)}</span>`;
  list.insertBefore(div, list.firstChild);
  while(list.children.length > 40) list.removeChild(list.lastChild);
  traceAgent(ev.agent||'Agent', ev.message||'', 'active');
}

function renderLeaderboard(board){
  const el = document.getElementById('evo-leaderboard');
  if(!el || !board) return;
  el.innerHTML = board.slice(0,6).map((g,i)=>{
    const medals  = (g.medals||[]).slice(-1)[0] || '';
    const name    = g.name && g.name !== '—' ? g.name : (g.id||'').slice(0,8);
    const isActive = g.is_active;
    const isProtected = g.is_protected;
    const wr = ((g.win_rate||0)*100).toFixed(0);
    const pf = (g.profit_factor||0).toFixed(2);
    const pnl = (g.total_pnl||0).toFixed(2);
    return `<div style="display:flex;align-items:center;gap:4px;padding:3px 4px;border-radius:4px;margin:2px 0;background:${isActive?'rgba(63,185,80,.1)':'transparent'};font-size:11px;">
      <span style="color:#8b949e;min-width:14px">${i+1}</span>
      <span style="flex:1;color:${isProtected?'#f0a500':isActive?'#3fb950':'#c9d1d9'};overflow:hidden;white-space:nowrap">${medals} ${name}</span>
      <span style="color:#3fb950;min-width:32px">WR:${wr}%</span>
      <span style="color:#58a6ff;min-width:28px">PF:${pf}</span>
      <span style="color:${pnl>=0?'#3fb950':'#ef5350'};min-width:40px">${pnl>=0?'+':''}$${pnl}</span>
    </div>`;
  }).join('');
}

fetch('/api/candles').then(r=>r.json()).then(d=>{
  if(d.candles&&d.candles.length){
    candles.setData(d.candles);
    chart.timeScale().fitContent();
  }
});
fetch('/api/state').then(r=>r.json()).then(s=>onState(s));
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="FRIDAY Web Dashboard")
    parser.add_argument("--profile",                default="scalping")
    parser.add_argument("--poll-seconds",           type=int,   default=30)
    parser.add_argument("--max-open-positions",     type=int,   default=2)
    parser.add_argument("--entry-cooldown-seconds", type=int,   default=60)
    parser.add_argument("--port",                   type=int,   default=PORT)
    parser.add_argument("--min-profit-trail",       type=float, default=0.01,
                        help="Move SL when position profit >= this value (USD)")
    parser.add_argument("--trail-points",           type=int,   default=10,
                        help="Keep SL this many points behind price")
    parser.add_argument("--symbols",                default="all",
                        help="Comma-separated list of symbols, or all/auto for every tradable MT5 symbol")
    parser.add_argument("--analysis-only",          action="store_true",
                        help="Run real agents and browser UI without sending broker orders")
    parser.add_argument("--threshold-update-every", type=int, default=5,
                        help="Adapt LearningEngine thresholds every N closed trades per symbol (default 5)")
    parser.add_argument("--threshold-halflife",     type=int, default=240,
                        help="Idle decay: halve learned-threshold distance-to-baseline every M elapsed bars (default 240)")
    args = parser.parse_args()

    print("=" * 60)
    print("⚡ FRIDAY WEB DASHBOARD")
    print("=" * 60)
    print(f"   Loading model:  {MODEL_PATH}")

    model, model_mode = _load_prediction_model()
    scaler = joblib.load(str(SCALER_PATH))
    brain  = TradingBrain(model=model, profile_name=args.profile)

    raw_gw = MT5Gateway()
    raw_gw.initialize()
    symbols = resolve_symbols(args.symbols, raw_gw.mt5)
    gw = _SafeGW(raw_gw)

    acct     = gw.account_snapshot()
    is_demo  = gw.is_demo_account(acct)
    acct_typ = "DEMO" if is_demo else "LIVE"

    print(f"   Account: {acct.get('login')} | {acct.get('server')}")
    print(f"   Type:    {acct_typ}")
    print(f"   Balance: {acct.get('balance')} {acct.get('currency','USD')}")

    _set("account", acct)
    _set("is_demo", is_demo)
    _set("account_type", acct_typ)
    _set("symbol", MT5_SYMBOL)
    _set("symbols", symbols)
    _set("active_symbol", symbols[0] if symbols else MT5_SYMBOL)
    _set("analysis_only", args.analysis_only)
    _set("model_mode", model_mode)
    if model_mode != "keras":
        _set("model_warning", "TensorFlow unavailable; using neutral probability fallback")

    log_file   = LOG_DIR / "auto_trades.jsonl"
    paper_exec = PaperExecutor()
    demo_exec  = DemoMT5Executor(gateway=gw)  # use safe wrapper — serialises MT5 calls

    # Load recent trades from log file
    if log_file.exists():
        try:
            lines = log_file.read_text(encoding="utf-8").strip().splitlines()
            recent = [json.loads(l) for l in lines[-50:]]
            _set("recent_trades", recent)
        except Exception:
            pass
    _sync_external_runtime_state(force=True)

    # Background threads
    trader = AutoTraderThread(
        gateway=gw, model=model, scaler=scaler, brain=brain,
        is_demo=is_demo, paper_exec=paper_exec, demo_exec=demo_exec,
        poll_seconds=args.poll_seconds,
        max_open_positions=args.max_open_positions,
        entry_cooldown_seconds=args.entry_cooldown_seconds,
        profile=args.profile, log_file=log_file,
        symbols=symbols,
        execution_enabled=not args.analysis_only,
        threshold_update_every=args.threshold_update_every,
        threshold_halflife=args.threshold_halflife,
    )

    trailing = None
    if not args.analysis_only:
        trailing = TrailingSLMonitor(
            gateway=gw, is_demo=is_demo,
            min_profit=args.min_profit_trail,
            trail_points=args.trail_points,
            interval=5,
        )

    candle_fetcher = CandleFetcher(gateway=gw, symbol=symbols[0] if symbols else MT5_SYMBOL, full_interval=60)

    trader.start()
    if trailing is not None:
        trailing.start()
    candle_fetcher.start()
    threading.Thread(target=_heartbeat_loop, daemon=True, name="heartbeat").start()

    # Start the autonomous self-evolving brain
    if trader.autonomous_brain is not None:
        trader.autonomous_brain.start()
        print("🧠 AutonomousBrain: ONLINE — Claude is watching and evolving autonomously")

    DashboardHandler.candle_fetcher = candle_fetcher
    DashboardHandler._evolver       = trader.evolver
    DashboardHandler._committee     = trader.committee
    DashboardHandler._trader        = trader

    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    server.daemon_threads = True

    print(f"\n🌐 Dashboard: http://127.0.0.1:{args.port}/")
    print(f"   Profile:      {args.profile} | Poll: {args.poll_seconds}s")
    if args.analysis_only:
        print("   Execution:    ANALYSIS ONLY (agents/UI active, broker orders disabled)")
        print("   Trailing SL:  disabled in analysis-only mode")
    else:
        print(f"   Trailing SL:  activates when profit >= ${args.min_profit_trail}")
        print(f"   Trail offset: {args.trail_points} points behind price")
    print("-" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
    finally:
        trader.stop()
        if trader.autonomous_brain is not None:
            trader.autonomous_brain.stop()
        if trailing is not None:
            trailing.stop()
        candle_fetcher.stop()
        raw_gw.shutdown()
        print("Goodbye.")


if __name__ == "__main__":
    main()
