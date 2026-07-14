"""
friday_memory.py — Persistent learning memory for FRIDAY Brain.

Tracks every closed trade with its setup signature, then provides:
  • Win-rate per setup pattern (which agent stance combo wins/loses)
  • Per-side stats (BUY win rate vs SELL win rate)
  • Per-regime stats (trend/range/event)
  • Per-hour stats (which hours of day work)
  • Daily P/L + drawdown limits
  • Kelly criterion for position sizing

Used by friday_brain.py to:
  • Avoid repeating losing setups (confidence penalty)
  • Halt trading when daily loss cap hit
  • Scale lot down after losing streaks
  • Refuse live trade until 24h paper validation passes
"""
from __future__ import annotations
import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import MetaTrader5 as mt5
    HAS_MT5 = True
except ImportError:
    HAS_MT5 = False

ROOT       = Path(r"C:\Users\Radhi\MT5")
MEMORY     = ROOT / "friday_memory.json"
PAPER_LOG  = ROOT / "friday_paper_trades.csv"   # simulated fills for paper mode
LIVE_LOG   = ROOT / "friday_live_trades.csv"    # real fills from MT5
MAGIC      = 20260600
SYMBOL     = "XAUUSDm"

# Risk caps
MAX_DAILY_LOSS_USD       = 5.00   # halt for the day
MAX_CONSECUTIVE_LOSSES   = 3      # halt for 30 min after this many
MAX_TRADES_PER_HOUR      = 6
PAPER_VALIDATION_HOURS   = 24
PAPER_MIN_WIN_RATE       = 0.40   # 40% required to graduate to live
PAPER_MIN_PROFIT_FACTOR  = 1.2

# Kelly fraction safety cap (never bet more than this)
KELLY_MAX_FRACTION = 0.10


# ─────────────────────────────────────────────────────────────────────────
# Setup signature — fingerprint for "what was the brain thinking?"
# ─────────────────────────────────────────────────────────────────────────

def setup_signature(decision: dict, market: dict, mom: dict | None = None) -> str:
    """Build a short string fingerprint that classifies the setup.
    Used as a key in win-rate tracking: similar setups should produce similar outcomes."""
    side = decision.get("side", "—")
    bias = market.get("smc_bias", "—")
    spread_band = "tight" if market.get("spread_pt", 999) < 200 else \
                  "wide"  if market.get("spread_pt", 999) > 400 else "med"
    trend = market.get("trend_5v5", "flat")
    direction_match = "align" if (side == "BUY" and bias == "BUY") or (side == "SELL" and bias == "SELL") \
                      else "neutral" if bias == "—" else "conflict"
    mom_tag = "—"
    if mom:
        if mom.get("whale"):    mom_tag = "whale"
        elif mom.get("push"):   mom_tag = "push"
        elif mom.get("breakout"): mom_tag = "breakout"
        else:                   mom_tag = "calm"
    return f"{side}|{bias}|{spread_band}|{trend}|{direction_match}|{mom_tag}"


# ─────────────────────────────────────────────────────────────────────────
# Persistent memory
# ─────────────────────────────────────────────────────────────────────────

def _load() -> dict:
    if not MEMORY.exists():
        return {
            "first_seen":       datetime.now(timezone.utc).isoformat(),
            "trades":           [],         # closed trades, oldest first
            "by_setup":         {},         # signature -> {wins, losses, pl}
            "by_hour_utc":      {},         # hour (0-23) -> stats
            "live_validation":  {           # gate for going live
                "paper_started_at": None,
                "paper_trades":     0,
                "paper_wins":       0,
                "paper_losses":     0,
                "paper_pl":         0.0,
                "live_allowed":     False,
            },
            "halts":            [],         # log of when we halted and why
        }
    try:
        return json.loads(MEMORY.read_text(encoding="utf-8"))
    except Exception:
        return _load()


def _save(mem: dict) -> None:
    tmp = MEMORY.with_suffix(".tmp")
    tmp.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(MEMORY)


