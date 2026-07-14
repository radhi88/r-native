"""
multi_symbol_champions.py  --  BRICK C: expand champions to ALL symbols.

Loads the algory-imported candidate genomes (data/algory_imported_genomes.json),
groups them by symbol, and for EACH symbol produces a ranked champion list using
a GENERAL out-of-sample-quality filter (NOT the gold-specific Radhi-sell filter):

    linearity_oos >= 0.3
    trades_oos    >= 40
    profit_factor >  1.1

The scoring + de-duplication reuse runtime.radhi_champions (robustness_score and
the dedupe signature), so the ranking metric is identical to the Radhi pipeline.

It ALSO reads the Algory meta-learning fitness store
(C:\\Users\\Radhi\\AppData\\Local\\Algory\\gene_fitness_v2.json) and, for each
symbol, extracts the top-3 winning modules per timeframe ("meta_favored_modules")
ranked by (wins desc, fails asc) -- so the factory can SEED those modules rather
than starting from random.

Output: data/multi_symbol_champions.json
    { "<SYMBOL>": { "ranked_champions": [...], "meta_favored_modules": {tf: [...]} } }

CLI prints a per-symbol summary: symbol -> (#champions, best PF, top-3 modules).

Stdlib only. Never writes to any live genome/data file other than the single
output JSON.
"""

import os
import sys
import json

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(_THIS_DIR)
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

# Reuse the Radhi scoring + dedupe machinery.
try:
    from runtime.radhi_champions import (
        robustness_score,
        _dedupe_signature,
        _num,
    )
except ImportError:
    if _THIS_DIR not in sys.path:
        sys.path.insert(0, _THIS_DIR)
    from radhi_champions import robustness_score, _dedupe_signature, _num


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
DATA_DIR = os.path.join(_PKG_ROOT, "data")
IMPORTED_GENOMES_PATH = os.path.join(DATA_DIR, "algory_imported_genomes.json")
OUT_PATH = os.path.join(DATA_DIR, "multi_symbol_champions.json")

GENE_FITNESS_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local")),
    "Algory",
    "gene_fitness_v2.json",
)

# --------------------------------------------------------------------------- #
# General OOS-quality acceptance filter (symbol-agnostic).
# --------------------------------------------------------------------------- #
MIN_LINEARITY_OOS = 0.3
MIN_TRADES_OOS = 40
MIN_PROFIT_FACTOR = 1.1  # strictly greater than

TOP_MODULES_PER_TF = 3


def general_accept(genome):
    """
    General OOS-quality filter applied to every symbol.

    Returns (ok, reason). Unlike runtime.radhi_filter.radhi_accept this is NOT
    gold/side-specific -- it only judges out-of-sample robustness.
    """
    stats = genome.get("algory_stats", {}) or {}
    lin_oos = _num(stats.get("linearity_oos"))
    trades_oos = _num(stats.get("trades_oos"))
    pf = _num(stats.get("profit_factor"))

    if lin_oos < MIN_LINEARITY_OOS:
        return False, "linearity_oos {:.3f} < {}".format(lin_oos, MIN_LINEARITY_OOS)
    if trades_oos < MIN_TRADES_OOS:
        return False, "trades_oos {:.0f} < {}".format(trades_oos, MIN_TRADES_OOS)
    if pf <= MIN_PROFIT_FACTOR:
        return False, "profit_factor {:.3f} <= {}".format(pf, MIN_PROFIT_FACTOR)
    return True, "ok"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _infer_tf(genome):
    """Infer the timeframe for a genome from its params or source string."""
    p = genome.get("params", {}) or {}
    tf = p.get("timeframe") or p.get("tf")
    if tf:
        return str(tf)
    src = genome.get("source") or ""
    # e.g. "... (schema_version=3, tf=H1)"
    marker = "tf="
    idx = src.find(marker)
    if idx != -1:
        rest = src[idx + len(marker):]
        token = ""
        for ch in rest:
            if ch.isalnum():
                token += ch
            else:
                break
        if token:
            return token
    return "UNKNOWN"


def group_by_symbol(genomes):
    """Group genome dicts by their 'symbol' key."""
    groups = {}
    for g in genomes:
        sym = g.get("symbol") or (g.get("params", {}) or {}).get("symbol") or "UNKNOWN"
        groups.setdefault(sym, []).append(g)
    return groups


# --------------------------------------------------------------------------- #
# Ranking (general filter, reuse Radhi scoring + dedupe)
# --------------------------------------------------------------------------- #
def rank_champions_general(genomes):
    """
    Rank candidate genomes for one symbol using the general OOS-quality filter.

    Steps mirror runtime.radhi_champions.rank_champions but swap in
    general_accept() instead of the gold-only radhi_accept:
      1. Keep only genomes passing general_accept.
      2. Score each via runtime.radhi_champions.robustness_score.
      3. De-duplicate near-identical genomes (Radhi dedupe signature).
      4. Sort by score descending (tie-break on name).
    """
    if not isinstance(genomes, list):
        genomes = [genomes]

    scored = []
    for g in genomes:
        ok, _reason = general_accept(g)
        if not ok:
            continue
        stats = g.get("algory_stats", {}) or {}
        item = dict(g)
        item["robustness_score"] = robustness_score(stats)
        scored.append(item)

    best_by_sig = {}
    for item in scored:
        sig = _dedupe_signature(item)
        existing = best_by_sig.get(sig)
        if existing is None or item["robustness_score"] > existing["robustness_score"]:
            best_by_sig[sig] = item

    deduped = list(best_by_sig.values())
    deduped.sort(key=lambda it: (-it["robustness_score"], it.get("name", "")))
    return deduped


