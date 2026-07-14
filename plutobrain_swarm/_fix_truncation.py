"""Repair the truncated tail of Agentic_Profiled_Grid_GOLD_LIVE.mq5.
Keep every complete line, drop the corrupted final partial Print, and restore
the box bottom-border + the two closing braces (if-block + OnDeinit).
No trading logic is invented — only the 3 structural lines that were cut off.
Backs up first. Pass --apply to write; default is dry-run (prints the plan)."""
import re
import shutil
import sys
import time
from pathlib import Path

F = Path(r"C:\Users\Radhi\MT5\live_ea\Agentic_Profiled_Grid_GOLD_LIVE.mq5")

raw = F.read_text(encoding="utf-8", errors="replace")
lines = raw.split("\n")

last = len(lines) - 1
while last >= 0 and lines[last].strip() == "":
    last -= 1
if "Print(" not in lines[last] or "�" not in lines[last]:
    sys.exit(f"ABORT: tail isn't the expected corrupted Print (line {last+1}): {lines[last]!r}")

top = next(l for l in reversed(lines[:last]) if "╔" in l)
width = top.count("═")
indent = re.match(r"\s*", lines[last]).group(0)
bottom = f'{indent}Print("╚{"═" * width}╝");'

new_tail = [bottom, "   }", "}", ""]
repaired = lines[:last] + new_tail

print("=== will REPLACE corrupted final line ===")
print(f"  {last+1}: {lines[last]!r}")
print("=== with these 3 lines + trailing newline ===")
for l in new_tail[:-1]:
    print(f"  + {l}")

if "--apply" in sys.argv:
    bak = F.with_suffix(F.suffix + f".bak_truncfix_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(F, bak)
    F.write_text("\n".join(repaired), encoding="utf-8")
    print(f"\nAPPLIED. backup: {bak.name}")
else:
    print("\n(dry-run — pass --apply to write)")
