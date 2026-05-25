"""genome_asymmetry.py — Track per-genome BUY vs SELL performance.

A genome can be brilliant on BUY but mediocre on SELL (or vice versa). When
overall WR or PF looks weak, naively killing it discards a directional
specialist that just needs a complementary partner.

This module reads the per-genome decision_log JSONL files and produces:
  • side_stats(): wins / losses / WR / PF split by BUY vs SELL
  • is_kill_protected(): True if genome is a directional specialist worth keeping
  • find_complement(): scan HoF for an opposite-side specialist on the same symbol
  • suggest_ensemble(): proposed deployed_genomes list combining the two
  • protect_in_hof(): writes "directional_specialist" flag into the HoF entry

Public read endpoints can be wired into brain_server later; for now the CLI
prints JSON.

Thresholds (tunable):
  SPECIALIST_MIN_TRADES_SIDE   minimum trades on the specialty side
  SPECIALIST_MIN_WR_SIDE       win-rate floor for being called a specialist
  SPECIALIST_DOMINANCE         specialty side must account for ≥ this fraction
                               of total trades (so we don't promote pure luck)
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DECISION_LOG_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\decision_log")
HOF_INDEX        = Path(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame\index.json")
HOF_BY_SYMBOL    = Path(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame\by_symbol")

SPECIALIST_MIN_TRADES_SIDE = 5
SPECIALIST_MIN_WR_SIDE     = 0.65
SPECIALIST_DOMINANCE       = 0.70


# ───────────────────────────────────────────────────────────────────────
# Decision-log parsing
# ───────────────────────────────────────────────────────────────────────

def _load_decisions(genome_id: str) -> list[dict]:
    """Return all OPEN/CLOSE events for this genome from its jsonl file."""
    p = DECISION_LOG_DIR / f"{genome_id}.jsonl"
    if not p.exists(): return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line: continue
        try: out.append(json.loads(line))
        except Exception: continue
    return out


def _pair_trades(events: list[dict]) -> list[dict]:
    """Pair each OPEN with its matching CLOSE by ticket. Returns closed trades only."""
    opens = {e["ticket"]: e for e in events
             if e.get("kind") == "OPEN" and e.get("ticket")}
    pairs = []
    for e in events:
        if e.get("kind") != "CLOSE": continue
        o = opens.get(e.get("ticket"))
        if not o: continue
        pairs.append({**o, **{
            "ts_close":     e.get("ts"),
            "exit_price":   e.get("exit_price"),
            "profit":       float(e.get("profit") or 0),
            "exit_reason":  e.get("exit_reason"),
        }})
    return pairs


# ───────────────────────────────────────────────────────────────────────
# Per-genome side stats
# ───────────────────────────────────────────────────────────────────────

def side_stats(genome_id: str) -> dict:
    """Compute WR / PF / net P/L split by side for a genome."""
    closed = _pair_trades(_load_decisions(genome_id))
    buckets = {"BUY":  {"trades": [], "wins": 0, "losses": 0,
                         "gross_win": 0.0, "gross_loss": 0.0},
               "SELL": {"trades": [], "wins": 0, "losses": 0,
                         "gross_win": 0.0, "gross_loss": 0.0}}
    for tr in closed:
        side = tr.get("side")
        if side not in buckets: continue
        pl = float(tr.get("profit") or 0)
        b = buckets[side]
        b["trades"].append(tr)
        if pl > 0:
            b["wins"] += 1; b["gross_win"] += pl
        else:
            b["losses"] += 1; b["gross_loss"] += abs(pl)

    def _wr(b): return round(b["wins"] / max(1, len(b["trades"])), 3)
    def _pf(b): return (round(b["gross_win"] / b["gross_loss"], 2)
                        if b["gross_loss"] > 0
                        else (float("inf") if b["gross_win"] > 0 else 0.0))
    def _net(b): return round(b["gross_win"] - b["gross_loss"], 2)

    total_trades = len(buckets["BUY"]["trades"]) + len(buckets["SELL"]["trades"])
    return {
        "genome_id": genome_id,
        "total_trades": total_trades,
        "buy":  {"trades": len(buckets["BUY"]["trades"]),
                 "wins":   buckets["BUY"]["wins"],
                 "losses": buckets["BUY"]["losses"],
                 "win_rate":      _wr(buckets["BUY"]),
                 "profit_factor": _pf(buckets["BUY"]),
                 "net_pl":        _net(buckets["BUY"])},
        "sell": {"trades": len(buckets["SELL"]["trades"]),
                 "wins":   buckets["SELL"]["wins"],
                 "losses": buckets["SELL"]["losses"],
                 "win_rate":      _wr(buckets["SELL"]),
                 "profit_factor": _pf(buckets["SELL"]),
                 "net_pl":        _net(buckets["SELL"])},
    }


# ───────────────────────────────────────────────────────────────────────
# Specialist classification + kill protection
# ───────────────────────────────────────────────────────────────────────

def classify(genome_id: str) -> dict:
    """Decide whether this genome is a BUY/SELL specialist or balanced.

    Returns:
      {
        type: "BUY_SPECIALIST" | "SELL_SPECIALIST" | "BALANCED" | "WEAK" | "UNKNOWN",
        specialty_side: "BUY" | "SELL" | null,
        confidence: 0..1,
        protected: bool,
        reasons: [str, ...]
      }
    """
    s = side_stats(genome_id)
    total = s["total_trades"]
    reasons: list[str] = []
    if total < SPECIALIST_MIN_TRADES_SIDE:
        return {"genome_id": genome_id, "type": "UNKNOWN",
                "specialty_side": None, "confidence": 0.0,
                "protected": False,
                "reasons": [f"only {total} closed trades — need ≥{SPECIALIST_MIN_TRADES_SIDE}"]}

    buy_t  = s["buy"]["trades"]
    sell_t = s["sell"]["trades"]
    buy_wr  = s["buy"]["win_rate"]
    sell_wr = s["sell"]["win_rate"]
    buy_pf  = s["buy"]["profit_factor"]
    sell_pf = s["sell"]["profit_factor"]

    def _is_specialist(side_trades, side_wr, side_pf, opp_trades):
        if side_trades < SPECIALIST_MIN_TRADES_SIDE: return False
        if side_wr < SPECIALIST_MIN_WR_SIDE: return False
        if side_trades < (side_trades + opp_trades) * SPECIALIST_DOMINANCE: return False
        return True

    buy_spec  = _is_specialist(buy_t,  buy_wr,  buy_pf,  sell_t)
    sell_spec = _is_specialist(sell_t, sell_wr, sell_pf, buy_t)

    if buy_spec and not sell_spec:
        reasons.append(f"BUY: {s['buy']['wins']}/{buy_t} ({buy_wr*100:.0f}% WR, PF {buy_pf})")
        reasons.append(f"SELL underused: {sell_t} trades")
        return {"genome_id": genome_id, "type": "BUY_SPECIALIST",
                "specialty_side": "BUY",
                "confidence": min(1.0, (buy_wr - 0.5) * 2),
                "protected": True, "reasons": reasons,
                "stats": s}
    if sell_spec and not buy_spec:
        reasons.append(f"SELL: {s['sell']['wins']}/{sell_t} ({sell_wr*100:.0f}% WR, PF {sell_pf})")
        reasons.append(f"BUY underused: {buy_t} trades")
        return {"genome_id": genome_id, "type": "SELL_SPECIALIST",
                "specialty_side": "SELL",
                "confidence": min(1.0, (sell_wr - 0.5) * 2),
                "protected": True, "reasons": reasons,
                "stats": s}
    if buy_spec and sell_spec:
        reasons.append("strong on both sides — balanced winner")
        return {"genome_id": genome_id, "type": "BALANCED",
                "specialty_side": None, "confidence": 0.9,
                "protected": True, "reasons": reasons, "stats": s}
    # Neither side qualifies → weak
    avg_wr = ((s["buy"]["wins"] + s["sell"]["wins"]) / max(1, total))
    if avg_wr < 0.4:
        reasons.append(f"weak both sides: avg WR {avg_wr*100:.0f}%")
        return {"genome_id": genome_id, "type": "WEAK",
                "specialty_side": None, "confidence": 0.0,
                "protected": False, "reasons": reasons, "stats": s}
    reasons.append(f"mediocre both sides — WR {avg_wr*100:.0f}%")
    return {"genome_id": genome_id, "type": "BALANCED",
            "specialty_side": None, "confidence": 0.3,
            "protected": False, "reasons": reasons, "stats": s}


def is_kill_protected(genome_id: str) -> tuple[bool, str]:
    """Quick yes/no with one-line reason. Used by hof.kill() guards."""
    c = classify(genome_id)
    if c["protected"]:
        return True, f"{c['type']}: {'; '.join(c['reasons'])}"
    return False, c['reasons'][0] if c["reasons"] else "no protection"


# ───────────────────────────────────────────────────────────────────────
# Complement finder
# ───────────────────────────────────────────────────────────────────────

def _hof_entries_for_symbol(symbol: str) -> list[dict]:
    p = HOF_BY_SYMBOL / f"{symbol}.json"
    if not p.exists(): return []
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return []


def find_complement(genome_id: str, max_results: int = 5) -> list[dict]:
    """Given a genome that's a directional specialist, find HoF candidates
    on the same symbol that specialize in the OPPOSITE direction.

    Returns a list ranked by complement quality (their side's WR + PF).
    Each result includes: id, specialty_side, win_rate, profit_factor,
    live_trades_on_opposite, complement_score.
    """
    cls = classify(genome_id)
    if not cls.get("protected") or not cls.get("specialty_side"):
        return []
    needed_side = "SELL" if cls["specialty_side"] == "BUY" else "BUY"

    # Find this genome's symbol from HoF (if registered) or from decisions
    symbol = None
    try:
        idx = json.loads(HOF_INDEX.read_text(encoding="utf-8")) if HOF_INDEX.exists() else {}
        symbol = (idx.get(genome_id) or {}).get("symbol")
    except Exception: pass
    if not symbol:
        d = _load_decisions(genome_id)
        if d: symbol = next((e.get("symbol") for e in d if e.get("symbol")), None)
    if not symbol: return []

    # Scan all HoF entries on same symbol, skip self + killed
    pool = _hof_entries_for_symbol(symbol)
    candidates = []
    for entry in pool:
        cid = entry.get("id")
        if not cid or cid == genome_id: continue
        if entry.get("killed"): continue
        c_class = classify(cid)
        # Only complement candidates: opposite specialty OR balanced+winning
        if c_class["type"] == f"{needed_side}_SPECIALIST":
            c_score = c_class["confidence"]
        elif c_class["type"] == "BALANCED" and c_class["confidence"] >= 0.7:
            c_score = c_class["confidence"] * 0.7   # discount balanced vs pure specialist
        else:
            continue
        side_data = c_class["stats"][needed_side.lower()] if c_class.get("stats") else {}
        candidates.append({
            "id":                cid,
            "type":              c_class["type"],
            "needed_side":       needed_side,
            "complement_score":  round(c_score, 3),
            "win_rate":          side_data.get("win_rate"),
            "profit_factor":     side_data.get("profit_factor"),
            "trades_on_side":    side_data.get("trades"),
            "backtest_pf":       entry.get("score"),
        })
    candidates.sort(key=lambda c: -c["complement_score"])
    return candidates[:max_results]


def suggest_ensemble(genome_id: str) -> dict:
    """Propose a deployed_genomes entry combining the genome + its best complement."""
    cls = classify(genome_id)
    comps = find_complement(genome_id, max_results=3)
    if not comps:
        return {"ok": False, "genome_id": genome_id,
                "reason": "no suitable complement found",
                "classification": cls}
    best = comps[0]
    return {
        "ok": True,
        "primary":     {"id": genome_id, "specialty": cls.get("specialty_side"),
                         "wr": cls.get("stats", {}).get(
                             (cls.get("specialty_side") or "").lower(),
                             {}).get("win_rate")},
        "complement":  {"id": best["id"], "specialty": cls["specialty_side"] == "BUY"
                                                       and "SELL" or "BUY",
                         "wr": best.get("win_rate")},
        "deployed_genomes_payload": [
            {"id": genome_id, "weight": 1.0},
            {"id": best["id"], "weight": 0.8},
        ],
        "alternatives": comps[1:],
    }


# ───────────────────────────────────────────────────────────────────────
# HoF guard integration
# ───────────────────────────────────────────────────────────────────────

def protect_in_hof(genome_id: str) -> bool:
    """Write the kill-protection flag back into the HoF entry. Returns True if updated."""
    if not HOF_INDEX.exists(): return False
    try: idx = json.loads(HOF_INDEX.read_text(encoding="utf-8"))
    except Exception: return False
    if genome_id not in idx: return False
    cls = classify(genome_id)
    entry = idx[genome_id]
    entry["directional_specialist"] = cls.get("specialty_side")
    entry["kill_protected"]         = bool(cls.get("protected"))
    entry["asymmetry_classified_at"] = datetime.now(timezone.utc).isoformat()
    idx[genome_id] = entry
    HOF_INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return True


def scan_and_protect_all() -> dict:
    """Walk every genome with a decision_log file, classify, persist protection flag."""
    if not DECISION_LOG_DIR.exists():
        return {"ok": False, "reason": "no decision_log dir"}
    summary = {"scanned": 0, "protected": 0, "weak": 0, "unknown": 0,
               "by_type": defaultdict(int), "protected_ids": []}
    for p in DECISION_LOG_DIR.glob("*.jsonl"):
        gid = p.stem
        if gid.startswith("_NONE") or gid.startswith("TEST_"): continue
        summary["scanned"] += 1
        c = classify(gid)
        summary["by_type"][c["type"]] += 1
        if c["type"] in ("WEAK",): summary["weak"] += 1
        if c["type"] == "UNKNOWN": summary["unknown"] += 1
        if c["protected"]:
            summary["protected"] += 1
            summary["protected_ids"].append(gid)
            protect_in_hof(gid)
    summary["by_type"] = dict(summary["by_type"])
    return summary


# ───────────────────────────────────────────────────────────────────────
# CLI
# ───────────────────────────────────────────────────────────────────────

def _cli():
    import argparse, time
    ap = argparse.ArgumentParser(prog="r_native.genome_asymmetry")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan-all", help="classify every genome with a decision_log")
    p_stats = sub.add_parser("stats", help="side stats for one genome")
    p_stats.add_argument("genome_id")
    p_class = sub.add_parser("classify", help="classify one genome + show reasons")
    p_class.add_argument("genome_id")
    p_comp = sub.add_parser("complement",
                            help="find complementary genome for ensemble")
    p_comp.add_argument("genome_id")
    p_sugg = sub.add_parser("suggest", help="suggest a 2-genome ensemble")
    p_sugg.add_argument("genome_id")
    p_dmn = sub.add_parser("daemon",
                            help="loop scan-all every --interval-min minutes")
    p_dmn.add_argument("--interval-min", type=int, default=5)
    args = ap.parse_args()

    if args.cmd == "daemon":
        print(f"[asymmetry] daemon — every {args.interval_min} min", flush=True)
        while True:
            try:
                r = scan_and_protect_all()
                print(f"[{datetime.now(timezone.utc):%H:%M:%S}] scanned={r.get('scanned')}"
                      f" protected={r.get('protected')} weak={r.get('weak')}",
                      flush=True)
            except Exception as e:
                print(f"[asymmetry] err: {e}", flush=True)
            time.sleep(args.interval_min * 60)
        return

    out = None
    if args.cmd == "scan-all":
        out = scan_and_protect_all()
    elif args.cmd == "stats":
        out = side_stats(args.genome_id)
    elif args.cmd == "classify":
        out = classify(args.genome_id)
    elif args.cmd == "complement":
        out = find_complement(args.genome_id)
    elif args.cmd == "suggest":
        out = suggest_ensemble(args.genome_id)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    _cli()
