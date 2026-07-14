"""runtime/buy_pulse.py — Live "نبض" screen: how close is the child to firing?

Born 2026-05-28: "أبني له شاشة نبض حي تعرض الشروط بالأخضر/الأحمر".

Refreshes every 2s. Shows, for the LIVE genome, both BUY and SELL
condition checklists with ✅/❌, plus current market state. You watch
this and SEE the moment all conditions go green.

Run:
    python -m runtime.buy_pulse
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path

from runtime.shared.tokens import PATHS

POLL_S = 2.0


def _clear(): os.system("cls" if os.name == "nt" else "clear")


def _read(p: Path) -> dict:
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}


def _check(label: str, ok: bool, detail: str) -> str:
    mark = "✅" if ok else "❌"
    return f"   {mark}  {label:30s} {detail}"


def render():
    snap = _read(PATHS["brain_live"])
    live = _read(PATHS["live_genome"])
    active = _read(PATHS["active_engines"])
    if not snap or not live:
        print("waiting for brain_live / live_genome ..."); return
    p = live.get("params", {})

    bias = snap.get("bias", {})
    up = sum(1 for v in bias.values() if v == "UP")
    dn = sum(1 for v in bias.values() if v == "DOWN")
    rsi = (snap.get("rsi") or {}).get("m1", 50)
    pressure = float(snap.get("pressure_10m1", 0))
    sess = snap.get("session", "?")
    reg = snap.get("regime", "?")

    min_mtf = p.get("min_mtf_agreement", 2)
    rsi_max = p.get("rsi_max", 72)
    rsi_min = 100 - rsi_max
    min_p = p.get("min_pressure_abs", 5)
    sess_filter = p.get("session_filter") or []
    reg_filter = p.get("regime_filter") or []

    # Gate checks (shared by both sides)
    gate_orch = 99782 in active.get("active_magics", [])
    gate_sess = (not sess_filter) or (sess in sess_filter)
    gate_reg = (not reg_filter) or (reg in reg_filter)

    _clear()
    W = 64
    print("╔" + "═" * W + "╗")
    print("║" + f"  💓 BUY PULSE — {live.get('name','?')[:34]}".ljust(W) + "║")
    print("╠" + "═" * W + "╣")
    print("║" + f"  bid {snap.get('bid','?')}  ·  {sess}  ·  {reg}".ljust(W) + "║")
    print("║" + f"  M1={bias.get('m1','?')} M5={bias.get('m5','?')} "
                f"M15={bias.get('m15','?')} H1={bias.get('h1','?')}  "
                f"→ {up}↑ / {dn}↓".ljust(W) + "║")
    print("║" + f"  RSI {rsi:.0f}  ·  Pressure {pressure:+.1f}".ljust(W) + "║")
    print("╠" + "═" * W + "╣")

    # Shared gates
    print("║" + "  🚦 GATES (تنطبق على الاتجاهين)".ljust(W) + "║")
    print("║" + _check("orchestrator يسمح", gate_orch,
                        f"regime {active.get('regime','?')}").ljust(W) + "║")
    print("║" + _check("session مسموح", gate_sess,
                        f"{sess} {'∈' if gate_sess else '∉'} {sess_filter or 'any'}").ljust(W) + "║")
    print("║" + _check("regime مسموح", gate_reg,
                        f"{reg}").ljust(W) + "║")

    # BUY conditions
    print("╠" + "═" * W + "╣")
    b1 = up >= min_mtf
    b2 = rsi < rsi_max
    b3 = abs(pressure) >= min_p
    b4 = pressure > 0
    buy_ready = all([gate_orch, gate_sess, gate_reg, b1, b2, b3, b4])
    print("║" + f"  🟢 BUY {'← READY!' if buy_ready else ''}".ljust(W) + "║")
    print("║" + _check(f"{up} timeframes UP", b1, f"يحتاج ≥{min_mtf}").ljust(W) + "║")
    print("║" + _check(f"RSI {rsi:.0f} < {rsi_max}", b2, "").ljust(W) + "║")
    print("║" + _check(f"|Pressure| ≥ {min_p}", b3, f"الآن {abs(pressure):.1f}").ljust(W) + "║")
    print("║" + _check("Pressure موجبة", b4, f"الآن {pressure:+.1f}").ljust(W) + "║")

    # SELL conditions
    print("╠" + "═" * W + "╣")
    s1 = dn >= min_mtf
    s2 = rsi > rsi_min
    s3 = abs(pressure) >= min_p
    s4 = pressure < 0
    sell_ready = all([gate_orch, gate_sess, gate_reg, s1, s2, s3, s4])
    print("║" + f"  🔴 SELL {'← READY!' if sell_ready else ''}".ljust(W) + "║")
    print("║" + _check(f"{dn} timeframes DOWN", s1, f"يحتاج ≥{min_mtf}").ljust(W) + "║")
    print("║" + _check(f"RSI {rsi:.0f} > {rsi_min}", s2, "").ljust(W) + "║")
    print("║" + _check(f"|Pressure| ≥ {min_p}", s3, f"الآن {abs(pressure):.1f}").ljust(W) + "║")
    print("║" + _check("Pressure سالبة", s4, f"الآن {pressure:+.1f}").ljust(W) + "║")

    print("╚" + "═" * W + "╝")
    verdict = "🟢 BUY الآن!" if buy_ready else ("🔴 SELL الآن!" if sell_ready else "⌛ ينتظر")
    print(f"  {verdict}   ·   Refresh {POLL_S}s · Ctrl+C")


def main():
    print("[buy_pulse] starting..."); time.sleep(1)
    while True:
        try:
            render(); time.sleep(POLL_S)
        except KeyboardInterrupt:
            print("\n[buy_pulse] stopped"); break
        except Exception as e:
            print(f"err: {e}"); time.sleep(POLL_S)


if __name__ == "__main__":
    main()
