"""runtime/performance_coordinator.py — Track per-engine performance.

Watches 3 trading engines simultaneously:
  • magic 99777 = claude_autonomous_trader.py (Python brain)
  • magic 99778 = CLAUDE_BRAIN_EA.mq5 (native MQL5 brain)
  • magic 20260605 = Algory/R Native genomes

For each engine, tracks: total_trades, wins, losses, total_pnl, win_rate,
avg_winner, avg_loser, expectancy, max_drawdown. Saves to
data/engine_performance.json every 30s.

Optional output: tells you which engine is performing best so you can
disable losers and amplify winners.

Run as background. No trade execution — read-only analytics.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

OUTPUT = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\engine_performance.json")
POLL = 30.0

ENGINES = {
    99777:    {"name": "Claude_Python",   "role": "rules_v1"},
    99778:    {"name": "Claude_EA_MQL5",  "role": "rules_v1_native"},
    20260605: {"name": "Algory_Genomes",  "role": "ga_evolved"},
    20260600: {"name": "R_Native_v1",     "role": "ga_evolved"},
}


def _save_atomic(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    tmp.replace(p)


def analyze_engine(mt5, magic: int, since_utc: datetime) -> dict:
    """Pull all deals for this magic since timestamp."""
    deals = mt5.history_deals_get(since_utc, datetime.now(timezone.utc)) or []
    my_deals = [d for d in deals if int(d.magic) == magic]
    if not my_deals: return None

    # Only count EXIT deals (entry=1=OUT for position close)
    exits = [d for d in my_deals if int(d.entry) in (1, 2)]
    if not exits:
        return {"trades": 0, "pnl": 0, "win_rate": 0, "expectancy": 0,
                "wins": 0, "losses": 0, "best": 0, "worst": 0}

    pnls = [float(d.profit) + float(d.swap) + float(d.commission) for d in exits]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = sum(pnls)
    avg_w = sum(wins) / max(1, len(wins))
    avg_l = sum(losses) / max(1, len(losses))
    win_rate = len(wins) / len(pnls) if pnls else 0
    expectancy = win_rate * avg_w + (1 - win_rate) * avg_l

    # Max drawdown approximation (running min of cumulative pnl)
    running = 0; peak = 0; mdd = 0
    sorted_deals = sorted(exits, key=lambda d: d.time)
    for d in sorted_deals:
        pnl = float(d.profit) + float(d.swap) + float(d.commission)
        running += pnl
        if running > peak: peak = running
        dd = peak - running
        if dd > mdd: mdd = dd

    return {
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate * 100, 1),
        "pnl": round(total, 2),
        "avg_winner": round(avg_w, 2),
        "avg_loser": round(avg_l, 2),
        "expectancy": round(expectancy, 2),
        "best_trade": round(max(pnls), 2),
        "worst_trade": round(min(pnls), 2),
        "max_dd": round(mdd, 2),
    }


def get_open_per_engine(mt5) -> dict:
    """How many positions currently open per engine."""
    positions = mt5.positions_get() or []
    by_magic = defaultdict(lambda: {"count": 0, "lot": 0.0, "floating": 0.0})
    for p in positions:
        m = int(p.magic)
        by_magic[m]["count"] += 1
        by_magic[m]["lot"] += float(p.volume)
        by_magic[m]["floating"] += float(p.profit)
    return dict(by_magic)


def rank_engines(performance: dict) -> list:
    """Sort engines by expectancy × trade count (need volume for confidence)."""
    items = []
    for magic, stats in performance.items():
        if not stats or stats["trades"] == 0:
            score = 0
        else:
            # Score = expectancy * sqrt(trades) — rewards consistency
            score = stats["expectancy"] * (stats["trades"] ** 0.5)
        items.append({
            "magic": magic,
            "name": ENGINES.get(magic, {}).get("name", "Unknown"),
            "stats": stats,
            "score": round(score, 2),
        })
    items.sort(key=lambda x: -x["score"])
    return items


def main_loop():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
    except Exception as e:
        print(f"mt5 err: {e}"); return

    print(f"[perf_coord] ONLINE — tracking {len(ENGINES)} engines")
    since = datetime.now(timezone.utc) - timedelta(days=7)   # last 7 days window

    while True:
        try:
            acc = mt5.account_info()
            performance = {}
            for magic in ENGINES.keys():
                stats = analyze_engine(mt5, magic, since)
                if stats: performance[magic] = stats

            open_pos = get_open_per_engine(mt5)
            ranked = rank_engines(performance)

            out = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "account": {
                    "balance": acc.balance if acc else 0,
                    "equity": acc.equity if acc else 0,
                    "floating": acc.profit if acc else 0,
                    "margin_level": acc.margin_level if acc and acc.margin else 0,
                },
                "engines": {str(k): v for k, v in performance.items()},
                "open_positions": {str(k): v for k, v in open_pos.items()},
                "ranking": ranked,
            }
            _save_atomic(OUTPUT, out)

            # Console summary
            print(f"\n[{datetime.now():%H:%M:%S}] perf snapshot:")
            print(f"  Balance ${acc.balance:.2f} · Equity ${acc.equity:.2f} · Floating ${acc.profit:+.2f}")
            print(f"  RANKING (last 7d):")
            for r in ranked[:5]:
                if r["stats"]["trades"] == 0:
                    print(f"    {r['name']:20} (magic {r['magic']}) — no trades yet")
                else:
                    s = r["stats"]
                    print(f"    {r['name']:20} (magic {r['magic']}) — "
                          f"{s['trades']}T  WR {s['win_rate']}%  PnL ${s['pnl']:+.2f}  "
                          f"EV ${s['expectancy']:+.2f}  score {r['score']}")
            print(f"  Open positions: {sum(v['count'] for v in open_pos.values())} total")

        except KeyboardInterrupt:
            print("[perf_coord] stopped"); break
        except Exception as e:
            print(f"[perf_coord] err: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main_loop()
