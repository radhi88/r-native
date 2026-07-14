# -*- coding: utf-8 -*-
"""Real-data unified signal bridge for the live EA stack.

This process does not place trades. It produces one normalized decision from
the local project files and writes it where the fast autopilot can consume it.
No synthetic price, SL, TP, or balance fallbacks are used.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
COMMON = Path(os.path.expanduser(r"~\AppData\Roaming\MetaQuotes\Terminal\Common\Files"))
BRAIN = BASE / "brain_vault"

STATUS_JSON = COMMON / "ea_realtime_status.json"
COMMON_UNIFIED_JSON = COMMON / "unified_signal.json"
UNIFIED_JSON = BASE / "unified_signal.json"
EXTERNAL_SIGNAL_JSON = BASE / "external_signal.json"
CONFLUENCE_JSON = BASE / "confluence_signal.json"
MULTI_TF_JSON = BASE / "multi_tf_signal.json"
VP_JSON = BASE / "volume_profile_signal.json"
UW_JSON = BASE / "unusual_whales_signal.json"
AGENTS_STATUS_JSON = BASE / "agents_status.json"
AUTOPILOT_JSON = BRAIN / "autopilot_status.json"
LATEST_DECISION_JSON = BRAIN / "latest_decision.json"
HISTORY_JSONL = BRAIN / "unified_signal_history.jsonl"
LEARNING_JSON = BRAIN / "unified_learning.json"

DEFAULT_WEIGHTS = {
    "external": 0.22,
    "smc": 0.24,
    "multi_tf": 0.18,
    "volume_profile": 0.12,
    "agents": 0.14,
    "unusual_whales": 0.10,
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return default
        return out
    except Exception:
        return default


def _pct(value: Any, default: float = 0.0) -> float:
    out = _num(value, default)
    if 0.0 <= out <= 1.0:
        out *= 100.0
    return max(0.0, min(100.0, out))


def _signal(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"BUY", "BULL", "BULLISH", "LONG", "AGENT_BUY"}:
        return "BUY"
    if text in {"SELL", "BEAR", "BEARISH", "SHORT", "AGENT_SELL"}:
        return "SELL"
    return "HOLD"


def _path_age_seconds(path: Path) -> float:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except Exception:
        return 999999.0


def _fresh(path: Path, max_age: float) -> bool:
    return path.exists() and _path_age_seconds(path) <= max_age


def _status_price(status: dict[str, Any]) -> float:
    bid = _num(status.get("bid"), 0)
    ask = _num(status.get("ask"), 0)
    close = _num(status.get("close"), 0)
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2.0, 3)
    return round(close, 3) if close > 0 else 0.0


def _load_learning() -> dict[str, Any]:
    data = _read_json(LEARNING_JSON, {})
    weights = dict(DEFAULT_WEIGHTS)
    if isinstance(data.get("weights"), dict):
        for key, val in data["weights"].items():
            if key in weights:
                weights[key] = max(0.05, min(0.45, _num(val, weights[key])))
    total = sum(weights.values()) or 1.0
    weights = {k: round(v / total, 4) for k, v in weights.items()}
    data["weights"] = weights
    data.setdefault("samples", 0)
    return data


def _update_learning(learning: dict[str, Any], previous: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    current_equity = _num(status.get("equity"), 0)
    previous_equity = _num(previous.get("equity_at_decision"), 0)
    previous_signal = _signal(previous.get("raw_unified_signal") or previous.get("final_signal"))
    if current_equity <= 0 or previous_equity <= 0 or previous_signal == "HOLD":
        return learning

    delta = current_equity - previous_equity
    if abs(delta) < 0.01:
        return learning

    weights = dict(learning.get("weights") or DEFAULT_WEIGHTS)
    agreed_sources = [
        s.get("source") for s in previous.get("sources", [])
        if _signal(s.get("signal")) == previous_signal
    ]
    step = 0.01 if delta > 0 else -0.01
    for source in agreed_sources:
        if source in weights:
            weights[source] = max(0.05, min(0.45, _num(weights[source], DEFAULT_WEIGHTS.get(source, 0.1)) + step))

    total = sum(weights.values()) or 1.0
    learning["weights"] = {k: round(v / total, 4) for k, v in weights.items()}
    learning["samples"] = int(_num(learning.get("samples"), 0)) + 1
    learning["last_outcome"] = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "equity_delta": round(delta, 2),
        "previous_signal": previous_signal,
        "agreed_sources": agreed_sources,
    }
    return learning


def _external_reading(max_age: float) -> dict[str, Any] | None:
    if not _fresh(EXTERNAL_SIGNAL_JSON, max_age):
        return None
    data = _read_json(EXTERNAL_SIGNAL_JSON, {})
    final_signal = _signal(data.get("signal") or data.get("final_signal"))
    raw_signal = _signal(data.get("unified_decision") or data.get("raw_unified_signal") or final_signal)
    confidence = _pct(data.get("confidence"), 0)
    risk = str(data.get("risk") or data.get("risk_level") or "").upper()
    if risk == "EXTREME" or confidence < 40:
        final_signal = "HOLD"
    return {
        "source": "external",
        "signal": final_signal,
        "raw_signal": raw_signal,
        "confidence": confidence,
        "risk_level": risk or "UNKNOWN",
        "price": _num(data.get("price"), 0),
        "stop_loss": _num(data.get("sl") or data.get("stop_loss"), 0),
        "take_profit": _num(data.get("tp") or data.get("take_profit"), 0),
        "reasoning": str(data.get("reasoning") or data.get("reason") or "external signal")[:240],
        "age_seconds": round(_path_age_seconds(EXTERNAL_SIGNAL_JSON), 2),
    }


def _build_readings(status: dict[str, Any], max_external_age: float) -> list[dict[str, Any]]:
    readings: list[dict[str, Any]] = []
    price = _status_price(status)

    external = _external_reading(max_external_age)
    if external:
        if external["price"] <= 0:
            external["price"] = price
        readings.append(external)

    confluence = _read_json(CONFLUENCE_JSON, {})
    votes = _num(confluence.get("votes"), 0)
    total = max(1.0, _num(confluence.get("total"), 5))
    direction = _signal(confluence.get("direction"))
    if direction == "HOLD":
        direction = _signal(status.get("smc_bias"))
    smc_conf = 30.0 + min(50.0, (votes / total) * 50.0)
    if confluence.get("approved"):
        smc_conf = min(95.0, smc_conf + 15.0)
    readings.append({
        "source": "smc",
        "signal": direction,
        "confidence": round(smc_conf, 2),
        "price": price,
        "reasoning": f"confluence votes={int(votes)}/{int(total)} approved={bool(confluence.get('approved'))}; {status.get('smc_status', '')}",
    })

    multi_tf = _read_json(MULTI_TF_JSON, {})
    mtf_signal = _signal(multi_tf.get("direction"))
    mtf_conf = 55.0 if mtf_signal in {"BUY", "SELL"} else 35.0
    if _num(multi_tf.get("vote"), 0) > 0:
        mtf_conf += 10.0
    readings.append({
        "source": "multi_tf",
        "signal": mtf_signal,
        "confidence": round(min(85.0, mtf_conf), 2),
        "price": _num(multi_tf.get("current"), price) or price,
        "reasoning": "multi-timeframe support/resistance map",
    })

    vp = _read_json(VP_JSON, {})
    vp_direction = _signal(vp.get("direction"))
    vp_bias = _signal(vp.get("bias"))
    vp_signal = vp_direction if vp_direction != "HOLD" else vp_bias
    readings.append({
        "source": "volume_profile",
        "signal": vp_signal,
        "confidence": 58.0 if vp_signal in {"BUY", "SELL"} else 35.0,
        "price": _num(vp.get("price"), price) or price,
        "reasoning": f"poc={vp.get('poc')} vah={vp.get('vah')} val={vp.get('val')} signal={vp.get('trade_signal')}",
    })

    agents = _read_json(AGENTS_STATUS_JSON, {})
    agent_conf = agents.get("confluence", {}) if isinstance(agents.get("confluence"), dict) else {}
    agent_signal = _signal(agent_conf.get("direction"))
    readings.append({
        "source": "agents",
        "signal": agent_signal,
        "confidence": 55.0 if agent_signal in {"BUY", "SELL"} else 35.0,
        "price": price,
        "reasoning": f"agent confluence={agent_conf.get('direction')} votes={agent_conf.get('votes')}",
    })

    uw = _read_json(UW_JSON, {})
    uw_signal = _signal(uw.get("bias") or uw.get("signal"))
    if uw.get("enabled") is False:
        uw_signal = "HOLD"
    readings.append({
        "source": "unusual_whales",
        "signal": uw_signal,
        "confidence": _pct(uw.get("confidence"), 30.0) or 30.0,
        "price": price,
        "reasoning": str(uw.get("reason") or uw.get("status") or "unusual whales bridge")[:160],
    })

    return [r for r in readings if _pct(r.get("confidence"), 0) > 0]


def make_decision(max_external_age: float = 90.0) -> dict[str, Any]:
    status = _read_json(STATUS_JSON, {})
    learning = _load_learning()
    previous = _read_json(UNIFIED_JSON, {})
    learning = _update_learning(learning, previous, status)

    readings = _build_readings(status, max_external_age)
    weights = learning.get("weights") or DEFAULT_WEIGHTS
    scores = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    weighted_total = 0.0
    for reading in readings:
        source = str(reading.get("source"))
        weight = _num(weights.get(source), DEFAULT_WEIGHTS.get(source, 0.1))
        confidence = _pct(reading.get("confidence"), 0) / 100.0
        signal = _signal(reading.get("signal"))
        scores[signal] += weight * confidence
        weighted_total += weight

    if weighted_total > 0:
        scores = {k: v / weighted_total for k, v in scores.items()}
    raw_signal = max(scores, key=scores.get) if scores else "HOLD"
    confidence = round((scores.get(raw_signal, 0.0) or 0.0) * 100.0, 2)

    buy_votes = sum(1 for r in readings if _signal(r.get("signal")) == "BUY")
    sell_votes = sum(1 for r in readings if _signal(r.get("signal")) == "SELL")
    hold_votes = sum(1 for r in readings if _signal(r.get("signal")) == "HOLD")
    consensus = f"{max(buy_votes, sell_votes, hold_votes)}/{max(1, len(readings))}"

    final_signal = raw_signal
    risk_level = "LOW" if confidence >= 80 else "MEDIUM" if confidence >= 65 else "HIGH" if confidence >= 50 else "EXTREME"
    veto_reasons: list[str] = []
    spread = _num(status.get("spread_points") or status.get("spread"), 0)
    max_spread = 450.0
    if spread > max_spread:
        veto_reasons.append(f"spread {spread:.0f}>{max_spread:.0f}")
    if confidence < 55.0:
        veto_reasons.append(f"confidence {confidence:.2f}<55")
    for reading in readings:
        if reading.get("source") == "external" and str(reading.get("risk_level", "")).upper() == "EXTREME":
            veto_reasons.append("external risk EXTREME")
    if raw_signal == "HOLD" or veto_reasons:
        final_signal = "HOLD"
        if veto_reasons:
            risk_level = "EXTREME" if "external risk EXTREME" in veto_reasons else risk_level

    price = _status_price(status)
    balance = _num(status.get("balance"), 0)
    volume = round(max(0.01, min(0.14, (balance * 0.0025) / 10.0)), 2) if balance > 0 else 0.0
    tp_money = round(max(0.50, min(8.0, balance * 0.004)), 2) if balance > 0 else 0.0
    sl_money = round(max(1.00, min(12.0, balance * 0.010)), 2) if balance > 0 else 0.0

    reasoning_lines = [
        f"Unified Decision: {raw_signal}",
        f"Final Signal: {final_signal}",
        f"Confidence: {confidence:.2f}%",
        f"Consensus: {consensus}",
        f"Risk Level: {risk_level}",
        f"Veto: {', '.join(veto_reasons) if veto_reasons else 'none'}",
        "Source Breakdown:",
    ]
    for reading in readings:
        reasoning_lines.append(
            f"- {reading['source']}: {_signal(reading.get('signal'))} "
            f"@ {_pct(reading.get('confidence'), 0):.0f}% - {reading.get('reasoning', '')}"
        )

    payload = {
        "time": datetime.now().isoformat(timespec="milliseconds"),
        "timestamp": time.time(),
        "fresh": True,
        "final_signal": final_signal,
        "raw_unified_signal": raw_signal,
        "confidence": confidence,
        "consensus_ratio": consensus,
        "risk_level": risk_level,
        "execution_mode": "MARKET" if final_signal in {"BUY", "SELL"} and confidence >= 70 else "LIMIT",
        "price": price,
        "stop_loss": 0.0,
        "take_profit": 0.0,
        "volume": volume,
        "tp_money": tp_money,
        "sl_money": sl_money,
        "spread_points": spread,
        "equity_at_decision": _num(status.get("equity"), 0),
        "trade_allowed": bool(status.get("trade_allowed")),
        "trade_block_reason": status.get("trade_block_reason", ""),
        "veto_reasons": veto_reasons,
        "scores": {k: round(v * 100.0, 2) for k, v in scores.items()},
        "weights": weights,
        "learning": {"samples": learning.get("samples", 0), "last_outcome": learning.get("last_outcome")},
        "sources": readings,
        "reasoning": "\n".join(reasoning_lines),
    }

    BRAIN.mkdir(parents=True, exist_ok=True)
    _write_json(UNIFIED_JSON, payload)
    _write_json(COMMON_UNIFIED_JSON, payload)
    _write_json(LATEST_DECISION_JSON, payload)
    _write_json(LEARNING_JSON, learning)
    with HISTORY_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def _safe_print(text: str) -> None:
    try:
        print(text, flush=True)
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Run forever")
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--external-max-age", type=float, default=90.0)
    args = parser.parse_args()

    interval = max(0.2, float(args.interval))
    while True:
        try:
            decision = make_decision(max_external_age=float(args.external_max_age))
            _safe_print(
                f"{decision['time']} unified={decision['final_signal']} "
                f"raw={decision['raw_unified_signal']} conf={decision['confidence']:.2f}% "
                f"risk={decision['risk_level']} price={decision['price']} veto={decision['veto_reasons']}"
            )
        except Exception as exc:
            _safe_print(f"unified_signal_bridge error: {exc}")
        if not args.loop:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
