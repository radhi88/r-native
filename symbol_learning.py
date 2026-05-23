"""symbol_learning.py - Each currency has its OWN learning bucket.

After every closed trade on SYMBOL_X:
  - Append to data/r_native/symbol_learning/<SYMBOL_X>.jsonl
  - Update per-symbol stats: WR, PF, best archetype, best hour, recent streak
  - Bump trust score (-100..+100)
  - Adapt SL/TP multipliers FOR THIS SYMBOL ONLY based on what won

Exposes:
  - record_trade(symbol, profit, archetype, sl_dist, tp_dist, hour, etc.)
  - get_symbol_intelligence(symbol) → dict with stats + recommended adjustments
  - get_all_symbol_stats() → for UI
"""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

LEARN_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_learning")
CONFIG_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")

# Per-symbol adapters live here
INTEL_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_intel")

ADAPT_ALPHA = 0.18  # how fast we adapt
MIN_TRADES_TO_ADAPT = 4


def _now_iso() -> str: return datetime.now(timezone.utc).isoformat()


def _ensure_dirs():
    LEARN_DIR.mkdir(parents=True, exist_ok=True)
    INTEL_DIR.mkdir(parents=True, exist_ok=True)


def record_trade(symbol: str, profit: float, archetype: str,
                 side: str, entry: float, exit_price: float,
                 sl: float, tp: float,
                 duration_min: float, exit_reason: str,
                 hour_utc: int, bid_at_entry: float = 0):
    """Append closed trade to per-symbol journal, recompute intel."""
    _ensure_dirs()
    rec = {
        "ts": _now_iso(),
        "symbol": symbol,
        "archetype": archetype,
        "side": side,
        "entry": float(entry),
        "exit": float(exit_price),
        "sl": float(sl),
        "tp": float(tp),
        "profit": round(float(profit), 4),
        "duration_min": round(float(duration_min), 1),
        "exit_reason": exit_reason,
        "hour_utc": int(hour_utc),
        "sl_dist": abs(entry - sl),
        "tp_dist": abs(tp - entry),
        "bid_at_entry": bid_at_entry,
    }
    journal = LEARN_DIR / f"{symbol}.jsonl"
    with open(journal, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _recompute_intel(symbol)
    return rec


def _recompute_intel(symbol: str):
    """Read this symbol's full journal, compute stats + adaptations, save to intel/<symbol>.json."""
    journal = LEARN_DIR / f"{symbol}.jsonl"
    if not journal.exists(): return
    trades = []
    try:
        with open(journal, encoding="utf-8") as f:
            for line in f:
                try: trades.append(json.loads(line))
                except Exception: pass
    except Exception: return
    if not trades:
        return

    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] < 0]
    gw = sum(t["profit"] for t in wins)
    gl = abs(sum(t["profit"] for t in losses))
    wr = (len(wins) / len(trades) * 100) if trades else 0
    pf = (gw / gl) if gl > 0 else (999 if wins else 0)
    avg_dur = sum(t["duration_min"] for t in trades) / len(trades)
    net = sum(t["profit"] for t in trades)

    # Per-archetype
    by_arch = defaultdict(lambda: {"trades": 0, "wins": 0, "net": 0.0, "avg_sl_dist": 0.0, "avg_tp_dist": 0.0})
    for t in trades:
        a = t.get("archetype") or "UNKNOWN"
        s = by_arch[a]
        s["trades"] += 1
        if t["profit"] > 0: s["wins"] += 1
        s["net"] += t["profit"]
        s["avg_sl_dist"] = (s["avg_sl_dist"] * (s["trades"]-1) + t.get("sl_dist", 0)) / s["trades"]
        s["avg_tp_dist"] = (s["avg_tp_dist"] * (s["trades"]-1) + t.get("tp_dist", 0)) / s["trades"]
    for a, s in by_arch.items():
        s["win_rate"] = round(s["wins"] / max(1, s["trades"]) * 100, 1)
        s["net"] = round(s["net"], 2)
        s["avg_sl_dist"] = round(s["avg_sl_dist"], 4)
        s["avg_tp_dist"] = round(s["avg_tp_dist"], 4)

    # Best/worst archetype on this symbol
    best_arch = max(by_arch.items(), key=lambda kv: kv[1]["net"]) if by_arch else (None, None)
    worst_arch = min(by_arch.items(), key=lambda kv: kv[1]["net"]) if by_arch else (None, None)

    # Per-hour stats
    by_hour = defaultdict(lambda: {"trades": 0, "wins": 0, "net": 0.0})
    for t in trades:
        h = int(t.get("hour_utc", -1))
        if h < 0: continue
        s = by_hour[h]
        s["trades"] += 1
        if t["profit"] > 0: s["wins"] += 1
        s["net"] += t["profit"]
    best_hours = sorted(by_hour.items(), key=lambda kv: -kv[1]["net"])[:5]

    # Recent trend (last 10 trades)
    recent = trades[-10:]
    recent_net = sum(t["profit"] for t in recent)
    consec_loss = 0
    for t in reversed(trades):
        if t["profit"] < 0: consec_loss += 1
        else: break

    # ─── Trust score (-100..+100) ───
    # Components: WR, PF, recent momentum, sample size confidence
    trust = 0
    if wr >= 60: trust += 30
    elif wr >= 50: trust += 15
    elif wr < 35: trust -= 30
    if pf >= 2.0: trust += 30
    elif pf >= 1.3: trust += 15
    elif pf < 1.0: trust -= 30
    if recent_net > 0: trust += 15
    else: trust -= 15
    if len(trades) < 5: trust -= 20    # not enough data
    elif len(trades) >= 30: trust += 10
    if consec_loss >= 3: trust -= 20
    trust = max(-100, min(100, trust))

    # ─── Adapted multipliers (only after enough trades) ───
    adj = {"sl_mult": 1.0, "tp_mult": 1.0}
    if len(trades) >= MIN_TRADES_TO_ADAPT and best_arch[1]:
        # If WR good, keep current; if WR weak, tighten SL
        if wr < 40: adj["sl_mult"] = max(0.6, 1.0 * (1 - ADAPT_ALPHA))
        elif wr > 60: adj["sl_mult"] = min(1.3, 1.0 * (1 + ADAPT_ALPHA / 2))
        # If PF good, extend TP; if poor, shorten
        if pf > 2.0: adj["tp_mult"] = min(1.5, 1.0 * (1 + ADAPT_ALPHA))
        elif pf < 1.0: adj["tp_mult"] = max(0.7, 1.0 * (1 - ADAPT_ALPHA))

    # ─── Final verdict ───
    if trust >= 50:    verdict = "PREFERRED"
    elif trust >= 0:   verdict = "OK"
    elif trust >= -40: verdict = "CAUTION"
    else:              verdict = "BLOCKED"

    intel = {
        "symbol": symbol,
        "ts": _now_iso(),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(wr, 1),
        "profit_factor": round(pf, 2),
        "net_pl": round(net, 2),
        "avg_duration_min": round(avg_dur, 1),
        "recent_10_net": round(recent_net, 2),
        "consecutive_losses_now": consec_loss,
        "trust_score": trust,
        "verdict": verdict,
        "best_archetype": best_arch[0],
        "worst_archetype": worst_arch[0],
        "by_archetype": dict(by_arch),
        "best_hours": [{"hour": h, "stats": s} for h, s in best_hours],
        "adjustments": adj,
    }
    (INTEL_DIR / f"{symbol}.json").write_text(
        json.dumps(intel, ensure_ascii=False, indent=2), encoding="utf-8")
    return intel


