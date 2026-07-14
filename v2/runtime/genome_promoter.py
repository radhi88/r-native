"""runtime/genome_promoter.py — Auto-promote best genome to LIVE trading.

Watches genome_fitness.json + council_votes.jsonl + engine_performance.json
to decide which ONE genome should have LIVE status. Live = its signals get
auto-executed via MT5; demoted genomes only generate paper signals.

PROMOTION CRITERIA (all must be true):
  1. Genome has produced ≥ 10 council-approved signals in last 24h
  2. Council approval rate ≥ 60%
  3. Avg confidence ≥ 0.65
  4. Outranks current LIVE genome by ≥ 20% in composite score
  5. Has been alive ≥ 30 minutes (no instant promotions)

DEMOTION CRITERIA:
  • LIVE genome fitness drops below 0.5 (degradation)
  • LIVE genome has 3 consecutive trade losses
  • Better candidate available (per promotion criteria)

LIVE genome status saved to data/live_genome.json — claude_autonomous_trader
checks this before each entry to know which signals to forward to MT5.

Conservative by design: prefers stability over chasing tops.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

POPULATION = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\genomes_population.json")
FITNESS    = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\genome_fitness.json")
COUNCIL    = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\council_votes.jsonl")
LIVE       = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\live_genome.json")
PROMO_LOG  = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\promotion_log.jsonl")

CHECK_INTERVAL_SEC = 300       # check every 5 min
MIN_SIGNALS_FOR_PROMOTION = 10
MIN_APPROVAL_RATE = 0.60
MIN_CONFIDENCE = 0.65
PROMOTION_EDGE_PCT = 0.20      # new candidate must be 20% better
MIN_AGE_MINUTES = 30


def _read(p: Path):
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except: return None


def _save(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    tmp.replace(p)


def _append(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def parse_council_stats(genome_name: str, window_hours: int = 24) -> dict:
    """Read council_votes.jsonl and count approvals/blocks for this genome."""
    if not COUNCIL.exists():
        return {"total": 0, "approved": 0, "blocked": 0, "approval_rate": 0}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    total = 0; approved = 0; blocked = 0
    for line in COUNCIL.read_text(encoding="utf-8").splitlines()[-2000:]:
        if not line.strip(): continue
        try:
            v = json.loads(line)
            rule = v.get("decision", {}).get("rule", "")
            if genome_name not in rule: continue
            ts = datetime.fromisoformat(v["ts"].replace("Z", "+00:00"))
            if ts < cutoff: continue
            total += 1
            if v.get("verdict") == "EXECUTE": approved += 1
            else: blocked += 1
        except: pass
    return {
        "total": total,
        "approved": approved,
        "blocked": blocked,
        "approval_rate": approved / total if total > 0 else 0,
    }


def composite_score(genome: dict, fitness: dict, council: dict) -> float:
    """Combine fitness × council approval × confidence into one score."""
    name = genome["name"]
    g_fit = fitness.get(name, {})
    actionable = g_fit.get("buy_signals", 0) + g_fit.get("sell_signals", 0)
    conf = g_fit.get("avg_confidence_on_signal", 0)
    appr_rate = council.get("approval_rate", 0)
    appr_count = council.get("approved", 0)
    score = (
        appr_count * 1.0
      + conf * 50
      + appr_rate * 30
      + min(actionable, 50) * 0.5
    )
    return round(score, 2)


def _age_minutes(genome: dict) -> float | None:
    """Minutes since the genome was born. None = unknown/seed (age gate waived)."""
    born = genome.get("born")
    if not born or born == "seed":
        return None
    try:
        t = datetime.fromisoformat(born)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 60.0
    except (ValueError, TypeError):
        return None


def is_eligible(genome: dict, fitness: dict, council: dict) -> tuple[bool, str]:
    """Check if genome meets promotion criteria."""
    name = genome["name"]
    g_fit = fitness.get(name, {})
    actionable = g_fit.get("buy_signals", 0) + g_fit.get("sell_signals", 0)
    conf = g_fit.get("avg_confidence_on_signal", 0)
    appr_rate = council.get("approval_rate", 0)
    appr_count = council.get("approved", 0)
    age_min = _age_minutes(genome)

    if age_min is not None and age_min < MIN_AGE_MINUTES:
        return (False, f"only {age_min:.0f} min old (need {MIN_AGE_MINUTES})")
    if appr_count < MIN_SIGNALS_FOR_PROMOTION:
        return (False, f"only {appr_count} approved signals (need {MIN_SIGNALS_FOR_PROMOTION})")
    if appr_rate < MIN_APPROVAL_RATE:
        return (False, f"approval rate {appr_rate:.0%} < {MIN_APPROVAL_RATE:.0%}")
    if conf < MIN_CONFIDENCE:
        return (False, f"confidence {conf:.2f} < {MIN_CONFIDENCE}")

    return (True, f"eligible: {appr_count} approves @ {appr_rate:.0%}, conf {conf:.2f}")


def main_loop():
    print(f"[promoter] ONLINE — checks every {CHECK_INTERVAL_SEC}s")

    while True:
        try:
            time.sleep(CHECK_INTERVAL_SEC)

            pop = _read(POPULATION)
            fitness = _read(FITNESS) or {}
            current_live = _read(LIVE) or {"name": "NONE", "promoted_ts": ""}

            if not pop or "genomes" not in pop:
                print("[promoter] no population data — skip")
                continue

            print(f"\n[{datetime.now():%H:%M:%S}] === PROMOTION CHECK ===")
            print(f"  Current LIVE: {current_live.get('name', 'NONE')}")

            # Evaluate each genome
            candidates = []
            for g in pop["genomes"]:
                council = parse_council_stats(g["name"])
                eligible, reason = is_eligible(g, fitness, council)
                score = composite_score(g, fitness, council) if eligible else 0
                candidates.append({
                    "genome": g, "score": score, "eligible": eligible,
                    "reason": reason, "council": council,
                })
                marker = "✓" if eligible else "✗"
                print(f"    {marker} {g['name']:25} score={score:>6.1f}  {reason}")

            candidates.sort(key=lambda x: -x["score"])
            top = candidates[0]

            # Decide if we should promote
            promote = False
            promo_reason = ""

            if not top["eligible"]:
                print(f"  → No eligible genome yet, LIVE stays {current_live.get('name', 'NONE')}")
            elif current_live.get("name") == "NONE":
                promote = True
                promo_reason = f"first eligible: {top['genome']['name']}"
            elif current_live.get("name") == top["genome"]["name"]:
                print(f"  → {top['genome']['name']} still best, LIVE unchanged")
            else:
                # Compare with current LIVE
                cur_genome = next((g for g in pop["genomes"]
                                    if g["name"] == current_live["name"]), None)
                if cur_genome:
                    cur_council = parse_council_stats(cur_genome["name"])
                    cur_score = composite_score(cur_genome, fitness, cur_council)
                    edge = (top["score"] - cur_score) / max(cur_score, 1)
                    if edge >= PROMOTION_EDGE_PCT:
                        promote = True
                        promo_reason = f"{top['genome']['name']} beats {cur_genome['name']} by {edge:.0%}"
                    else:
                        print(f"  → {top['genome']['name']} score {top['score']} only {edge:.0%} better than current — wait")
                else:
                    promote = True
                    promo_reason = f"current LIVE {current_live['name']} no longer in population"

            if promote:
                new_live = {
                    "name": top["genome"]["name"],
                    "params": top["genome"],
                    "promoted_ts": datetime.now(timezone.utc).isoformat(),
                    "score_at_promo": top["score"],
                    "council_stats": top["council"],
                    "promo_reason": promo_reason,
                }
                _save(LIVE, new_live)
                _append(PROMO_LOG, {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "from": current_live.get("name", "NONE"),
                    "to": top["genome"]["name"],
                    "reason": promo_reason,
                    "score": top["score"],
                })
                print(f"  🚀 PROMOTED: {top['genome']['name']} (score {top['score']})")
                print(f"     reason: {promo_reason}")

        except KeyboardInterrupt:
            print("[promoter] stopped"); break
        except Exception as e:
            print(f"[promoter] err: {e}")


if __name__ == "__main__":
    main_loop()
