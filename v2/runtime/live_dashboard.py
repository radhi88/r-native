"""runtime/live_dashboard.py — Unified live view of everything.

Born 2026-05-28 to replace flipping between 20 console windows.
Shows account state, regime, active engines, open positions,
last trades, genome status, council activity — all in ONE view.

Refresh every 3s. Clears screen + redraws.
Run in its own terminal window.
"""
from __future__ import annotations
import MetaTrader5 as mt5
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

DATA = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
SYMBOL = "XAUUSDm"
POLL = 3.0

ENGINE_NAMES = {
    99777: "claude_auto",
    99778: "CLAUDE_BRAIN_EA",
    99779: "palace_council",
    99780: "claude_simple",
    99781: "claude_smart",
    99782: "claude_genome",
    20260600: "FRIDAY_brain",
    20260605: "algory_sniper",
    0: "MANUAL",
}


def _read(p: Path):
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except: return None


def _read_jsonl_tail(p: Path, n: int):
    if not p.exists(): return []
    lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    return [json.loads(l) for l in lines if l.strip()]


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def fmt_age(ts: str) -> str:
    if not ts: return "?"
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - t).total_seconds()
        if age < 60: return f"{int(age)}s"
        if age < 3600: return f"{int(age/60)}m"
        return f"{int(age/3600)}h"
    except: return "?"


