"""genome_rollback.py — auto-revert a newly-deployed genome if it regresses
on its first N live trades.

When `continuous_evolution._maybe_auto_deploy` ships a new genome onto a
symbol, this module starts watching its live win-rate. If after a few
trades the new genome materially under-performs the genome it replaced,
we revert the deploy and demote the new genome to a HoF "regressed" tag
so it doesn't get re-deployed without further evolution.

Run via the orchestrator (RollbackMonitor agent in Phase 8b) — this
module is pure logic so the same code works in unit tests and live.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Symbol configs (Windows path used by the rest of the stack)
SYMBOL_CFG = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
ROLLBACK_LOG = Path(r"C:\Users\Radhi\MT5\data\r_native\rollback_log.jsonl")


def evaluate_post_deploy(symbol: str,
                          window_trades: int = 10,
                          regression_pct: float = 15.0) -> dict:
    """Inspect the currently deployed genome's last `window_trades` outcomes
    and compare against the genome it replaced (if any). Returns a verdict.

    Decision rule: if the new genome's win-rate is more than `regression_pct`
    percentage points BELOW the predecessor's win-rate over the same
    sample size — recommend rollback.
    """
    cfg_path = SYMBOL_CFG / f"{symbol}.json"
    if not cfg_path.exists():
        return {"ok": False, "reason": "no symbol config"}
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "reason": f"cfg read err: {e}"}

    deployed = cfg.get("deployed_genome") or {}
    new_id = deployed.get("id")
    if not new_id:
        return {"ok": False, "reason": "no deployed genome"}

    prev_id = (cfg.get("previous_deployed") or {}).get("id")
    if not prev_id:
        return {"ok": False, "reason": "no previous deploy to compare against"}

    # Read recent live trades for this symbol from HoF index
    try:
        from r_native.hall_of_fame import load_index
        idx = load_index()
    except Exception as e:
        return {"ok": False, "reason": f"hof read err: {e}"}

    new_entry  = idx.get(new_id)  or {}
    prev_entry = idx.get(prev_id) or {}

    new_wr  = _live_winrate(new_entry,  window_trades)
    prev_wr = _live_winrate(prev_entry, window_trades)

    # Need enough sample on the new genome before we judge
    new_trades = int(new_entry.get("live_trades") or 0)
    if new_trades < window_trades:
        return {"ok": True, "regressed": False, "reason":
                f"need {window_trades} live trades, have {new_trades}"}

    regressed = (new_wr is not None and prev_wr is not None
                 and prev_wr - new_wr >= regression_pct)
    return {
        "ok": True,
        "regressed": regressed,
        "new_id":     new_id,  "new_wr":  new_wr,
        "prev_id":    prev_id, "prev_wr": prev_wr,
        "gap_pct":    (prev_wr - new_wr) if (new_wr is not None and prev_wr is not None) else None,
        "window":     window_trades,
        "reason":     "regression" if regressed else "within tolerance",
    }


def execute_rollback(symbol: str,
                      reason: str = "",
                      backup_to_killed: bool = False) -> dict:
    """Restore the symbol's `previous_deployed` genome to active duty.
    Idempotent — if there's no previous to restore, returns ok=False with
    a reason. The new (failing) genome is tagged in HoF with
    `rolled_back=True` so future GA cycles know to skip it as a parent."""
    cfg_path = SYMBOL_CFG / f"{symbol}.json"
    if not cfg_path.exists():
        return {"ok": False, "reason": "no symbol config"}
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "reason": f"cfg read err: {e}"}

    prev = cfg.get("previous_deployed")
    if not prev or not prev.get("id"):
        return {"ok": False, "reason": "no previous deployed to roll back to"}

    current = dict(cfg.get("deployed_genome") or {})
    failed_id = current.get("id")

    # Swap: previous becomes current, current becomes "rolled_back"
    cfg["deployed_genome"]   = dict(prev)
    cfg["previous_deployed"] = None
    cfg["rolled_back_from"]  = {
        "id":     failed_id,
        "reason": reason,
        "at":     datetime.now(timezone.utc).isoformat(),
    }
    try:
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    except Exception as e:
        return {"ok": False, "reason": f"cfg write err: {e}"}

    # Tag in HoF so future breeders avoid using this genome as a parent
    try:
        from r_native.hall_of_fame import load_index, _write_json, INDEX_PATH
        idx = load_index()
        if failed_id and failed_id in idx:
            idx[failed_id]["rolled_back"] = True
            idx[failed_id]["rolled_back_reason"] = reason
            idx[failed_id]["last_updated"] = datetime.now(timezone.utc).isoformat()
            _write_json(INDEX_PATH, idx)
            if backup_to_killed:
                from r_native.hall_of_fame import kill
                kill(failed_id, f"rollback: {reason}")
    except Exception as e:
        pass    # HoF tagging is best-effort

    _append_rollback_log({
        "ts":         datetime.now(timezone.utc).isoformat(),
        "symbol":     symbol,
        "failed_id":  failed_id,
        "restored_id": prev.get("id"),
        "reason":     reason,
    })
    return {"ok": True, "restored": prev.get("id"), "failed": failed_id,
            "reason": reason}


# ─── Helpers ─────────────────────────────────────────────────────
def _live_winrate(entry: dict, window: int) -> Optional[float]:
    """Approximate live win-rate using the running P/L + trade count
    stored on the HoF entry. We don't have per-trade history here, so we
    use the entry's running stats as a proxy. Conservative — returns None
    if the entry doesn't carry enough info."""
    trades = int(entry.get("live_trades") or 0)
    if trades < window: return None
    # Prefer a precomputed wr field if it exists
    if isinstance(entry.get("live_winrate"), (int, float)):
        return float(entry["live_winrate"])
    # Otherwise use stats.win_rate (backtest), warn-only
    stats = entry.get("stats") or {}
    if isinstance(stats.get("win_rate"), (int, float)):
        return float(stats["win_rate"])
    return None


def _append_rollback_log(entry: dict) -> None:
    try:
        ROLLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ROLLBACK_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def history(limit: int = 50) -> list[dict]:
    """Return the most recent rollbacks (for the inspector UI)."""
    if not ROLLBACK_LOG.exists(): return []
    try:
        with ROLLBACK_LOG.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        out = []
        for line in lines[-limit:]:
            try: out.append(json.loads(line))
            except Exception: continue
        return out
    except Exception:
        return []
