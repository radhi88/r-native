"""Verify the Grid Tester vs Live shared functions are FULL byte-exact matches
(not just 240-char-prefix). Read-only. Extracts complete brace-balanced function
bodies from each file and compares."""
import re
from pathlib import Path

TESTER = Path(r"C:\Users\Radhi\MT5\active_ea\Agentic_Profiled_Grid_Tester_GOLD_v7_2_DNA_EVOLVE.mq5")
LIVE = Path(r"C:\Users\Radhi\MT5\live_ea\Agentic_Profiled_Grid_GOLD_LIVE.mq5")

SIG = re.compile(r"\b(?:void|int|double|bool|string|datetime|long|ulong|color)\s+"
                 r"([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", re.M)


def functions(path):
    """name -> full source (signature through matching close brace)."""
    t = path.read_text(encoding="utf-8", errors="replace")
    out = {}
    for m in SIG.finditer(t):
        name = m.group(1)
        i = m.end() - 1            # at the opening {
        depth, j = 0, i
        while j < len(t):
            c = t[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out[name] = t[m.start():j + 1]
    return out


ft, fl = functions(TESTER), functions(LIVE)
common = sorted(set(ft) & set(fl))
exact, differ = [], []
for n in common:
    (exact if ft[n] == fl[n] else differ).append(n)

print(f"common functions: {len(common)}")
print(f"  byte-exact in both: {len(exact)}")
print(f"  differ (NOT safe to share): {len(differ)}")
if differ:
    for n in differ:
        print(f"    ~ {n}  (tester {len(ft[n])}b vs live {len(fl[n])}b)")
print()
print("EXACT (safe to extract):")
print("  " + ", ".join(exact))
# total bytes saved by extracting
saved = sum(len(fl[n]) for n in exact)
print(f"\nextractable: {len(exact)} functions, ~{saved} bytes of duplication removed from the live EA")