def record_trade(ticket: int, side: str, entry: float, exit_price: float,
                 sl: float, tp: float, lot: float, profit: float,
                 opened_at: str, closed_at: str, signature: str,
                 paper: bool) -> None:
    """Append a closed trade to memory."""
    mem = _load()
    trade = {
        "ts":         closed_at,
        "ticket":     ticket,
        "side":       side,
        "entry":      entry,
        "exit":       exit_price,
        "sl":         sl,
        "tp":         tp,
        "lot":        lot,
        "profit":     round(profit, 4),
        "win":        profit > 0,
        "signature":  signature,
        "paper":      paper,
    }
    mem["trades"].append(trade)
    # Keep last 1000 trades
    mem["trades"] = mem["trades"][-1000:]

    # Update by_setup
    sig = mem["by_setup"].setdefault(signature, {"wins": 0, "losses": 0, "pl": 0.0, "trades": 0})
    sig["trades"] += 1
    sig["pl"]     += profit
    if profit > 0: sig["wins"]   += 1
    else:          sig["losses"] += 1

    # Update by hour
    hour = datetime.fromisoformat(closed_at.replace("Z","+00:00")).hour if "T" in closed_at else 0
    h = mem["by_hour_utc"].setdefault(str(hour), {"wins": 0, "losses": 0, "pl": 0.0, "trades": 0})
    h["trades"] += 1
    h["pl"]     += profit
    if profit > 0: h["wins"]   += 1
    else:          h["losses"] += 1

    # Paper validation tracking
    if paper:
        pv = mem["live_validation"]
        if pv["paper_started_at"] is None:
            pv["paper_started_at"] = datetime.now(timezone.utc).isoformat()
        pv["paper_trades"] += 1
        pv["paper_pl"]     += profit
        if profit > 0: pv["paper_wins"]   += 1
        else:          pv["paper_losses"] += 1
        # Check if graduation criteria met
        if pv["paper_trades"] >= 30:
            hours_elapsed = (datetime.now(timezone.utc) -
                             datetime.fromisoformat(pv["paper_started_at"])).total_seconds() / 3600
            win_rate = pv["paper_wins"] / max(1, pv["paper_trades"])
            if hours_elapsed >= PAPER_VALIDATION_HOURS and win_rate >= PAPER_MIN_WIN_RATE:
                pv["live_allowed"] = True

    _save(mem)


def log_halt(reason: str, duration_min: int = 30) -> None:
    mem = _load()
    mem["halts"].append({
        "ts":           datetime.now(timezone.utc).isoformat(),
        "reason":       reason,
        "duration_min": duration_min,
    })
    mem["halts"] = mem["halts"][-100:]
    _save(mem)


# ─────────────────────────────────────────────────────────────────────────
# Decision helpers — consulted before each trade
# ─────────────────────────────────────────────────────────────────────────

def setup_confidence_modifier(signature: str) -> tuple[float, str]:
    """Returns (multiplier, reason) — how much to scale a fresh signal based on history.
    < 1.0 means reduce confidence; > 1.0 means boost; 0.0 means refuse."""
    mem = _load()
    sig = mem["by_setup"].get(signature)
    if not sig or sig["trades"] < 3:
        return (1.0, "new setup — no history")
    wr = sig["wins"] / sig["trades"]
    n = sig["trades"]
    # Hard reject if 4+ losses and < 20% win rate
    if n >= 4 and wr < 0.20:
        return (0.0, f"REJECT: setup lost {sig['losses']}/{n} times (wr={wr:.0%})")
    if wr < 0.35:
        return (0.5, f"low wr={wr:.0%} ({n} trades) — half size")
    if wr > 0.60 and n >= 5:
        return (1.2, f"good wr={wr:.0%} ({n} trades) — boost")
    return (1.0, f"neutral wr={wr:.0%} ({n} trades)")


