"""
r_learning.py — R's adaptive learning system.

Two complementary learning loops:

  ❶ AFTER-TRADE LEARNING
     Every time an R-magic position closes, record:
       - archetype used, side, entry/exit, SL/TP at open & close
       - actual SL/TP final values (might differ from initial if user/R moved them)
       - profit, duration, exit_reason
       - market context: H1 ATR, H1 bias, hour-of-day, regime
     Aggregate into per-archetype stats:
       - win rate, average win, average loss, profit factor
       - best/worst hours, best/worst regimes
       - effective SL multiplier (final SL distance / opening ATR)
       - effective TP multiplier
     Use this to gradually shift the archetype templates' SL_ATR_MULT
     and TP_ATR_MULT toward what actually works.

  ❷ MANUAL-OVERRIDE LEARNING
     Every cycle (8s), for each open R position, compare CURRENT broker
     SL/TP to the values R originally placed.  If user moved them:
       - record the delta (tightened SL? widened TP? moved to BE?)
       - tag as "USER_OVERRIDE"
     When ≥ 3 manual moves of the same kind are observed, automatically
     adjust the archetype template:
       - if user tightens SL → reduce SL_ATR_MULT
       - if user widens TP → increase TP_ATR_MULT
       - if user moves SL to BE earlier than R → trigger BE earlier

Files written:
  data/r_learning/trades.jsonl       — every closed trade (append-only)
  data/r_learning/overrides.jsonl    — every detected manual SL/TP change
  data/r_learning/archetype_stats.json — rolling aggregates
  data/r_learning/adjustments.json   — current template adjustments
"""
from __future__ import annotations
import json
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

LEARN_DIR    = Path(r"C:\Users\Radhi\MT5\friday_v3\data\r_learning")
TRADES_FILE  = LEARN_DIR / "trades.jsonl"
OVERRIDES_FILE = LEARN_DIR / "overrides.jsonl"
ARCH_STATS    = LEARN_DIR / "archetype_stats.json"
ADJUSTMENTS   = LEARN_DIR / "adjustments.json"
ORIGINS_FILE  = LEARN_DIR / "trade_origins.json"   # what R originally requested

# Default adjustments (multipliers on archetype templates)
DEFAULT_ADJ = {
    "BREAKOUT_HUNTER":  {"sl_mult": 1.0, "tp_mult": 1.0, "be_trigger_factor": 1.0},
    "MEAN_REVERTER":    {"sl_mult": 1.0, "tp_mult": 1.0, "be_trigger_factor": 1.0},
    "MULTI_SIGNAL":     {"sl_mult": 1.0, "tp_mult": 1.0, "be_trigger_factor": 1.0},
    "PATTERN_SPOTTER":  {"sl_mult": 1.0, "tp_mult": 1.0, "be_trigger_factor": 1.0},
}

# How fast we adapt (exponential moving average alpha)
ADAPT_ALPHA = 0.20        # 20% weight to new observation
MIN_TRADES_TO_ADAPT = 3   # need at least 3 trades per archetype before adjusting
USER_OVERRIDE_THRESHOLD = 2  # how many consistent overrides before learning


def _load(path: Path, default):
    if not path.exists(): return default
    try:    return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default


