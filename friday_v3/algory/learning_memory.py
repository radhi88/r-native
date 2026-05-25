"""
learning_memory.py — Persistent memory that accumulates R's understanding of
Algory's genetic factory over time.

Each watcher tick produces a snapshot. This module:
  1. Detects deltas vs. previous snapshot (new strategies, gene rating changes)
  2. Appends timestamped events to a journal
  3. Updates a confidence model per gene (rolling pass-rate over time)
  4. Tracks archetype evolution (which archetypes are winning lately)
  5. Computes a "R IQ score" — how much R has learned

Files:
  data/r_memory/journal.jsonl       — append-only event log
  data/r_memory/gene_history.json   — per-gene rolling stats
  data/r_memory/strategy_index.json — every strategy ever observed
  data/r_memory/archetype_trends.json — archetype performance over time
"""
from __future__ import annotations
import json
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

R_HOME    = Path(r"C:\Users\Radhi\MT5\friday_v3\data\r_memory")
JOURNAL   = R_HOME / "journal.jsonl"
GENE_HIST = R_HOME / "gene_history.json"
STRAT_IDX = R_HOME / "strategy_index.json"
ARCH_TR   = R_HOME / "archetype_trends.json"
IQ_FILE   = R_HOME / "r_iq.json"


def _load(path: Path, default):
    if not path.exists(): return default
    try:    return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default


