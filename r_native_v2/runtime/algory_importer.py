"""
algory_importer.py  --  STANDALONE Algory -> FRIDAY genome importer.

Reads Algory generated-strategy JSON files and maps EACH one onto OUR live
genome dict, using ONLY the `params` keys that `unified_trader.py` actually
honors (per runtime/factory_spec/integration_contract.md, Part 1).

This module does NOT import or touch unified_trader.py, genome_evolver.py, or
anything under the data/ folder at import time. It only WRITES a single output
artifact (algory_imported_genomes.json) when run as a CLI.

Stdlib only.

CLI:
    cd C:\\Users\\Radhi\\MT5\\r_native_v2
    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe -m runtime.algory_importer

    -> reads every strategy JSON under the Algory source dir + its .recycle
       subfolder, prints "total read" and "total mapped", and writes the mapped
       genome list to data\\algory_imported_genomes.json.
"""

import os
import sys
import glob
import json

# --------------------------------------------------------------------------- #
# Paths (absolute, per task spec)
# --------------------------------------------------------------------------- #
DEFAULT_SRC_DIR = r"C:\Users\Radhi\AppData\Local\Algory\Generated_Strategies"
OUTPUT_PATH = r"C:\Users\Radhi\MT5\r_native_v2\data\algory_imported_genomes.json"

# --------------------------------------------------------------------------- #
# Mapping constants -- documented scaling / defaults
# --------------------------------------------------------------------------- #
# Algory sl_mult / tp_mult are ATR-multiples. unified_trader wants sl_pts/tp_pts
# in "gold-points" (later multiplied by the symbol pt-scale). We apply a flat,
# documented linear scale of 1.5 gold-points per ATR-multiple. This keeps the
# relative SL/TP geometry of each Algory strategy intact while landing the
# resulting points in the same ballpark as the hand-tuned RADHI clone
# (sl_pts=4.0, tp_pts=12.0). tp_pts is additionally floored by unified_trader
# itself to max(tp_pts, 20.0) at order-build time, so small values are safe.
SL_TP_SCALE = 1.5

# Defaults requested by the task for every mapped genome.
DEFAULT_LOT = 0.01
DEFAULT_USE_FOOTPRINT = True   # inert in unified_trader, honored by other traders
DEFAULT_TREND_ALIGN = True

# Session-bucket boundaries (UTC hours). These mirror the contract's session
# tags and the radhi_dna bucket definitions:
#   LONDON      08-13
#   NY_OVERLAP  13-17
#   NY_LATE     17-21
#   ASIAN       everything else (21-08 wrap-around / night)
SESSION_TAGS = ("NY_OVERLAP", "LONDON", "NY_LATE", "ASIAN")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _session_for_hour(hour):
    """Map a single UTC hour (0-23) to one of our 4 session tags."""
    h = hour % 24
    if 13 <= h < 17:
        return "NY_OVERLAP"
    if 8 <= h < 13:
        return "LONDON"
    if 17 <= h < 21:
        return "NY_LATE"
    # 21,22,23,0..7  -> Asian / night
    return "ASIAN"


def _session_filter_from_hours(start_hour, end_hour):
    """
    Convert an Algory [start_hour, end_hour] active window into the list of
    session tags it OVERLAPS. We walk every hour the strategy is active and
    collect each session it touches.

    The window is treated as a half-open [start, end) range of hours. If
    end <= start the window is assumed to wrap past midnight (e.g. 22->06).
    If either bound is missing we return [] (= trade all sessions / 24-7),
    which is exactly how unified_trader interprets an empty session_filter.
    """
    if start_hour is None or end_hour is None:
        return []

    try:
        start_hour = int(start_hour)
        end_hour = int(end_hour)
    except (TypeError, ValueError):
        return []

    # Build the ordered list of active hours.
    if end_hour > start_hour:
        hours = range(start_hour, end_hour)
    elif end_hour < start_hour:
        # wrap-around window: start..23 then 0..end
        hours = list(range(start_hour, 24)) + list(range(0, end_hour))
    else:
        # start == end -> degenerate / full day; treat as all sessions
        return []

    found = set()
    for h in hours:
        found.add(_session_for_hour(h))

    if not found:
        return []

    # Return in our canonical tag order for deterministic output.
    return [tag for tag in SESSION_TAGS if tag in found]


def _scale_points(mult):
    """sl_mult/tp_mult (ATR-multiple) -> *_pts (gold-points), rounded 2dp."""
    if mult is None:
        return None
    try:
        return round(float(mult) * SL_TP_SCALE, 2)
    except (TypeError, ValueError):
        return None


def _infer_side_bias(stats):
    """
    Infer side_bias from the Algory long/short trade counts:
      shorts >= 2*longs  -> SELL_ONLY
      longs  >= 2*shorts -> BUY_ONLY
      otherwise          -> None  (both sides allowed)
    """
    longs = stats.get("longs")
    shorts = stats.get("shorts")
    if longs is None or shorts is None:
        return None
    try:
        longs = int(longs)
        shorts = int(shorts)
    except (TypeError, ValueError):
        return None

    if shorts >= 2 * longs:
        return "SELL_ONLY"
    if longs >= 2 * shorts:
        return "BUY_ONLY"
    return None


