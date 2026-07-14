# -*- coding: utf-8 -*-
"""Unusual Whales market-data bridge for XAUUSDm context.

Unusual Whales does not publish the broker symbol XAUUSDm directly. For gold,
this bridge reads US proxy instruments (GLD/GDX/IAU/SLV) and turns their flow
into a small sentiment overlay for the MT5 EA agents. If UW_API_KEY is missing,
it writes a disabled status and does not fabricate data.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
OUT = BASE / "unusual_whales_signal.json"
BRAIN = BASE / "brain_vault"
LOG = BRAIN / "unusual-whales-bridge.jsonl"
API_BASE = os.getenv("UW_API_BASE", "https://api.unusualwhales.com/api").rstrip("/")
PROXIES = ["GLD", "GDX", "IAU", "SLV"]


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lstrip("\ufeff")
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v in ("", None):
            return default
        return float(v)
    except Exception:
        return default


def _get(path: str, key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    r = requests.get(
        API_BASE + path,
        params=params or {},
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        timeout=2.5,
    )
    if not r.ok:
        return {"ok": False, "status": r.status_code, "error": r.text[:300]}
    try:
        return {"ok": True, "json": r.json()}
    except Exception as exc:
        return {"ok": False, "status": r.status_code, "error": str(exc)}


def _score_tide(payload: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        return 0.0, {"samples": 0}
    tail = data[-8:]
    call = sum(_num(x.get("net_call_premium")) for x in tail if isinstance(x, dict))
    put_abs = sum(abs(_num(x.get("net_put_premium"))) for x in tail if isinstance(x, dict))
    score = (call - put_abs) / max(call + put_abs, 1.0)
    return score, {"samples": len(tail), "net_call_premium": call, "abs_put_premium": put_abs}


def run_once() -> dict[str, Any]:
    _load_env()
    key = os.getenv("UW_API_KEY") or os.getenv("UNUSUAL_WHALES_API_KEY")
    now = datetime.now().isoformat(timespec="seconds")
    if not key:
        payload = {
            "time": now,
            "enabled": False,
            "source": "unusual_whales",
            "reason": "missing_UW_API_KEY",
            "symbol": "XAUUSDm",
            "proxies": PROXIES,
            "bias": "NEUTRAL",
            "confidence": 0,
            "mcp": {
                "remote_url": "https://api.unusualwhales.com/api/mcp",
                "local_package": "@unusualwhales/mcp",
                "requires": "UW_API_KEY",
            },
        }
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    proxy_scores = {}
    errors = {}
    for symbol in PROXIES:
        tide = _get(f"/market/{symbol}/etf-tide", key)
        if tide.get("ok"):
            score, meta = _score_tide(tide.get("json") or {})
            proxy_scores[symbol] = {"score": round(score, 4), **meta}
        else:
            errors[symbol] = tide
        time.sleep(0.08)

    if proxy_scores:
        avg = sum(x["score"] for x in proxy_scores.values()) / len(proxy_scores)
    else:
        avg = 0.0
    bias = "BUY" if avg > 0.12 else "SELL" if avg < -0.12 else "NEUTRAL"
    confidence = int(min(85, max(0, abs(avg) * 100)))
    payload = {
        "time": now,
        "enabled": True,
        "source": "unusual_whales",
        "symbol": "XAUUSDm",
        "proxies": PROXIES,
        "bias": bias,
        "confidence": confidence,
        "score": round(avg, 4),
        "proxy_scores": proxy_scores,
        "errors": errors,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    BRAIN.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args()
    if not args.loop:
        print(json.dumps(run_once(), ensure_ascii=False, indent=2))
        return
    interval = max(5.0, float(args.interval))
    print(f"Unusual Whales bridge loop: interval={interval}s")
    while True:
        try:
            payload = run_once()
            print(f"{payload['time']} uw bias={payload.get('bias')} conf={payload.get('confidence')} enabled={payload.get('enabled')}", flush=True)
        except Exception as exc:
            print(f"unusual_whales_bridge error: {exc}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
