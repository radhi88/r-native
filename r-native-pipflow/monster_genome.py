"""monster_genome.py — Detect "beast mode" genomes worthy of bigger lots.

A *Monster Genome* is one that:
  • trades BOTH sides (BUY + SELL) confidently with high WR on each
  • only fires when its conviction is high (avg entry-confidence ≥ 85)
  • turns trades over fast (short hold time = it's not hoping, it's executing)
  • is profitable overall (PF ≥ 2)

These are the genomes you want to ride bigger — `compute_lot_multiplier()`
returns 1.5x–2.5x for them when the live gate confidence is also at the
ceiling. Used inline by `r_executor.try_enter_trade`.

CLI:
  python -m r_native.monster_genome scan
  python -m r_native.monster_genome classify B99880
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from r_native.genome_asymmetry import (
    _load_decisions, _pair_trades, side_stats, DECISION_LOG_DIR,
)

HOF_INDEX = Path(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame\index.json")
MONSTERS_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\monster_genomes.json")

# Qualification thresholds (tuned conservatively — false positives are expensive)
MONSTER_MIN_TRADES        = 10
MONSTER_MIN_SIDE_TRADES   = 3
MONSTER_MIN_SIDE_WR       = 0.70
MONSTER_MIN_AVG_CONF      = 85.0
MONSTER_MAX_HOLD_MIN      = 60.0
MONSTER_MIN_PF            = 2.0
MONSTER_LOT_CAP_X         = 2.5
MONSTER_LIVE_CONF_FLOOR   = 95     # live gate must agree with this much conviction


# ───────────────────────────────────────────────────────────────────────
# Profile extraction
# ───────────────────────────────────────────────────────────────────────

def profile(genome_id: str) -> dict:
    """Compute all the numbers needed to judge a genome's monster status."""
    events  = _load_decisions(genome_id)
    closed  = _pair_trades(events)
    opens   = [e for e in events if e.get("kind") == "OPEN"]

    side = side_stats(genome_id)
    total = side["total_trades"]

    # Average confidence at OPEN
    confs = [int(o.get("confidence") or 0) for o in opens
             if o.get("confidence") is not None]
    avg_conf = round(statistics.mean(confs), 1) if confs else 0.0
    median_conf = round(statistics.median(confs), 1) if confs else 0.0

    # Hold time (minutes) — only from closed trades with both timestamps
    holds = []
    for tr in closed:
        ts_o = tr.get("ts")
        ts_c = tr.get("ts_close")
        if not ts_o or not ts_c: continue
        try:
            to = datetime.fromisoformat(ts_o.replace("Z", "+00:00"))
            tc = datetime.fromisoformat(ts_c.replace("Z", "+00:00"))
            holds.append((tc - to).total_seconds() / 60)
        except Exception: continue
    avg_hold_min = round(statistics.mean(holds), 1) if holds else None
    median_hold_min = round(statistics.median(holds), 1) if holds else None

    # Combined PF across both sides
    gw = side["buy"]["net_pl"] if side["buy"]["net_pl"] > 0 else 0
    gw += side["sell"]["net_pl"] if side["sell"]["net_pl"] > 0 else 0
    gl = abs(side["buy"]["net_pl"]) if side["buy"]["net_pl"] < 0 else 0
    gl += abs(side["sell"]["net_pl"]) if side["sell"]["net_pl"] < 0 else 0
    # Use sum of gross from individual side's PF if simpler — but net_pl already net.
    # Recompute from gross via summing all closed trades:
    gross_win = sum(float(t.get("profit") or 0) for t in closed if float(t.get("profit") or 0) > 0)
    gross_loss = sum(abs(float(t.get("profit") or 0)) for t in closed if float(t.get("profit") or 0) < 0)
    combined_pf = (round(gross_win / gross_loss, 2)
                   if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0))

    return {
        "genome_id":         genome_id,
        "total_trades":      total,
        "buy_trades":        side["buy"]["trades"],
        "sell_trades":       side["sell"]["trades"],
        "buy_win_rate":      side["buy"]["win_rate"],
        "sell_win_rate":     side["sell"]["win_rate"],
        "buy_pf":            side["buy"]["profit_factor"],
        "sell_pf":           side["sell"]["profit_factor"],
        "combined_pf":       combined_pf,
        "avg_confidence":    avg_conf,
        "median_confidence": median_conf,
        "avg_hold_min":      avg_hold_min,
        "median_hold_min":   median_hold_min,
        "net_pl":            round(gross_win - gross_loss, 2),
    }


