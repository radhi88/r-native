# -*- coding: utf-8 -*-
r"""Sub-second execution loop for EA live control.

This loop does not place trades directly. It writes bounded parameter decisions to
Common\Files\claude_live_control.csv, which the MQL5 EA reads every second.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_router import complete_json, provider_status

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).resolve().parent
COMMON = Path(os.path.expanduser(r"~\AppData\Roaming\MetaQuotes\Terminal\Common\Files"))

STATUS_JSON = COMMON / "ea_realtime_status.json"
CONTROL_CSV = COMMON / "claude_live_control.csv"
DNA_MEMORY = COMMON / "gold_dna_memory.csv"
CONFLUENCE_JSON = BASE / "confluence_signal.json"
VP_JSON = BASE / "volume_profile_signal.json"
UW_JSON = BASE / "unusual_whales_signal.json"
UNIFIED_JSON = BASE / "unified_signal.json"
BRAIN = BASE / "brain_vault"
AUTOPILOT_JSON = BRAIN / "autopilot_status.json"
AUTOPILOT_LOG = BRAIN / "autopilot-decisions.jsonl"

HEADER = [
    "epoch", "bar", "action", "confidence",
    "gap", "tp", "sl",
    "lock_start", "lock_giveback", "secure_start", "secure_lock",
    "modify_step", "lot_factor", "grid_factor",
    "profit_factor", "drawdown_pct", "spread_points", "reason_code",
]


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return default
        return value
    except Exception:
        return default


def _clamp(v: float, mn: float, mx: float) -> float:
    return max(mn, min(mx, v))


def _pct(value: Any, default: float = 0.0) -> float:
    out = _num(value, default)
    if 0.0 <= out <= 1.0:
        out *= 100.0
    return _clamp(out, 0.0, 100.0)


def _norm_signal(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in ("BUY", "BULL", "BULLISH", "LONG", "AGENT_BUY"):
        return "BUY"
    if text in ("SELL", "BEAR", "BEARISH", "SHORT", "AGENT_SELL"):
        return "SELL"
    return "HOLD"


def _decision(status: dict[str, Any], confluence: dict[str, Any], vp: dict[str, Any], uw: dict[str, Any], unified: dict[str, Any]) -> dict[str, Any]:
    bal = _num(status.get("balance"), 0)
    spread = _num(status.get("spread_points", status.get("spread")), 0)
    atr = _num(status.get("atr"), 0)
    positions = int(_num(status.get("positions"), 0))
    pnl = _num(status.get("basket_pnl", status.get("open_pnl")), 0)
    dd = _num(status.get("drawdown_pct"), 0)
    current_gap = int(_num(status.get("dna_gap"), 150))
    current_tp = _num(status.get("dna_tp"), 2.0)
    current_sl = _num(status.get("dna_sl"), 5.0)

    approved = bool(confluence.get("approved"))
    votes = int(_num(confluence.get("votes"), 0))
    direction = str(confluence.get("direction") or "").upper()
    if direction not in ("BUY", "SELL"):
        direction = str(status.get("smc_bias") or status.get("ema_dir") or "AUTO").upper()
    vp_signal = str(vp.get("trade_signal") or vp.get("signal") or "NEUTRAL").upper()
    uw_bias = str(uw.get("bias") or "NEUTRAL").upper()
    unified_final = _norm_signal(unified.get("final_signal") or unified.get("signal"))
    unified_raw = _norm_signal(unified.get("raw_unified_signal") or unified.get("unified_decision") or unified_final)
    unified_conf = _pct(unified.get("confidence"), 0)
    unified_risk = str(unified.get("risk_level") or unified.get("risk") or "").upper()
    unified_fresh = bool(unified) and (time.time() - _num(unified.get("timestamp"), time.time())) <= 10.0

    confidence = 58
    if approved:
        confidence += 16
    confidence += min(12, max(0, votes) * 2)
    if vp_signal in ("BUY", "SELL") and direction == vp_signal:
        confidence += 6
    if uw_bias in ("BUY", "SELL") and direction == uw_bias:
        confidence += 4
    if spread > 350:
        confidence -= 10
    if dd > 12:
        confidence -= 10
    confidence = int(_clamp(confidence, 50, 92))
    if unified_fresh:
        if unified_final in ("BUY", "SELL") and unified_risk != "EXTREME":
            direction = unified_final
            confidence = int(_clamp(max(confidence, unified_conf), 50, 95))
        elif unified_final == "HOLD":
            direction = "NONE"
            confidence = int(_clamp(unified_conf or confidence, 1, 95))

    volatility_gap = max(spread * 2.35, atr * 0.18, 150)
    if approved and votes >= 4 and spread < 300:
        volatility_gap *= 0.88
    if spread > 350:
        volatility_gap *= 1.18
    gap = int(_clamp(round(volatility_gap), 150, 1500))

    tp = _clamp((bal or 500) * 0.004, 0.50, 5.00)
    if approved and votes >= 4:
        tp *= 1.25
    if positions > 0 and pnl > 0:
        tp = min(tp, max(0.50, pnl + 0.60))
    tp = round(_clamp(tp, 0.50, 8.00), 2)
    sl = round(_clamp(max(tp + 0.50, (bal or 500) * 0.010), 1.00, 12.00), 2)
    secure = round(_clamp(max(0.10, tp * 0.25), 0.10, 1.00), 2)

    lot_factor = _clamp(_num(status.get("lot_factor"), 0.25), 0.25, 1.0)
    # 100% confidence gate: only increase lot when OB+BOS/CHoCH structural signal present
    # AND confidence >= 90 AND strong vote agreement AND low drawdown
    sr = confluence.get("sr_analysis", {}) if isinstance(confluence.get("sr_analysis"), dict) else {}
    ob_bos_alert = bool(sr.get("ob_bos_alert", False))
    choch_alert  = bool(sr.get("choch_alert",  False))
    high_quality_signal = ob_bos_alert or choch_alert  # OB+BOS or CHoCH = structural confirmation
    if approved and high_quality_signal and votes >= 5 and confidence >= 90 and dd < 8:
        lot_factor = _clamp(lot_factor + 0.05, 0.25, 0.55)
    elif dd > 10 or spread > 400:
        lot_factor = _clamp(lot_factor - 0.05, 0.25, 0.55)

    grid_factor = _clamp(_num(status.get("grid_factor"), 1.0), 1.0, 4.0)
    if spread > 350 or dd > 10:
        grid_factor = _clamp(grid_factor + 0.10, 1.0, 2.5)
    elif approved and votes >= 4:
        grid_factor = _clamp(grid_factor - 0.05, 1.0, 2.5)

    reason = f"fast_autopilot dir={direction} votes={votes} vp={vp_signal} uw={uw_bias} spread={spread:.0f}"
    if unified_fresh:
        reason += f" unified={unified_final}/{unified_raw} {unified_conf:.0f}% risk={unified_risk or 'NA'}"
    if abs(gap - current_gap) < 25:
        gap = current_gap
    if abs(tp - current_tp) < 0.05:
        tp = current_tp
    if abs(sl - current_sl) < 0.05:
        sl = current_sl

    action_dir = direction if direction in ("BUY", "SELL") else "NONE"
    return {
        "action": f"AGENT_{action_dir}" if action_dir != "NONE" else "AGENT_HOLD",
        "confidence": confidence,
        "params": {
            "gap": gap,
            "tp": tp,
            "sl": sl,
            "lock_start": round(max(0.50, tp * 0.75), 2),
            "lock_giveback": round(max(0.10, tp * 0.30), 2),
            "secure_start": secure,
            "secure_lock": secure,
            "modify_step": 1,
            "lot_factor": round(lot_factor, 2),
            "grid_factor": round(grid_factor, 2),
            "profit_factor": _num(status.get("profit_factor"), 0),
            "drawdown_pct": dd,
            "spread_points": spread,
        },
        "reason": reason,
    }


def _llm_refine(base: dict[str, Any], status: dict[str, Any], confluence: dict[str, Any], vp: dict[str, Any], uw: dict[str, Any], unified: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    system = "You are a low-latency trading parameter governor. Return JSON only. Never suggest unbounded risk."
    prompt = json.dumps({
        "task": "Refine these bounded MT5 XAUUSDm live-control parameters. Keep values within provided ranges.",
        "base": base,
        "status": status,
        "confluence": confluence,
        "volume_profile": vp,
        "unusual_whales": uw,
        "unified_signal": unified,
        "ranges": {
            "gap": [150, 1500], "tp": [0.5, 8.0], "sl": [1.0, 12.0],
            "secure_start": [0.10, 1.0], "secure_lock": [0.10, 1.0],
            "lot_factor": [0.25, 0.55], "grid_factor": [1.0, 2.5],
        },
        "output_schema": {"action": "EXECUTE_FAST", "confidence": 50, "params": {}, "reason": "short"},
    }, ensure_ascii=False)
    return complete_json(system, prompt, base, timeout=1.6)


def _bounded(decision: dict[str, Any]) -> dict[str, Any]:
    params = dict(decision.get("params") or {})
    params["gap"] = int(_clamp(_num(params.get("gap"), 150), 150, 1500))
    params["tp"] = round(_clamp(_num(params.get("tp"), 2.0), 0.50, 8.00), 2)
    params["sl"] = round(_clamp(max(_num(params.get("sl"), 5.0), params["tp"] + 0.50), 1.00, 12.00), 2)
    params["lock_start"] = round(_clamp(_num(params.get("lock_start"), params["tp"] * 0.75), 0.50, 10.00), 2)
    params["lock_giveback"] = round(_clamp(_num(params.get("lock_giveback"), params["tp"] * 0.30), 0.10, 5.00), 2)
    params["secure_start"] = round(_clamp(_num(params.get("secure_start"), 0.50), 0.10, 1.00), 2)
    params["secure_lock"] = round(_clamp(_num(params.get("secure_lock"), 0.50), 0.10, 1.00), 2)
    params["modify_step"] = int(_clamp(_num(params.get("modify_step"), 1), 1, 5))
    params["lot_factor"] = round(_clamp(_num(params.get("lot_factor"), 0.25), 0.25, 0.55), 2)
    params["grid_factor"] = round(_clamp(_num(params.get("grid_factor"), 1.0), 1.0, 2.5), 2)
    params["profit_factor"] = round(_num(params.get("profit_factor"), 0), 3)
    params["drawdown_pct"] = round(_num(params.get("drawdown_pct"), 0), 2)
    params["spread_points"] = round(_num(params.get("spread_points"), 0), 1)
    raw_action = str(decision.get("action") or "")
    reason = str(decision.get("reason") or "fast_autopilot")[:120]
    marker = (raw_action + " " + reason).upper()
    if "DIR=BUY" in marker or "AGENT_BUY" in marker:
        action = "AGENT_BUY"
    elif "DIR=SELL" in marker or "AGENT_SELL" in marker:
        action = "AGENT_SELL"
    elif "AGENT_HOLD" in marker or "HOLD" in marker:
        action = "AGENT_HOLD"
    else:
        action = "AGENT_HOLD"
    raw_confidence = _num(decision.get("confidence"), 55)
    if action == "AGENT_HOLD":
        confidence = int(_clamp(raw_confidence, 1, 95))
    else:
        confidence = int(_clamp(raw_confidence, 50, 95))
    return {
        "action": action,
        "confidence": confidence,
        "params": params,
        "reason": reason,
    }


def _write_control(decision: dict[str, Any], bar: int) -> None:
    p = decision["params"]
    row = [
        int(time.time()), bar, decision["action"], decision["confidence"],
        p["gap"], p["tp"], p["sl"],
        p["lock_start"], p["lock_giveback"], p["secure_start"], p["secure_lock"],
        p["modify_step"], p["lot_factor"], p["grid_factor"],
        p["profit_factor"], p["drawdown_pct"], p["spread_points"], decision["reason"],
    ]
    COMMON.mkdir(parents=True, exist_ok=True)
    with CONTROL_CSV.open("w", newline="", encoding="ansi") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerow(row)


def _safe_print(text: str) -> None:
    try:
        print(text, flush=True)
    except OSError:
        pass


def run_once(use_llm: bool, llm_every: float, state: dict[str, Any]) -> dict[str, Any]:
    status = _read_json(STATUS_JSON, {})
    confluence = _read_json(CONFLUENCE_JSON, {})
    vp = _read_json(VP_JSON, {})
    uw = _read_json(UW_JSON, {})
    unified = _read_json(UNIFIED_JSON, {})
    base = _decision(status, confluence, vp, uw, unified)
    provider = "deterministic"
    decision = base
    now = time.time()
    if use_llm and now - float(state.get("last_llm", 0)) >= llm_every:
        provider, decision = _llm_refine(base, status, confluence, vp, uw, unified)
        state["last_llm"] = now
    decision = _bounded(decision)
    bar = int(_num(status.get("bar"), 0))
    _write_control(decision, bar)

    payload = {
        "time": datetime.now().isoformat(timespec="milliseconds"),
        "provider": provider,
        "llm": provider_status(),
        "bar": bar,
        "connected": bool(status),
        "decision": decision,
        "confluence": {
            "approved": bool(confluence.get("approved")),
            "votes": confluence.get("votes"),
            "direction": confluence.get("direction"),
        },
        "unified": {
            "final_signal": unified.get("final_signal"),
            "raw_unified_signal": unified.get("raw_unified_signal"),
            "confidence": unified.get("confidence"),
            "risk_level": unified.get("risk_level"),
            "veto_reasons": unified.get("veto_reasons", []),
        },
        "paths": {"control": str(CONTROL_CSV), "dna": str(DNA_MEMORY), "brain": str(BRAIN)},
    }
    BRAIN.mkdir(parents=True, exist_ok=True)
    AUTOPILOT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with AUTOPILOT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--llm-every", type=float, default=3.0)
    args = parser.parse_args()
    interval = max(0.2, float(args.interval))
    state: dict[str, Any] = {"last_llm": 0.0}
    _safe_print(f"Fast autopilot loop: interval={interval}s llm={'off' if args.no_llm else 'on'}")
    while True:
        started = time.time()
        try:
            payload = run_once(not args.no_llm, max(1.0, args.llm_every), state)
            d = payload["decision"]
            p = d["params"]
            _safe_print(
                f"{payload['time']} bar={payload['bar']} {d['action']} conf={d['confidence']} "
                f"gap={p['gap']} tp={p['tp']} sl={p['sl']} provider={payload['provider']}"
            )
        except Exception as exc:
            _safe_print(f"fast_autopilot error: {exc}")
        time.sleep(max(0.02, interval - (time.time() - started)))


if __name__ == "__main__":
    main()
