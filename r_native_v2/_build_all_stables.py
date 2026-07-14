"""One-shot: «كل العملات نفس الشيء» — session-specialist builds for EVERY liquid candidate.
Any symbol that proves a session edge (50k bars + real spread + >=40 trades + >=3/4 folds)
joins the live roster automatically via the session router. Logged to _all_stables.log."""
import sys, json, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import genome_factory as gf

LOG = Path(__file__).resolve().parent / "data" / "_all_stables.log"
CANDS = ["EURUSDm","GBPUSDm","USDJPYm","USDCHFm","USDCADm","AUDUSDm","NZDUSDm",
         "EURJPYm","GBPJPYm","EURGBPm","EURAUDm","EURCADm","EURCHFm","EURNZDm","GBPAUDm",
         "GBPCADm","GBPCHFm","GBPNZDm","AUDJPYm","AUDCADm","AUDCHFm","AUDNZDm","CADJPYm",
         "CADCHFm","CHFJPYm","NZDJPYm","NZDCADm","XAUEURm","XAUGBPm","XAGUSDm","XNGUSDm",
         "US500m","USTECm","UK100m","AUS200m","FRA40m","HK50m","ETHUSDm","BNBUSDm","SOLUSDm",
         "XRPUSDm","LTCUSDm"]


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        LOG.write_text("mt5 init failed\n", encoding="utf-8"); return 1
    done = set()
    try:
        done = {ln.split(":")[0] for ln in LOG.read_text(encoding="utf-8").splitlines() if ":" in ln}
    except Exception:
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        for s in CANDS:
            if s in done:
                continue
            try:
                if not gf._liquid_ok(mt5, s, thr=0.45):
                    f.write(s + ": SKIP (سبريد يأكل الحافة)\n"); f.flush(); continue
                st = gf.build_session_specialists(mt5, s)
                f.write(s + ": " + json.dumps([(x["session"], x["tf"], x["pf"]) for x in st],
                                              ensure_ascii=False) + "\n")
            except Exception:
                f.write(s + " ERR " + traceback.format_exc()[-200:] + "\n")
            f.flush()
        f.write("DONE\n")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