def _save(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


# ─── CONTEXT FINGERPRINTING ───
# A compact, comparable signature of the market context at trade open.
# Lets the gate ask: "this setup looks like N winners over the last week".
def _session_of(hour_utc: int) -> str:
    """Bucket UTC hour into a trading session label."""
    try: h = int(hour_utc)
    except Exception: return "UNK"
    if 0 <= h < 7:   return "ASIA"
    if 7 <= h < 13:  return "LONDON"
    if 13 <= h < 21: return "NY"
    return "LATE"     # 21-24 (overlaps the 22-08 night block)


def build_fingerprint(symbol: str, side: str, archetype: str,
                      bias_h1: str, hour_utc: int) -> dict:
    """Compact, bucketed market-context signature (order-independent dict)."""
    return {
        "symbol":    (symbol or "").upper(),
        "side":      (side or "").upper(),
        "archetype": archetype or "UNKNOWN",
        "bias":      (bias_h1 or "").upper() or "NA",
        "session":   _session_of(hour_utc),
    }


def fingerprint_key(fp: dict) -> str:
    return "|".join([fp.get("symbol",""), fp.get("side",""),
                     fp.get("archetype",""), fp.get("bias",""),
                     fp.get("session","")])


def _fingerprint_from_record(rec: dict) -> dict:
    """Rebuild a fingerprint from any closed-trade record (old or new schema)."""
    fp = rec.get("context_fingerprint")
    if isinstance(fp, dict) and fp.get("side"):
        return fp
    return build_fingerprint(
        symbol=rec.get("symbol", ""),
        side=rec.get("side", ""),
        archetype=rec.get("archetype", ""),
        bias_h1=rec.get("bias_h1_at_open", ""),
        hour_utc=rec.get("hour_utc_open", -1),
    )


def _iter_closed_trades():
    if not TRADES_FILE.exists(): return
    try:
        with open(TRADES_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: yield json.loads(line)
                except Exception: continue
    except Exception:
        return


def find_similar_trades(symbol: str, side: str, archetype: str,
                        bias_h1: str, hour_utc: int) -> dict:
    """Find historical closed trades whose context matches the current setup.

    Matching is graded: full = all 5 fields agree; partial = symbol+side+session
    agree (archetype/bias may differ). Returns win rate + net P/L for both tiers
    so the gate can answer "this setup looks like N winners last week".
    """
    q = build_fingerprint(symbol, side, archetype, bias_h1, hour_utc)

    def _bucket():
        return {"n": 0, "wins": 0, "net_pl": 0.0, "samples": []}
    full, partial = _bucket(), _bucket()

    for rec in _iter_closed_trades():
        fp = _fingerprint_from_record(rec)
        profit = float(rec.get("profit", 0) or 0)
        same_core = (fp.get("symbol") == q["symbol"] and
                     fp.get("side") == q["side"] and
                     fp.get("session") == q["session"])
        if not same_core:
            continue
        partial["n"] += 1
        partial["net_pl"] += profit
        if profit > 0: partial["wins"] += 1
        if len(partial["samples"]) < 5:
            partial["samples"].append({"ts": rec.get("ts"), "profit": round(profit, 2),
                                       "exit": rec.get("exit_reason")})
        if fp.get("archetype") == q["archetype"] and fp.get("bias") == q["bias"]:
            full["n"] += 1
            full["net_pl"] += profit
            if profit > 0: full["wins"] += 1
            if len(full["samples"]) < 5:
                full["samples"].append({"ts": rec.get("ts"), "profit": round(profit, 2),
                                        "exit": rec.get("exit_reason")})

    def _finish(b):
        b["net_pl"] = round(b["net_pl"], 2)
        b["win_rate"] = round(b["wins"] / b["n"] * 100, 1) if b["n"] else None
        return b
    full, partial = _finish(full), _finish(partial)

    # Verdict: prefer the full-match tier if it has a meaningful sample.
    tier = full if full["n"] >= 3 else partial
    n, wr, net = tier["n"], tier["win_rate"], tier["net_pl"]
    if n < 3 or wr is None:
        verdict = "INSUFFICIENT"   # not enough history → gate ignores this signal
    elif wr >= 60 and net > 0:
        verdict = "FAVORABLE"      # "looks like winners"
    elif wr <= 35 or net < 0:
        verdict = "UNFAVORABLE"    # "looks like losers"
    else:
        verdict = "NEUTRAL"

    return {
        "query":   q,
        "key":     fingerprint_key(q),
        "full":    full,
        "partial": partial,
        "verdict": verdict,
        "ts":      datetime.now(timezone.utc).isoformat(),
    }


# ─── ORIGIN TRACKING ───
# When R opens an order it calls record_trade_origin so later we can detect
# whether SL/TP were moved manually by user vs by R's trailing logic.
def record_trade_origin(ticket: int, archetype: str, side: str,
                        entry: float, sl: float, tp: float,
                        atr_h1: float = 0, hour_utc: int = 0,
                        bias_h1: str = "", symbol: str = ""):
    origins = _load(ORIGINS_FILE, {})
    origins[str(ticket)] = {
        "ticket":     int(ticket),
        "symbol":     symbol,
        "archetype":  archetype,
        "side":       side,
        "open_ts":    datetime.now(timezone.utc).isoformat(),
        "open_price": float(entry),
        "orig_sl":    float(sl),
        "orig_tp":    float(tp),
        "atr_h1":     float(atr_h1),
        "hour_utc":   int(hour_utc),
        "bias_h1":    bias_h1,
        # R's own trailing log (so we can distinguish R-moved vs user-moved)
        "r_sl_history":  [],   # [(ts, sl, reason), ...]
        "last_observed_sl": float(sl),
        "last_observed_tp": float(tp),
    }
    _save(ORIGINS_FILE, origins)


def get_trade_origin(ticket: int) -> Optional[dict]:
    return _load(ORIGINS_FILE, {}).get(str(ticket))


def record_r_sl_move(ticket: int, new_sl: float, reason: str):
    origins = _load(ORIGINS_FILE, {})
    o = origins.get(str(ticket))
    if not o: return
    o["r_sl_history"].append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "sl": float(new_sl),
        "reason": reason,
    })
    o["last_observed_sl"] = float(new_sl)
    _save(ORIGINS_FILE, origins)


