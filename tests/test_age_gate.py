"""Unit checks for the genome_promoter minimum-age promotion gate.

Runs with plain asserts (no pytest needed):  python tests/test_age_gate.py
"""
import importlib.util
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_promoter():
    spec = importlib.util.spec_from_file_location(
        "genome_promoter", ROOT / "v2" / "runtime" / "genome_promoter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    gp = load_promoter()
    now = datetime.now(timezone.utc)

    young = {"born": now.isoformat()}
    old = {"born": (now - timedelta(hours=2)).isoformat()}
    seed = {"born": "seed"}
    naive = {"born": (now - timedelta(hours=2)).replace(tzinfo=None).isoformat()}
    garbage = {"born": "not-a-date"}
    missing = {}

    assert gp._age_minutes(young) < 1
    assert 119 < gp._age_minutes(old) < 121
    assert gp._age_minutes(seed) is None
    assert 119 < gp._age_minutes(naive) < 121
    assert gp._age_minutes(garbage) is None
    assert gp._age_minutes(missing) is None

    perfect_fitness = {"g1": {"buy_signals": 20, "sell_signals": 20,
                              "avg_confidence_on_signal": 0.9}}
    perfect_council = {"approval_rate": 0.9, "approved": 50}

    ok, why = gp.is_eligible({"name": "g1", **young}, perfect_fitness, perfect_council)
    assert not ok and "min old" in why, (ok, why)

    ok, why = gp.is_eligible({"name": "g1", **old}, perfect_fitness, perfect_council)
    assert ok, (ok, why)

    ok, why = gp.is_eligible({"name": "g1", **seed}, perfect_fitness, perfect_council)
    assert ok, (ok, why)

    print("age gate: all checks pass")


if __name__ == "__main__":
    main()
