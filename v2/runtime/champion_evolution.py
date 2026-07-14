"""runtime/champion_evolution.py — Our son keeps getting smarter.

Born 2026-05-28: "ب — تطوير". Continuous self-improvement.

THE LOOP (every EVOLVE_EVERY_HOURS):
  1. Breed a fresh challenger CHILD from the LATEST winning data
     (decision_log + trades — now includes unified_trader's own wins
     + the user's newest manual trades via trade_sync).
  2. Score challenger vs reigning champion using recent realized PnL
     of trades that match each genome's would-have-fired conditions.
  3. If challenger is clearly better → CROWN it:
       • write live_genome.json (becomes LIVE)
       • overwrite genomes/champion_genome.json (the immortal record)
       • log the coronation to data/champion_lineage.jsonl
  4. Else → keep the reigning champion. Never downgrade.

SAFETY:
  • Only promotes on a real improvement margin (CHALLENGE_MARGIN).
  • Champion record is always backed up before overwrite.
  • The immortal champion file only ever moves UP in fitness.

Run:
    python -m runtime.champion_evolution
"""
from __future__ import annotations
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from runtime.shared.tokens import PATHS, ROOT
from runtime.shared.db import db

EVOLVE_EVERY_HOURS = 4.0
CHALLENGE_MARGIN = 1.10      # challenger must beat champion fitness by ≥10%
MIN_SAMPLES = 20             # need this many winning samples to breed

CHAMPION_FILE = ROOT / "genomes" / "champion_genome.json"
LINEAGE = PATHS["brain_decisions"].parent / "champion_lineage.jsonl"


def _load(p: Path) -> dict:
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}


def _save(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, default=str, ensure_ascii=False), encoding="utf-8")


def _fitness(genome_params: dict) -> float:
    """Score a genome by how the trades matching its conditions performed.

    Heuristic: pull closed trades from trading.db whose entry context
    (regime/session/RSI/pressure) would satisfy this genome, sum their PnL,
    weight by win-rate. Higher = better.
    """
    rsi_max = genome_params.get("rsi_max", 60)
    min_p   = genome_params.get("min_pressure_abs", 3)
    sess_f  = genome_params.get("session_filter") or []

    # Use entry_decisions (has context per trade) — fall back to trades-only.
    raw = db.query("""
        SELECT pnl, rsi_m1, pressure_10m1, session
        FROM entry_decisions
        WHERE pnl IS NOT NULL
        ORDER BY ts DESC LIMIT 500
    """)
    rows = [dict(r) for r in raw]
    if not rows:
        rows = [{"pnl": dict(r)["pnl"], "rsi_m1": 50, "pressure_10m1": 0, "session": "?"}
                for r in db.query("SELECT pnl FROM trades WHERE pnl IS NOT NULL ORDER BY ts DESC LIMIT 200")]

    matched = []
    for r in rows:
        rsi = r.get("rsi_m1") or 50
        pres = abs(r.get("pressure_10m1") or 0)
        sess = r.get("session") or "?"
        if rsi >= rsi_max: continue
        if pres < min_p: continue
        if sess_f and sess not in sess_f: continue
        matched.append(r["pnl"])
        if len(matched) >= 200: break

    if not matched:
        return 0.0
    total = sum(matched)
    wins = sum(1 for p in matched if p > 0)
    wr = wins / len(matched)
    # Fitness = total PnL × win-rate (rewards both profit and consistency)
    return round(total * wr, 2)


def _breed_challenger() -> dict | None:
    """Use genome_birth's distillation to create a fresh challenger."""
    try:
        from runtime.genome_birth import _pull_winning_context, _derive_genome
        rows = _pull_winning_context(min_wins_per_source=3)
        if len(rows) < MIN_SAMPLES:
            return None
        return _derive_genome(rows)
    except Exception as e:
        print(f"  breed error: {e}")
        return None


def evolve_once() -> dict:
    """One challenge round. Returns status dict."""
    champ_wrap = _load(CHAMPION_FILE)
    champion = champ_wrap.get("champion_genome", champ_wrap)
    champ_params = champion.get("params", champion)
    champ_fit = _fitness(champ_params)

    challenger = _breed_challenger()
    if not challenger:
        return {"action": "skip", "reason": "not enough fresh data", "champ_fitness": champ_fit}

    chal_fit = _fitness(challenger)
    result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "champion": champion.get("name"),
        "champ_fitness": champ_fit,
        "challenger": challenger.get("name"),
        "chal_fitness": chal_fit,
    }

    if chal_fit > champ_fit * CHALLENGE_MARGIN and chal_fit > 0:
        # CROWN the challenger
        new_champ = {
            "champion_genome": {
                "name": challenger["name"],
                "generation": 0,
                "promoted_ts": datetime.now(timezone.utc).isoformat(),
                "params": challenger,
                "parents": challenger.get("parents", []),
            },
            "captured_ts": datetime.now(timezone.utc).isoformat(),
            "fitness": chal_fit,
            "dethroned": champion.get("name"),
            "note": f"crowned by champion_evolution (fitness {chal_fit} > {champ_fit})",
        }
        # Backup old champion
        if CHAMPION_FILE.exists():
            shutil.copy2(CHAMPION_FILE, CHAMPION_FILE.with_suffix(".json.prev"))
        _save(CHAMPION_FILE, new_champ)
        # Promote to LIVE
        _save(PATHS["live_genome"], new_champ["champion_genome"])
        result["action"] = "CROWNED"
        # Lineage log
        with LINEAGE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, default=str) + "\n")
    else:
        result["action"] = "keep_champion"

    return result


def main():
    print(f"═══ 🧬 CHAMPION EVOLUTION — ولدنا يتطور ═══")
    print(f"  challenge every {EVOLVE_EVERY_HOURS}h · margin {CHALLENGE_MARGIN}x · min {MIN_SAMPLES} samples\n")
    while True:
        try:
            r = evolve_once()
            ts = datetime.now().strftime("%H:%M:%S")
            if r["action"] == "CROWNED":
                print(f"[{ts}] 👑 CROWNED {r['challenger']} "
                       f"(fit {r['chal_fitness']} > champ {r['champ_fitness']}) — dethroned {r['champion']}")
            elif r["action"] == "keep_champion":
                print(f"[{ts}] champion {r['champion']} holds "
                       f"(fit {r['champ_fitness']} ≥ challenger {r.get('chal_fitness')})")
            else:
                print(f"[{ts}] {r['action']}: {r.get('reason')}")
            time.sleep(EVOLVE_EVERY_HOURS * 3600)
        except KeyboardInterrupt:
            print("[champion_evolution] stopped"); break
        except Exception as e:
            print(f"err: {e}"); time.sleep(300)


if __name__ == "__main__":
    main()