def detect_manual_override(ticket: int, current_sl: float, current_tp: float,
                           sym_digits: int = 3) -> Optional[dict]:
    """Compare CURRENT broker SL/TP to R's last-known values.

    Returns an override record if user changed something, else None.
    Updates last_observed_* either way.
    """
    origins = _load(ORIGINS_FILE, {})
    o = origins.get(str(ticket))
    if not o: return None
    last_sl = float(o.get("last_observed_sl", o["orig_sl"]))
    last_tp = float(o.get("last_observed_tp", o["orig_tp"]))
    eps = 10 ** (-sym_digits)

    sl_changed = abs(current_sl - last_sl) > eps
    tp_changed = abs(current_tp - last_tp) > eps
    if not (sl_changed or tp_changed):
        return None

    # Distinguish from R's own moves: if the latest r_sl_history entry matches
    # current_sl, it's R, not user.
    r_history = o.get("r_sl_history", [])
    r_just_moved = False
    if r_history and abs(float(r_history[-1]["sl"]) - current_sl) < eps:
        r_just_moved = True

    # Update tracking regardless
    o["last_observed_sl"] = float(current_sl)
    o["last_observed_tp"] = float(current_tp)
    _save(ORIGINS_FILE, origins)

    if r_just_moved and not tp_changed:
        return None    # it was R, not user

    side = o.get("side", "")
    orig_sl = float(o["orig_sl"])
    orig_tp = float(o["orig_tp"])
    entry   = float(o["open_price"])

    record = {
        "ts":          datetime.now(timezone.utc).isoformat(),
        "ticket":      int(ticket),
        "archetype":   o.get("archetype"),
        "side":        side,
        "entry":       entry,
        "from_sl":     last_sl,
        "to_sl":       float(current_sl),
        "from_tp":     last_tp,
        "to_tp":       float(current_tp),
        "delta_sl":    round(current_sl - last_sl, sym_digits),
        "delta_tp":    round(current_tp - last_tp, sym_digits),
        "orig_sl":     orig_sl,
        "orig_tp":     orig_tp,
    }

    # Interpret the change
    intents = []
    if sl_changed:
        # For BUY: SL up = tighter (less risk). For SELL: SL down = tighter.
        if (side == "BUY" and current_sl > last_sl) or \
           (side == "SELL" and current_sl < last_sl):
            intents.append("TIGHTEN_SL")
            # Check if SL crossed entry (lock profit)
            if (side == "BUY" and current_sl >= entry) or \
               (side == "SELL" and current_sl <= entry):
                intents.append("BREAK_EVEN_PLUS")
        else:
            intents.append("WIDEN_SL")
    if tp_changed:
        if (side == "BUY" and current_tp > last_tp) or \
           (side == "SELL" and current_tp < last_tp):
            intents.append("EXTEND_TP")
        else:
            intents.append("REDUCE_TP")
    record["intents"] = intents
    record["source"]  = "USER" if not r_just_moved else "MIXED"

    _append_jsonl(OVERRIDES_FILE, record)
    return record


