"""orb_trader.py — نمط ORB (Opening Range Breakout): أقوى حافة يومية موثّقة على المؤشرات/الذهب.

الفكرة (من EDGE_RESEARCH_PLAN): عند افتتاح الجلسة، سجّل نطاق أول N دقيقة (أعلى/أدنى)، ثم ادخل
مع اختراقه — BUY_STOP فوق القمة / SELL_STOP تحت القاع. OCO (المنفّذ يلغي الآخر)، وقف عند الطرف
المقابل للنطاق، تريل للرابح، إغلاق عند نهاية الجلسة. مرّة واحدة لكل رمز لكل جلسة.

محرّك مستقل (لا يلمس multi_trader) · magic 20260616 · DEMO فقط + فحص طوارئ + لوت أدنى ·
يطيع risk_register · يُسجّل صفقاته للتعلّم. Windowless.  Run:  pythonw orb_trader.py
"""
from __future__ import annotations
from engine_lock import claim
from engine_gov import gov_mult            # 🎛️ مضاعِف حوكمة المايسترو
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
STATE = RN / "orb_state.json"
MAGIC = 20260616
OR_MIN = 15            # نافذة نطاق الافتتاح (دقائق)
HOLD_H = 6            # أقصى مدّة مسكة بعد الافتتاح
POLL_S = 20
# ساعة افتتاح الجلسة لكل رمز (UTC) — حيث ORB له حافة موثّقة
OPENS = {
    "US30m": (13, 30), "US500m": (13, 30), "USTECm": (13, 30),  # NY cash open
    "DE30m": (8, 0), "UK100m": (8, 0), "FRA40m": (8, 0),         # أوروبا
    "JP225m": (0, 0),                                            # طوكيو
    "XAUUSDm": (13, 0),                                          # ذهب — افتتاح نيويورك
}
for p in (str(MT5DIR), str(MT5DIR / "r_native_v2")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, p)


def _is_demo(mt5):
    a = mt5.account_info()
    if not a:
        return False
    if a.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
        return True
    srv = (a.server or "").lower()
    return ("trial" in srv or "demo" in srv) and "real" not in srv


def _emergency():
    d = _load(RN / "risk_register.json", {}) or {}
    return bool(d.get("emergency")) and time.time() - float(d.get("ts", 0)) < 300


def _risk_mult():
    d = _load(RN / "risk_register.json", {}) or {}
    return float(d.get("lot_mult", 1.0)) if time.time() - float(d.get("ts", 0)) < 300 else 1.0


def _opening_range(mt5, sym, oh, om):
    """نطاق أول OR_MIN دقيقة بعد افتتاح اليوم الحالي. يعيد (hi, lo) أو None لو لم يكتمل بعد."""
    now = datetime.now(timezone.utc)
    open_dt = now.replace(hour=oh, minute=om, second=0, microsecond=0)
    if now < open_dt:
        return None, None, "before_open"
    if (now - open_dt).total_seconds() < OR_MIN * 60:
        return None, None, "forming"
    if (now - open_dt).total_seconds() > HOLD_H * 3600:
        return None, None, "session_over"
    r = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, open_dt,
                             open_dt.replace(minute=om) + __import__("datetime").timedelta(minutes=OR_MIN))
    if r is None or len(r) < 3:
        return None, None, "no_data"
    hi = max(float(x["high"]) for x in r)
    lo = min(float(x["low"]) for x in r)
    return hi, lo, "ready"


def main():
    claim("orb_trader")                      # 🔒 قفل نسخة-مفردة (لا تداول مزدوج)
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print(f"[ORB] نمط اختراق نطاق الافتتاح حيّ · magic {MAGIC} · {list(OPENS)}", flush=True)
    st = _load(STATE, {}) or {}
    st.setdefault("done", {})        # f"{sym}:{date}" -> True (مرّة لكل جلسة)
    while True:
        try:
            ti = mt5.terminal_info()
            if not (ti and ti.trade_allowed) or not _is_demo(mt5) or _emergency():
                time.sleep(30); continue
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for sym, (oh, om) in OPENS.items():
                key = f"{sym}:{today}"
                # إدارة المراكز/الأوامر القائمة (OCO + إغلاق نهاية الجلسة)
                poss = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
                ords = [o for o in (mt5.orders_get(symbol=sym) or []) if o.magic == MAGIC]
                if poss and ords:
                    for o in ords:           # OCO: امتلأ جانب → ألغِ المعلّق الآخر
                        mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
                now = datetime.now(timezone.utc)
                open_dt = now.replace(hour=oh, minute=om, second=0, microsecond=0)
                if (now - open_dt).total_seconds() > HOLD_H * 3600:     # نهاية الجلسة → أغلق وألغِ
                    for o in ords:
                        mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
                    for p in poss:
                        t = mt5.symbol_info_tick(sym); ib = p.type == 0
                        mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket,
                                        "symbol": sym, "volume": p.volume,
                                        "type": mt5.ORDER_TYPE_SELL if ib else mt5.ORDER_TYPE_BUY,
                                        "price": t.bid if ib else t.ask, "deviation": 50,
                                        "magic": MAGIC, "comment": "ORB-eod",
                                        "type_filling": mt5.ORDER_FILLING_IOC})
                    continue
                if st["done"].get(key) or poss or ords:
                    continue                 # نُفّذ اليوم أو هناك صفقة قائمة
                hi, lo, status = _opening_range(mt5, sym, oh, om)
                if status != "ready":
                    continue
                info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
                if not info or not tick:
                    continue
                rng = hi - lo
                if rng <= 0:
                    continue
                buf = rng * 0.10
                lot = max(info.volume_min, round(info.volume_min * 2 * _risk_mult() * gov_mult(20260616), 2))
                exp = int(open_dt.timestamp()) + HOLD_H * 3600
                # BUY_STOP فوق القمة (وقف=قاع النطاق) · SELL_STOP تحت القاع (وقف=قمة النطاق)
                placed = 0
                for ot, px, slp, tpp in (
                    (mt5.ORDER_TYPE_BUY_STOP, hi + buf, lo - buf, hi + buf + 1.5 * rng),
                    (mt5.ORDER_TYPE_SELL_STOP, lo - buf, hi + buf, lo - buf - 1.5 * rng)):
                    r = mt5.order_send({"action": mt5.TRADE_ACTION_PENDING, "symbol": sym,
                                        "volume": float(lot), "type": ot, "price": round(px, info.digits),
                                        "sl": round(slp, info.digits), "tp": round(tpp, info.digits),
                                        "deviation": 50, "magic": MAGIC, "comment": "ORB",
                                        "type_time": mt5.ORDER_TIME_SPECIFIED, "expiration": exp,
                                        "type_filling": mt5.ORDER_FILLING_IOC})
                    if getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE:
                        placed += 1
                if placed:
                    st["done"][key] = True
                    print(f"[ORB] 🎯 {sym} نطاق افتتاح [{lo:.2f}-{hi:.2f}] → سلّحت {placed} اختراق", flush=True)
            # نظّف مفاتيح الأيام القديمة
            st["done"] = {k: v for k, v in st["done"].items() if today in k}
            st["ts"] = time.time()
            _save(STATE, st)
        except Exception as e:
            print(f"[ORB] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
