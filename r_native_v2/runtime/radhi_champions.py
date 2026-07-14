"""
radhi_champions.py  --  STANDALONE Radhi champion ranker.

Loads the algory-imported candidate genomes, keeps only those that pass the
Radhi Acceptance Filter (runtime.radhi_filter.radhi_accept), scores the
survivors by an out-of-sample robustness metric, de-duplicates near-identical
genomes, and returns the ranked list.

Robustness score per genome:

    robustness = linearity_oos
                 * min(trades_oos / 100, 1.5)
                 * min(profit_factor, 2.5)
                 * (1 - min(drawdown_pct / 100, 0.9))

De-duplication: genomes that share the same
    (side_bias, session_filter, round(sl_pts), round(tp_pts))
signature are considered near-identical; only the highest-scoring one is kept.

This module never writes to any live genome/data file. The optional CLI writes
ONLY data/radhi_champions.json (top 15 ranked champions).

Stdlib only.
"""

import os
import sys
import json

# Make sure the package root (which contains the "runtime" package) is on the
# import path whether this file is run as a module or as a script.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(_THIS_DIR)
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

try:
    from runtime.radhi_filter import radhi_accept
except ImportError:
    # Fallback: same-directory import when "runtime" is not a discoverable pkg.
    if _THIS_DIR not in sys.path:
        sys.path.insert(0, _THIS_DIR)
    from radhi_filter import radhi_accept


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
DATA_DIR = os.path.join(_PKG_ROOT, "data")
IMPORTED_GENOMES_PATH = os.path.join(DATA_DIR, "algory_imported_genomes.json")
CHAMPIONS_OUT_PATH = os.path.join(DATA_DIR, "radhi_champions.json")

TOP_N = 15


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def _num(value, default=0.0):
    """Coerce a possibly-None/str stat to float; fall back to default."""
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def robustness_score(stats):
    """
    Compute the out-of-sample robustness score for one algory_stats block.

        linearity_oos
        * min(trades_oos / 100, 1.5)
        * min(profit_factor, 2.5)
        * (1 - min(drawdown_pct / 100, 0.9))
    """
    stats = stats or {}
    lin_oos = _num(stats.get("linearity_oos"))
    trades_oos = _num(stats.get("trades_oos"))
    pf = _num(stats.get("profit_factor"))
    dd = _num(stats.get("drawdown_pct"))

    trades_term = min(trades_oos / 100.0, 1.5)
    pf_term = min(pf, 2.5)
    dd_term = 1.0 - min(dd / 100.0, 0.9)

    return lin_oos * trades_term * pf_term * dd_term


def _dedupe_signature(genome):
    """
    Signature for near-identical genomes:
        (side_bias, session_filter tuple, round(sl_pts), round(tp_pts))
    """
    p = genome.get("params", {}) or {}
    side_bias = p.get("side_bias")
    session_filter = tuple(p.get("session_filter") or [])
    sl = p.get("sl_pts")
    tp = p.get("tp_pts")
    sl_r = round(_num(sl)) if sl is not None else None
    tp_r = round(_num(tp)) if tp is not None else None
    return (side_bias, session_filter, sl_r, tp_r)


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #
def rank_champions(genomes):
    """
    Rank Radhi-aligned candidate genomes.

    Steps:
      1. Keep only genomes that pass runtime.radhi_filter.radhi_accept.
      2. Score each by the out-of-sample robustness metric.
      3. De-duplicate near-identical genomes (same side_bias + session_filter +
         rounded sl_pts/tp_pts), keeping the highest score.
      4. Return the list sorted by score, descending.

    Each returned item is the original genome dict augmented with a
    "robustness_score" key (the live source genomes are not mutated).
    """
    if not isinstance(genomes, list):
        genomes = [genomes]

    # 1 + 2: filter then score.
    scored = []
    for g in genomes:
        ok, _reason = radhi_accept(g)
        if not ok:
            continue
        stats = g.get("algory_stats", {}) or {}
        score = robustness_score(stats)
        # Shallow copy so we never mutate the source genome dict.
        item = dict(g)
        item["robustness_score"] = score
        scored.append(item)

    # 3: de-duplicate by signature, keeping the highest score.
    best_by_sig = {}
    for item in scored:
        sig = _dedupe_signature(item)
        existing = best_by_sig.get(sig)
        if existing is None or item["robustness_score"] > existing["robustness_score"]:
            best_by_sig[sig] = item

    deduped = list(best_by_sig.values())

    # 4: rank by score descending (stable tie-break on name for determinism).
    deduped.sort(key=lambda it: (-it["robustness_score"], it.get("name", "")))
    return deduped


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _to_champion_record(item):
    """Build the trimmed output record for radhi_champions.json."""
    p = item.get("params", {}) or {}
    return {
        "name": item.get("name"),
        "score": round(item["robustness_score"], 6),
        "side_bias": p.get("side_bias"),
        "session_filter": p.get("session_filter") or [],
        "sl_pts": p.get("sl_pts"),
        "tp_pts": p.get("tp_pts"),
        "algory_stats": item.get("algory_stats", {}) or {},
    }


def _main(argv):
    path = argv[1] if len(argv) > 1 else IMPORTED_GENOMES_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            genomes = json.load(fh)
    except (OSError, ValueError) as exc:
        print("radhi_champions: cannot read {} ({})".format(path, exc))
        return 1

    if not isinstance(genomes, list):
        genomes = [genomes]

    ranked = rank_champions(genomes)
    top = ranked[:TOP_N]

    records = [_to_champion_record(it) for it in top]
    try:
        with open(CHAMPIONS_OUT_PATH, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2)
    except OSError as exc:
        print("radhi_champions: cannot write {} ({})".format(CHAMPIONS_OUT_PATH, exc))
        return 1

    print("radhi_champions: {} input genomes -> {} accepted+deduped -> top {} written to {}".format(
        len(genomes), len(ranked), len(top), CHAMPIONS_OUT_PATH))
    print("")
    print("Top 5 ranked champions:")
    for i, it in enumerate(top[:5], 1):
        p = it.get("params", {}) or {}
        a = it.get("algory_stats", {}) or {}
        print("  {}. {} | score={:.4f} | side_bias={} | session={} | "
              "linearity_oos={} | trades_oos={} | PF={}".format(
                  i,
                  it.get("name"),
                  it["robustness_score"],
                  p.get("side_bias"),
                  p.get("session_filter") or [],
                  a.get("linearity_oos"),
                  a.get("trades_oos"),
                  a.get("profit_factor"),
              ))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