# ─── AFTER-TRADE LEARNING ───
def record_closed_trade(ticket: int, exit_price: float, profit: float,
                         exit_reason: str, sym_digits: int = 3):
    """Called when an R position closes — records the full lifecycle."""
    origins = _load(ORIGINS_FILE, {})
    o = origins.get(str(ticket))
    if not o: return    # unknown trade

    now = datetime.now(timezone.utc)
    open_dt = datetime.fromisoformat(o["open_ts"].replace("Z","+00:00"))
    duration_min = (now - open_dt).total_seconds() / 60

    # Final SL/TP after all R+user moves
    final_sl = float(o.get("last_observed_sl", o["orig_sl"]))
    final_tp = float(o.get("last_observed_tp", o["orig_tp"]))

    record = {
        "ts":              now.isoformat(),
        "ticket":          int(ticket),
        "symbol":          o.get("symbol", ""),
        "archetype":       o.get("archetype"),
        "side":            o.get("side"),
        "open_price":      o["open_price"],
        "close_price":     float(exit_price),
        "orig_sl":         o["orig_sl"],
        "orig_tp":         o["orig_tp"],
        "final_sl":        final_sl,
        "final_tp":        final_tp,
        "profit":          round(float(profit), 2),
        "duration_min":    round(duration_min, 1),
        "exit_reason":     exit_reason,
        "atr_h1_at_open":  o.get("atr_h1", 0),
        "hour_utc_open":   o.get("hour_utc", 0),
        "bias_h1_at_open": o.get("bias_h1", ""),
        "r_sl_moves":      len(o.get("r_sl_history", [])),
        # Effective multipliers (what actually was the SL/TP distance ÷ ATR)
        "effective_sl_atr": round(abs(o["open_price"] - final_sl) / o["atr_h1"], 2)
                            if o.get("atr_h1") else None,
        "effective_tp_atr": round(abs(o["open_price"] - final_tp) / o["atr_h1"], 2)
                            if o.get("atr_h1") else None,
    }
    # Context fingerprint — compact signature for similarity matching
    record["context_fingerprint"] = build_fingerprint(
        symbol=o.get("symbol", ""), side=o.get("side", ""),
        archetype=o.get("archetype", ""), bias_h1=o.get("bias_h1", ""),
        hour_utc=o.get("hour_utc", -1),
    )
    _append_jsonl(TRADES_FILE, record)
    # Remove from origins (closed)
    origins.pop(str(ticket), None)
    _save(ORIGINS_FILE, origins)

    # Aggregate stats
    _update_archetype_stats(record)
    # Adapt templates from user overrides + closed trades
    _adapt_from_history()

    return record