def get_symbol_intelligence(symbol: str) -> dict:
    """Read this symbol's intel (or a default empty)."""
    p = INTEL_DIR / f"{symbol}.json"
    if not p.exists():
        return {
            "symbol": symbol, "total_trades": 0, "verdict": "UNKNOWN",
            "trust_score": 0, "adjustments": {"sl_mult": 1.0, "tp_mult": 1.0},
        }
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {"symbol": symbol, "error": "read fail"}


def get_all_symbol_stats() -> dict:
    """All symbols' intel — for the UI Genes / Live tab."""
    _ensure_dirs()
    out = {}
    for p in INTEL_DIR.glob("*.json"):
        sym = p.stem
        try: out[sym] = json.loads(p.read_text(encoding="utf-8"))
        except Exception: pass
    return out


def should_trade_symbol(symbol: str) -> tuple[bool, str]:
    """Check if R should trade this symbol RIGHT NOW based on learned intel."""
    intel = get_symbol_intelligence(symbol)
    verdict = intel.get("verdict", "UNKNOWN")
    if verdict == "BLOCKED":
        return False, f"trust score {intel.get('trust_score')} blocked"
    if intel.get("consecutive_losses_now", 0) >= 4:
        return False, f"{intel.get('consecutive_losses_now')} consecutive losses on this symbol"
    return True, f"verdict={verdict} trust={intel.get('trust_score',0)}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        sym = sys.argv[1]
        intel = get_symbol_intelligence(sym)
        print(json.dumps(intel, ensure_ascii=False, indent=2))
    else:
        all_intel = get_all_symbol_stats()
        for sym, intel in all_intel.items():
            print(f"{sym}: verdict={intel.get('verdict')} trust={intel.get('trust_score')} "
                  f"trades={intel.get('total_trades')} PF={intel.get('profit_factor')}")
