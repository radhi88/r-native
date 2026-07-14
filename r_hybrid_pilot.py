"""
r_hybrid_pilot.py — تجربة حيّة محكومة للنموذجين الناجيين جزئيّاً من مختبر التهجين.

⚠️ هذا ليس «حافّة مثبتة» — المختبر (r_hybrid_lab, 60 يوماً walk-forward) رفض النماذج
الخمسة كلّها عن بوّابة t≥2. لكن اثنين استحقّا عيّنة حيّة أكبر بدل الدفن:
  B (ASIA_SELL_STRICT): أعلى جودة/صفقة (PF 1.65, 0.52R متوسّطاً, WR 69%) لكن n=13 فقط.
  E (HYBRID_ASIA_LEVEL): الوحيد الموجب في نصفَي الفترة (+$7.9/+$4.4) لكن t=0.23.

فالمهمّة: جمع العيّنة بأصغر رهانٍ ممكن، والصندوق الأسود (r_trade_journal) هو القاضي.

الضوابط الصلبة (لا تُرفع بلا رقمٍ يثبت):
  • ديمو فقط (كشف Trial/Demo من اسم الخادم) + kill_switch.txt يوقفه.
  • لوت ثابت 0.01 — لا تكيّف حجم قبل إثبات الحافّة.
  • مركز واحد، تبريد 25د، سقف خسارة يوميّ $5، فيتو سبريد ≤$0.30.
  • ساعات النموذجين فقط (23-00 UTC) — خاملٌ بقيّة اليوم.

magic 20260713 · XAUUSDm · M5 · تشغيل: pythonw r_hybrid_pilot.py
إيقاف: enabled=false في data/r_native/r_hybrid_pilot_config.json (يسري خلال ثوانٍ).
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import MetaTrader5 as mt5

MAGIC = 20260713
SYM = "XAUUSDm"
LOT = 0.01
ROOT = Path(__file__).resolve().parent
CFG_F = ROOT / "data" / "r_native" / "r_hybrid_pilot_config.json"
STATUS_F = ROOT / "data" / "r_native" / "r_hybrid_pilot_status.json"
ENTRIES_F = ROOT / "data" / "r_native" / "gold_sentinel_entries.jsonl"  # يقرأه الصندوق الأسود
KILL_F = ROOT / "data" / "r_native" / "kill_switch.txt"


def _cfg():
    d = {"enabled": True, "execute": True, "models": ["B", "E"],
         "models_rehab": [], "monster_models": [], "window_hours": list(range(24)),
         "daily_loss_usd": 5.0, "cooldown_min": 0, "rehab_cooldown_min": 60,
         "max_positions": 1,
         "spread_abs_max": 0.30, "stop_atr_mult": 0.65, "target_r": 1.2,
         "trail_arm_r": 0.8, "trail_atr_mult": 0.6}
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        try:
            CFG_F.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
    return d


def _is_demo():
    try:
        a = mt5.account_info()
        return bool(a and ("Trial" in a.server or "Demo" in a.server or "demo" in a.server))
    except Exception:
        return False


def _ema(x, n):
    x = np.asarray(x, float); k = 2.0 / (n + 1.0)
    e = np.empty(len(x)); e[0] = x[0]
    for i in range(1, len(x)):
        e[i] = x[i] * k + e[i - 1] * (1 - k)
    return e


def _atr(r, n=14):
    h, l, c = r["high"], r["low"], r["close"]
    trs = [max(float(h[i] - l[i]), abs(float(h[i] - c[i - 1])), abs(float(l[i] - c[i - 1])))
           for i in range(1, len(r))]
    return float(np.mean(trs[-n:])) if len(trs) >= n else 0.0


def _stoch(r, kp=14, slow=3):
    h, l, c = r["high"], r["low"], r["close"]; n = len(c)
    if n < kp:
        return 50.0
    raw = np.full(n, 50.0)
    for i in range(kp - 1, n):
        hh = h[i - kp + 1:i + 1].max(); ll = l[i - kp + 1:i + 1].min()
        raw[i] = 100.0 * (c[i] - ll) / ((hh - ll) or 1e-9)
    return float(_ema(raw, slow)[-1])


def _levels(price, r5):
    """شبكة $5 المستديرة + قمّة/قاع اليوم السابق (نفس مجموعة المختبر)."""
    out = [round(price / 5.0) * 5.0 + k * 5.0 for k in (-2, -1, 0, 1, 2)]
    try:
        d1 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_D1, 1, 1)
        if d1 is not None and len(d1):
            out += [float(d1[0]["high"]), float(d1[0]["low"])]
    except Exception:
        pass
    return out


def _h1_up():
    r = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H1, 0, 60)
    if r is None or len(r) < 51:
        return None
    c = r["close"][:-1]                      # آخر شمعة مكتملة فقط (لا تلصّص)
    return float(c[-1]) > float(_ema(c, 50)[-1])


def _daily_pnl():
    day0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return sum(d.profit + d.commission + d.swap
               for d in (mt5.history_deals_get(day0, datetime.now()) or [])
               if d.magic == MAGIC and d.entry == 1)


def _signal(cfg, r5):
    """يقيّم النموذجين على آخر شمعة M5 *مكتملة*. يرجع (dir, model, ctx) أو (0,None,{})."""
    b = r5[:-1]                              # الشمعة الجارية مستبعدة
    if len(b) < 25:
        return 0, None, {}
    o, h, l, c = (float(b[-1]["open"]), float(b[-1]["high"]),
                  float(b[-1]["low"]), float(b[-1]["close"]))
    hr = datetime.fromtimestamp(int(b[-1]["time"]), tz=timezone.utc).hour
    # 2026-07-14: نافذة موسّعة 23-01 — الساعة 01 UTC هي ساعة 99780 الرابحة المقيسة
    # (+$58 أفضل ساعاته)، توسيعٌ بدليل بصمة لا بالتمنّي. قابلة للضبط من config.
    if hr not in tuple(cfg.get("window_hours", (23, 0, 1))):
        return 0, None, {}
    e20 = float(_ema(b["close"], 20)[-1])
    atr = _atr(b)
    st = _stoch(b)
    h1u = _h1_up()
    bearish = c < o
    rng = (h - l) or 1e-9
    uw = h - max(o, c)
    # 🏥 عقيدة المستشفى: نماذج العناية تواصل التداول (بتبريدها الخاص في _try_enter)
    models = list(cfg.get("models", ["B", "E"])) + list(cfg.get("models_rehab", []))
    # B: بيع الارتداد في اتّجاه H1 الهابط
    if "B" in models and bearish and c < e20 and h1u is False and st > 60:
        return -1, "B", {"stoch": round(st, 1), "atr": round(atr, 2), "h1_up": h1u}
    # E: رفضٌ بيعيّ عند مستوى (اختراق ثم إغلاق دونه بذيلٍ ≥30%)
    if "E" in models and uw >= 0.3 * rng:
        for L in _levels(c, b):
            if h >= L > c:
                return -1, "E", {"level": L, "atr": round(atr, 2), "h1_up": h1u}
    return 0, None, {}


def _manage(cfg):
    """ترييل النموذج E: تعادل+0.2R بعد +0.8R، ثمّ ترييل 0.6×ATR بعد +1.2R."""
    for p in (mt5.positions_get(symbol=SYM) or []):
        if p.magic != MAGIC:
            continue
        ti = mt5.symbol_info_tick(SYM)
        if not ti:
            continue
        cur = ti.bid if p.type == 0 else ti.ask
        r5 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 0, 20)
        atr = _atr(r5) if r5 is not None else 0.0
        stop0 = abs(p.price_open - p.sl) if p.sl else 0.0
        if stop0 <= 0 or atr <= 0:
            continue
        fav = (cur - p.price_open) if p.type == 0 else (p.price_open - cur)
        new_sl = None
        if fav >= cfg.get("trail_arm_r", 0.8) * stop0:
            be = p.price_open + (0.2 * stop0 if p.type == 0 else -0.2 * stop0)
            if (p.type == 0 and (not p.sl or p.sl < be)) or (p.type == 1 and (not p.sl or p.sl > be)):
                new_sl = be
        if fav >= 1.2 * stop0:
            tr = cur - cfg.get("trail_atr_mult", 0.6) * atr if p.type == 0 \
                else cur + cfg.get("trail_atr_mult", 0.6) * atr
            if (p.type == 0 and tr > (new_sl or p.sl or 0)) or \
               (p.type == 1 and tr < (new_sl or p.sl or 1e12)):
                new_sl = tr
        if new_sl:
            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": SYM,
                            "position": p.ticket, "sl": round(float(new_sl), 3),
                            "tp": p.tp, "magic": MAGIC})


_last = {"bar": 0, "exec": 0.0, "exec_by_model": {}}


def _try_enter(cfg):
    if not (cfg.get("enabled") and cfg.get("execute")):
        return
    if KILL_F.exists() or not _is_demo():
        return
    if time.time() - _last["exec"] < cfg.get("cooldown_min", 25) * 60:
        return
    if len([p for p in (mt5.positions_get() or []) if p.magic == MAGIC]) >= cfg.get("max_positions", 1):
        return
    if _daily_pnl() <= -abs(cfg.get("daily_loss_usd", 5.0)):
        return
    r5 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 0, 60)
    if r5 is None or len(r5) < 30:
        return
    bar_t = int(r5[-1]["time"])
    if bar_t == _last["bar"]:                 # قرارٌ واحد لكل شمعة جديدة
        return
    _last["bar"] = bar_t
    sig, model, ctx = _signal(cfg, r5)
    if sig == 0:
        return
    # 🏥 نموذج في العناية: يتداول لكن بربع الوتيرة (تبريد خاص أطول)
    if model in cfg.get("models_rehab", []):
        cd_m = cfg.get("rehab_cooldown_min", 240) * 60
        if time.time() - _last["exec_by_model"].get(model, 0.0) < cd_m:
            return
    ti = mt5.symbol_info_tick(SYM)
    if not ti:
        return
    spr = float(ti.ask - ti.bid)
    if spr > cfg.get("spread_abs_max", 0.30):
        print(f"🛑 فيتو سبريد {spr:.3f}")
        return
    atr = ctx.get("atr") or _atr(r5[:-1])
    stop = cfg.get("stop_atr_mult", 0.65) * atr        # = 0.5×(1.3×ATR) كما في المختبر
    price = ti.ask if sig > 0 else ti.bid
    sl = price - stop if sig > 0 else price + stop
    tp = price + cfg.get("target_r", 1.2) * stop if sig > 0 else price - cfg.get("target_r", 1.2) * stop
    # 👹 وحش الهجين: لوت 0.02 للنموذج المُثبَت وحشاً (المُرقّي يمنح اللقب بالأرقام)
    lot_eff = 0.02 if model in cfg.get("monster_models", []) else LOT
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYM, "volume": lot_eff,
           "type": mt5.ORDER_TYPE_BUY if sig > 0 else mt5.ORDER_TYPE_SELL,
           "price": float(price), "sl": round(float(sl), 3), "tp": round(float(tp), 3),
           "deviation": 30, "magic": MAGIC, "comment": f"hybrid_{model}",
           "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
        _last["exec"] = time.time()
        _last["exec_by_model"][model] = time.time()
        print(f"⚡ hybrid_{model}: {'شراء' if sig>0 else 'بيع'} {lot_eff} @ {price:.2f} وقف {sl:.2f} هدف {tp:.2f}")
        try:                                    # 📓 سياق الدخول → الصندوق الأسود
            rec = {"ts": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "ticket": int(getattr(r, "order", 0) or 0), "engine": "r_hybrid_pilot",
                   "model": model, "side": "BUY" if sig > 0 else "SELL",
                   "entry": float(price), "sl": float(sl), "tp": float(tp),
                   "lot": lot_eff, "spread": round(spr, 3), **{k: v for k, v in ctx.items()}}
            with open(ENTRIES_F, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
    else:
        print(f"⏭️ لم تُنفّذ: {getattr(r,'retcode','?')}")


def main():
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print(f"🟢 hybrid pilot بدأ — B+E · magic {MAGIC} · lot {LOT} ثابت · نافذة 23-00 UTC فقط")
    while True:
        try:
            cfg = _cfg()
            if cfg.get("enabled", True):
                _manage(cfg)
                _try_enter(cfg)
            try:
                json.dump({"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                           "magic": MAGIC, "models": cfg.get("models"),
                           "enabled": cfg.get("enabled"), "window": "23-00 UTC"},
                          open(STATUS_F, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception:
                pass
        except Exception as e:
            print(f"cycle err: {type(e).__name__}: {e}")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
