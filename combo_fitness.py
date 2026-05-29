"""combo_fitness.py — Algory-style per-combo gene fitness tracking.

The "secret sauce" of Algory: after each campaign, record how each unique gene
COMBO performed (wins/fails/avg_return/mid_oos_pass/fail). Engine can then bias
mutation toward proven winners and away from dead-end combos.

Store: data/r_native/combo_fitness.json
Structure:
{
  "_global": {
    "total_campaigns": 7,
    "genes": {"use_bias_ema": {wins, fails, mid_oos_pass, mid_oos_fail,
                                avg_return, avg_dd, best_return, appearances,
                                last_seen}},
    "combos": {"bias_ema+sig_macd+filt_adx": {wins, fails, avg_return, last_seen}},
    "exec_modes": {"market2": {wins, fails, avg_return, last_seen}}
  },
  "XAUUSDm": {"H1": { ...same shape... }},
  ...
}

Conventions:
- A "combo key" is a comma-sorted underscore-joined list of gene short names.
- A "win" = strategy passed purge AND OOS validation.
- A "fail" = strategy was killed by purge OR failed OOS.
- "mid_oos_pass/fail" tracks the OOS half specifically.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

FITNESS_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\combo_fitness.json")

# Score thresholds for win/fail classification (mirrors Algory's defaults)
WIN_PF_MIN  = 1.5
WIN_TRADES_MIN = 40
WIN_DD_MAX  = 10.0

# Cap on per-combo entries to keep file size manageable
MAX_COMBOS_PER_BUCKET = 5000

_today = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Combo-key generation ───────────────────────────────────────────────
def _short(g: str) -> str:
    """Convert 'use_bias_ema' → 'bias_ema'. Keep canonical short form."""
    return g.replace("use_", "")


def combo_key(active_genes: Iterable[str]) -> str:
    """Build deterministic combo key from active gene names (sorted)."""
    shorts = sorted(set(_short(g) for g in active_genes))
    return "+".join(shorts) if shorts else "(empty)"


# ── Persistence ────────────────────────────────────────────────────────
def _empty_db() -> dict:
    return {
        "_global": {
            "total_campaigns": 0,
            "genes":      {},
            "combos":     {},
            "exec_modes": {},
            "params":     {"start_hour": {}, "rr_bucket": {}},
        }
    }


def load() -> dict:
    if not FITNESS_PATH.exists():
        return _empty_db()
    try:
        return json.loads(FITNESS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _empty_db()


def save(db: dict) -> None:
    FITNESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FITNESS_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2),
                            encoding="utf-8")


# ── Bucket selection ──────────────────────────────────────────────────
def _bucket(db: dict, symbol: str | None, tf: str | None) -> dict:
    """Get the {symbol -> {tf -> data}} bucket. Falls back to _global."""
    if symbol and tf:
        sym = db.setdefault(symbol, {})
        return sym.setdefault(tf, {
            "total_campaigns": 0,
            "genes":      {},
            "combos":     {},
            "exec_modes": {},
            "params":     {"start_hour": {}, "rr_bucket": {}},
        })
    return db["_global"]


# ── Record outcomes ───────────────────────────────────────────────────
def _is_winner(stats: dict) -> bool:
    pf = stats.get("profit_factor", 0) or 0
    tr = stats.get("trades", 0) or 0
    dd = abs(stats.get("max_drawdown_pct", 0) or 0)
    return pf >= WIN_PF_MIN and tr >= WIN_TRADES_MIN and dd <= WIN_DD_MAX


def _is_oos_pass(stats: dict) -> bool:
    """Proxy for OOS validation: high linearity + meaningful return."""
    lin = stats.get("linearity", 0) or 0
    ret = stats.get("total_return_pct", 0) or 0
    return lin >= 0.7 and ret > 0


def _bump_gene(bucket: dict, gene: str, stats: dict, won: bool, oos_pass: bool):
    g = bucket["genes"].setdefault(gene, {
        "wins": 0, "fails": 0,
        "mid_oos_pass": 0, "mid_oos_fail": 0,
        "avg_return": 0.0, "avg_dd": 0.0,
        "best_return": 0.0, "appearances": 0,
        "last_seen": _today(),
    })
    g["appearances"] += 1
    g["last_seen"]    = _today()
    if won:    g["wins"]   += 1
    else:      g["fails"]  += 1
    if oos_pass: g["mid_oos_pass"] += 1
    else:        g["mid_oos_fail"] += 1
    # Running averages (incremental)
    n  = g["appearances"]
    ret = stats.get("total_return_pct", 0) or 0
    dd  = abs(stats.get("max_drawdown_pct", 0) or 0)
    g["avg_return"] = round((g["avg_return"] * (n - 1) + ret) / n, 4)
    g["avg_dd"]     = round((g["avg_dd"]     * (n - 1) + dd ) / n, 4)
    g["best_return"] = max(g["best_return"], ret)


def _bump_combo(bucket: dict, key: str, stats: dict, won: bool):
    c = bucket["combos"].setdefault(key, {
        "wins": 0, "fails": 0,
        "avg_return": 0.0, "last_seen": _today(),
    })
    if won: c["wins"]  += 1
    else:   c["fails"] += 1
    c["last_seen"] = _today()
    total = c["wins"] + c["fails"]
    ret = stats.get("total_return_pct", 0) or 0
    c["avg_return"] = round((c["avg_return"] * (total - 1) + ret) / total, 4)


def _bump_exec_mode(bucket: dict, exec_mode: str, stats: dict, won: bool):
    e = bucket["exec_modes"].setdefault(exec_mode, {
        "wins": 0, "fails": 0, "avg_return": 0.0, "last_seen": _today(),
    })
    if won: e["wins"]  += 1
    else:   e["fails"] += 1
    e["last_seen"] = _today()
    total = e["wins"] + e["fails"]
    ret = stats.get("total_return_pct", 0) or 0
    e["avg_return"] = round((e["avg_return"] * (total - 1) + ret) / total, 4)


def _bump_param(bucket: dict, name: str, value):
    p = bucket["params"].setdefault(name, {})
    k = str(value)
    p[k] = p.get(k, 0) + 1


# ── SMC per-trade context recording (Phase 6 / learning loop) ─────────
# Lets the breeder distinguish "OB trades that worked because IDM was swept
# first" from "raw OB trades that failed" — by partitioning the SAME flag
# set's trades across the idm_swept_before vs no_idm_sweep context keys.
_SMC_CTX_KEYS_ALL = (
    "bos_aligned", "bos_counter",
    "in_fresh_ob", "in_mitigated_ob",
    "in_fresh_fvg", "in_mitigated_fvg",
    "idm_swept_before", "no_idm_sweep",
    "htf_aligned", "htf_misaligned",
    "tp_hit_liquidity", "tp_hit_opposite_ob", "tp_hit_atr_target",
    "exit_sl", "exit_trail",
)


def _ensure_smc_buckets(bucket: dict) -> None:
    """Backfill smc sub-dicts on a bucket that predates this feature."""
    bucket.setdefault("smc_combos", {})
    bucket.setdefault("smc_contexts", {})


def _bump_record(store: dict, key: str, stats: dict, won: bool) -> None:
    """Increment a {key -> {wins,fails,avg_return,last_seen}} record store.
    Unlike _bump_combo, operates directly on the flat dict (not bucket['combos'])."""
    c = store.setdefault(key, {"wins": 0, "fails": 0,
                               "avg_return": 0.0, "last_seen": _today()})
    if won: c["wins"]  += 1
    else:   c["fails"] += 1
    c["last_seen"] = _today()
    total = c["wins"] + c["fails"]
    ret = stats.get("total_return_pct", 0) or 0
    c["avg_return"] = round((c["avg_return"] * (total - 1) + ret) / total, 4)


def _smc_ctx_keys(ctx: dict) -> list[str]:
    """Derive the list of context dimensions a trade belongs to."""
    keys: list[str] = []
    if ctx.get("trade_aligned_with_bos") is True:    keys.append("bos_aligned")
    elif ctx.get("trade_aligned_with_bos") is False: keys.append("bos_counter")

    if ctx.get("entry_in_ob") == "fresh":            keys.append("in_fresh_ob")
    elif ctx.get("entry_in_ob") == "mitigated":      keys.append("in_mitigated_ob")

    if ctx.get("entry_in_fvg") == "fresh":           keys.append("in_fresh_fvg")
    elif ctx.get("entry_in_fvg") == "mitigated":     keys.append("in_mitigated_fvg")

    if ctx.get("idm_swept") is True:                 keys.append("idm_swept_before")
    elif ctx.get("idm_swept") is False:              keys.append("no_idm_sweep")

    if ctx.get("htf_aligned") is True:               keys.append("htf_aligned")
    elif ctx.get("htf_aligned") is False:            keys.append("htf_misaligned")

    exit_via = ctx.get("exit_via")
    if   exit_via == "liquidity_pool":  keys.append("tp_hit_liquidity")
    elif exit_via == "opposite_ob":     keys.append("tp_hit_opposite_ob")
    elif exit_via == "atr_tp":          keys.append("tp_hit_atr_target")
    elif exit_via == "sl":              keys.append("exit_sl")
    elif exit_via == "trail":           keys.append("exit_trail")
    return keys


def record_smc_trade(symbol: str, tf: str, active_genes: list,
                     smc_context: dict, stats: dict,
                     db: dict | None = None) -> dict:
    """Record one trade's SMC context into per-symbol+TF and global buckets.

    Called from ga_simulator (per simulated trade) and from the live
    executor on position close. `stats` only needs the keys _is_winner
    reads (profit_factor/trades/max_drawdown_pct) OR a simple
    {"won": bool, "return_pct": float} shape for single-trade recording.
    """
    own_db = db is None
    db = db if db is not None else load()

    # Single-trade convenience: accept {"won": ..., "return_pct": ...}
    if "won" in stats:
        won = bool(stats["won"])
        norm_stats = {"total_return_pct": stats.get("return_pct", 0)}
    else:
        won = _is_winner(stats)
        norm_stats = stats

    smc_active = [g for g in (active_genes or []) if "smc" in g]
    ctx_keys = _smc_ctx_keys(smc_context or {})

    for bucket in (_bucket(db, symbol, tf), db["_global"]):
        _ensure_smc_buckets(bucket)
        if smc_active:
            _bump_record(bucket["smc_combos"], combo_key(smc_active), norm_stats, won)
        for k in ctx_keys:
            _bump_record(bucket["smc_contexts"], k, norm_stats, won)

    if own_db:
        save(db)
    return db


def smc_lookup(symbol: str | None = None, tf: str | None = None,
               active_genes: list | None = None,
               context_key: str | None = None) -> dict:
    """Query SMC combo or context win-rate. Symbol+TF first, then global.

    - pass active_genes to look up an SMC gene combo
    - pass context_key (e.g. "idm_swept_before") to look up a context
    """
    db = load()

    def _from(bucket: dict) -> dict | None:
        _ensure_smc_buckets(bucket)
        if active_genes:
            smc_active = [g for g in active_genes if "smc" in g]
            if smc_active:
                rec = bucket["smc_combos"].get(combo_key(smc_active))
                if rec: return {**rec, "key": combo_key(smc_active)}
        if context_key:
            rec = bucket["smc_contexts"].get(context_key)
            if rec: return {**rec, "key": context_key}
        return None

    if symbol and tf and symbol in db and tf in db[symbol]:
        r = _from(db[symbol][tf])
        if r: return {**r, "scope": f"{symbol}/{tf}"}
    r = _from(db["_global"])
    if r: return {**r, "scope": "global"}
    return {"scope": "unseen"}


def smc_context_report(symbol: str | None = None,
                       tf: str | None = None) -> dict:
    """Return win-rate for every SMC context dimension. For the inspector
    UI — shows e.g. 'idm_swept_before: 68% (34W/16L)' vs
    'no_idm_sweep: 41%'."""
    db = load()
    bucket = db["_global"]
    if symbol and tf and symbol in db and tf in db[symbol]:
        bucket = db[symbol][tf]
    _ensure_smc_buckets(bucket)
    out = {}
    for key, rec in bucket["smc_contexts"].items():
        total = rec.get("wins", 0) + rec.get("fails", 0)
        if total == 0: continue
        out[key] = {
            "win_rate":   round(rec["wins"] / total * 100, 1),
            "wins":       rec["wins"],
            "fails":      rec["fails"],
            "avg_return": rec.get("avg_return", 0.0),
        }
    return out


# ── Public API: ingest a full campaign vault ──────────────────────────
def ingest_campaign(symbol: str, tf: str, vault: list[dict],
                    db: dict | None = None) -> dict:
    """Update fitness DB with results from one campaign's vault.

    Args:
        symbol: e.g. "BTCUSDm"
        tf:     e.g. "M5"
        vault:  list of dicts from genetic_engine vault.json
                (each has {genome: {active_genes, params, ...}, stats: {...}, ...})
        db:     optional pre-loaded fitness db (else loads from disk)

    Returns the updated db (also saved to disk).
    """
    db = db or load()
    bucket_sym = _bucket(db, symbol, tf)
    bucket_glb = db["_global"]

    bucket_sym["total_campaigns"] += 1
    bucket_glb["total_campaigns"] += 1

    for r in vault:
        if not r or not r.get("genome"): continue
        g = r["genome"]; s = r.get("stats", {})
        active = g.get("active_genes", []) or []
        params = g.get("params", {}) or {}

        won      = _is_winner(s)
        oos_pass = _is_oos_pass(s)

        # 1) Per-gene stats (both per-symbol AND global)
        for gene in active:
            _bump_gene(bucket_sym, gene, s, won, oos_pass)
            _bump_gene(bucket_glb, gene, s, won, oos_pass)

        # 2) Combo key — only meaningful subset (drop exec_* — they're orthogonal)
        non_exec = [a for a in active if not a.startswith("exec_")]
        if non_exec:
            key = combo_key(non_exec)
            _bump_combo(bucket_sym, key, s, won)
            _bump_combo(bucket_glb, key, s, won)

        # 3) Exec mode (each exec_* gene is a distinct mode)
        for a in active:
            if a.startswith("exec_"):
                mode = a.replace("exec_", "")
                _bump_exec_mode(bucket_sym, mode, s, won)
                _bump_exec_mode(bucket_glb, mode, s, won)

        # 4) Param distributions (start_hour, rr_bucket)
        sh = params.get("start_hour")
        if sh is not None:
            _bump_param(bucket_sym, "start_hour", sh)
            _bump_param(bucket_glb, "start_hour", sh)
        sl = params.get("sl_atr_mult"); tp = params.get("tp_atr_mult")
        if sl and tp and sl > 0:
            rr = round(tp / sl, 1)
            bucket_glb_label = f"{rr:.1f}"
            _bump_param(bucket_sym, "rr_bucket", bucket_glb_label)
            _bump_param(bucket_glb, "rr_bucket", bucket_glb_label)

    # Cap combos to MAX per bucket (keep top by wins)
    for bucket in (bucket_sym, bucket_glb):
        if len(bucket["combos"]) > MAX_COMBOS_PER_BUCKET:
            kept = dict(sorted(bucket["combos"].items(),
                               key=lambda kv: -kv[1].get("wins", 0)
                              )[:MAX_COMBOS_PER_BUCKET])
            bucket["combos"] = kept

    save(db)
    return db


# ── Public API: query combo stats ────────────────────────────────────
def lookup_combo(active_genes: list, symbol: str | None = None,
                 tf: str | None = None) -> dict:
    """Return the fitness record for a specific combo. Tries symbol+TF first,
    falls back to global. Returns empty dict if not seen."""
    db = load()
    non_exec = [a for a in active_genes if not a.startswith("exec_")]
    if not non_exec: return {}
    key = combo_key(non_exec)
    if symbol and tf and symbol in db and tf in db[symbol]:
        c = db[symbol][tf]["combos"].get(key)
        if c: return {**c, "scope": f"{symbol}/{tf}", "key": key}
    c = db["_global"]["combos"].get(key)
    if c: return {**c, "scope": "global", "key": key}
    return {"key": key, "scope": "unseen"}


def gene_summary(gene: str, symbol: str | None = None,
                 tf: str | None = None) -> dict:
    """Return wins/fails/avg_return for a single gene."""
    db = load()
    if symbol and tf and symbol in db and tf in db[symbol]:
        g = db[symbol][tf]["genes"].get(gene)
        if g: return {**g, "scope": f"{symbol}/{tf}"}
    g = db["_global"]["genes"].get(gene)
    if g: return {**g, "scope": "global"}
    return {"gene": gene, "scope": "unseen"}


def top_genes(symbol: str | None = None, tf: str | None = None,
              n: int = 10) -> list[dict]:
    """Return top N genes by win rate (min 5 appearances)."""
    db = load()
    bucket = db["_global"]
    if symbol and tf and symbol in db and tf in db[symbol]:
        bucket = db[symbol][tf]
    items = []
    for gene, g in bucket["genes"].items():
        n_total = g["wins"] + g["fails"]
        if n_total < 5: continue
        wr = g["wins"] / n_total * 100
        items.append({
            "gene": gene, "win_rate": round(wr, 1),
            "wins": g["wins"], "fails": g["fails"],
            "avg_return": g["avg_return"], "appearances": g["appearances"],
        })
    items.sort(key=lambda x: -x["win_rate"])
    return items[:n]
