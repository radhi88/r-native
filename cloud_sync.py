"""cloud_sync.py — J.15 — Sync combo_fitness + symbol_configs across machines.

Two backends:
  1. GIST (default, free) — sync via private GitHub Gist
  2. FILE (e.g. OneDrive folder) — sync via any shared filesystem

Use case: federated learning. Run R Native on a workstation + laptop + VPS.
Each contributes campaigns to shared `combo_fitness.json`. All three get
smarter together.

Settings: data/r_native/cloud_sync.json
{
  "enabled":   true,
  "backend":   "gist",
  "gist_token": "ghp_...",        // GitHub Personal Access Token (gist scope)
  "gist_id":    "abc123...",       // private Gist ID
  "file_path": "C:/OneDrive/r_native_sync/",  // for FILE backend
  "sync_files": ["combo_fitness.json"],
  "auto_sync_minutes": 60          // periodic background sync
}

Conflict resolution:
- combo_fitness.json: MERGE entries (sum wins/fails, max last_seen)
- symbol_configs: keep latest by `created_at` per genome_id
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\cloud_sync.json")
LOCAL_DIR   = Path(r"C:\Users\Radhi\MT5\data\r_native")

DEFAULTS = {
    "enabled":           False,
    "backend":           "gist",
    "gist_token":        "",
    "gist_id":           "",
    "file_path":         "",
    "sync_files":        ["combo_fitness.json"],
    "auto_sync_minutes": 60,
    "last_synced":       None,
}

_stop = threading.Event()
_thread: threading.Thread | None = None


def load() -> dict:
    if not CONFIG_PATH.exists(): return DEFAULTS.copy()
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = DEFAULTS.copy(); cfg.update(loaded); return cfg
    except Exception:
        return DEFAULTS.copy()


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


# ── Merge logic for combo_fitness ─────────────────────────────────────
def _merge_combo_fitness(local: dict, remote: dict) -> dict:
    """Per-bucket merge. Sum wins/fails, take max for cumulative stats."""
    if not isinstance(local, dict): return remote
    if not isinstance(remote, dict): return local
    merged = {}
    for key in set(local) | set(remote):
        if key in ("_global",) or (key in local and isinstance(local[key], dict) and "genes" in local[key]):
            # Bucket-level merge
            merged[key] = _merge_bucket(local.get(key, {}), remote.get(key, {}))
        elif isinstance(local.get(key), dict) and isinstance(remote.get(key), dict):
            # Per-symbol/per-TF nested
            merged[key] = {}
            for tf in set(local[key]) | set(remote[key]):
                merged[key][tf] = _merge_bucket(local[key].get(tf, {}),
                                                 remote[key].get(tf, {}))
        else:
            merged[key] = local.get(key, remote.get(key))
    return merged


def _merge_bucket(a: dict, b: dict) -> dict:
    out = {
        "total_campaigns": (a.get("total_campaigns", 0) +
                            b.get("total_campaigns", 0)),
        "genes":      _merge_counters(a.get("genes", {}),      b.get("genes", {})),
        "combos":     _merge_counters(a.get("combos", {}),     b.get("combos", {})),
        "exec_modes": _merge_counters(a.get("exec_modes", {}), b.get("exec_modes", {})),
        "params":     {**a.get("params", {}), **b.get("params", {})},
    }
    return out


def _merge_counters(a: dict, b: dict) -> dict:
    """For each key, sum wins/fails, average other numeric fields, max last_seen."""
    out = {}
    for k in set(a) | set(b):
        va = a.get(k, {})
        vb = b.get(k, {})
        if not isinstance(va, dict) or not isinstance(vb, dict):
            out[k] = vb or va; continue
        merged = {}
        for field in set(va) | set(vb):
            if field in ("wins", "fails", "mid_oos_pass", "mid_oos_fail",
                          "appearances"):
                merged[field] = va.get(field, 0) + vb.get(field, 0)
            elif field == "last_seen":
                merged[field] = max(va.get(field, ""), vb.get(field, ""))
            elif field == "best_return":
                merged[field] = max(va.get(field, 0), vb.get(field, 0))
            elif field in ("avg_return", "avg_dd"):
                # Weighted average by appearances
                na = va.get("appearances", 0) or 1
                nb = vb.get("appearances", 0) or 1
                merged[field] = round((va.get(field, 0) * na + vb.get(field, 0) * nb)
                                       / (na + nb), 4)
            else:
                merged[field] = vb.get(field, va.get(field))
        out[k] = merged
    return out


# ── GIST backend ──────────────────────────────────────────────────────
def _gist_pull(token: str, gist_id: str, filename: str) -> dict | None:
    if not (token and gist_id): return None
    req = urllib.request.Request(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"token {token}",
                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
        f = (d.get("files") or {}).get(filename)
        if not f or not f.get("content"): return None
        return json.loads(f["content"])
    except Exception as e:
        print(f"[cloud_sync] gist pull err: {e}"); return None


def _gist_push(token: str, gist_id: str, filename: str, content: dict) -> bool:
    if not (token and gist_id): return False
    data = json.dumps({
        "files": {filename: {"content": json.dumps(content, ensure_ascii=False, indent=2)}}
    }).encode()
    req = urllib.request.Request(
        f"https://api.github.com/gists/{gist_id}",
        data=data, method="PATCH",
        headers={"Authorization": f"token {token}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        print(f"[cloud_sync] gist push err: {e}"); return False


# ── FILE backend ──────────────────────────────────────────────────────
def _file_pull(folder: Path, filename: str) -> dict | None:
    p = folder / filename
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


def _file_push(folder: Path, filename: str, content: dict) -> bool:
    folder.mkdir(parents=True, exist_ok=True)
    try:
        (folder / filename).write_text(json.dumps(content, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        return True
    except Exception as e:
        print(f"[cloud_sync] file push err: {e}"); return False


# ── Master sync ───────────────────────────────────────────────────────
def sync_now() -> dict:
    """Pull remote → merge with local → push merged. Returns result summary."""
    cfg = load()
    if not cfg.get("enabled"): return {"ok": False, "reason": "disabled"}
    results = {}
    for fn in cfg.get("sync_files", []):
        local_path = LOCAL_DIR / fn
        if not local_path.exists():
            results[fn] = "local missing"; continue
        try: local = json.loads(local_path.read_text(encoding="utf-8"))
        except Exception as e: results[fn] = f"local read err: {e}"; continue

        # Pull remote
        if cfg["backend"] == "gist":
            remote = _gist_pull(cfg["gist_token"], cfg["gist_id"], fn)
        else:
            remote = _file_pull(Path(cfg["file_path"]), fn)

        # Merge (only combo_fitness has merge logic; others are last-write-wins)
        if fn == "combo_fitness.json" and remote:
            merged = _merge_combo_fitness(local, remote)
        else:
            merged = local

        # Write merged locally
        local_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                              encoding="utf-8")

        # Push back
        if cfg["backend"] == "gist":
            ok = _gist_push(cfg["gist_token"], cfg["gist_id"], fn, merged)
        else:
            ok = _file_push(Path(cfg["file_path"]), fn, merged)

        results[fn] = "synced" if ok else "push failed"

    cfg["last_synced"] = datetime.now(timezone.utc).isoformat()
    save(cfg)
    return {"ok": True, "results": results, "synced_at": cfg["last_synced"]}


def _auto_loop():
    while not _stop.is_set():
        cfg = load()
        if cfg.get("enabled"):
            try: sync_now()
            except Exception as e: print(f"[cloud_sync] auto err: {e}")
        _stop.wait(max(60, int(cfg.get("auto_sync_minutes", 60)) * 60))


def start_auto_sync():
    global _thread
    if _thread and _thread.is_alive(): return
    _stop.clear()
    _thread = threading.Thread(target=_auto_loop, daemon=True, name="cloud-sync")
    _thread.start()


def stop_auto_sync():
    _stop.set()


if __name__ == "__main__":
    print(json.dumps(sync_now(), indent=2))
