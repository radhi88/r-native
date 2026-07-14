"""Wire GridDNA_Common.mqh into a Grid EA: replace the 31 byte-exact inline helper
functions with a single #include. Globals stay above (verified safe insertion point).
Dry-run by default; pass --apply to write (backs up first).

    python _refactor_ea.py tester
    python _refactor_ea.py live --apply
"""
import re
import shutil
import sys
import time
from pathlib import Path

EAS = {
    "tester": Path(r"C:\Users\Radhi\MT5\active_ea\Agentic_Profiled_Grid_Tester_GOLD_v7_2_DNA_EVOLVE.mq5"),
    "live": Path(r"C:\Users\Radhi\MT5\live_ea\Agentic_Profiled_Grid_GOLD_LIVE.mq5"),
}
COMMON = Path(r"C:\Users\Radhi\MT5\mql5_shared\GridDNA_Common.mqh")
INCLUDE_LINE = '#include "..\\mql5_shared\\GridDNA_Common.mqh"   // PlutoBrain: shared Grid helpers'

SIG = re.compile(r"\b(?:void|int|double|bool|string|datetime|long|ulong|color)\s+"
                 r"([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", re.M)


def shared_names():
    """the 31 names defined in the include."""
    t = COMMON.read_text(encoding="utf-8")
    return {m.group(1) for m in SIG.finditer(t)}


def spans(text, targets):
    """list of (start, end, name) full brace-matched spans for target functions."""
    out = []
    for m in SIG.finditer(text):
        if m.group(1) not in targets:
            continue
        depth, j = 0, m.end() - 1
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append((m.start(), j + 1, m.group(1)))
    return out


def refactor(key, apply):
    f = EAS[key]
    text = f.read_text(encoding="utf-8", errors="replace")
    targets = shared_names()
    sp = spans(text, targets)
    found = {n for _, _, n in sp}
    missing = targets - found
    print(f"[{key}] {f.name}")
    print(f"  shared functions in include: {len(targets)} | found inline in EA: {len(sp)}")
    if missing:
        print(f"  WARNING: not inline in this EA (skipped): {sorted(missing)}")

    insert_at = min(s for s, _, _ in sp)
    # remove spans back-to-front, then insert include at the earliest original start
    pieces = sorted(sp, key=lambda x: x[0], reverse=True)
    new = text
    for s, e, _ in pieces:
        # also swallow trailing blank line after the function
        end = e
        while end < len(new) and new[end] in "\r\n":
            end += 1
        new = new[:s] + new[end:]
    # recompute insertion offset (shifted by removals before it = none, insert_at was the first)
    new = new[:insert_at] + INCLUDE_LINE + "\n\n" + new[insert_at:]

    ob, cb = new.count("{"), new.count("}")
    op, cp = new.count("("), new.count(")")
    remaining = spans(new, targets)
    print(f"  braces {ob}/{cb}  parens {op}/{cp}  -> {'OK' if ob==cb and op==cp else 'IMBALANCED'}")
    print(f"  inline duplicates remaining after refactor: {len(remaining)} (want 0)")
    print(f"  size {len(text)} -> {len(new)} bytes ({len(text)-len(new)} removed)")

    if apply:
        if ob != cb or op != cp or remaining:
            sys.exit("  ABORT: post-refactor verification failed, not writing.")
        bak = f.with_suffix(f.suffix + f".bak_dedup_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(f, bak)
        f.write_text(new, encoding="utf-8")
        print(f"  APPLIED. backup: {bak.name}")
    else:
        print("  (dry-run — pass --apply to write)")


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "tester"
    refactor(key, "--apply" in sys.argv)
