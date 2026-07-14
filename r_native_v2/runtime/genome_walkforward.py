"""genome_walkforward.py — walk-forward validation of a GENOME (the key to
un-pausing 99782). Wraps the independent oos_backtest.backtest_genome across
several recency WINDOWS and only declares a genome VALIDATED if its
out-of-sample edge (PF_oos > threshold, enough OOS trades) holds in the
MAJORITY of windows — not just one lucky period.

Discipline: the live genome was paused for chronic live losses. We resume ONLY
a genome that survives walk-forward here. Running it on the paused genome gives
an honest verdict (expected: FAIL → pause was correct). Reusable for GA
candidates: pass any genome dict.

Run:  python -m runtime.genome_walkforward --once            (validate the live genome)
      python -m runtime.genome_walkforward --once --unpause  (delete pause flag IF it passes)
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

from runtime import oos_backtest as ob

DATA = _V2 / "data"
WINDOWS_DAYS = [60, 120, 180]      # recency windows for the walk-forward robustness check
PF_OOS_MIN = 1.15                  # out-of-sample profit factor must clear this
MIN_OOS_TRADES = 40                # ...on at least this many OOS trades
MIN_WINDOWS_PASS = 2               # ...in at least this many of the windows
REPORT = DATA / "genome_walkforward.md"
VERDICT = DATA / "genome_walkforward.json"
PAUSE_FLAG = DATA / "genome_paused.json"


def validate_genome(genome: dict, symbol: str, tf: str) -> dict:
    name = genome.get("name") or (genome.get("params", {}) or {}).get("name") or "?"
    per_window = []
    for days in WINDOWS_DAYS:
        try:
            r = ob.backtest_genome(symbol, tf, genome, days=days)
            pf = r.get("profit_factor_oos")
            per_window.append({
                "days": days, "pf_oos": pf, "trades_oos": r.get("trades_oos"),
                "ret_pct": r.get("return_pct"), "lin_oos": r.get("linearity_oos"),
                "pass": bool(isinstance(pf, (int, float)) and pf > PF_OOS_MIN
                             and (r.get("trades_oos") or 0) >= MIN_OOS_TRADES),
            })
        except Exception as e:
            per_window.append({"days": days, "error": str(e), "pass": False})
    passes = sum(1 for w in per_window if w.get("pass"))
    validated = passes >= MIN_WINDOWS_PASS
    return {"name": name, "symbol": symbol, "tf": tf, "windows": per_window,
            "windows_passed": passes, "validated": validated, "ts": int(time.time())}


def _live_genome(symbol: str) -> dict | None:
    f = DATA / f"live_genome__{symbol}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def run(symbol: str = "XAUUSDm", unpause: bool = False) -> dict:
    g = _live_genome(symbol)
    if not g:
        return {"ok": False, "reason": f"no live genome for {symbol}"}
    tf = ob._infer_timeframe_from_name(g, default="M5")
    v = validate_genome(g, symbol, tf)

    L = ["# تحقّق Walk-Forward للجينوم — مفتاح إعادة التشغيل\n",
         f"الجينوم: **{v['name']}** · {symbol} {tf} · نوافذ: {WINDOWS_DAYS} يوم\n",
         f"عتبة القبول: PF_oos > {PF_OOS_MIN} على ≥{MIN_OOS_TRADES} صفقة OOS، في ≥{MIN_WINDOWS_PASS} نوافذ\n",
         "| نافذة | PF_oos | صفقات OOS | عائد% | خطّية_oos | نجح؟ |",
         "|------|--------|-----------|-------|-----------|------|"]
    for w in v["windows"]:
        if "error" in w:
            L.append(f"| {w['days']}d | خطأ: {w['error'][:30]} | - | - | - | ✗ |")
        else:
            L.append(f"| {w['days']}d | {w['pf_oos']} | {w['trades_oos']} | {w['ret_pct']} | {w['lin_oos']} | {'✓' if w['pass'] else '✗'} |")
    L.append("")
    L.append(f"**النتيجة: {'✅ مُثبَت — يصمد walk-forward' if v['validated'] else '⛔ غير مُثبَت — يبقى موقوفاً (القرار صحيح)'}** "
             f"({v['windows_passed']}/{len(WINDOWS_DAYS)} نوافذ)")
    L.append("\n> الانضباط: لا نعيد تشغيل الجينوم إلا لو صمد out-of-sample عبر عدّة نوافذ. (تقريب core-indicators — sanity check لا وعد ربح.)")
    REPORT.write_text("\n".join(L), encoding="utf-8")
    VERDICT.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")

    unpaused = False
    if v["validated"] and unpause and PAUSE_FLAG.exists():
        PAUSE_FLAG.unlink()
        unpaused = True
    v["ok"] = True; v["unpaused"] = unpaused
    return v


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSDm")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--unpause", action="store_true",
                    help="delete genome_paused.json IF the genome passes walk-forward")
    args = ap.parse_args(argv)
    r = run(args.symbol, unpause=args.unpause)
    print(f"[genome_walkforward] {json.dumps({k: r[k] for k in ('ok','name','validated','windows_passed','unpaused') if k in r}, ensure_ascii=False)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
