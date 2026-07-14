"""genome_evo_logger.py — records each currency's genome quality over TIME so the dashboard can
show "وين كان الجين ووين صار بنسبة" (where the gene started → where it is now, in %).

The per-symbol genome files only hold the CURRENT OOS stats (pf/win/folds) — no history. This
logger snapshots them every ~15min into genome_evo_history.json, building a real series from the
first time it runs (baseline) onward, plus the GA factory's generation activity (born/killed/kept).

Read-only on genomes. Windowless.  Run:  python genome_evo_logger.py --loop
"""
from __future__ import annotations
import argparse, json, time, glob
from datetime import datetime, timezone
from pathlib import Path

V2 = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
GENO = V2 / "genomes"
HIST = V2 / "genome_evo_history.json"
LINEAGE = V2 / "genome_lineage.jsonl"
INTERVAL = 900          # snapshot every 15 min
MAX_SERIES = 96         # keep ~24h of points


def _load(p, d):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return d


def _ga_state() -> dict:
    """Latest GA factory generation + born/killed churn + the FITNESS EVOLUTION of the gene pool
    (best score per generation): the real 'where the engine started → where it is now, %'."""
    try:
        lines = LINEAGE.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            return {}
        last = json.loads(lines[-1])
        born = killed = 0
        scores = []
        for ln in lines:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            born += len(r.get("born", [])); killed += len(r.get("killed", []))
            ranks = r.get("fitness_ranks", []) or []
            best = max((float(x.get("score", 0) or 0) for x in ranks), default=0.0)
            if best > 0:
                scores.append(round(best, 3))
        first = scores[0] if scores else None
        peak = max(scores) if scores else None
        cur = scores[-1] if scores else None
        pct = round((peak - first) / abs(first) * 100, 1) if (first and peak) else None
        # downsample the series to ~40 points for a clean sparkline
        ser = scores
        if len(ser) > 40:
            step = len(ser) / 40.0
            ser = [ser[int(i * step)] for i in range(40)] + [ser[-1]]
        return {"generation": last.get("generation"), "kept": len(last.get("kept", [])),
                "born_recent": len(last.get("born", [])), "killed_recent": len(last.get("killed", [])),
                "born_total": born, "killed_total": killed,
                "fit_first": first, "fit_cur": cur, "fit_peak": peak, "fit_pct": pct, "fit_series": ser}
    except Exception:
        return {}


def snapshot() -> dict:
    hist = _load(HIST, {}) or {}
    syms = hist.get("symbols", {})
    now_iso = datetime.now(timezone.utc).isoformat()
    for f in glob.glob(str(GENO / "*.json")):
        g = _load(f, {})
        sym = g.get("symbol") or Path(f).stem
        oos = g.get("oos", {}) or {}
        pf = oos.get("pf")
        if pf is None:
            continue
        pf = float(pf)
        st = syms.get(sym)
        if not st:
            st = syms[sym] = {"first_pf": pf, "first_t": now_iso, "series": [], "trained": g.get("trained")}
        st["cur_pf"] = pf
        st["win"] = round(float(oos.get("win_rate", 0)) * 100, 1)
        st["folds"] = oos.get("folds_pos")
        st["trades"] = oos.get("trades")
        st["net_R"] = oos.get("net_R")
        st["trained"] = g.get("trained")
        # append a point only if it changed or series is empty (avoid flat spam)
        if not st["series"] or abs(st["series"][-1] - pf) > 1e-6:
            st["series"].append(round(pf, 3)); st["series"] = st["series"][-MAX_SERIES:]
        fp = float(st.get("first_pf", pf)) or 1e-9
        st["pct"] = round((pf - fp) / abs(fp) * 100, 1)
    out = {"updated": now_iso, "ga": _ga_state(), "symbols": syms}
    HIST.parent.mkdir(parents=True, exist_ok=True)
    tmp = HIST.with_suffix(".json.tmp"); tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    import os; os.replace(tmp, HIST)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", action="store_true"); a = ap.parse_args(argv)
    while True:
        try:
            o = snapshot()
            n = len(o["symbols"]); ga = o.get("ga", {})
            print(f"[EVO] {n} جين · GA جيل {ga.get('generation','?')} · وُلد {ga.get('born_total',0)} قُتل {ga.get('killed_total',0)}", flush=True)
        except Exception as e:
            print(f"[EVO] err {e}", flush=True)
        if not a.loop:
            break
        time.sleep(INTERVAL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
