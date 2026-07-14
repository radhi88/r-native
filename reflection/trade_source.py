"""trade_source.py - load realized FRIDAY trades for the reflection engine.

Primary source: the `trade_outcomes` list that friday_trade_outcome_learner.py
writes into friday_strategy_genes.json (it reads closed MT5 deals, demo-guarded).

This module is READ-ONLY on trade data. It never sends orders. It can optionally
ask the existing outcome learner to refresh from MT5 first, but that call is fully
guarded and a failure (e.g. MT5 not running) never breaks reflection.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent          # ...\MT5
GENES_FILE = ROOT / "friday_strategy_genes.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def refresh_from_mt5(hours_back: int = 720) -> tuple[bool, str]:
    """Best-effort: ask the existing outcome learner to scan closed MT5 deals.
    Returns (ok, message). Never raises."""
    try:
        import importlib.util
        learner_path = ROOT / "friday_trade_outcome_learner.py"
        if not learner_path.exists():
            return False, "friday_trade_outcome_learner.py not found"
        spec = importlib.util.spec_from_file_location("friday_trade_outcome_learner", learner_path)
        if spec is None or spec.loader is None:
            return False, "could not load outcome learner module"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # imports MetaTrader5 at module level
        learned = mod.scan_closed_deals(hours_back=hours_back)
        return True, f"outcome learner scanned MT5, learned {learned} new deal(s)"
    except Exception as exc:  # MT5 not installed / terminal closed / not demo
        return False, f"MT5 refresh skipped: {type(exc).__name__}: {exc}"


def _normalize(outcome: dict[str, Any]) -> dict[str, Any] | None:
    deal = outcome.get("deal") or {}
    ticket = str(outcome.get("ticket") or deal.get("ticket") or "").strip()
    if not ticket:
        return None
    try:
        profit = float(outcome.get("profit", deal.get("profit", 0.0)) or 0.0)
    except (TypeError, ValueError):
        profit = 0.0
    return {
        "ticket": ticket,
        "symbol": str(outcome.get("symbol") or deal.get("symbol") or ""),
        "side": str(deal.get("side") or ""),
        "profit": profit,
        "result": str(outcome.get("result") or ""),
        "family": str(outcome.get("family") or ""),
        "comment": str(deal.get("comment") or ""),
        "magic": int(deal.get("magic") or 0),
        "time_epoch": int(deal.get("time") or 0),
    }


def load_realized_trades(refresh: bool = False) -> tuple[list[dict[str, Any]], str]:
    """Return (sorted unique closed trades, source_note)."""
    note = ""
    if refresh:
        ok, msg = refresh_from_mt5()
        note = msg

    genes = _read_json(GENES_FILE, {})
    raw = genes.get("trade_outcomes") or []

    seen: set[str] = set()
    trades: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        t = _normalize(item)
        if t is None or t["ticket"] in seen:
            continue
        seen.add(t["ticket"])
        trades.append(t)

    trades.sort(key=lambda t: t["time_epoch"])
    return trades, note


def is_night_trade(time_epoch: int, start_utc: int, end_utc: int) -> bool:
    """True if the deal's UTC hour falls inside the blocked night window.
    Window wraps midnight when start_utc > end_utc (e.g. 22 -> 8)."""
    if not time_epoch:
        return False
    hour = datetime.fromtimestamp(time_epoch, tz=timezone.utc).hour
    if start_utc <= end_utc:
        return start_utc <= hour < end_utc
    return hour >= start_utc or hour < end_utc
