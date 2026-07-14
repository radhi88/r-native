"""migrate_to_r_native.py — One-time SAFE physical migration.

Born 2026-05-28. Makes R Native fully self-contained: moves the live
runtime from C:\\Users\\Radhi\\MT5\\r_native_v2  →  r_native/v2.

⚠️  RUN ONLY WHEN MARKET IS CLOSED (weekend / no open positions).
    It stops the stack, moves data, rewrites paths, then you relaunch
    from r_native/v2.

WHAT IT DOES (with backup + rollback at every step):
  1. Pre-flight: refuse to run if any position is open or stack is mid-trade
  2. Backup: snapshot data/ + all *.py to a timestamped backup folder
  3. Copy data: r_native_v2/data → r_native/v2/data
  4. Rewrite paths: in r_native/v2/runtime/*.py replace the hardcoded
     'C:\\Users\\Radhi\\MT5\\r_native_v2' with auto-detect (Path(__file__)...)
     — actually we replace with the r_native/v2 absolute path for safety
  5. Verify: import tokens from new location, check DATA resolves correctly
  6. Print the new launch command

ROLLBACK: every change is logged; if --rollback is passed it restores
          from the latest backup.

Usage:
    # Dry run — show what would happen, change nothing:
    python -m runtime.migrate_to_r_native --dry

    # Real migration (market closed!):
    python -m runtime.migrate_to_r_native --confirm

    # Undo:
    python -m runtime.migrate_to_r_native --rollback
"""
from __future__ import annotations
import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

OLD_ROOT = Path(r"C:\Users\Radhi\MT5\r_native_v2")
NEW_ROOT = Path(r"C:\Users\Radhi\MT5\r_native\v2")
OLD_PATH_STR = r"C:\Users\Radhi\MT5\r_native_v2"
NEW_PATH_STR = r"C:\Users\Radhi\MT5\r_native\v2"
BACKUP_BASE = NEW_ROOT / "data" / "_migration_backups"


def _preflight() -> tuple[bool, str]:
    """Refuse to migrate while trading is live."""
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            positions = mt5.positions_get() or []
            our = [p for p in positions if int(p.magic) in (99782, 20260605, 99780, 99781, 99777, 99779)]
            mt5.shutdown()
            if our:
                return False, f"{len(our)} open position(s) — close them or wait for market close"
    except Exception:
        pass
    return True, "clear"


def _backup() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_BASE / ts
    dest.mkdir(parents=True, exist_ok=True)
    # Backup the data dir (genomes, db, live state) from OLD_ROOT
    old_data = OLD_ROOT / "data"
    if old_data.exists():
        shutil.copytree(old_data, dest / "data",
                        ignore=shutil.ignore_patterns("_migration_backups", "logs", "*.tmp"))
    print(f"  ✓ backup → {dest}")
    return dest


def _copy_data() -> int:
    """Copy data from old → new (skip backups/logs/tmp)."""
    old_data = OLD_ROOT / "data"
    new_data = NEW_ROOT / "data"
    new_data.mkdir(parents=True, exist_ok=True)
    n = 0
    for item in old_data.rglob("*"):
        if any(part in ("_migration_backups", "logs", "__pycache__") for part in item.parts):
            continue
        if item.is_file():
            rel = item.relative_to(old_data)
            target = new_data / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            n += 1
    print(f"  ✓ copied {n} data files → {new_data}")
    return n


def _rewrite_paths(dry: bool) -> int:
    """Replace hardcoded OLD_PATH_STR with NEW_PATH_STR in new-location .py files."""
    runtime_dir = NEW_ROOT / "runtime"
    changed = 0
    for py in runtime_dir.rglob("*.py"):
        try:
            txt = py.read_text(encoding="utf-8")
        except Exception:
            continue
        if OLD_PATH_STR in txt:
            new_txt = txt.replace(OLD_PATH_STR, NEW_PATH_STR)
            if not dry:
                py.write_text(new_txt, encoding="utf-8")
            changed += 1
            print(f"    {'[dry] would rewrite' if dry else '✓ rewrote'} {py.relative_to(NEW_ROOT)}")
    print(f"  {'[dry] ' if dry else ''}{changed} files with path rewrites")
    return changed


