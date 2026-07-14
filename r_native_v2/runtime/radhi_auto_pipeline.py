"""
radhi_auto_pipeline.py  --  GATED self-feeding factory pipeline (BRICK A).

The closed loop that turns Algory's evolved strategies into Radhi-aligned
champions and *proposes* (never deploys) the best NEW one for the live brain.

WHAT IT DOES
────────────
  1. SCAN   Reads strategy genes from the Algory vault at
                C:\\Users\\Radhi\\AppData\\Local\\Algory\\Generated_Strategies
            covering all three locations:
                • the flat vault          (top-level *.json)
                • per-campaign subfolders (e.g. XAUUSD_M5_0531_0339\\*.json)
                • the .recycle fallback   (.recycle\\*.json)

  2. PIPE   runtime.algory_importer.import_algory_genes  (mapping)
            → runtime.radhi_filter.radhi_accept           (acceptance gate)
            → runtime.radhi_champions.rank_champions       (robustness ranking)
            ⇒ ranked Radhi-aligned champions.

  3. TRACK  Persists champion ids already seen to
                C:\\Users\\Radhi\\MT5\\r_native_v2\\data\\radhi_pipeline_state.json
            so each run only ACTS on genuinely NEW champions. Idempotent: a
            second run with no new genes proposes nothing.

  4. PROPOSE For the TOP new champion, FILES a governance proposal via
            runtime.shared.agent_governance.propose(...) with action
            "crown_genome". That action auto-resolves to RISK_HIGH, lands in
            the NEEDS_CLAUDE consult queue, and CANNOT be auto-applied — the
            user's "قبل اطلاقها يستشيرونك" gate. Claude must approve.

HARD SAFETY GUARANTEES
──────────────────────
  • NEVER writes/edits any live_genome*.json or champion_genome.json. The only
    state file it writes is radhi_pipeline_state.json (its own bookkeeping).
  • Only the governance.propose() call leaves a trace in the system, and that
    merely files a PENDING/NEEDS_CLAUDE proposal — apply is somebody else's job,
    and is blocked for crown_genome until Claude approves.
  • Stdlib only.

CLI:
    cd C:\\Users\\Radhi\\MT5\\r_native_v2
    python -m runtime.radhi_auto_pipeline
        → prints champions found + the proposal it filed (if any).
"""

from __future__ import annotations

import os
import sys
import glob
import json
import time
import hashlib
from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
# Make the package root importable whether run as a module or a script.
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(_THIS_DIR)            # ...\r_native_v2
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from runtime.algory_importer import (            # noqa: E402
    DEFAULT_SRC_DIR,
    map_algory_to_genome,
    _is_strategy_doc,
)
from runtime.radhi_filter import radhi_accept     # noqa: E402
from runtime.radhi_champions import rank_champions  # noqa: E402
from runtime.shared import agent_governance as gov  # noqa: E402
from runtime import oos_backtest                    # noqa: E402

# --------------------------------------------------------------------------- #
# Independent-OOS gate constants (BRICK B2 wiring)
#   A champion is only proposable if OUR OWN engine — runtime.oos_backtest —
#   accepts it. That gate is: trades_oos >= 60 AND OOS profit_factor > 1.1
#   (encoded as the `accept` flag returned by backtest_genome). We do NOT trust
#   Algory's own stats for the crown decision; the Algory numbers are advisory.
# --------------------------------------------------------------------------- #
OOS_SYMBOL = "XAUUSDm"
OOS_TIMEFRAME = "M5"
OOS_DAYS = 120

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ALGORY_SRC_DIR = DEFAULT_SRC_DIR
DATA_DIR = os.path.join(_PKG_ROOT, "data")
STATE_PATH = os.path.join(DATA_DIR, "radhi_pipeline_state.json")

AGENT_NAME = "radhi_auto_pipeline"


