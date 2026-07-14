"""strategy_monitor.py — live evaluation + decision-log feed (Feature 4).

For each ACTIVE strategy, evaluate every configured pair on the strategy's
timeframe using signal_engine, and stream LogEntry lines (Pipflow style) into
strategy_store's ring/JSONL so the monitor UI can poll them. Does NOT place
real orders — execution stays behind the existing trade gate + user
confirmation / demo flag.

evaluate_strategy_once() is the unit the brain loop (or a manual /api call)
invokes; it is pure-ish (its only side effects are reading MT5 bars and
emitting log lines).
"""
from __future__ import annotations

from typing import Optional

from r_native.strategy_types import Strategy, TF_TO_MT5_NAME
from r_native import strategy_store as store
from r_native import signal_engine as sig


def _fetch_bars(symbol: str, tf: str, n: int = 160) -> list:
    try:
        import MetaTrader5 as mt5
    except Exception:
        return []
    try:
        if not mt5.initialize():
            mt5.initialize()
        tf_name = TF_TO_MT5_NAME.get(tf, "M15")
        tf_const = getattr(mt5, f"TIMEFRAME_{tf_name}", None)
        if tf_const is None:
            return []
        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, n)
        if rates is None:
            return []
        return [{"time": int(r["time"]), "open": float(r["open"]),
                 "high": float(r["high"]), "low": float(r["low"]),
                 "close": float(r["close"])} for r in rates]
    except Exception:
        return []


def evaluate_strategy_once(strategy: Strategy, *,
                           bars_by_symbol: Optional[dict] = None) -> list[dict]:
    """Evaluate one strategy across its pairs. Emits + returns LogEntry list.

    bars_by_symbol: optional {symbol: bars} to bypass MT5 (tests / batch).
    """
    emitted: list[dict] = []

    def log(level, text):
        emitted.append(store.emit_log(level, "Signal", text))

    if strategy.status != "ACTIVE":
        e = store.emit_log("info", "Monitor",
                           f"{strategy.name}: status {strategy.status}, skip")
        return [e]

    pairs = strategy.pairs or []
    if not pairs:
        return [store.emit_log("warn", "Monitor",
                               f"{strategy.name}: no pairs configured")]

    for sym in pairs:
        bars = (bars_by_symbol or {}).get(sym) or _fetch_bars(sym, strategy.timeframe)
        if not bars or len(bars) < 50:
            log("warn", f"{sym}: insufficient bars")
            continue
        log("info", f"Evaluating {sym} ({strategy.timeframe})…")
        decision = sig.evaluate_entry(strategy, bars)
        cs = decision.get("confluence", {})
        log("info", f"{sym}: confluence {cs.get('bullish',0)}↑/"
                    f"{cs.get('bearish',0)}↓ of {cs.get('enabled',0)} "
                    f"-> {decision.get('signal')}")
        d = decision["decision"]
        if d == "NONE":
            struct = decision.get("structure") or {}
            conf = struct.get("confidence", 0)
            if decision.get("signal") != "NONE" and conf:
                log("warn", f"{sym}: SKIP — confidence {conf:.0f} < "
                            f"{strategy.risk.minConfidence:.0f}")
            else:
                log("info", f"{sym}: no setup")
            continue
        # We have a setup
        log("ok", f"{sym}: {d}_ENTRY @ {decision['entry']:.5f} "
                  f"SL {decision['stop']:.5f} "
                  f"T1/T2/T3 {decision['targets'][0]:.5f}/"
                  f"{decision['targets'][1]:.5f}/{decision['targets'][2]:.5f} "
                  f"(conf {decision['confidence']:.0f}%, R:R {decision['rr']:.1f})")
        # Persist into the structured decision_log too (audit trail), best-effort
        _record_decision_log(strategy, sym, decision)
    return emitted


def evaluate_all_active(*, bars_by_symbol: Optional[dict] = None) -> dict:
    """Run evaluate_strategy_once for every ACTIVE strategy. Returns a summary."""
    results = {}
    for d in store.list_strategies():
        if d.get("status") != "ACTIVE":
            continue
        strat = Strategy.from_dict(d)
        logs = evaluate_strategy_once(strat, bars_by_symbol=bars_by_symbol)
        results[strat.id] = {"name": strat.name, "log_lines": len(logs)}
    return {"evaluated": len(results), "strategies": results}


def _record_decision_log(strategy: Strategy, symbol: str, decision: dict) -> None:
    """Mirror the setup into decision_log.py (the structured per-genome audit
    trail) using the strategy id as the 'genome_id'. Best-effort."""
    try:
        from r_native import decision_log
        decision_log.record_open(
            ticket=None, genome_id=strategy.id, symbol=symbol,
            side="BUY" if decision["decision"] == "LONG" else "SELL",
            entry=decision["entry"], sl=decision["stop"],
            tp=decision["targets"][-1], lot=0.0,
            confidence=int(decision.get("confidence", 0)),
            archetype=strategy.methodology,
            gate_verdict_dict={"reasons": decision.get("reasons", [])},
            indicators_dict={"confluence": decision.get("confluence", {})},
        )
    except Exception:
        pass