def _save(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_journal(event: dict):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _hash_strategy(data: dict) -> str:
    """Stable hash of a strategy ID + symbol + tf."""
    key = f"{data.get('id','?')}_{data.get('symbol','?')}_{data.get('timeframe','?')}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def absorb_snapshot(report: dict) -> dict:
    """Process a fresh algory_report.json — detect deltas, update memory.
    Returns a small summary of what changed.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── 1. Track strategies ──
    strat_idx = _load(STRAT_IDX, {})   # hash → record
    vault = (report.get("vault_summary") or {}).get("top_10", [])
    new_strategies = []
    updated_returns = []
    for s in vault:
        h = _hash_strategy(s)
        old = strat_idx.get(h)
        rec = {
            "first_seen":   (old or {}).get("first_seen", now_iso),
            "last_seen":    now_iso,
            "best_return":  max((old or {}).get("best_return", 0),
                                s.get("return_pct") or 0),
            "best_dd":      min((old or {}).get("best_dd", 999),
                                s.get("drawdown_pct") or 999),
            "snapshot":     s,
        }
        strat_idx[h] = rec
        if old is None:
            new_strategies.append(s)
        elif (s.get("return_pct") or 0) > (old.get("best_return") or 0):
            updated_returns.append((s, old.get("best_return", 0)))
    _save(STRAT_IDX, strat_idx)

    # ── 2. Track gene history (rolling pass-rate) ──
    gene_hist = _load(GENE_HIST, {})
    glb = report.get("gene_rankings_global", {})
    xau = report.get("gene_rankings_xauh1", {})
    gene_changes = []

    def _update_gene_log(gene_dict, scope_prefix):
        for gene, stats in gene_dict.items():
            key = f"{scope_prefix}:{gene}"
            old = gene_hist.get(key, {})
            new_pr = stats.get("pass_rate", 0)
            old_pr = old.get("latest_pass_rate", None)
            history = old.get("history", [])
            # only append if rate changed materially or first time
            if old_pr is None or abs(new_pr - old_pr) >= 1.0:
                history.append({"ts": now_iso, "pass_rate": new_pr,
                                "pass": stats.get("pass", 0),
                                "fail": stats.get("fail", 0),
                                "verdict": stats.get("verdict", "")})
                # keep last 200 points
                history = history[-200:]
                if old_pr is not None:
                    gene_changes.append({
                        "gene": gene, "scope": scope_prefix,
                        "old_pass_rate": old_pr, "new_pass_rate": new_pr,
                        "delta": round(new_pr - old_pr, 1),
                    })
            gene_hist[key] = {
                "gene":            gene,
                "scope":           scope_prefix,
                "latest_pass_rate": new_pr,
                "latest_verdict":  stats.get("verdict", ""),
                "appearances":     stats.get("appearances", stats.get("total", 0)),
                "history":         history,
            }
    _update_gene_log(glb, "global")
    _update_gene_log(xau, "XAU_H1")
    _save(GENE_HIST, gene_hist)

    # ── 3. Archetype trends ──
    arch_tr = _load(ARCH_TR, {})
    arch_now = (report.get("vault_summary") or {}).get("by_archetype", {})
    for arch, stats in arch_now.items():
        rec = arch_tr.setdefault(arch, {"snapshots": []})
        rec["snapshots"].append({
            "ts": now_iso,
            "count": stats.get("count", 0),
            "avg_return": stats.get("avg_return", 0),
            "avg_dd": stats.get("avg_dd", 0),
        })
        rec["snapshots"] = rec["snapshots"][-100:]
        rec["latest"] = rec["snapshots"][-1]
        # Trend: compare last vs first
        if len(rec["snapshots"]) >= 2:
            first = rec["snapshots"][0]
            last  = rec["snapshots"][-1]
            rec["trend_count"]  = last["count"]  - first["count"]
            rec["trend_return"] = round(last["avg_return"] - first["avg_return"], 1)
    _save(ARCH_TR, arch_tr)

    # ── 4. Journal events ──
    if new_strategies:
        _append_journal({
            "ts": now_iso, "type": "NEW_STRATEGY",
            "count": len(new_strategies),
            "best": new_strategies[0] if new_strategies else None,
        })
    for s, old_ret in updated_returns[:5]:
        _append_journal({
            "ts": now_iso, "type": "RETURN_IMPROVED",
            "strategy_id": s.get("id"), "symbol": s.get("symbol"),
            "old": round(old_ret, 1), "new": round(s.get("return_pct",0), 1),
        })
    for c in gene_changes[:10]:
        _append_journal({
            "ts": now_iso, "type": "GENE_RATING_CHANGE",
            "gene": c["gene"], "scope": c["scope"],
            "delta": c["delta"], "new_pass_rate": c["new_pass_rate"],
        })

    # ── 5. R IQ Score ──
    iq = compute_r_iq(report, strat_idx, gene_hist, arch_tr)
    _save(IQ_FILE, iq)

    return {
        "ts":                now_iso,
        "new_strategies":    len(new_strategies),
        "updated_returns":   len(updated_returns),
        "gene_changes":      len(gene_changes),
        "iq":                iq,
    }


def compute_r_iq(report: dict, strat_idx: dict, gene_hist: dict, arch_tr: dict) -> dict:
    """
    R IQ — a single composite of how much R has learned.

    Components:
      • observation_breadth: # unique strategies tracked
      • temporal_depth:      span of journal (hours/days)
      • gene_resolution:     # genes with >5 history points
      • archetype_coverage:  # archetypes tracked
      • signal_clarity:      # genes with high-confidence verdict (TRUSTED or AVOID)
    """
    breadth = len(strat_idx)
    # journal time span
    span_h = 0.0
    if JOURNAL.exists():
        try:
            with open(JOURNAL, encoding="utf-8") as f:
                lines = f.readlines()
                if lines:
                    first_ts = json.loads(lines[0])["ts"]
                    last_ts  = json.loads(lines[-1])["ts"]
                    span_h = (datetime.fromisoformat(last_ts.replace("Z","+00:00")) -
                              datetime.fromisoformat(first_ts.replace("Z","+00:00"))).total_seconds() / 3600
        except Exception: pass

    high_res_genes = sum(1 for k, v in gene_hist.items() if len(v.get("history", [])) >= 5)
    clarity = sum(1 for k, v in gene_hist.items() if v.get("latest_verdict") in ("TRUSTED","AVOID"))

    # Score 0-1000
    raw = (
        min(200, breadth * 2.5) +              # 200 pts max from strategies
        min(200, span_h * 2) +                 # 200 pts max from time depth (100h)
        min(200, high_res_genes * 4) +         # 200 pts max from gene resolution
        min(100, len(arch_tr) * 25) +          # 100 pts max from archetype coverage
        min(300, clarity * 5)                  # 300 pts max from clarity
    )
    level = (
        "NOVICE"   if raw < 100 else
        "STUDENT"  if raw < 300 else
        "ADEPT"    if raw < 500 else
        "MASTER"   if raw < 800 else
        "ORACLE"
    )
    return {
        "raw":                  round(raw, 1),
        "level":                level,
        "observation_breadth":  breadth,
        "temporal_depth_hours": round(span_h, 1),
        "gene_resolution":      high_res_genes,
        "archetype_coverage":   len(arch_tr),
        "signal_clarity":       clarity,
        "computed_at":          datetime.now(timezone.utc).isoformat(),
    }


def get_memory_summary(max_journal: int = 30) -> dict:
    """Return everything needed by the R Factory UI."""
    journal_lines = []
    if JOURNAL.exists():
        try:
            with open(JOURNAL, encoding="utf-8") as f:
                for line in f.readlines()[-max_journal:][::-1]:
                    try: journal_lines.append(json.loads(line))
                    except Exception: pass
        except Exception: pass

    return {
        "iq":               _load(IQ_FILE, {}),
        "journal":          journal_lines,
        "strategy_index":   _load(STRAT_IDX, {}),
        "gene_history":     _load(GENE_HIST, {}),
        "archetype_trends": _load(ARCH_TR, {}),
    }


if __name__ == "__main__":
    # Standalone: read latest algory_report and absorb it
    report_path = Path(r"C:\Users\Radhi\MT5\friday_v3\data\algory_report.json")
    if not report_path.exists():
        print("Run friday_v3.algory.algory_watcher first."); raise SystemExit(1)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = absorb_snapshot(report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
