"""runtime/trader_orchestrator.py — Master controller for all 8 trader engines.

Born 2026-05-28 to stop the "8 traders fighting" problem.

WHAT IT DOES:
  1. Reads market_regime.json (TREND_UP/TREND_DOWN/CHOP/SPIKE)
  2. Reads engine_performance.json (which engine wins per regime)
  3. Reads live_genome.json (currently promoted genome)
  4. Decides which engine(s) should be ACTIVE this minute
  5. Writes data/trader_orchestrator.json — each engine reads this and self-disables

PRINCIPLE:
  Only the BEST-FITTING engine for current regime trades.
  Others go on standby (no new entries, manage existing only).

TRADER PROFILES:
  • claude_simple   (99780): aggressive, fits TREND_UP/DOWN only
  • claude_smart    (99781): defensive w/ filters, fits TRANSITION + LIGHT_TREND
  • claude_genome   (99782): evolved best, fits whatever genome was trained on
  • claude_auto     (99777): 7 rules, fits niche setups
  • palace_council  (99779): vote-based, fits high-confluence only
  • FRIDAY_brain    (20260600): LLM brain orders, fits structured signals

  In CHOP/SPIKE: ALL on standby.
  In TREND: enable genome (always) + best historical performer.
  In TRANSITION: enable smart only.

Writes data/active_engines.json — each trader checks this before firing.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

REGIME_FILE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\market_regime.json")
PERF_FILE   = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\engine_performance.json")
GENOME_FILE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\live_genome.json")
OUTPUT      = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\active_engines.json")
DECISION_LOG = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\orchestrator_decisions.jsonl")
POLL = 15.0  # decide every 15s

# Engine catalog
ENGINES = {
    99777: {"name": "claude_auto",      "type": "rules",   "aggressive": False},
    99778: {"name": "CLAUDE_BRAIN_EA",  "type": "rules",   "aggressive": False},
    99779: {"name": "palace_council",   "type": "vote",    "aggressive": False},
    99780: {"name": "claude_simple",    "type": "rules",   "aggressive": True},
    99781: {"name": "claude_smart",     "type": "rules",   "aggressive": False},
    99782: {"name": "claude_genome",    "type": "evolved", "aggressive": True},
    20260600: {"name": "FRIDAY_brain",  "type": "llm",     "aggressive": False},
    20260605: {"name": "algory_sniper", "type": "rules",   "aggressive": True},
}


def _save(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(p)


def _append(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def _read(p: Path) -> dict | None:
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except: return None


def decide(regime_data: dict, perf_data: dict, genome_data: dict) -> dict:
    """Return list of active magic numbers + reasoning."""
    regime = regime_data.get("regime", "TRANSITION") if regime_data else "TRANSITION"
    active = []
    reasons = []

    # CHOP / SPIKE → all standby
    if regime in ("CHOP", "SPIKE"):
        return {
            "regime": regime,
            "active_magics": [],
            "standby_magics": list(ENGINES.keys()),
            "reasoning": [f"Regime {regime} — all engines on standby (no edge)"],
        }

    # TRENDING → enable genome (always-on for evolution feedback)
    active.append(99782)
    reasons.append(f"99782 genome (LIVE: {genome_data.get('name','?') if genome_data else '?'}) — always-on for evolution")

    # Pick best historical performer for this regime
    if perf_data:
        ranking = perf_data.get("ranking", [])
        # Pick top engine that has trades + positive expectancy + not already in active
        for r in ranking:
            magic = r.get("magic")
            stats = r.get("stats", {})
            if magic in active: continue
            if stats.get("trades", 0) < 3: continue
            if stats.get("expectancy", 0) <= 0: continue
            if magic in ENGINES:
                active.append(magic)
                reasons.append(f"{magic} {ENGINES[magic]['name']} — best historical perf "
                                f"({stats['trades']}T, EV ${stats['expectancy']:+.2f})")
                break  # only one additional active

    # TRANSITION → only smart (defensive)
    if regime == "TRANSITION":
        if 99781 not in active:
            active.append(99781)
            reasons.append("99781 claude_smart — defensive for TRANSITION")
        # Remove aggressive ones in transition
        active = [m for m in active if not ENGINES.get(m, {}).get("aggressive", False)
                  or m == 99782]  # keep genome

    standby = [m for m in ENGINES.keys() if m not in active]
    return {
        "regime": regime,
        "active_magics": active,
        "standby_magics": standby,
        "reasoning": reasons,
    }


def main():
    print("[trader_orchestrator] ONLINE")
    last_active = []
    while True:
        try:
            regime = _read(REGIME_FILE)
            perf   = _read(PERF_FILE)
            genome = _read(GENOME_FILE)

            decision = decide(regime, perf, genome)
            decision["ts"] = datetime.now(timezone.utc).isoformat()
            decision["regime_metrics"] = regime.get("metrics", {}) if regime else {}
            decision["genome_live"] = (genome or {}).get("name", "NONE")

            _save(OUTPUT, decision)

            if decision["active_magics"] != last_active:
                print(f"\n[{datetime.now():%H:%M:%S}] ORCHESTRATOR DECISION")
                print(f"  Regime: {decision['regime']}")
                print(f"  ACTIVE: {decision['active_magics']}")
                print(f"  STANDBY: {decision['standby_magics']}")
                for r in decision["reasoning"]:
                    print(f"    • {r}")
                _append(DECISION_LOG, decision)
                last_active = decision["active_magics"]

            time.sleep(POLL)
        except KeyboardInterrupt:
            print("[trader_orchestrator] stopped"); break
        except Exception as e:
            print(f"[trader_orchestrator] err: {e}")
            time.sleep(POLL)


if __name__ == "__main__":
    main()