def daily_loss_cap_hit() -> tuple[bool, float]:
    """Check if today's loss exceeds MAX_DAILY_LOSS_USD."""
    mem = _load()
    today = datetime.now(timezone.utc).date()
    today_pl = 0.0
    for t in mem["trades"][-200:]:
        try:
            ts = datetime.fromisoformat(t["ts"].replace("Z", "+00:00")).date()
            if ts == today:
                today_pl += t["profit"]
        except Exception: continue
    return (today_pl <= -MAX_DAILY_LOSS_USD, today_pl)


def consecutive_losses() -> int:
    mem = _load()
    streak = 0
    for t in reversed(mem["trades"]):
        if t["profit"] < 0: streak += 1
        else: break
    return streak


def hourly_trade_count() -> int:
    mem = _load()
    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    count = 0
    for t in mem["trades"][-50:]:
        try:
            ts = datetime.fromisoformat(t["ts"].replace("Z", "+00:00"))
            if ts >= hour_ago: count += 1
        except Exception: continue
    return count


def kelly_lot_multiplier() -> float:
    """Position sizing based on overall win rate + average R:R.
    Returns multiplier (0.1 to 1.0) to apply to base lot."""
    mem = _load()
    trades = [t for t in mem["trades"] if not t.get("paper", False)]   # live only
    if len(trades) < 10:
        return 0.5    # half-size until proven
    wins   = [t["profit"] for t in trades if t["profit"] > 0]
    losses = [abs(t["profit"]) for t in trades if t["profit"] < 0]
    if not wins or not losses:
        return 0.5
    win_rate = len(wins) / len(trades)
    avg_win  = statistics.mean(wins)
    avg_loss = statistics.mean(losses)
    rr       = avg_win / avg_loss if avg_loss > 0 else 1.0
    # Kelly: f = (p*b - q) / b  where b=rr, p=wr, q=1-wr
    kelly = (win_rate * rr - (1 - win_rate)) / rr if rr > 0 else 0
    # Half-Kelly + safety cap
    multiplier = max(0.1, min(KELLY_MAX_FRACTION, kelly * 0.5))
    return multiplier


def is_live_allowed() -> bool:
    """Live trading is gated by paper validation."""
    mem = _load()
    return mem["live_validation"].get("live_allowed", False)


def safety_check(force_paper: bool = True) -> dict:
    """Full pre-trade safety check. Returns dict with `allowed` bool + `reason`."""
    mem = _load()
    reasons = []
    allowed = True

    # 1. Daily loss cap
    hit, pl_today = daily_loss_cap_hit()
    if hit:
        allowed = False
        reasons.append(f"daily loss cap hit: ${pl_today:.2f} <= -${MAX_DAILY_LOSS_USD}")

    # 2. Consecutive losses
    cl = consecutive_losses()
    if cl >= MAX_CONSECUTIVE_LOSSES:
        allowed = False
        reasons.append(f"consecutive losses: {cl} >= {MAX_CONSECUTIVE_LOSSES} (30min halt)")

    # 3. Hourly trade rate
    h = hourly_trade_count()
    if h >= MAX_TRADES_PER_HOUR:
        allowed = False
        reasons.append(f"hourly cap: {h} >= {MAX_TRADES_PER_HOUR}")

    # 4. Recent halts (within last 30 min)
    now = datetime.now(timezone.utc)
    for h in mem["halts"][-5:]:
        try:
            ts = datetime.fromisoformat(h["ts"].replace("Z","+00:00"))
            mins_ago = (now - ts).total_seconds() / 60
            if mins_ago < h.get("duration_min", 30):
                allowed = False
                reasons.append(f"halted {mins_ago:.0f}min ago for {h.get('duration_min',30)}min: {h['reason']}")
        except Exception: continue

    # 5. Live validation gate
    if not force_paper and not is_live_allowed():
        allowed = False
        pv = mem["live_validation"]
        reasons.append(f"live not allowed: paper_trades={pv['paper_trades']}/30, "
                       f"wr={pv['paper_wins']}/{max(1,pv['paper_trades'])}")

    return {
        "allowed":  allowed,
        "reasons":  reasons,
        "daily_pl": round(pl_today, 2),
        "consecutive_losses": cl,
        "hourly_count":       h,
        "kelly_mult":         round(kelly_lot_multiplier(), 3),
    }