def render():
    if not mt5.initialize() and not mt5.initialize(): return
    acc = mt5.account_info()
    positions = mt5.positions_get(symbol=SYMBOL) or []
    tick = mt5.symbol_info_tick(SYMBOL)

    snap = _read(DATA / "brain_live.json") or {}
    regime = _read(DATA / "market_regime.json") or {}
    orch = _read(DATA / "active_engines.json") or {}
    genome = _read(DATA / "live_genome.json") or {}
    perf = _read(DATA / "engine_performance.json") or {}
    fitness = _read(DATA / "genome_fitness.json") or {}

    clear()
    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print(f"║  CLAUDE TRADING DASHBOARD  ·  {datetime.now():%Y-%m-%d %H:%M:%S}  ·  XAU @ {tick.bid:.2f}    ║")
    print("╠══════════════════════════════════════════════════════════════════════════╣")

    # Account
    print(f"║  💰 ACCOUNT                                                                  ║")
    print(f"║     Balance ${acc.balance:>8.2f}  ·  Equity ${acc.equity:>8.2f}  ·  Floating ${acc.profit:>+7.2f}     ║")
    print(f"║     Margin Free ${acc.margin_free:>8.2f}  ·  Level {acc.margin_level:>5.0f}%  ·  Open {len(positions)}             ║")

    # Regime
    print(f"║                                                                              ║")
    print(f"║  🌡️ REGIME                                                                   ║")
    reg = regime.get("regime", "?")
    print(f"║     {reg:14s} — {(regime.get('reason') or '')[:55]:55s}     ║")
    print(f"║     → {(regime.get('advice') or '')[:65]:65s}      ║")

    # Active engines (from orchestrator)
    active = orch.get("active_magics", [])
    standby = orch.get("standby_magics", [])
    print(f"║                                                                              ║")
    print(f"║  🚦 ORCHESTRATOR                                                             ║")
    print(f"║     ACTIVE:  {', '.join([ENGINE_NAMES.get(m, str(m)) for m in active]) or '(none)':62s}║")
    print(f"║     STANDBY: {', '.join([ENGINE_NAMES.get(m, str(m))[:8] for m in standby])[:62]:62s}║")

    # Live genome
    print(f"║                                                                              ║")
    print(f"║  🧬 LIVE GENOME                                                              ║")
    g = genome.get("params", {})
    print(f"║     {genome.get('name','NONE'):20s}  promoted {fmt_age(genome.get('promoted_ts',''))} ago        ║")
    print(f"║     rsi≤{g.get('rsi_max','?')}  imb≥{g.get('min_imb_count','?')}  lot {g.get('lot','?')}  "
          f"mtf≥{g.get('min_mtf_agreement','?')}  FP={g.get('use_footprint','?')}              ║")

    # Open positions
    print(f"║                                                                              ║")
    print(f"║  📈 OPEN POSITIONS                                                           ║")
    if positions:
        for p in positions[:5]:
            side = "BUY " if int(p.type) == 0 else "SELL"
            name = ENGINE_NAMES.get(int(p.magic), str(p.magic))[:13]
            line = f"     #{p.ticket} {side} {p.volume:.2f}@{p.price_open:.2f} [{name:13s}] P/L ${p.profit:>+6.2f}"
            print(f"║  {line:75s}║")
    else:
        print(f"║     (no open positions)                                                      ║")

    # Engine performance ranking
    print(f"║                                                                              ║")
    print(f"║  🏆 ENGINE PERFORMANCE (last 7d)                                             ║")
    ranking = perf.get("ranking", [])[:5]
    if ranking:
        for r in ranking:
            stats = r.get("stats", {})
            name = r.get("name", "?")[:13]
            if stats.get("trades", 0) > 0:
                line = (f"     {name:13s}  {stats['trades']:>4d}T  WR {stats['win_rate']:>4.0f}%  "
                        f"PnL ${stats['pnl']:>+7.2f}  EV ${stats['expectancy']:>+6.2f}")
                print(f"║  {line:75s}║")
            else:
                print(f"║     {name:13s}  no trades yet                                         ║")
    else:
        print(f"║     (no performance data yet)                                                ║")

    # Recent trades (all magics)
    print(f"║                                                                              ║")
    print(f"║  📜 RECENT CLOSES (last 5)                                                   ║")
    since = datetime.now(timezone.utc) - timedelta(hours=2)
    deals = mt5.history_deals_get(since, datetime.now(timezone.utc)) or []
    exits = [d for d in deals if int(d.entry) in (1, 2)][-5:]
    for d in reversed(exits):
        name = ENGINE_NAMES.get(int(d.magic), str(d.magic))[:13]
        t = datetime.fromtimestamp(d.time).strftime("%H:%M:%S")
        mark = "🎯" if d.profit > 0 else "🔴"
        line = f"     {t} {mark} {name:13s} {d.volume:.2f}@{d.price:.2f}  ${d.profit:>+6.2f}"
        print(f"║  {line:75s}║")
    if not exits:
        print(f"║     (no recent closes)                                                       ║")

    # Genome fitness
    print(f"║                                                                              ║")
    print(f"║  🧪 GENOME FITNESS                                                           ║")
    for name, stats in list(fitness.items())[:5]:
        if name.startswith("_"): continue
        sigs = stats.get("buy_signals", 0) + stats.get("sell_signals", 0)
        conf = stats.get("avg_confidence_on_signal", 0)
        line = f"     {name[:20]:20s}  signals {sigs:>4d}  conf {conf:.2f}"
        print(f"║  {line:75s}║")

    # Brain state
    print(f"║                                                                              ║")
    print(f"║  🧠 BRAIN SNAPSHOT                                                           ║")
    b = snap.get("bias", {})
    last_m1 = snap.get("m1_last5", [{}])[-1] if snap.get("m1_last5") else {}
    print(f"║     M1={b.get('m1','?'):4s} M5={b.get('m5','?'):4s} M15={b.get('m15','?'):4s} H1={b.get('h1','?'):4s}  "
          f"MTF={snap.get('mtf_align','?'):6s}     ║")
    print(f"║     RSI_M1={snap.get('rsi',{}).get('m1','?'):>5}  "
          f"Pressure={snap.get('pressure_10m1','?'):>+5}  Session={snap.get('session','?')[:12]:12s} ║")
    print(f"║     Last M1: {last_m1.get('kind','?'):16s} body {last_m1.get('body_pct','?')}% close {last_m1.get('c','?')}     ║")

    print("╚══════════════════════════════════════════════════════════════════════════╝")
    print(f"  Refresh {POLL}s · Ctrl+C to exit")


def main():
    print("[live_dashboard] starting...")
    time.sleep(1)
    while True:
        try:
            render()
            time.sleep(POLL)
        except KeyboardInterrupt:
            mt5.shutdown()
            print("\n[live_dashboard] stopped"); break
        except Exception as e:
            print(f"err: {e}")
            time.sleep(POLL)


if __name__ == "__main__":
    main()