def classify(genome_id: str) -> dict:
    """Return verdict + monster_score + reasons. Always returns a dict."""
    p = profile(genome_id)
    reasons: list[str] = []
    fails: list[str]   = []

    if p["total_trades"] < MONSTER_MIN_TRADES:
        fails.append(f"only {p['total_trades']} closed trades (need ≥{MONSTER_MIN_TRADES})")
    if p["buy_trades"] < MONSTER_MIN_SIDE_TRADES:
        fails.append(f"BUY trades {p['buy_trades']} < {MONSTER_MIN_SIDE_TRADES}")
    if p["sell_trades"] < MONSTER_MIN_SIDE_TRADES:
        fails.append(f"SELL trades {p['sell_trades']} < {MONSTER_MIN_SIDE_TRADES}")
    if p["buy_win_rate"] < MONSTER_MIN_SIDE_WR:
        fails.append(f"BUY WR {p['buy_win_rate']*100:.0f}% < {int(MONSTER_MIN_SIDE_WR*100)}%")
    if p["sell_win_rate"] < MONSTER_MIN_SIDE_WR:
        fails.append(f"SELL WR {p['sell_win_rate']*100:.0f}% < {int(MONSTER_MIN_SIDE_WR*100)}%")
    if p["avg_confidence"] < MONSTER_MIN_AVG_CONF:
        fails.append(f"avg conf {p['avg_confidence']} < {MONSTER_MIN_AVG_CONF}")
    if p["avg_hold_min"] is None:
        fails.append("no hold-time samples")
    elif p["avg_hold_min"] > MONSTER_MAX_HOLD_MIN:
        fails.append(f"avg hold {p['avg_hold_min']}m > {MONSTER_MAX_HOLD_MIN}m")
    pf = p["combined_pf"]
    if pf < MONSTER_MIN_PF:
        fails.append(f"PF {pf} < {MONSTER_MIN_PF}")

    is_monster = len(fails) == 0
    # Composite monster_score (only meaningful when qualified, but always returned)
    bal = min(p["buy_win_rate"], p["sell_win_rate"])
    aggr = p["avg_confidence"] / 100.0
    speed = (max(0.0, 1.0 - (p["avg_hold_min"] or 999) / 120.0)
             if p["avg_hold_min"] is not None else 0.0)
    sample = (p["total_trades"]) ** 0.5
    pf_factor = min(5.0, p["combined_pf"]) / 2.0
    monster_score = round(bal * aggr * speed * sample * pf_factor, 3)

    if is_monster:
        reasons.append(
            f"🔥 BUY {p['buy_win_rate']*100:.0f}% / SELL {p['sell_win_rate']*100:.0f}%"
            f" · avg conf {p['avg_confidence']} · hold {p['avg_hold_min']}m · PF {p['combined_pf']}")
    else:
        reasons.extend(fails)

    return {
        "genome_id":     genome_id,
        "is_monster":    is_monster,
        "monster_score": monster_score,
        "profile":       p,
        "reasons":       reasons,
    }


# ───────────────────────────────────────────────────────────────────────
# Lot multiplier — called from r_executor at order time
# ───────────────────────────────────────────────────────────────────────

def compute_lot_multiplier(genome_id: Optional[str], live_confidence: int) -> tuple[float, str]:
    """How much to multiply the base lot for this entry.

    Returns (multiplier, reason). Multiplier ranges 1.0 → MONSTER_LOT_CAP_X.
    Only scales up when BOTH:
      • genome qualifies as a monster
      • live gate conviction ≥ MONSTER_LIVE_CONF_FLOOR

    The multiplier interpolates linearly between 1.0 (at conf=floor) and
    MONSTER_LOT_CAP_X (at conf=100), so 100% conviction = full beast mode.
    """
    if not genome_id:
        return 1.0, "no genome"
    try:
        c = classify(genome_id)
    except Exception as e:
        return 1.0, f"classify err {e}"
    if not c.get("is_monster"):
        return 1.0, "not yet qualified as monster"
    if live_confidence < MONSTER_LIVE_CONF_FLOOR:
        return 1.0, f"live conf {live_confidence} < monster floor {MONSTER_LIVE_CONF_FLOOR}"
    # Linear ramp: conf 95 → 1.0×, conf 100 → MONSTER_LOT_CAP_X
    span = (100 - MONSTER_LIVE_CONF_FLOOR) or 1
    t    = max(0.0, min(1.0, (live_confidence - MONSTER_LIVE_CONF_FLOOR) / span))
    mult = round(1.0 + t * (MONSTER_LOT_CAP_X - 1.0), 2)
    return mult, f"🔥 monster (score {c['monster_score']}) × live conf {live_confidence}"