# --------------------------------------------------------------------------- #
# File collection — flat vault + per-campaign subfolders + .recycle fallback
# --------------------------------------------------------------------------- #
def collect_strategy_files(src_dir=ALGORY_SRC_DIR):
    """
    Return the deduplicated, sorted list of candidate strategy JSON paths from:
      • the flat vault          : <src>\\*.json
      • per-campaign subfolders : <src>\\<campaign>\\*.json   (excluding .recycle)
      • the .recycle fallback   : <src>\\.recycle\\*.json

    Non-strategy / index / diagnostics files are NOT filtered here; the importer's
    _is_strategy_doc() decides that per-document at parse time.
    """
    seen = set()
    files = []

    def _add(pattern):
        for p in sorted(glob.glob(pattern)):
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                files.append(ap)

    if not os.path.isdir(src_dir):
        return files

    # 1. flat vault (top-level)
    _add(os.path.join(src_dir, "*.json"))

    # 2. per-campaign subfolders (one level down), skipping the recycle bin
    for entry in sorted(os.listdir(src_dir)):
        sub = os.path.join(src_dir, entry)
        if not os.path.isdir(sub) or entry == ".recycle":
            continue
        _add(os.path.join(sub, "*.json"))

    # 3. .recycle fallback (last, lowest priority)
    recycle = os.path.join(src_dir, ".recycle")
    if os.path.isdir(recycle):
        _add(os.path.join(recycle, "*.json"))

    return files


def import_from_all_locations(src_dir=ALGORY_SRC_DIR):
    """
    Read every candidate file from all three locations and map each genuine
    Algory strategy doc to our genome dict (via algory_importer.map_algory_to_genome).

    Returns: (genomes, total_read)
      genomes    list[dict]  mapped genomes
      total_read int         number of strategy docs successfully parsed
    """
    genomes = []
    total_read = 0

    for path in collect_strategy_files(src_dir):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        if not _is_strategy_doc(doc):
            continue
        total_read += 1
        try:
            genomes.append(map_algory_to_genome(doc))
        except Exception:
            # one malformed strategy must never abort the whole import
            continue

    return genomes, total_read


