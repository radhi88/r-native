"""
friday_mql5_compile.py — Compile any .mq5 file using metaeditor64.exe.

Usage:
    from friday_mql5_compile import compile_mq5
    ok, log = compile_mq5(r"C:\path\to\file.mq5")
    if ok: print("compiled clean")
    else:  print("errors:", log)

Or from CLI:
    python friday_mql5_compile.py "C:\path\to\file.mq5"
"""
from __future__ import annotations
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

METAEDITOR = Path(r"C:\Program Files\MetaTrader 5 EXNESS\metaeditor64.exe")
COMPILE_LOG_FALLBACK = Path(r"C:\Users\Radhi\MT5\mql5_compile.log")
INCLUDE_DIR = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\53785E099C927DB68A545C249CDBCE06\MQL5")


def compile_mq5(src_path: str | Path, timeout_s: int = 60) -> tuple[bool, str]:
    """
    Compile a .mq5 file. Returns (ok, log_text).

    metaeditor64.exe CLI:
        /compile:"<file>"   compile target file
        /log:"<file>"       write compile log to file
        /inc:"<dir>"        include path (auto-set from /compile by default)
    """
    src = Path(src_path)
    if not src.exists():
        return False, f"file not found: {src}"
    if not METAEDITOR.exists():
        return False, f"metaeditor not found: {METAEDITOR}"

    log_file = src.with_suffix(".log")
    if log_file.exists():
        try: log_file.unlink()
        except: pass

    cmd = [
        str(METAEDITOR),
        f"/compile:{src}",
        f"/log:{log_file}",
        f"/inc:{INCLUDE_DIR}",
    ]
    try:
        # MetaEditor exits 0 on success, 1 on errors. Exit code is reliable.
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        log_text = ""
        if log_file.exists():
            # Logs are UTF-16 LE by default
            try:
                log_text = log_file.read_text(encoding="utf-16-le")
            except Exception:
                log_text = log_file.read_text(encoding="utf-8", errors="replace")

        # Parse "Result: N errors, M warnings" — this is the authoritative signal
        m = re.search(r"Result:\s*(\d+)\s+errors?,\s*(\d+)\s+warnings?", log_text, re.IGNORECASE)
        if m:
            n_errors   = int(m.group(1))
            n_warnings = int(m.group(2))
            ok = (n_errors == 0)
            summary_str = f"{n_errors} errors, {n_warnings} warnings"
        else:
            # No "Result:" line — use exit code as fallback
            ok = (proc.returncode == 0)
            summary_str = f"no Result line (exit={proc.returncode})"

        return ok, log_text + f"\n\n[EXIT={proc.returncode}] [SUMMARY: {summary_str}]"
    except subprocess.TimeoutExpired:
        return False, f"compile timeout after {timeout_s}s"
    except Exception as e:
        return False, f"compile error: {e}"


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    src = sys.argv[1]
    print(f"Compiling: {src}")
    ok, log = compile_mq5(src)
    tag = "✓ OK" if ok else "✗ FAILED"
    print(f"{tag}\n{'─'*60}")
    print(log[-2000:])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
