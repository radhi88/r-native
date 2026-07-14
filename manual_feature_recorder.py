"""manual_feature_recorder.py — يلتقط بصمة السوق الكاملة لحظة كل صفقة يدوية (magic-0) ويربطها
بالنتيجة، لبناء مجموعة بيانات مُعلّمة (features → outcome) يتعلّم منها الذكاء أفضل من المستخدم.

يلتقط (سببياً، فقط بيانات ≤ وقت الدخول): السبريد (حيّ)، السعر، EMA8/21 + الاتجاه + البُعد عنه،
RSI14، Stochastic K/D، ATR14 + نظام التذبذب (مئوي)، شكل آخر 5 شموع (جسم/ذيول/لون/مدى)،
اتجاه الفريم الأعلى (H1)، الجلسة/الساعة/اليوم. عند الإغلاق يُعلّم السجل بالنتيجة (صافي/فوز/مدة).

وضعان: backfill (يبني من التاريخ فوراً) + live (watchdog، يسجّل كل صفقة جديدة لحظياً).
Run: pythonw manual_feature_recorder.py        (live, watchdog-managed)
     python  manual_feature_recorder.py backfill 180
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import MetaTrader5 as mt5

RN = Path(r"C:\Users\Radhi\MT5\data\r_native")
DATASET = RN / "manual_trade_features.jsonl"
OPEN_MAP = RN / "manual_feature_open.json"     # ticket -> features (awaiting close to label)
CYCLE_S = 30
_TF5 = None  # set after init


def _ema(c, n):
    k = 2.0 / (n + 1); e = c[0]
    for x in c[1:]:
        e = x * k + e * (1 - k)
    return e


def _rsi(c, n=14):
    if len(c) < n + 1: return 50.0
    d = np.diff(c[-(n + 1):]); up = d[d > 0].sum(); dn = -d[d < 0].sum()
    if dn == 0: return 100.0
    rs = (up / n) / (dn / n)
    return 100 - 100 / (1 + rs)


def _atr(h, l, c, n=14):
    if len(c) < n + 1: return float(np.mean(h - l)) if len(h) else 0.0
    pc = c[:-1]; tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
    return float(np.mean(tr[-n:]))


def _stoch(h, l, c, k=14):
    if len(c) < k: return 50.0
    hh = h[-k:].max(); ll = l[-k:].min()
    return float((c[-1] - ll) / (hh - ll + 1e-9) * 100)


def snapshot(symbol, at_unix, live_spread=None):
    """ميزات سببية عند at_unix من شموع M5 (+ اتجاه H1). يرجع dict أو None."""
    r5 = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_M5, int(at_unix), 320)
    if r5 is None or len(r5) < 60:
        return None
    r5 = [x for x in r5 if x["time"] <= at_unix]
    if len(r5) < 60:
        return None
    o = np.array([x["open"] for x in r5], float); h = np.array([x["high"] for x in r5], float)
    l = np.array([x["low"] for x in r5], float); c = np.array([x["close"] for x in r5], float)
    px = c[-1]; atr = _atr(h, l, c); ema8 = _ema(c[-60:], 8); ema21 = _ema(c[-60:], 21)
    # نظام تذبذب: مئوي ATR الحالي مقابل آخر 200 شمعة
    trs = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr_pctile = float((trs[-1] >= trs[-200:]).mean() * 100) if len(trs) >= 50 else 50.0
    # آخر 5 شموع: جسم/ذيلين/لون منسوبة لـATR
    cn = []
    for i in range(-5, 0):
        rng = h[i] - l[i] + 1e-9; body = c[i] - o[i]
        up_wick = h[i] - max(c[i], o[i]); dn_wick = min(c[i], o[i]) - l[i]
        cn.append({"body_atr": round(body / (atr + 1e-9), 2), "uw_atr": round(up_wick / (atr + 1e-9), 2),
                   "dw_atr": round(dn_wick / (atr + 1e-9), 2), "bull": int(c[i] >= o[i])})
    # اتجاه H1
    rh = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_H1, int(at_unix), 60)
    htf = 0
    if rh is not None and len(rh) >= 25:
        ch = np.array([x["close"] for x in rh if x["time"] <= at_unix], float)
        if len(ch) >= 25:
            htf = 1 if _ema(ch, 8) > _ema(ch, 21) else -1
    dt = datetime.fromtimestamp(at_unix, timezone.utc)
    sp = None
    if live_spread is None:
        si = mt5.symbol_info(symbol); sp = int(si.spread) if si else None
    else:
        sp = live_spread
    return {
        "price": round(px, 5), "spread": sp, "atr": round(atr, 5), "atr_pctile": round(atr_pctile, 1),
        "ema8": round(ema8, 5), "ema21": round(ema21, 5),
        "trend": (1 if ema8 > ema21 else -1), "dist_ema_atr": round((px - ema8) / (atr + 1e-9), 2),
        "rsi": round(_rsi(c), 1), "stoch": round(_stoch(h, l, c), 1), "htf_trend": htf,
        "hour": dt.hour, "dow": dt.weekday(),
        "session": ("ASIAN" if (dt.hour >= 22 or dt.hour < 7) else "LONDON" if dt.hour < 12 else "NYOVL" if dt.hour < 16 else "NYPM"),
        "candles": cn,
    }


def _append(rec):
    with open(DATASET, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def backfill(days=180):
    if not (mt5.initialize() or mt5.initialize()):
        print("init failed"); return
    now = time.time()
    deals = mt5.history_deals_get(int(now - days * 86400), int(now)) or []
    pos = {}
    for d in deals:
        if d.magic != 0: continue
        p = pos.setdefault(d.position_id, {"in": None, "out": None, "net": 0.0})
        if d.entry == 0: p["in"] = d
        elif d.entry == 1: p["out"] = d
        p["net"] += d.profit + d.commission + d.swap
    done = 0
    seen = set()
    if DATASET.exists():
        for ln in DATASET.read_text(encoding="utf-8").splitlines():
            try: seen.add(json.loads(ln).get("ticket"))
            except Exception: pass
    for pid, p in pos.items():
        din = p["in"];
        if not din or din.ticket in seen: continue
        feat = snapshot(din.symbol, din.time)
        if not feat: continue
        hold = ((p["out"].time - din.time) / 60.0) if p["out"] else None
        _append({"ticket": din.ticket, "src": "backfill", "time": din.time,
                 "iso": datetime.fromtimestamp(din.time, timezone.utc).isoformat(),
                 "symbol": din.symbol, "dir": (1 if din.type == 0 else -1), "lot": din.volume,
                 "features": feat, "net": round(p["net"], 2), "win": int(p["net"] > 0),
                 "hold_min": round(hold, 1) if hold is not None else None})
        done += 1
    mt5.shutdown()
    print(f"backfilled {done} labeled manual trades -> {DATASET}")


def live():
    # windowless singleton: قفل صريح + توجيه المخرجات (يمنع نسختين تسجّلان نفس الصفقة)
    try:
        import engine_lock; engine_lock.claim("manual_feature_recorder")
    except Exception:
        pass
    print("[FEAT] manual_feature_recorder live", flush=True)
    openmap = {}
    if OPEN_MAP.exists():
        try: openmap = json.loads(OPEN_MAP.read_text(encoding="utf-8"))
        except Exception: openmap = {}
    seeded = False
    labeled = set()
    if DATASET.exists():
        for ln in DATASET.read_text(encoding="utf-8").splitlines():
            try: labeled.add(json.loads(ln).get("ticket"))
            except Exception: pass
    while True:
        try:
            if not (mt5.initialize() or mt5.initialize()):
                time.sleep(CYCLE_S); continue
            now = time.time()
            pos = [p for p in (mt5.positions_get() or []) if p.magic == 0]
            cur = {str(p.ticket): p for p in pos}
            if not seeded:
                # on first run, snapshot any already-open manual trades we haven't captured
                seeded = True
            for tk, p in cur.items():
                if tk not in openmap and int(tk) not in labeled:
                    feat = snapshot(p.symbol, p.time)
                    if feat:
                        openmap[tk] = {"ticket": p.ticket, "time": p.time, "symbol": p.symbol,
                                       "dir": (1 if p.type == 0 else -1), "lot": p.volume, "features": feat}
                        print(f"[FEAT] captured open {p.symbol} #{tk}", flush=True)
            # any tracked ticket no longer open → it closed → label from history
            closed = [tk for tk in list(openmap) if tk not in cur]
            if closed:
                deals = mt5.history_deals_get(int(now - 7 * 86400), int(now)) or []
                netmap = {}
                holdmap = {}
                for d in deals:
                    if d.magic == 0 and d.entry == 1:
                        netmap[str(d.position_id)] = netmap.get(str(d.position_id), 0.0) + d.profit + d.commission + d.swap
                        holdmap[str(d.position_id)] = d.time
                for tk in closed:
                    rec = openmap.pop(tk)
                    net = netmap.get(tk)
                    if net is None:
                        openmap[tk] = rec; continue       # close not in history yet, retry next cycle
                    hold = (holdmap.get(tk, rec["time"]) - rec["time"]) / 60.0
                    rec.update({"src": "live", "net": round(net, 2), "win": int(net > 0), "hold_min": round(hold, 1),
                                "iso": datetime.fromtimestamp(rec["time"], timezone.utc).isoformat()})
                    _append(rec); labeled.add(int(tk))
                    print(f"[FEAT] labeled close #{tk} net={net:+.2f}", flush=True)
            mt5.shutdown()
            OPEN_MAP.parent.mkdir(parents=True, exist_ok=True)
            OPEN_MAP.write_text(json.dumps(openmap, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"[FEAT] err {e}", flush=True)
        time.sleep(CYCLE_S)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        backfill(int(sys.argv[2]) if len(sys.argv) > 2 else 180)
    else:
        live()
