"""smc_lab.py — تجربة توليفات SMC بصدق علمي: أي رمز × فريم × اتجاه × طريقة TP، OOS بلا lookahead.

يعيد استخدام محرّك cot_ob_backtest الموجود (دخول OB-mitigation، خروج SL هيكلي، صافي بعد
cost_model الحقيقي، تقسيم 67/33 IS/OOS) — لكن يعمّمه على أي فريم ويشغّل مصفوفة كاملة.

السؤال الذي يجيبه بالأرقام (لا وعود): لأي (رمز×فريم) دخول OB له حافة OOS؟ وهل TP عند منطقة
SMC (NZ = أقرب منطقة معاكسة) يتفوّق على R الثابت (2R/3R) بعد السبريد؟ الحافة = OOS PF فقط.

Run: .venv\\Scripts\\python.exe r_native_v2\\runtime\\smc_lab.py [SYM1,SYM2] [TF1,TF2]
"""
from __future__ import annotations
import datetime as _dt, json, sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME)); sys.path.insert(0, str(RUNTIME / "shared"))
from cot_ob_backtest import simulate, split_metrics  # محرّك مثبت بلا lookahead

# فريم → (ثابت MT5، أيام التحميل). عيّنة أكبر = حكم إحصائي أقوى (الحل لحاجز 25-صفقة).
_TF_DAYS = {"M1": 45, "M5": 180, "M15": 365, "M30": 540, "H1": 900, "H4": 1100}
MIN_OOS_TRADES = 12          # عتبة دلالة: تجاهل التوليفات بأقل من هذا OOS
EDGE_PF = 1.20               # حد الحافة المقبولة OOS PF


def load_bars(symbol, tf, days=None):
    import MetaTrader5 as mt5
    tfmap = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
             "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
    days = days or _TF_DAYS.get(tf, 120)
    ok = mt5.initialize() or mt5.initialize()
    if not ok:
        raise RuntimeError(f"mt5 init: {mt5.last_error()}")
    try:
        now = _dt.datetime.now(_dt.timezone.utc)
        rates = mt5.copy_rates_range(symbol, tfmap[tf], now - _dt.timedelta(days=days), now)
        return rates
    finally:
        try: mt5.shutdown()
        except Exception: pass


def run_symbol_tf(symbol, tf):
    """كل التوليفات (اتجاه × TP) لهذا الرمز/الفريم. يرجع صفوف OOS."""
    rates = load_bars(symbol, tf)
    rows = []
    if rates is None or len(rates) < 400:
        return rows
    bars = len(rates)
    for side in ("long", "short"):
        for tp in ("2R", "3R", "NZ"):     # NZ = TP عند منطقة SMC معاكسة (طلب المستخدم) vs R ثابت
            try:
                trades = simulate(rates, symbol, side, tp, gate_fn=None)
                oos = split_metrics(trades)["OOS"]
                rows.append({"symbol": symbol, "tf": tf, "side": side, "tp": tp,
                             "bars": bars, "oos_trades": oos["trades"], "oos_wr": oos["win_rate"],
                             "oos_pf": oos["profit_factor"], "oos_net": oos["net"],
                             "oos_dd": oos["max_drawdown"]})
            except Exception as e:
                rows.append({"symbol": symbol, "tf": tf, "side": side, "tp": tp, "error": str(e)[:80]})
    return rows


def main():
    syms = (sys.argv[1].split(",") if len(sys.argv) > 1 else ["XAUUSDm", "BTCUSDm"])
    tfs = (sys.argv[2].split(",") if len(sys.argv) > 2 else ["M5", "M15", "H1"])
    allrows = []
    for s in syms:
        for tf in tfs:
            print(f"[SMC-LAB] {s} {tf} ...", flush=True)
            try:
                allrows.extend(run_symbol_tf(s, tf))
            except Exception as e:
                print(f"  err {s} {tf}: {e}", flush=True)
    valid = [r for r in allrows if "error" not in r and r.get("oos_trades", 0) >= MIN_OOS_TRADES]
    valid.sort(key=lambda r: -r["oos_pf"])
    print("\n=== OOS ranked (>= %d trades) — الحافة = PF>%.2f ===" % (MIN_OOS_TRADES, EDGE_PF))
    print(f"{'sym':9} {'tf':4} {'side':5} {'tp':3} {'n':>4} {'wr%':>5} {'PF':>6} {'net$':>9}  edge")
    for r in valid:
        edge = "✅ EDGE" if r["oos_pf"] >= EDGE_PF else ("~" if r["oos_pf"] >= 1.0 else "✗")
        print(f"{r['symbol']:9} {r['tf']:4} {r['side']:5} {r['tp']:3} {r['oos_trades']:>4} "
              f"{r['oos_wr']:>5} {r['oos_pf']:>6} {r['oos_net']:>9.1f}  {edge}")
    winners = [r for r in valid if r["oos_pf"] >= EDGE_PF]
    out = RUNTIME.parent / "data" / "smc_lab_results.json"
    out.write_text(json.dumps({"ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                               "ranked": valid, "winners": winners}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwinners (OOS edge): {len(winners)}/{len(valid)} configs -> {out}")
    return winners


if __name__ == "__main__":
    main()