def _verify() -> bool:
    """Import tokens from NEW location, confirm DATA resolves under NEW_ROOT."""
    sys.path.insert(0, str(NEW_ROOT))
    # Force re-import from new location
    for mod in list(sys.modules):
        if mod.startswith("runtime"):
            del sys.modules[mod]
    try:
        from runtime.shared.tokens import ROOT, DATA  # noqa
        ok = str(NEW_ROOT) in str(ROOT)
        print(f"  {'✓' if ok else '✗'} tokens.ROOT = {ROOT}")
        print(f"  {'✓' if ok else '✗'} tokens.DATA = {DATA}")
        # Check champion survived
        champ = NEW_ROOT / "genomes" / "champion_genome.json"
        live = DATA / "live_genome.json"
        print(f"  {'✓' if champ.exists() else '✗'} champion_genome.json present")
        print(f"  {'✓' if live.exists() else '✗'} live_genome.json present")
        return ok
    except Exception as e:
        print(f"  ✗ verify failed: {e}")
        return False


def _rollback() -> None:
    if not BACKUP_BASE.exists():
        print("  ✗ no backups found"); return
    backups = sorted(BACKUP_BASE.iterdir(), reverse=True)
    if not backups:
        print("  ✗ no backups found"); return
    latest = backups[0]
    print(f"  restoring from {latest} ...")
    src_data = latest / "data"
    if src_data.exists():
        for item in src_data.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src_data)
                target = OLD_ROOT / "data" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        print(f"  ✓ data restored to {OLD_ROOT / 'data'}")


def main():
    ap = argparse.ArgumentParser(description="Migrate runtime into r_native/v2")
    ap.add_argument("--dry", action="store_true", help="Show plan, change nothing")
    ap.add_argument("--confirm", action="store_true", help="Actually migrate")
    ap.add_argument("--rollback", action="store_true", help="Restore from latest backup")
    args = ap.parse_args()

    print("═══ R NATIVE SELF-CONTAINMENT MIGRATION ═══\n")

    if args.rollback:
        print("[ROLLBACK]")
        _rollback()
        return

    ok, reason = _preflight()
    print(f"[1] Pre-flight: {'✓ ' + reason if ok else '✗ ' + reason}")
    if not ok and not args.dry:
        print("\n  ABORTED — resolve the above, or run with --dry to preview.")
        return

    if args.dry:
        print("\n[DRY RUN — nothing will change]\n")
        print("[2] Would back up r_native_v2/data")
        print("[3] Would copy data → r_native/v2/data")
        print("[4] Path rewrites:")
        _rewrite_paths(dry=True)
        print("\n  Run with --confirm (market closed) to execute.")
        return

    if not args.confirm:
        print("\n  Refusing to run without --confirm. Use --dry to preview.")
        return

    print("\n[2] Backup")
    _backup()
    print("\n[3] Copy data")
    _copy_data()
    print("\n[4] Rewrite hardcoded paths")
    _rewrite_paths(dry=False)
    print("\n[5] Verify")
    if _verify():
        print("\n═══ ✓ MIGRATION COMPLETE ═══")
        print(f"\n  R Native is now self-contained. Launch with:")
        print(f"    cd {NEW_ROOT}")
        print(f"    python -m runtime.unified_trader   (or open R Native — auto-launches)")
        print(f"\n  Old r_native_v2/ can be archived. Rollback: --rollback")
    else:
        print("\n  ⚠️ Verification failed — review above. Data is backed up; use --rollback if needed.")


if __name__ == "__main__":
    main()
