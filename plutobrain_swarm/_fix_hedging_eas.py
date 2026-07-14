"""Fix the 3 gold hedging-grid EAs' compile errors. Backs up each file first."""
import shutil
import time
from pathlib import Path

EXP = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\53785E099C927DB68A545C249CDBCE06\MQL5\Experts")


def patch(name, replacements, insert_after=None, insert_text=None):
    f = EXP / name
    t = f.read_text(encoding="utf-8", errors="replace")
    orig = t
    for old, new in replacements:
        if old not in t:
            print(f"  [{name}] WARN: not found: {old[:50]!r}")
        t = t.replace(old, new)
    if insert_after and insert_after in t and insert_text not in t:
        t = t.replace(insert_after, insert_after + insert_text, 1)
    if t == orig:
        print(f"  [{name}] no change")
        return
    shutil.copy2(f, f.with_suffix(f".mq5.bak_compilefix_" + time.strftime("%Y%m%d_%H%M%S")))
    f.write_text(t, encoding="utf-8")
    print(f"  [{name}] patched + backed up")


# V2: wrong account property for hedging check
patch("EA_Hedging_Grid_Gold_V2.mq5", [
    ("long tradeMode = AccountInfoInteger(ACCOUNT_TRADE_MODE);",
     "long tradeMode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);"),
    ("if(tradeMode == ACCOUNT_TRADE_MODE_RETAIL_HEDGING)",
     "if(tradeMode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)"),
])

# Robot: same, with the enum cast
patch("EA_Robot_Hedging_Grid.mq5", [
    ("ENUM_ACCOUNT_TRADE_MODE tradeMode = (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);",
     "ENUM_ACCOUNT_MARGIN_MODE tradeMode = (ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE);"),
    ("if(tradeMode == ACCOUNT_TRADE_MODE_RETAIL_HEDGING)",
     "if(tradeMode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)"),
])

# V3: declare the missing input near the grid inputs
patch("EA_Hedging_Grid_Gold_V3.mq5", [],
      insert_after="input bool     InpDynamicGrid   = true;        // Dynamic Grid (based on ATR)",
      insert_text="\ninput bool     InpCloseOnOpposite= false;       // Close opposite positions when a deal opens")