def _is_strategy_doc(doc):
    """
    A genuine Algory strategy file has a `genome` dict. Skip index/metadata
    files such as `_vault_index.json` (which only carry disk_count/entries).
    """
    return isinstance(doc, dict) and isinstance(doc.get("genome"), dict)


def _collect_files(src_dir):
    """
    Return the list of candidate JSON paths: top-level *.json in src_dir plus
    *.json inside the .recycle subfolder. Non-recursive otherwise (the
    date-named subfolders use a different, non-strategy layout and are not part
    of the import contract).
    """
    files = []
    files.extend(sorted(glob.glob(os.path.join(src_dir, "*.json"))))
    recycle = os.path.join(src_dir, ".recycle")
    if os.path.isdir(recycle):
        files.extend(sorted(glob.glob(os.path.join(recycle, "*.json"))))
    return files


# --------------------------------------------------------------------------- #
# Core mapping
# --------------------------------------------------------------------------- #
def map_algory_to_genome(doc):
    """
    Map ONE parsed Algory strategy document onto OUR genome dict.

    Returns the genome dict, shaped like the live genome files:
        { "name", "symbol", "params": {...}, "source", "ts", "algory_stats": {...} }

    Only `params` keys honored by unified_trader.py are populated. The full
    Algory stats block is copied verbatim under both the top-level
    `algory_stats` key (where radhi_filter reads it) and left untouched
    otherwise.
    """
    genome = doc.get("genome", {}) or {}
    stats = doc.get("stats", {}) or {}

    symbol = doc.get("symbol") or genome.get("symbol") or ""
    algory_id = doc.get("id") or ""
    timeframe = doc.get("timeframe") or ""
    name = "ALGORY-{}-{}-{}".format(algory_id or "NA", symbol or "NA", timeframe or "NA")

    session_filter = _session_filter_from_hours(
        genome.get("start_hour"), genome.get("end_hour")
    )
    sl_pts = _scale_points(genome.get("sl_mult"))
    tp_pts = _scale_points(genome.get("tp_mult"))
    side_bias = _infer_side_bias(stats)

    # params: ONLY keys unified_trader.py reads (integration_contract Part 1).
    params = {
        "name": name,
        "symbol": symbol,
        # signal gates
        "session_filter": session_filter,
        "regime_filter": [],
        "min_mtf_agreement": 2,
        "side_bias": side_bias,            # may be None (both sides allowed)
        "rsi_max": 60,
        "min_pressure_abs": 3,
        # post-signal gates
        "trend_align": DEFAULT_TREND_ALIGN,
        "trend_align_min": 0.45,
        "struct_min": 0.10,
        # execution / sizing
        "sl_pts": sl_pts if sl_pts is not None else 4.0,
        "tp_pts": tp_pts if tp_pts is not None else 12.0,
        "lot": DEFAULT_LOT,
        "risk_pct": 0.0,
        # inert passthrough (honored by footprint-aware traders)
        "use_footprint": DEFAULT_USE_FOOTPRINT,
    }

    return {
        "name": name,
        "symbol": symbol,
        "params": params,
        "source": "algory_importer: {} (schema_version={}, tf={})".format(
            algory_id, doc.get("schema_version"), timeframe
        ),
        "ts": doc.get("created_at", ""),
        # Full Algory stats copied verbatim; radhi_filter reads its OOS fields.
        "algory_stats": stats,
    }


def import_algory_genes(src_dir=DEFAULT_SRC_DIR):
    """
    Read every Algory strategy JSON under `src_dir` (+ its .recycle subfolder)
    and map each to our genome dict.

    Returns: (genomes, total_read)
        genomes    -> list[dict] of mapped genomes (one per strategy file)
        total_read -> int, number of strategy files successfully parsed
                      (excludes non-strategy / index files and parse errors)

    No side effects on the live system: nothing under data/ is written here;
    the CLI is responsible for writing the output artifact.
    """
    genomes = []
    total_read = 0

    for path in _collect_files(src_dir):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            # unreadable or not valid JSON -> skip silently
            continue

        if not _is_strategy_doc(doc):
            # index/metadata file (e.g. _vault_index.json) -> skip
            continue

        total_read += 1
        try:
            genomes.append(map_algory_to_genome(doc))
        except Exception:
            # a single malformed strategy must not abort the whole import
            continue

    return genomes, total_read


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _main(argv):
    src_dir = argv[1] if len(argv) > 1 else DEFAULT_SRC_DIR

    genomes, total_read = import_algory_genes(src_dir)
    total_mapped = len(genomes)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(genomes, fh, indent=2)

    print("Algory importer")
    print("  source dir : {}".format(src_dir))
    print("  total read : {}".format(total_read))
    print("  total mapped: {}".format(total_mapped))
    print("  written to : {}".format(OUTPUT_PATH))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