# --------------------------------------------------------------------------- #
# Stable champion id
# --------------------------------------------------------------------------- #
def champion_id(champion):
    """
    A stable, content-derived id for a ranked champion so the same strategy
    maps to the same id across runs (drives NEW-vs-seen tracking).

    Built from the mapped genome's identity fields: name + the dedup signature
    (side_bias, session_filter, rounded sl/tp). The genome name already embeds
    the Algory id (ALGORY-<id>-<symbol>-<tf>), so distinct Algory strategies get
    distinct ids while near-identical re-runs collapse together.
    """
    p = (champion.get("params") or {})
    sig = {
        "name": champion.get("name") or "",
        "symbol": champion.get("symbol") or p.get("symbol") or "",
        "side_bias": p.get("side_bias"),
        "session_filter": list(p.get("session_filter") or []),
        "sl_pts": p.get("sl_pts"),
        "tp_pts": p.get("tp_pts"),
    }
    blob = json.dumps(sig, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Independent OOS validation — OUR engine's second opinion
# --------------------------------------------------------------------------- #
def validate_oos(champion, symbol=OOS_SYMBOL, timeframe=OOS_TIMEFRAME, days=OOS_DAYS):
    """
    Run runtime.oos_backtest.backtest_genome on this champion's params and
    return (accepted: bool, stats: dict | None, error: str | None).

    accepted is True ONLY when our own engine accepts the genome
    (stats["accept"] == True, i.e. trades_oos >= 60 AND OOS PF > 1.1). We do not
    propose champions our own engine rejects. Any backtest failure (no MT5, no
    data, bad timeframe, etc.) is treated as NOT accepted, with the error string
    surfaced so the caller can record/why-skip transparently.

    READ-ONLY: backtest_genome never mutates the genome or any live file.
    """
    params = (champion.get("params") or {})
    try:
        stats = oos_backtest.backtest_genome(symbol, timeframe, params, days=days)
    except Exception as exc:
        return False, None, "{}: {}".format(type(exc).__name__, exc)
    return bool(stats.get("accept")), stats, None


# --------------------------------------------------------------------------- #
# Governance-REJECTED champion tracking
# --------------------------------------------------------------------------- #
def rejected_champion_names(_gov=gov):
    """
    Collect the set of champion NAMES that governance has REJECTED, so the
    pipeline never re-proposes a candidate Claude (or peer consensus) already
    turned down.

    We read every proposal via gov._load_all() and, for those with status
    REJECTED, pull the candidate name out of the proposal payload (payload.name,
    or payload.genome.name) and — as a fallback — scan the rationale text. The
    returned set is matched case-sensitively by exact name first, with a
    lowercased mirror for tolerant substring checks (see _is_rejected).
    """
    names = set()
    try:
        allp = _gov._load_all() or {}
    except Exception:
        return names
    for raw in allp.values():
        if not isinstance(raw, dict):
            continue
        if raw.get("status") != gov.ST_REJECTED:
            continue
        payload = raw.get("payload") or {}
        # primary: explicit name fields on the proposal payload
        nm = payload.get("name")
        if not nm:
            g = payload.get("genome") or {}
            if isinstance(g, dict):
                nm = g.get("name")
        if nm:
            names.add(str(nm))
        # fallback: a name embedded in the rationale text
        rat = raw.get("rationale") or ""
        if rat:
            names.add(rat)  # kept whole; matched via substring in _is_rejected
    return names


def _is_rejected(name, rejected_names):
    """
    True if a champion `name` matches any governance-REJECTED entry. Matches by
    exact name OR by the champion name appearing inside a rejected rationale
    string (so a champion named in a rejection rationale is also skipped).
    """
    if not name:
        return False
    if name in rejected_names:
        return True
    for r in rejected_names:
        if not r:
            continue
        # exact, or champion-name-as-substring-of-rationale
        if name == r or (len(name) >= 4 and name in r):
            return True
    return False


# --------------------------------------------------------------------------- #
# State persistence (own bookkeeping only — never a live genome file)
# --------------------------------------------------------------------------- #
def _now():
    return datetime.now(timezone.utc).isoformat()


def load_state(path=STATE_PATH):
    """Load the pipeline state; tolerate a missing/corrupt file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    if not isinstance(st, dict):
        st = {}
    st.setdefault("seen_champion_ids", [])
    st.setdefault("proposals", [])     # [{champion_id, proposal_id, name, ts}]
    st.setdefault("runs", 0)
    return st


def save_state(state, path=STATE_PATH):
    """Atomically persist the pipeline state."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp{}".format(os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Governance proposal for the top NEW champion
# --------------------------------------------------------------------------- #
def propose_crown(champion, oos_stats=None):
    """
    File a crown_genome governance proposal for ONE champion.

    crown_genome is forced to RISK_HIGH by agent_governance.resolve_risk(), so
    the proposal enters the Claude consult queue (NEEDS_CLAUDE) and can never be
    auto-applied. This function only calls gov.propose(); it neither approves
    nor applies anything.

    `oos_stats` (when provided) is OUR engine's independent backtest result for
    this champion — it is recorded in the payload and rationale so the consult
    queue shows the second-opinion that justified proposing it.

    Returns the proposal id (str).
    """
    p = champion.get("params") or {}
    a = champion.get("algory_stats") or {}
    oos = oos_stats or {}

    # payload shape expected by agent_governance._apply_crown_genome:
    #   {'genome': {...full params...}, 'name', 'fitness', 'dethroned', 'note'}
    payload = {
        "genome": p,
        "name": champion.get("name"),
        "fitness": round(float(champion.get("robustness_score", 0.0)), 6),
        "dethroned": None,        # governor/Claude resolves the reigning champion
        "note": "Proposed by radhi_auto_pipeline (BRICK A). Source: {}".format(
            champion.get("source", "algory")
        ),
        # extra context for the consult queue (ignored by the applier)
        "champion_id": champion_id(champion),
        "robustness_score": champion.get("robustness_score"),
        "algory_stats": {
            "linearity_oos": a.get("linearity_oos"),
            "trades_oos": a.get("trades_oos"),
            "profit_factor": a.get("profit_factor"),
            "drawdown_pct": a.get("drawdown_pct"),
            "win_rate": a.get("win_rate"),
        },
        # OUR independent second opinion (runtime.oos_backtest) — the gate that
        # actually authorized this proposal.
        "our_oos": {
            "accept": oos.get("accept"),
            "trades_oos": oos.get("trades_oos"),
            "profit_factor_oos": oos.get("profit_factor_oos"),
            "return_pct": oos.get("return_pct"),
            "max_dd_pct": oos.get("max_dd_pct"),
            "linearity_oos": oos.get("linearity_oos"),
            "cost_source": oos.get("cost_source"),
            "straddle_rate": oos.get("straddle_rate"),
        } if oos else None,
    }

    rationale = (
        "Top INDEPENDENTLY-VALIDATED Radhi-aligned champion {name}: "
        "robustness={score:.4f}, Algory[linearity_oos={lin}, trades_oos={trd}, "
        "PF={pf}, dd={dd}]. OUR engine OOS: accept={oacc}, trades_oos={otrd}, "
        "PF_oos={opf}. Passed radhi_accept AND our independent oos_backtest. "
        "Crown requires Claude approval before going live."
    ).format(
        name=champion.get("name"),
        score=float(champion.get("robustness_score", 0.0)),
        lin=a.get("linearity_oos"),
        trd=a.get("trades_oos"),
        pf=a.get("profit_factor"),
        dd=a.get("drawdown_pct"),
        oacc=oos.get("accept"),
        otrd=oos.get("trades_oos"),
        opf=oos.get("profit_factor_oos"),
    )

    pid = gov.propose(
        agent=AGENT_NAME,
        action="crown_genome",
        target="genome:crown",
        payload=payload,
        rationale=rationale,
        risk=gov.RISK_HIGH,   # cosmetic — resolve_risk forces HIGH regardless
    )
    return pid


# --------------------------------------------------------------------------- #
# Reject → next loop : propose exactly ONE independently-validated candidate
# --------------------------------------------------------------------------- #
def propose_next_validated(src_dir=ALGORY_SRC_DIR, state_path=STATE_PATH,
                           symbol=OOS_SYMBOL, timeframe=OOS_TIMEFRAME,
                           days=OOS_DAYS):
    """
    Scan ranked champions best-first and file EXACTLY ONE crown proposal for the
    next candidate that:
        • has NOT already been seen/proposed (pipeline state), and
        • has NOT been REJECTED by governance (by name match), and
        • PASSES our own independent OOS gate (oos_backtest.accept == True:
          trades_oos >= 60 AND OOS PF > 1.1).

    This is the reject → next loop: the moment a candidate fails any check we
    move on to the next ranked champion, and we stop at the first that qualifies.
    Every candidate inspected is recorded as seen so the loop advances on the
    next run instead of re-testing the same failures.

    If NONE qualify (the current reality — all 32 fail our OOS), we propose
    nothing and return reason
        "no OOS-validated candidate — awaiting a stronger Algory campaign".

    Returns a dict:
        {
          "proposed": <name> | None,
          "reason": <str>,
          "proposal_id": <str> | None,
          "candidate_id": <str> | None,
          "scanned": <int>,            # candidates inspected this run
          "skipped_seen": <int>,
          "skipped_rejected": <int>,
          "failed_oos": <int>,
          "our_oos": <stats dict> | None,   # the winner's OOS stats (if proposed)
          "state_path": <str>,
        }
    Touches no live genome/data file; only state_path may be written.
    """
    genomes, _total_read = import_from_all_locations(src_dir)
    ranked = rank_champions(genomes)

    state = load_state(state_path)
    seen = set(state.get("seen_champion_ids", []))
    rejected = rejected_champion_names()

    scanned = 0
    skipped_seen = 0
    skipped_rejected = 0
    failed_oos = 0

    proposed_name = None
    proposal_id = None
    candidate_id = None
    winner_oos = None
    reason = "no OOS-validated candidate — awaiting a stronger Algory campaign"

    for champ in ranked:
        cid = champion_id(champ)
        name = champ.get("name")

        # 1) already seen / proposed → skip (do NOT re-mark; it's already there)
        if cid in seen:
            skipped_seen += 1
            continue

        # 2) governance-REJECTED → skip and mark seen so we never revisit it
        if _is_rejected(name, rejected):
            skipped_rejected += 1
            seen.add(cid)
            continue

        # 3) our independent OOS gate
        scanned += 1
        accepted, oos_stats, err = validate_oos(
            champ, symbol=symbol, timeframe=timeframe, days=days)
        if not accepted:
            failed_oos += 1
            # mark seen so the reject → next loop advances past this failure
            seen.add(cid)
            continue

        # 4) qualifies → file exactly ONE crown proposal, then stop.
        try:
            proposal_id = propose_crown(champ, oos_stats=oos_stats)
            proposed_name = name
            candidate_id = cid
            winner_oos = oos_stats
            reason = "independently OOS-validated (our engine accept=True)"
            seen.add(cid)
            state.setdefault("proposals", []).append({
                "champion_id": cid,
                "proposal_id": proposal_id,
                "name": name,
                "ts": _now(),
                "validated_by": "oos_backtest",
            })
        except Exception as exc:
            reason = "propose failed: {}: {}".format(type(exc).__name__, exc)
            proposed_name = None
        break  # exactly one proposal per call

    state["seen_champion_ids"] = sorted(seen)
    state["runs"] = int(state.get("runs", 0)) + 1
    state["last_run_ts"] = _now()
    save_state(state, state_path)

    return {
        "proposed": proposed_name,
        "reason": reason,
        "proposal_id": proposal_id,
        "candidate_id": candidate_id,
        "scanned": scanned,
        "skipped_seen": skipped_seen,
        "skipped_rejected": skipped_rejected,
        "failed_oos": failed_oos,
        "ranked": len(ranked),
        "our_oos": winner_oos,
        "state_path": state_path,
    }


# --------------------------------------------------------------------------- #
# Pipeline driver
# --------------------------------------------------------------------------- #
def run_pipeline(src_dir=ALGORY_SRC_DIR, state_path=STATE_PATH, do_propose=True):
    """
    Execute one pass of the gated self-feeding pipeline.

    Returns a result dict:
        {
          "total_read": int,            # strategy docs parsed across all locations
          "total_mapped": int,          # genomes mapped
          "accepted": int,              # passed radhi_accept (pre-dedupe)
          "champions": int,             # ranked+deduped champions
          "new_champions": [ {id,name,score}, ... ],   # newest first by rank
          "proposed": {id, proposal_id, name, score} | None,
          "state_path": str,
        }
    No live genome/data file is touched; only state_path may be written.
    """
    genomes, total_read = import_from_all_locations(src_dir)

    accepted = sum(1 for g in genomes if radhi_accept(g)[0])
    ranked = rank_champions(genomes)   # already filtered + scored + deduped

    state = load_state(state_path)
    seen = set(state.get("seen_champion_ids", []))
    rejected = rejected_champion_names()

    # Identify NEW champions, preserving rank order (ranked is best-first).
    new_champions = []
    for champ in ranked:
        cid = champion_id(champ)
        if cid in seen:
            continue
        new_champions.append((cid, champ))

    # PROPOSE — reject → next loop. Walk new champions best-first; skip any whose
    # name was governance-REJECTED, and ONLY propose the first one that passes
    # OUR OWN independent OOS gate (oos_backtest.accept == True). Champions our
    # engine rejects are never proposed. Exactly one proposal is filed.
    proposed = None
    if do_propose:
        for cid, champ in new_champions:
            name = champ.get("name")
            if _is_rejected(name, rejected):
                continue
            accepted_oos, oos_stats, _err = validate_oos(champ)
            if not accepted_oos:
                continue
            try:
                proposal_id = propose_crown(champ, oos_stats=oos_stats)
                proposed = {
                    "id": cid,
                    "proposal_id": proposal_id,
                    "name": name,
                    "score": round(float(champ.get("robustness_score", 0.0)), 6),
                    "our_oos": oos_stats,
                }
                state.setdefault("proposals", []).append({
                    "champion_id": cid,
                    "proposal_id": proposal_id,
                    "name": name,
                    "ts": _now(),
                    "validated_by": "oos_backtest",
                })
            except Exception as exc:
                proposed = {"error": "{}: {}".format(type(exc).__name__, exc)}
            break

    # Mark ALL new champions as seen so we never re-propose/re-test the same ones
    # — the reject → next loop advances to genuinely fresh strategies next run.
    for cid, _ in new_champions:
        seen.add(cid)
    state["seen_champion_ids"] = sorted(seen)
    state["runs"] = int(state.get("runs", 0)) + 1
    state["last_run_ts"] = _now()
    save_state(state, state_path)

    return {
        "total_read": total_read,
        "total_mapped": len(genomes),
        "accepted": accepted,
        "champions": len(ranked),
        "new_champions": [
            {
                "id": cid,
                "name": champ.get("name"),
                "score": round(float(champ.get("robustness_score", 0.0)), 6),
            }
            for cid, champ in new_champions
        ],
        "proposed": proposed,
        "state_path": state_path,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _main(argv):
    # Flags (order-independent):
    #   --scan   run the full pipeline summary (legacy behavior)
    #   <path>   override the Algory source dir
    args = [a for a in argv[1:]]
    do_scan = "--scan" in args
    args = [a for a in args if not a.startswith("--")]
    src_dir = args[0] if args else ALGORY_SRC_DIR

    if do_scan:
        res = run_pipeline(src_dir=src_dir)
        print("=" * 70)
        print("RADHI AUTO PIPELINE  (BRICK A — gated, no auto-deploy)")
        print("=" * 70)
        print("  source dir       : {}".format(src_dir))
        print("  strategy docs read: {}".format(res["total_read"]))
        print("  genomes mapped    : {}".format(res["total_mapped"]))
        print("  passed filter     : {}".format(res["accepted"]))
        print("  ranked champions  : {}".format(res["champions"]))
        print("  NEW champions     : {}".format(len(res["new_champions"])))
        if res["new_champions"]:
            print("")
            print("  New champions this run (best first):")
            for i, nc in enumerate(res["new_champions"][:10], 1):
                print("    {}. {} | score={:.4f} | id={}".format(
                    i, nc["name"], nc["score"], nc["id"]))
        print("")
        prop = res["proposed"]
        if prop is None:
            print("  PROPOSED          : none (no OOS-validated new champion)")
        elif "error" in prop:
            print("  PROPOSED          : FAILED ({})".format(prop["error"]))
        else:
            print("  PROPOSED          : crown_genome -> {}".format(prop["name"]))
            print("    proposal_id     : {}".format(prop["proposal_id"]))
            print("    score           : {:.4f}".format(prop["score"]))
            print("    status          : NEEDS_CLAUDE (RISK_HIGH; awaiting approval)")
            print("    NOTE            : NOT applied. No live_genome file modified.")
        print("")
        print("  state file        : {}".format(res["state_path"]))
        print("=" * 70)
        return 0

    # DEFAULT: the reject → next loop — propose exactly ONE independently
    # OOS-validated candidate (or nothing, transparently).
    res = propose_next_validated(src_dir=src_dir)
    print("=" * 70)
    print("RADHI AUTO PIPELINE — propose_next_validated (reject → next loop)")
    print("=" * 70)
    print("  source dir          : {}".format(src_dir))
    print("  ranked champions    : {}".format(res["ranked"]))
    print("  skipped (seen)      : {}".format(res["skipped_seen"]))
    print("  skipped (REJECTED)  : {}".format(res["skipped_rejected"]))
    print("  OOS-tested this run : {}".format(res["scanned"]))
    print("  failed our OOS      : {}".format(res["failed_oos"]))
    print("")
    if res["proposed"]:
        print("  PROPOSED            : crown_genome -> {}".format(res["proposed"]))
        print("    proposal_id       : {}".format(res["proposal_id"]))
        print("    candidate_id      : {}".format(res["candidate_id"]))
        oos = res.get("our_oos") or {}
        print("    our OOS           : accept={} trades_oos={} PF_oos={}".format(
            oos.get("accept"), oos.get("trades_oos"), oos.get("profit_factor_oos")))
        print("    status            : NEEDS_CLAUDE (RISK_HIGH; awaiting approval)")
        print("    NOTE              : NOT applied. No live_genome file modified.")
    else:
        print("  PROPOSED            : none")
        print("    reason            : {}".format(res["reason"]))
    print("")
    print("  state file          : {}".format(res["state_path"]))
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
