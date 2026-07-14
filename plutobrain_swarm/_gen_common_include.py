"""Generate GridDNA_Common.mqh from the 31 byte-exact functions shared by the
Grid Tester and Live gold EAs. Pulls full bodies from the LIVE EA (identical to
tester, verified). Additive only — does NOT modify either EA."""
import re
from pathlib import Path

TESTER = Path(r"C:\Users\Radhi\MT5\active_ea\Agentic_Profiled_Grid_Tester_GOLD_v7_2_DNA_EVOLVE.mq5")
LIVE = Path(r"C:\Users\Radhi\MT5\live_ea\Agentic_Profiled_Grid_GOLD_LIVE.mq5")
OUT = Path(r"C:\Users\Radhi\MT5\mql5_shared\GridDNA_Common.mqh")

SIG = re.compile(r"\b(?:void|int|double|bool|string|datetime|long|ulong|color)\s+"
                 r"([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", re.M)


def functions(path):
    t = path.read_text(encoding="utf-8", errors="replace")
    out = {}
    for m in SIG.finditer(t):
        depth, j = 0, m.end() - 1
        while j < len(t):
            if t[j] == "{":
                depth += 1
            elif t[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out[m.group(1)] = t[m.start():j + 1]
    return out


ft, fl = functions(TESTER), functions(LIVE)
exact = sorted(n for n in (set(ft) & set(fl)) if ft[n] == fl[n])

OUT.parent.mkdir(exist_ok=True)
header = f"""//+------------------------------------------------------------------+
//| GridDNA_Common.mqh                                               |
//| Shared utility library for the Agentic Grid GOLD EAs.            |
//|                                                                  |
//| Extracted by PlutoBrain swarm (A-05) — {len(exact)} functions that are     |
//| BYTE-EXACT in both the Tester (active_ea) and Live (live_ea) EAs.|
//| Only verified-identical pure helpers are here; functions that    |
//| differ between the two EAs were deliberately left in place.      |
//|                                                                  |
//| To adopt (after a MetaEditor compile-test):                      |
//|   1. #include "<path>/GridDNA_Common.mqh" near the top of the EA |
//|      (AFTER any globals/inputs these helpers reference).         |
//|   2. Delete the inline copies of the functions below from the EA.|
//+------------------------------------------------------------------+
#ifndef __GRIDDNA_COMMON_MQH__
#define __GRIDDNA_COMMON_MQH__

"""
body = "\n\n".join(fl[n] for n in exact)
OUT.write_text(header + body + "\n\n#endif // __GRIDDNA_COMMON_MQH__\n", encoding="utf-8")
print(f"wrote {OUT} — {len(exact)} functions, {OUT.stat().st_size} bytes")
print("functions:", ", ".join(exact))
