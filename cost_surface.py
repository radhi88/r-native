# -*- coding: utf-8 -*-
"""cost_surface.py — خريطة التكلفة التجريبية (سبريد لكل رمز × ساعة). الرافعة #1 المُثبتة.

العائق الوحيد المُثبت في المشروع = التكلفة > الربح الخام (sr_zone: ربح 0.070R < تكلفة 0.089R).
المنفّذون يستعملون رقم سبريد ثابتاً من الإعداد. هذه الأداة تُجمّع السبريد الحيّ (الذي نبثّه أصلاً)
في توزيع تجريبيّ لكل رمز: التوزيع العامّ (هل اللحظة غالية؟) + متوسّط لكل ساعة (أيّ الساعات أرخص).

**تجميع صرف — لا تنبّؤ.** يُستهلَك في بوّابة الربح-vs-التكلفة (الخطوة التالية): امنع صفقةً
سبريدها في أسوأ عُشر، أو لا يتجاوز ربحُها المتوقّع كلفتَها. windowless, read-mostly.

Writes: data/r_native/cost_surface.json
API (يستوردها المنفّذون): pctile_now(sym, spread_atr) · hour_cost(sym, hour) · is_expensive(sym, spread_atr)
Run: pythonw cost_surface.py
"""
from __future__ import annotations
import json, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
OUT = RN / "cost_surface.json"
LOG = RN / "cost_surface.log"
POLL_S = 60.0                       # عيّنة سبريد كل دقيقة
WRITE_EVERY = 120.0                 # اكتب الملفّ كل دقيقتين
RECENT_CAP = 300                    # آخر N عيّنة للتوزيع العامّ لكل رمز (للمئويّات)
CORE = ["BTCUSDm", "ETHUSDm", "XAUUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm",
        "USDCADm", "USDCHFm", "GBPJPYm", "US30m", "USTECm", "DE30m", "XAGUSDm"]

_SURF: dict = {}                    # {sym: {"recent":[spread_atr...], "by_hour":{h:{"n","sum_atr","sum_pts"}}}}
_loaded = False


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _load():
    global _SURF, _loaded
    if _loaded:
        return
    try:
        _SURF = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        _SURF = {}
    _loaded = True


def _atr(sym, n=14):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n + 1)
    if r is None or len(r) < n:
        return 0.0
    h, l, c = r["high"], r["low"], r["close"]
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(tr.mean()) if len(tr) else 0.0


def _universe():
    syms = set(CORE)
    try:
        syms |= {p.symbol for p in (mt5.positions_get() or [])}     # أيّ رمز نتداوله الآن
    except Exception:
        pass
    return sorted(syms)


# ── API للمنفّذين ──────────────────────────────────────────────────────────────
def pctile_now(sym, spread_atr):
    """أين يقع السبريد الحاليّ (بوحدة ATR) ضمن توزيع الرمز الأخير؟ 0..1 (1=الأغلى). None إن لا بيانات."""
    _load()
    rec = (_SURF.get(sym) or {}).get("recent") or []
    if len(rec) < 20 or spread_atr is None:
        return None
    arr = np.asarray(rec, dtype=float)
    return float((arr <= spread_atr).mean())


def hour_cost(sym, hour=None):
    """متوسّط سبريد (بوحدة ATR) لساعة UTC المعطاة (أو الحاليّة). None إن لا بيانات."""
    _load()
    if hour is None:
        hour = datetime.now(timezone.utc).hour
    bh = ((_SURF.get(sym) or {}).get("by_hour") or {}).get(str(hour))
    if not bh or bh.get("n", 0) < 5:
        return None
    return bh["sum_atr"] / bh["n"]


def is_expensive(sym, spread_atr, thresh=0.9):
    """هل السبريد الحاليّ في أسوأ (1-thresh) من توزيع الرمز؟ fail-open (False) إن لا بيانات."""
    p = pctile_now(sym, spread_atr)
    return bool(p is not None and p >= thresh)


def cheap_hours(sym, k=6):
    """أرخص k ساعة UTC للرمز (بأقلّ متوسّط سبريد). للعرض/الجدولة."""
    _load()
    bh = (_SURF.get(sym) or {}).get("by_hour") or {}
    rows = [(int(h), v["sum_atr"] / v["n"]) for h, v in bh.items() if v.get("n", 0) >= 5]
    return [h for h, _ in sorted(rows, key=lambda x: x[1])[:k]]


# ── حلقة التجميع ───────────────────────────────────────────────────────────────
def _sample():
    hour = str(datetime.now(timezone.utc).hour)
    for sym in _universe():
        try:
            tk = mt5.symbol_info_tick(sym); inf = mt5.symbol_info(sym)
            if not tk or not inf:
                continue
            sp = tk.ask - tk.bid
            if sp <= 0:
                continue
            atr1 = _atr(sym)
            sp_atr = (sp / atr1) if atr1 > 0 else None
            sp_pts = sp / (inf.point or 1e-9)
            s = _SURF.setdefault(sym, {"recent": [], "by_hour": {}})
            if sp_atr is not None:
                s["recent"].append(round(sp_atr, 4))
                if len(s["recent"]) > RECENT_CAP:
                    s["recent"] = s["recent"][-RECENT_CAP:]
            bh = s["by_hour"].setdefault(hour, {"n": 0, "sum_atr": 0.0, "sum_pts": 0.0})
            bh["n"] += 1
            bh["sum_atr"] += (sp_atr or 0.0)
            bh["sum_pts"] += sp_pts
        except Exception:
            pass


def _write():
    try:
        RN.mkdir(parents=True, exist_ok=True)
        tmp = OUT.with_suffix(".json.tmp")
        json.dump({**_SURF, "_updated": time.strftime("%Y-%m-%dT%H:%M:%S")},
                  open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        import os
        os.replace(tmp, OUT)
    except Exception as e:
        _log(f"write err: {e}")


def main():
    mt5.initialize()
    _load()
    _log(f"cost_surface start — universe {len(_universe())} رمز")
    last_write = 0.0
    while True:
        try:
            _sample()
            if time.time() - last_write >= WRITE_EVERY:
                _write(); last_write = time.time()
        except Exception as e:
            _log(f"loop err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        mt5.initialize(); _load(); _sample(); _write()
        for s in ("BTCUSDm", "XAUUSDm", "EURUSDm"):
            print(f"{s}: ساعة-تكلفة(ATR)={hour_cost(s)} رخيصة={cheap_hours(s)} عيّنات={len((_SURF.get(s) or {}).get('recent',[]))}")
    else:
        main()
