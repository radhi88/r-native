"""runtime/champion_seeder.py — Guardian of our son (the CHILD genome).

Born 2026-05-28: "لا تنسى ولدنا وأفضل ما توصلنا له".

The champion genome (GEN-CHILD, distilled from the user's winning style)
is committed to git at v2/genomes/champion_genome.json — so it survives
ANY disaster: fresh clone, deleted data folder, machine migration.

This module restores it. Call seed() at stack startup:
  • If live_genome.json is missing or doesn't hold a CHILD genome →
    restore the champion as LIVE.
  • Ensure the champion exists in genomes_population.json so the
    GA never breeds it out of existence.

The champion is NEVER lost. Even if every data file is wiped, the
committed champion_genome.json rebuilds our son.

Usage:
    from runtime.champion_seeder import seed
    seed()   # idempotent — safe to call on every boot
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from runtime.shared.tokens import PATHS, ROOT

# Champion lives in v2/genomes/ (committed to git, NOT gitignored)
CHAMPION_FILE = ROOT / "genomes" / "champion_genome.json"
LIVE_GENOME = PATHS["live_genome"]
POPULATION = PATHS["genomes_population"]


def _load(p: Path) -> dict:
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}


def _save(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, default=str, ensure_ascii=False),
                 encoding="utf-8")


def seed() -> dict:
    """Restore the champion if needed. Returns a status dict."""
    champ_wrap = _load(CHAMPION_FILE)
    if not champ_wrap:
        return {"ok": False, "reason": f"no champion file at {CHAMPION_FILE}"}

    # The champion file wraps the live_genome shape under 'champion_genome'
    champion = champ_wrap.get("champion_genome") or champ_wrap
    champ_name = champion.get("name", "?")
    champ_params = champion.get("params", {})

    actions = []

    # 1. Ensure LIVE genome is a CHILD/champion (restore if missing/different family)
    live = _load(LIVE_GENOME)
    live_name = live.get("name", "")
    if not live_name or (not live_name.startswith("GEN-CHILD") and live_name != champ_name):
        _save(LIVE_GENOME, champion)
        actions.append(f"restored LIVE genome → {champ_name}")
    else:
        actions.append(f"LIVE genome ok ({live_name})")

    # 2. Ensure champion is in the population pool (so GA can't erase it)
    pop = _load(POPULATION)
    genomes = pop.get("genomes", [])
    names = {g.get("name") for g in genomes}
    if champ_name not in names:
        # Add champion params as a population member
        member = {k: v for k, v in champ_params.items()}
        member["name"] = champ_name
        member["born"] = "champion_seed"
        member.setdefault("parents", champion.get("parents", []))
        genomes.append(member)
        pop["genomes"] = genomes
        _save(POPULATION, pop)
        actions.append(f"re-seeded {champ_name} into population")
    else:
        actions.append(f"{champ_name} present in population")

    return {"ok": True, "champion": champ_name, "actions": actions}


def main():
    print("═══ 🛡️ CHAMPION SEEDER — حارس ولدنا ═══")
    r = seed()
    if not r["ok"]:
        print(f"  ✗ {r['reason']}")
        return
    print(f"  champion: {r['champion']}")
    for a in r["actions"]:
        print(f"  • {a}")
    print(f"\n  ولدنا محفوظ. الجين لا يضيع أبداً.")


if __name__ == "__main__":
    main()