# ─────────────────────────────────────────────────────────────────────────
# Sync MT5 closed deals into memory (call periodically)
# ─────────────────────────────────────────────────────────────────────────

def sync_from_mt5(hours_back: int = 24) -> int:
    """Ingest any closed brain trades from MT5 history into memory.
    Returns number of new trades added."""
    if not HAS_MT5: return 0
    if not mt5.initialize(): return 0
    deals = mt5.history_deals_get(datetime.now() - timedelta(hours=hours_back), datetime.now()) or []
    mt5.shutdown()
    mem = _load()
    known_tickets = {t["ticket"] for t in mem["trades"]}
    new = 0
    for d in deals:
        if d.symbol != SYMBOL or d.magic != MAGIC: continue
        if d.entry not in (1, 3): continue   # only closes
        if d.ticket in known_tickets: continue
        side = "BUY" if d.type == 0 else "SELL"
        record_trade(
            ticket=d.ticket, side=side,
            entry=0.0, exit_price=d.price,
            sl=0.0, tp=0.0, lot=d.volume,
            profit=d.profit,
            opened_at=datetime.fromtimestamp(d.time).isoformat(),
            closed_at=datetime.fromtimestamp(d.time).isoformat(),
            signature="unknown-pre-memory",
            paper=False,
        )
        new += 1
    return new


# ─────────────────────────────────────────────────────────────────────────
# Statistics view (for dashboard)
# ─────────────────────────────────────────────────────────────────────────

def stats() -> dict:
    mem = _load()
    trades = mem["trades"]
    live   = [t for t in trades if not t.get("paper", False)]
    paper  = [t for t in trades if     t.get("paper", False)]

    def _wr(seq):
        if not seq: return 0
        wins = sum(1 for t in seq if t["profit"] > 0)
        return round(wins / len(seq) * 100, 1)

    def _pl(seq):
        return round(sum(t["profit"] for t in seq), 2)

    today = datetime.now(timezone.utc).date()
    today_trades = [t for t in trades if
                    "T" in t["ts"] and datetime.fromisoformat(t["ts"].replace("Z","+00:00")).date() == today]

    return {
        "total_trades":   len(trades),
        "live_trades":    len(live),
        "paper_trades":   len(paper),
        "win_rate_live":  _wr(live),
        "win_rate_paper": _wr(paper),
        "pl_total":       _pl(trades),
        "pl_live":        _pl(live),
        "pl_paper":       _pl(paper),
        "pl_today":       _pl(today_trades),
        "trades_today":   len(today_trades),
        "consecutive_losses": consecutive_losses(),
        "kelly_multiplier":   round(kelly_lot_multiplier(), 3),
        "live_allowed":       is_live_allowed(),
        "live_validation":    mem["live_validation"],
        "top_winning_setups": [{"sig": k, **v, "wr": round(v["wins"]/max(1,v["trades"])*100,1)}
                                for k, v in sorted(mem["by_setup"].items(),
                                                   key=lambda x: -(x[1]["wins"]/max(1,x[1]["trades"])))[:5]],
        "top_losing_setups":  [{"sig": k, **v, "wr": round(v["wins"]/max(1,v["trades"])*100,1)}
                                for k, v in sorted(mem["by_setup"].items(),
                                                   key=lambda x: (x[1]["wins"]/max(1,x[1]["trades"])))[:5]],
        "recent_halts":   mem["halts"][-5:],
    }


if __name__ == "__main__":
    # CLI sync + stats
    n = sync_from_mt5(168)   # 7 days
    print(f"Synced {n} new trades from MT5\n")
    s = stats()
    print(json.dumps(s, ensure_ascii=False, indent=2))