def _update_archetype_stats(record: dict):
    stats = _load(ARCH_STATS, {})
    arch = record.get("archetype") or "UNKNOWN"
    s = stats.setdefault(arch, {
        "trades": 0, "wins": 0, "losses": 0,
        "total_profit": 0.0, "total_loss_abs": 0.0,
        "avg_duration": 0.0,
        "avg_eff_sl_atr": 0.0, "avg_eff_tp_atr": 0.0,
        "best_hours": {},     # hour → net_pl
        "best_bias":  {},     # UP/DOWN/RANGE → net_pl
        "last_updated": "",
    })
    s["trades"] += 1
    if record["profit"] > 0:
        s["wins"]         += 1
        s["total_profit"] += record["profit"]
    else:
        s["losses"]         += 1
        s["total_loss_abs"] += abs(record["profit"])
    # Rolling averages
    n = s["trades"]
    s["avg_duration"] = round(((s["avg_duration"] * (n - 1)) + record["duration_min"]) / n, 1)
    if record.get("effective_sl_atr") is not None:
        s["avg_eff_sl_atr"] = round(((s["avg_eff_sl_atr"] * (n - 1)) + record["effective_sl_atr"]) / n, 3)
    if record.get("effective_tp_atr") is not None:
        s["avg_eff_tp_atr"] = round(((s["avg_eff_tp_atr"] * (n - 1)) + record["effective_tp_atr"]) / n, 3)
    # Per-hour / per-bias tracking
    h = str(record.get("hour_utc_open", -1))
    s["best_hours"][h] = round(s["best_hours"].get(h, 0) + record["profit"], 2)
    b = record.get("bias_h1_at_open", "")
    if b:
        s["best_bias"][b] = round(s["best_bias"].get(b, 0) + record["profit"], 2)
    # Derived
    s["win_rate"]      = round(s["wins"] / n * 100, 1)
    s["profit_factor"] = round(s["total_profit"] / s["total_loss_abs"], 2) if s["total_loss_abs"] > 0 else (999 if s["wins"] else 0)
    s["net_pl"]        = round(s["total_profit"] - s["total_loss_abs"], 2)
    s["last_updated"]  = datetime.now(timezone.utc).isoformat()
    stats[arch] = s
    _save(ARCH_STATS, stats)


def _adapt_from_history():
    """Update template multipliers based on closed trades + user overrides."""
    adj = _load(ADJUSTMENTS, DEFAULT_ADJ)

    # Closed-trade learning
    stats = _load(ARCH_STATS, {})
    for arch, s in stats.items():
        if s.get("trades", 0) < MIN_TRADES_TO_ADAPT: continue
        a = adj.setdefault(arch, dict(DEFAULT_ADJ.get(arch, {"sl_mult":1,"tp_mult":1,"be_trigger_factor":1})))

        # If archetype's PF is low (< 0.5), tighten SL & shorten TP (cut losses faster)
        pf = s.get("profit_factor", 1.0)
        if pf < 0.5 and pf > 0:
            a["sl_mult"] = max(0.5, a["sl_mult"] * (1 - ADAPT_ALPHA))
            a["tp_mult"] = max(0.5, a["tp_mult"] * (1 - ADAPT_ALPHA / 2))
        elif pf > 2.0:
            # winning — loosen SL slightly (give room) and extend TP (let winners run)
            a["sl_mult"] = min(2.0, a["sl_mult"] * (1 + ADAPT_ALPHA / 4))
            a["tp_mult"] = min(2.0, a["tp_mult"] * (1 + ADAPT_ALPHA / 2))
        # If user keeps making the SL tighter than R's effective, learn from it
        # (handled in user-override loop below)

    # User-override learning
    overrides = []
    if OVERRIDES_FILE.exists():
        try:
            with open(OVERRIDES_FILE, encoding="utf-8") as f:
                for line in f:
                    try: overrides.append(json.loads(line))
                    except Exception: pass
        except Exception: pass

    # Group by archetype and intent
    by_arch_intent = defaultdict(list)
    for ov in overrides[-50:]:  # last 50 overrides
        for intent in (ov.get("intents") or []):
            by_arch_intent[(ov.get("archetype"), intent)].append(ov)

    for (arch, intent), ovs in by_arch_intent.items():
        if not arch or len(ovs) < USER_OVERRIDE_THRESHOLD: continue
        a = adj.setdefault(arch, dict(DEFAULT_ADJ.get(arch, {"sl_mult":1,"tp_mult":1,"be_trigger_factor":1})))
        if intent == "TIGHTEN_SL":
            # Compute average ratio of new SL distance vs original
            ratios = []
            for ov in ovs:
                orig_dist = abs(ov["entry"] - ov["orig_sl"])
                new_dist  = abs(ov["entry"] - ov["to_sl"])
                if orig_dist > 0: ratios.append(new_dist / orig_dist)
            if ratios:
                target_mult = sum(ratios) / len(ratios)
                a["sl_mult"] = max(0.3, a["sl_mult"] * (1 - ADAPT_ALPHA) + target_mult * ADAPT_ALPHA)
        elif intent == "EXTEND_TP":
            ratios = []
            for ov in ovs:
                orig_dist = abs(ov["entry"] - ov["orig_tp"])
                new_dist  = abs(ov["entry"] - ov["to_tp"])
                if orig_dist > 0: ratios.append(new_dist / orig_dist)
            if ratios:
                target_mult = sum(ratios) / len(ratios)
                a["tp_mult"] = max(0.5, min(3.0, a["tp_mult"] * (1 - ADAPT_ALPHA) + target_mult * ADAPT_ALPHA))
        elif intent == "BREAK_EVEN_PLUS":
            # User moves SL to BE faster than R does → trigger earlier
            a["be_trigger_factor"] = max(0.3, a["be_trigger_factor"] * (1 - ADAPT_ALPHA) + 0.7 * ADAPT_ALPHA)
        elif intent == "REDUCE_TP":
            ratios = []
            for ov in ovs:
                orig_dist = abs(ov["entry"] - ov["orig_tp"])
                new_dist  = abs(ov["entry"] - ov["to_tp"])
                if orig_dist > 0: ratios.append(new_dist / orig_dist)
            if ratios:
                target_mult = sum(ratios) / len(ratios)
                a["tp_mult"] = max(0.4, a["tp_mult"] * (1 - ADAPT_ALPHA) + target_mult * ADAPT_ALPHA)

        # Round nicely
        a["sl_mult"] = round(a["sl_mult"], 3)
        a["tp_mult"] = round(a["tp_mult"], 3)
        a["be_trigger_factor"] = round(a["be_trigger_factor"], 3)

    adj["_last_adapted"] = datetime.now(timezone.utc).isoformat()
    _save(ADJUSTMENTS, adj)


