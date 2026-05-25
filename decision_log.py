"""decision_log.py — per-genome JSONL log of WHY a live trade opened/closed.

One file per genome at:
  C:\\Users\\Radhi\\MT5\\data\\r_native\\decision_log\\<genome_id>.jsonl
Use "_NONE" when genome_id is null/empty.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOG_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\decision_log")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(gid) -> str:
    if gid is None: return "_NONE"
    s = str(gid).strip()
    return s if s else "_NONE"


def _path_for(gid) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"{_safe_id(gid)}.jsonl"


def _append(gid, record: dict) -> None:
    p = _path_for(gid)
    line = json.dumps(record, ensure_ascii=False)
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _flatten_signal(item) -> dict:
    """Accept tuple (flag, dir, reason) OR dict — return canonical dict."""
    if isinstance(item, dict):
        return {
            "flag":   item.get("flag") or item.get("name") or "?",
            "vote":   item.get("vote") if "vote" in item else item.get("dir"),
            "reason": item.get("reason") or item.get("why") or "",
        }
    if isinstance(item, (list, tuple)):
        flag = item[0] if len(item) > 0 else "?"
        d    = item[1] if len(item) > 1 else None
        why  = item[2] if len(item) > 2 else ""
        vote = d
        if isinstance(d, str):
            vote = 1 if d.upper() == "BUY" else -1 if d.upper() == "SELL" else 0
        return {"flag": flag, "vote": vote, "reason": why}
    return {"flag": str(item), "vote": 0, "reason": ""}


def _flatten_pair(item) -> dict:
    """For biases_aligned / filters_blocking — usually (flag, reason)."""
    if isinstance(item, dict):
        return {"flag": item.get("flag") or item.get("name") or "?",
                "reason": item.get("reason") or item.get("why") or ""}
    if isinstance(item, (list, tuple)):
        return {"flag": item[0] if len(item) > 0 else "?",
                "reason": item[1] if len(item) > 1 else ""}
    return {"flag": str(item), "reason": ""}


def record_open(*, ticket, genome_id, symbol, side, entry, sl, tp, lot,
                confidence, archetype, gate_verdict_dict, indicators_dict) -> None:
    g = gate_verdict_dict or {}
    sig = [_flatten_signal(x) for x in (g.get("signals_fired") or [])]
    bia = [_flatten_pair(x)   for x in (g.get("biases_aligned") or [])]
    flt = [_flatten_pair(x)   for x in (g.get("filters_blocking") or [])]
    rec = {
        "ts":              _now_iso(),
        "kind":            "OPEN",
        "ticket":          int(ticket) if ticket is not None else None,
        "genome_id":       _safe_id(genome_id),
        "symbol":          symbol,
        "side":            side,
        "entry":           float(entry) if entry is not None else None,
        "sl":              float(sl)    if sl    is not None else None,
        "tp":              float(tp)    if tp    is not None else None,
        "lot":             float(lot)   if lot   is not None else None,
        "confidence":      int(confidence) if confidence is not None else None,
        "archetype":       archetype,
        "signals_fired":   sig,
        "biases_aligned":  bia,
        "filters_blocking": flt,
        "indicators":      indicators_dict or {},
    }
    _append(genome_id, rec)


def record_close(*, ticket, genome_id, exit_price, profit, exit_reason) -> None:
    rec = {
        "ts":          _now_iso(),
        "kind":        "CLOSE",
        "ticket":      int(ticket) if ticket is not None else None,
        "genome_id":   _safe_id(genome_id),
        "exit_price":  float(exit_price) if exit_price is not None else None,
        "profit":      float(profit) if profit is not None else None,
        "exit_reason": exit_reason,
    }
    _append(genome_id, rec)


def _read_jsonl(p: Path) -> list:
    out = []
    if not p.exists(): return out
    try:
        with open(p, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln: continue
                try: out.append(json.loads(ln))
                except Exception: pass
    except Exception:
        pass
    return out


def list_decisions(genome_id: Optional[str] = None) -> list:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if genome_id is not None:
        return _read_jsonl(_path_for(genome_id))
    out = []
    for p in sorted(LOG_DIR.glob("*.jsonl")):
        out.extend(_read_jsonl(p))
    return out


def query_by_ticket(ticket: int) -> Optional[dict]:
    try: t = int(ticket)
    except Exception: return None
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for p in sorted(LOG_DIR.glob("*.jsonl")):
        for rec in _read_jsonl(p):
            if rec.get("ticket") == t and rec.get("kind") == "OPEN":
                return rec
    return None
