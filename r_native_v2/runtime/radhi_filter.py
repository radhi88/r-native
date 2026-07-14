"""
radhi_filter.py  --  STANDALONE Radhi acceptance filter.

Implements the Radhi Acceptance Filter from
runtime/factory_spec/integration_contract.md (Part 2).

A candidate genome (as produced by algory_importer.map_algory_to_genome) is
ACCEPTED only if ALL of these hold:

  1. Permits SELL   : params.side_bias != "BUY_ONLY"   (SELL_ONLY or null OK)
  2. Trades NY      : params.session_filter includes "NY_OVERLAP", OR is empty []
  3. Linearity (OOS): algory_stats.linearity_oos >= LINEARITY_OOS_MIN (0.3)
  4. Sample  (OOS)  : algory_stats.trades_oos     >= TRADES_OOS_MIN     (40)
  5. Profitability  : algory_stats.profit_factor  >  PROFIT_FACTOR_MIN  (1.1)

Thresholds come from the contract. If radhi_dna.json happens to carry an
explicit "radhi_filter" / "thresholds" override block, those numeric values are
used instead -- otherwise the documented contract defaults below apply. The
file is read for thresholds ONLY; this module never writes anything and does
not touch the live system.

Stdlib only.
"""

import os
import json

# --------------------------------------------------------------------------- #
# Paths + contract default thresholds
# --------------------------------------------------------------------------- #
RADHI_DNA_PATH = r"C:\Users\Radhi\MT5\r_native_v2\data\radhi_dna.json"

# Defaults straight from integration_contract.md Part 2.
LINEARITY_OOS_MIN = 0.3
TRADES_OOS_MIN = 40
PROFIT_FACTOR_MIN = 1.1   # strictly greater-than


def _load_thresholds(dna_path=RADHI_DNA_PATH):
    """
    Return (linearity_oos_min, trades_oos_min, profit_factor_min).

    Starts from the contract defaults and, if radhi_dna.json exists and exposes
    an explicit override block under "radhi_filter" or "thresholds", applies any
    of the recognized numeric keys found there. Any read/parse problem falls
    back silently to the contract defaults (the filter must never crash).
    """
    lin = LINEARITY_OOS_MIN
    trd = TRADES_OOS_MIN
    pf = PROFIT_FACTOR_MIN

    try:
        with open(dna_path, "r", encoding="utf-8") as fh:
            dna = json.load(fh)
    except (OSError, ValueError):
        return lin, trd, pf

    if isinstance(dna, dict):
        override = dna.get("radhi_filter") or dna.get("thresholds") or {}
        if isinstance(override, dict):
            lin = override.get("linearity_oos_min", lin)
            trd = override.get("trades_oos_min", trd)
            pf = override.get("profit_factor_min", pf)

    return lin, trd, pf


def radhi_accept(genome):
    """
    Apply the Radhi acceptance rule to one genome dict.

    Returns (accepted: bool, reason: str). The reason names the FIRST failing
    gate, or "accepted" when all five gates pass.

    Expects the genome shape produced by algory_importer:
        { "params": {...}, "algory_stats": {...}, ... }
    Missing fields are treated conservatively (numeric stats default to 0 and
    thus fail the OOS/PF gates).
    """
    lin_min, trd_min, pf_min = _load_thresholds()

    p = genome.get("params", {}) or {}
    a = genome.get("algory_stats", {}) or {}

    # 1. Permits SELL
    if p.get("side_bias") == "BUY_ONLY":
        return False, "rejects SELL (side_bias BUY_ONLY)"

    # 2. Trades NY (non-empty filter must contain NY_OVERLAP; empty = all OK)
    sf = p.get("session_filter") or []
    if sf and "NY_OVERLAP" not in sf:
        return False, "no NY session ({})".format(sf)

    # 3. Linearity (OOS)
    lin = a.get("linearity_oos", 0) or 0
    if lin < lin_min:
        return False, "linearity_oos {} < {}".format(a.get("linearity_oos"), lin_min)

    # 4. Sample (OOS)
    trd = a.get("trades_oos", 0) or 0
    if trd < trd_min:
        return False, "trades_oos {} < {}".format(a.get("trades_oos"), trd_min)

    # 5. Profitability (strictly greater than)
    pf = a.get("profit_factor", 0) or 0
    if pf <= pf_min:
        return False, "profit_factor {} <= {}".format(a.get("profit_factor"), pf_min)

    return True, "accepted"


# --------------------------------------------------------------------------- #
# Optional CLI: score the imported genome list and print an accept/reject tally
# --------------------------------------------------------------------------- #
def _main(argv):
    import sys

    path = argv[1] if len(argv) > 1 else \
        r"C:\Users\Radhi\MT5\r_native_v2\data\algory_imported_genomes.json"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            genomes = json.load(fh)
    except (OSError, ValueError) as exc:
        print("radhi_filter: cannot read {} ({})".format(path, exc))
        return 1

    if not isinstance(genomes, list):
        genomes = [genomes]

    accepted = 0
    for g in genomes:
        ok, reason = radhi_accept(g)
        accepted += 1 if ok else 0
        print("  [{}] {} :: {}".format(
            "ACCEPT" if ok else "REJECT", g.get("name", "?"), reason))

    print("radhi_filter: {} / {} accepted".format(accepted, len(genomes)))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv))