# ───────────────────────────────────────────────────────────────────────
# Scanner — find all monsters across decision_log
# ───────────────────────────────────────────────────────────────────────

def scan_all() -> dict:
    """Walk every genome with a decision_log file. Persist monster list."""
    if not DECISION_LOG_DIR.exists():
        return {"ok": False, "reason": "no decision_log dir"}
    monsters: list[dict] = []
    near: list[dict] = []
    for p in DECISION_LOG_DIR.glob("*.jsonl"):
        gid = p.stem
        if gid.startswith("_NONE") or gid.startswith("TEST_"): continue
        try: c = classify(gid)
        except Exception: continue
        row = {"id": gid,
               "is_monster":    c["is_monster"],
               "monster_score": c["monster_score"],
               **{k: c["profile"][k] for k in
                  ("total_trades", "buy_win_rate", "sell_win_rate",
                   "avg_confidence", "avg_hold_min", "combined_pf")}}
        if c["is_monster"]:
            monsters.append(row)
        elif (c["profile"]["total_trades"] >= MONSTER_MIN_TRADES
              and c["monster_score"] >= 1.0):
            near.append({**row, "fails": c["reasons"]})
    monsters.sort(key=lambda r: -r["monster_score"])
    near.sort(key=lambda r: -r["monster_score"])
    # Persist for the UI badge to read fast
    try:
        MONSTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        MONSTERS_PATH.write_text(json.dumps({
            "ts":       datetime.now(timezone.utc).isoformat(),
            "monsters": monsters,
            "near":     near[:10],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass
    return {"ok": True, "monster_count": len(monsters),
            "near_count": len(near),
            "monsters": monsters, "near": near[:10]}


def load_monster_ids() -> set:
    """Fast lookup used by UI badge logic — returns set of monster genome IDs."""
    if not MONSTERS_PATH.exists(): return set()
    try:
        d = json.loads(MONSTERS_PATH.read_text(encoding="utf-8"))
        return {m["id"] for m in (d.get("monsters") or [])}
    except Exception:
        return set()


# ───────────────────────────────────────────────────────────────────────
# CLI
# ───────────────────────────────────────────────────────────────────────

def _cli():
    import argparse, time
    ap = argparse.ArgumentParser(prog="r_native.monster_genome")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="classify all genomes and persist monster list")
    p_cls = sub.add_parser("classify", help="classify one genome verbose")
    p_cls.add_argument("genome_id")
    p_prof = sub.add_parser("profile", help="raw profile numbers")
    p_prof.add_argument("genome_id")
    p_mult = sub.add_parser("multiplier",
                             help="compute lot multiplier for genome+live-conf")
    p_mult.add_argument("genome_id")
    p_mult.add_argument("live_confidence", type=int)
    p_dmn = sub.add_parser("daemon",
                            help="loop scan every --interval-min minutes")
    p_dmn.add_argument("--interval-min", type=int, default=5)
    args = ap.parse_args()

    if args.cmd == "daemon":
        print(f"[monster] daemon — every {args.interval_min} min", flush=True)
        while True:
            try:
                r = scan_all()
                print(f"[{datetime.now(timezone.utc):%H:%M:%S}] "
                      f"monsters={r.get('monster_count')} "
                      f"near={r.get('near_count')}", flush=True)
            except Exception as e:
                print(f"[monster] err: {e}", flush=True)
            time.sleep(args.interval_min * 60)
        return

    if args.cmd == "scan":
        out = scan_all()
    elif args.cmd == "classify":
        out = classify(args.genome_id)
    elif args.cmd == "profile":
        out = profile(args.genome_id)
    elif args.cmd == "multiplier":
        m, why = compute_lot_multiplier(args.genome_id, args.live_confidence)
        out = {"multiplier": m, "reason": why}
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    _cli()