def get_adjusted_multipliers(archetype: str) -> dict:
    """Return current sl_mult / tp_mult / be_trigger_factor for an archetype.
       trade_gate / r_executor read this to apply learned adjustments."""
    adj = _load(ADJUSTMENTS, DEFAULT_ADJ)
    return adj.get(archetype, DEFAULT_ADJ.get(archetype, {"sl_mult":1,"tp_mult":1,"be_trigger_factor":1}))


def get_learning_summary() -> dict:
    """For the UI."""
    stats = _load(ARCH_STATS, {})
    adj   = _load(ADJUSTMENTS, DEFAULT_ADJ)
    # Tail of trades + overrides
    trades = []; overrides = []
    if TRADES_FILE.exists():
        try:
            with open(TRADES_FILE, encoding="utf-8") as f:
                trades = [json.loads(l) for l in f.readlines()[-30:]][::-1]
        except Exception: pass
    if OVERRIDES_FILE.exists():
        try:
            with open(OVERRIDES_FILE, encoding="utf-8") as f:
                overrides = [json.loads(l) for l in f.readlines()[-30:]][::-1]
        except Exception: pass

    # Best/worst archetypes
    ranked = sorted(stats.items(), key=lambda x: -x[1].get("profit_factor", 0))
    return {
        "archetype_stats": stats,
        "adjustments":     adj,
        "recent_trades":   trades,
        "recent_overrides": overrides,
        "best_archetype":  ranked[0][0] if ranked else None,
        "worst_archetype": ranked[-1][0] if ranked and len(ranked) > 1 else None,
        "total_closed":    sum(s.get("trades", 0) for s in stats.values()),
        "total_overrides": len(overrides),
        "ts":              datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    print(json.dumps(get_learning_summary(), ensure_ascii=False, indent=2))