def _to_champion_record(item):
    """Trimmed per-champion output record."""
    p = item.get("params", {}) or {}
    return {
        "name": item.get("name"),
        "symbol": item.get("symbol"),
        "timeframe": _infer_tf(item),
        "score": round(item["robustness_score"], 6),
        "side_bias": p.get("side_bias"),
        "session_filter": p.get("session_filter") or [],
        "sl_pts": p.get("sl_pts"),
        "tp_pts": p.get("tp_pts"),
        "algory_stats": item.get("algory_stats", {}) or {},
    }


# --------------------------------------------------------------------------- #
# Meta-learning: top-3 winning modules per timeframe.
# --------------------------------------------------------------------------- #
def _module_sort_key(name_stats):
    """Sort modules by wins desc, fails asc, then name for determinism."""
    name, st = name_stats
    wins = _num((st or {}).get("wins"))
    fails = _num((st or {}).get("fails"))
    return (-wins, fails, name)


def extract_meta_favored(symbol, gene_fitness):
    """
    For one symbol, return {timeframe: [top-3 module dicts]} ranked by
    (wins desc, fails asc). Timeframes are the TF keys under the symbol that
    contain a "genes" mapping.
    """
    out = {}
    sym_block = (gene_fitness or {}).get(symbol)
    if not isinstance(sym_block, dict):
        return out

    for tf, tf_block in sym_block.items():
        if not isinstance(tf_block, dict):
            continue
        genes = tf_block.get("genes")
        if not isinstance(genes, dict) or not genes:
            continue
        ranked = sorted(genes.items(), key=_module_sort_key)
        top = []
        for name, st in ranked[:TOP_MODULES_PER_TF]:
            st = st or {}
            top.append({
                "module": name,
                "wins": int(_num(st.get("wins"))),
                "fails": int(_num(st.get("fails"))),
                "appearances": int(_num(st.get("appearances"))),
                "avg_return": round(_num(st.get("avg_return")), 4),
            })
        if top:
            out[tf] = top
    return out


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def build_multi_symbol(genomes, gene_fitness, top_n=None):
    """
    Build the per-symbol {ranked_champions, meta_favored_modules} mapping.

    top_n: optional cap on ranked_champions per symbol (None = keep all).
    """
    groups = group_by_symbol(genomes)
    result = {}
    for sym, sym_genomes in sorted(groups.items()):
        ranked = rank_champions_general(sym_genomes)
        if top_n is not None:
            ranked = ranked[:top_n]
        result[sym] = {
            "ranked_champions": [_to_champion_record(it) for it in ranked],
            "meta_favored_modules": extract_meta_favored(sym, gene_fitness),
        }
    return result


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _main(argv):
    genomes_path = argv[1] if len(argv) > 1 else IMPORTED_GENOMES_PATH
    fitness_path = argv[2] if len(argv) > 2 else GENE_FITNESS_PATH

    genomes = _load_json(genomes_path, None)
    if genomes is None:
        print("multi_symbol_champions: cannot read genomes {}".format(genomes_path))
        return 1
    if not isinstance(genomes, list):
        genomes = [genomes]

    gene_fitness = _load_json(fitness_path, {})
    if not gene_fitness:
        print("multi_symbol_champions: WARNING could not read gene_fitness {} "
              "(meta_favored_modules will be empty)".format(fitness_path))

    result = build_multi_symbol(genomes, gene_fitness)

    try:
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
    except OSError as exc:
        print("multi_symbol_champions: cannot write {} ({})".format(OUT_PATH, exc))
        return 1

    print("multi_symbol_champions: {} genomes across {} symbols -> {}".format(
        len(genomes), len(result), OUT_PATH))
    print("filter: linearity_oos>={}, trades_oos>={}, profit_factor>{}".format(
        MIN_LINEARITY_OOS, MIN_TRADES_OOS, MIN_PROFIT_FACTOR))
    print("")
    print("Per-symbol summary:")
    for sym in sorted(result.keys()):
        block = result[sym]
        champs = block["ranked_champions"]
        n = len(champs)
        best_pf = None
        for c in champs:
            pf = _num((c.get("algory_stats") or {}).get("profit_factor"))
            if best_pf is None or pf > best_pf:
                best_pf = pf
        # Flatten top modules across timeframes -> show distinct module names.
        mods = []
        for tf, lst in block["meta_favored_modules"].items():
            for m in lst:
                if m["module"] not in mods:
                    mods.append(m["module"])
        top3_mods = mods[:3] if mods else ["(none)"]
        best_pf_str = "{:.3f}".format(best_pf) if best_pf is not None else "n/a"
        print("  {:<10} -> champions={:<3} best_PF={:<7} top3_modules={}".format(
            sym, n, best_pf_str, ", ".join(top3_mods)))

    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
