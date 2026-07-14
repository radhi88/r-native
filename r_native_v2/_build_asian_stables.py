"""One-shot: build session-specialist stables for Asian-liquidity candidates, log to file."""
import sys, json, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import genome_factory as gf

LOG = Path(__file__).resolve().parent / "data" / "_asian_build.log"
SYMS = ["USDJPYm", "EURJPYm", "GBPJPYm", "JP225m", "BTCUSDm", "AUDUSDm", "NZDUSDm"]


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        LOG.write_text("mt5 init failed\n", encoding="utf-8"); return 1
    with open(LOG, "w", encoding="utf-8") as f:
        for s in SYMS:
            try:
                st = gf.build_session_specialists(mt5, s)
                f.write(s + ": " + json.dumps([(x["session"], x["tf"], x["pf"], x["trades"]) for x in st]) + "\n")
            except Exception:
                f.write(s + " ERR " + traceback.format_exc()[-300:] + "\n")
            f.flush()
        f.write("DONE\n")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
