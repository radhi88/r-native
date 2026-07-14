# -*- coding: utf-8 -*-
"""regret_learner.py — تعلّم بالندم (counterfactual): «لو فعلتُ كذا لصار كذا».

(قراءة-فقط من MT5 + friday-db، windowless. لا order_send.)

لكل صفقة سكالب مُغلقة يعيد بناء مسار M1 من الفتح للإغلاق ويحسب:
  • MFE = أقصى ربح عائم خلال الصفقة (لو أغلقتُ عند القمة).
  • MAE = أقصى خسارة عائمة (كم غاصت قبل أن تعود).
  • المحقّق الفعليّ، و**الندم = MFE − المحقّق** (كم تركتُ على الطاولة).
ثم يجمع: نسبة التقاط القمة، والندم المتوسّط، وهل نُغلق مبكّراً (ندم +) أم متأخّراً (نُعيد ربحاً)،
ويقترح ضبطاً (مثلاً: «تُغلق عند 40% من القمة — أمسك أطول» أو «تحتجز خاسرين يعودون بعد MAE عميق»).

هذا بالضبط ما قاله المستخدم: بعد تجارب كثيرة نفهم «لو فعلنا كذا» — فنُحسّن التوقيت بلا خوف.
"""
from __future__ import annotations
import json, math, time
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5

RN = Path(r"C:\Users\Radhi\MT5") / "data" / "r_native"
OUT = RN / "regret_report.json"
LOG = RN / "regret_learner.log"
MAGIC = 20260628
POLL_S = 300.0


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _positions(days=2):
    """يعيد بناء صفقات السكالب المُغلقة (IN+OUT) من تاريخ الصفقات."""
    deals = mt5.history_deals_get(time.time() - days * 86400, time.time()) or []
    by_pos = {}
    for d in deals:
        if d.magic != MAGIC:
            continue
        by_pos.setdefault(d.position_id, []).append(d)
    out = []
    for pid, ds in by_pos.items():
        ds.sort(key=lambda d: d.time)
        ent = next((d for d in ds if d.entry == 0), None)
        ex = next((d for d in ds if d.entry == 1), None)
        if not ent or not ex:
            continue
        out.append({"sym": ent.symbol, "type": ent.type, "open_t": ent.time, "close_t": ex.time,
                    "entry": ent.price, "exit": ex.price, "vol": ent.volume,
                    "net": ex.profit + ex.commission + ex.swap})
    return out


def _mfe_mae(p):
    """MFE/MAE بوحدات السعر عبر مسار M1 من الفتح للإغلاق."""
    n = max(int((p["close_t"] - p["open_t"]) / 60) + 3, 3)
    r = mt5.copy_rates_from(p["sym"], mt5.TIMEFRAME_M1, p["open_t"], min(n, 500))
    if r is None or len(r) < 1:
        return None
    hi = float(r["high"].max()); lo = float(r["low"].min())
    if p["type"] == 0:                                  # BUY
        mfe = hi - p["entry"]; mae = p["entry"] - lo
    else:                                               # SELL
        mfe = p["entry"] - lo; mae = hi - p["entry"]
    realized = (p["exit"] - p["entry"]) if p["type"] == 0 else (p["entry"] - p["exit"])
    return {"mfe": mfe, "mae": mae, "realized": realized, "net": p["net"]}


def analyze():
    pos = _positions()
    rows = [m for p in pos if (m := _mfe_mae(p))]
    if not rows:
        return {"n": 0}
    mfe = np.array([r["mfe"] for r in rows]); real = np.array([r["realized"] for r in rows])
    mae = np.array([r["mae"] for r in rows]); net = np.array([r["net"] for r in rows])
    pos_mfe = mfe[mfe > 0]
    capture = float((real[mfe > 0] / pos_mfe).clip(-2, 2).mean()) if len(pos_mfe) else 0.0
    regret = float((mfe - real).clip(min=0).mean())       # متوسط ما تُرك على الطاولة
    winners = real[real > 0]; losers = real[real < 0]
    return {"n": len(rows), "net_total": round(float(net.sum()), 2),
            "capture_pct": round(100 * capture, 0),       # كم % من القمة نلتقط
            "avg_regret_pts": round(regret, 2),           # متوسط الندم (نقاط متروكة)
            "avg_mfe": round(float(mfe.mean()), 2), "avg_realized": round(float(real.mean()), 3),
            "avg_mae": round(float(mae.mean()), 2),
            "early_exit": bool(capture < 0.6),            # نُغلق مبكّراً (قبل 60% من القمة)
            "win_rate": round(100 * float((real > 0).mean())),
            "lesson": ("نُغلق مبكّراً — لو أمسكنا أطول لالتقطنا أكثر (لكن MAE يحذّر من الاحتجاز)"
                       if capture < 0.6 else "التقاط جيّد للقمة")}


def main():
    if not (mt5.initialize() or mt5.initialize()):
        _log("mt5 init failed"); return
    RN.mkdir(parents=True, exist_ok=True)
    _log("regret_learner start")
    while True:
        try:
            rep = analyze()
            rep["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            json.dump(rep, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
            if rep.get("n"):
                _log(f"n={rep['n']} capture={rep.get('capture_pct')}% regret={rep.get('avg_regret_pts')} net={rep.get('net_total')}")
        except Exception as e:
            _log(f"err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        mt5.initialize()
        print(json.dumps(analyze(), ensure_ascii=False, indent=1))
    else:
        main()
