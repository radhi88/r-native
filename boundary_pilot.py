"""
boundary_pilot.py — منفّذ هجوم اللحظات ⚔️ (magic 20260714).

أمر المستخدم (2026-07-14): «نهجم هجوماً شرساً على كل لحظات الأسواق» + «اهجم مع
السبريد العالي». التنفيذ بطريقة الوحوش لا الانتحار:

  • اللحظة: افتتاح H1/H4/D1 + لحظة صدور خبر High (البوّابتان الأعلى انفجاراً).
  • الدخول: يركب الانفجار مع اتجاهه — السعر يبتعد ≥0.15×ATR عن سعر الافتتاح
    خلال أول 3 دقائق ⇒ أمر سوق فوريّ بنفس الاتجاه (استمرار لا انعكاس —
    الذاكرة: الخبر يستمرّ 58-71%، والانعكاس المُقاس بلا حافّة).
  • السبريد: سقف **نسبيّ** spread ≤ 0.15×ATR(M5) — وقت الانفجار يتّسع الـATR
    فيُقبل السبريد العالي تلقائيّاً؛ وقت الركود يُرفض نفس السبريد. عالٍ مسموح،
    قاتلٌ ممنوع. السبريد يُسجَّل في كل صفقة ليحاسبه الصندوق الأسود.
  • العيّنة أولاً: لوت 0.01 ثابت، مركز واحد، سقف يوميّ $5، تبريد 20د.
    المُرقّي يحكم عند n≥30 — ومنها طريق الوحوش (لوت عالٍ) مفتوح بالأرقام.

ديمو فقط · kill_switch يوقفه · إيقاف: enabled=false في boundary_pilot_config.json
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import MetaTrader5 as mt5

MAGIC = 20260714
# 2026-07-14 (أمر المستخدم «وين باقي العملات؟ أكثر من الصفقات»): التوسّع بالعرض —
# 12 رمزاً × 5 لحظات، بجودة الصفقة نفسها (انفجار مؤكَّد + سبريد نسبيّ). الحجم من
# الاتّساع لا من الرشّ على رمز واحد (نمط النزيف المُثبت).
SYMBOLS = ["XAUUSDm", "BTCUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm",
           "USDCADm", "USDCHFm", "EURJPYm", "GBPJPYm", "ETHUSDm", "US30m"]
LOT = 0.01
ROOT = Path(__file__).resolve().parent
RN = ROOT / "data" / "r_native"
CFG_F = RN / "boundary_pilot_config.json"
STATUS_F = RN / "boundary_pilot_status.json"
ENTRIES_F = RN / "gold_sentinel_entries.jsonl"      # يقرأه الصندوق الأسود
KILL_F = RN / "kill_switch.txt"
NEWS_F = ROOT / "friday_v3" / "data" / "news_calendar.json"

BOUNDARIES = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
CONFIRM_S = 180            # نافذة تأكيد الانفجار بعد اللحظة
BURST_ATR = 0.15           # الابتعاد المطلوب عن سعر الافتتاح ليُعدّ انفجاراً


def _cfg():
    d = {"enabled": True, "execute": True, "daily_loss_usd": 10.0,
         "cooldown_min": 0, "max_positions": 3, "max_trades_day": 100,
         "spread_atr_max": 0.15, "stop_atr": 0.6, "target_atr": 1.2,
         "trail_arm_atr": 1.0, "trail_atr": 0.5}
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
        return bool(a and ("Trial" in a.server or "Demo" in a.server))
    except Exception:
        return False


def _atr_m5(sym, n=14):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, n + 6)
    if r is None or len(r) < n + 1:
        return 0.0
    h, l, c = r["high"], r["low"], r["close"]
    trs = [max(float(h[i] - l[i]), abs(float(h[i] - c[i - 1])), abs(float(l[i] - c[i - 1])))
           for i in range(1, len(r))]
    return float(np.mean(trs[-n:]))


def _news_fire():
    """أخبار High صدرت خلال آخر 3 دقائق (لحظة الانفجار الخبريّ)."""
    try:
        events = json.loads(NEWS_F.read_text(encoding="utf-8"))
        if isinstance(events, dict):
            events = events.get("events", [])
    except Exception:
        return None
    now = datetime.now(timezone.utc)
    for ev in events:
        if str(ev.get("impact", "")).lower() not in ("high", "3"):
            continue
        for k in ("time_utc", "datetime", "date", "time"):
            v = ev.get(k)
            if not v:
                continue
            try:
                t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            dt = (now - t).total_seconds()
            if 0 <= dt <= 180:
                return str(ev.get("title", ev.get("event", "خبر")))[:50]
    return None


def _daily(sym=None):
    day0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    _all = mt5.history_deals_get(day0, datetime.now()) or []
    # 🩺 2026-07-15: عملية رصيد اليوم (type 2/3 تصفير/إيداع) = خطُّ أساس جديد —
    # تصفيةُ التصفير لا تُحسب خسارةَ يومٍ توقف الدخول.
    _rst = max((float(d.time) for d in _all if getattr(d, "type", -1) in (2, 3)), default=0.0)
    deals = [d for d in _all if d.magic == MAGIC and float(getattr(d, "time", 0)) >= _rst]
    net = sum(d.profit + d.commission + d.swap for d in deals if d.entry == 1)
    n_entries = sum(1 for d in deals if d.entry == 0)
    return net, n_entries


# ── ربط المخّ (أمر المستخدم «وين المخ الموحّد والخريطة والتعلّم؟») ──
MAP_F = RN / "market_map.json"          # خريطة الماسح الحيّة (ترند كل فريم لكل رمز)
BKNOW_F = RN / "boundary_knowledge.json"  # معرفة صيّاد اللحظات (نمط→نتيجة مُقاسة)


def _brain_context(sym, direction):
    """يستشير المخّ قبل الضربة: خريطة الترند + معرفة اللحظات المُقاسة.
    يرجع (allow, ctx): يمنع فقط عند دليلٍ مُقاس ضدّه (SIGNIFICANT سالب)؛
    أثناء جمع العيّنة (COLLECTING) يسمح ويسجّل — التعلّم يشتدّ قبضةً مع النضج."""
    ctx = {}
    try:
        m = json.loads(MAP_F.read_text(encoding="utf-8")).get("symbols", {}).get(sym, {})
        ctx["map_m15_trend"] = m.get("M15", {}).get("trend")
        ctx["map_h1_trend"] = m.get("H1", {}).get("trend")
        ctx["map_h4_trend"] = m.get("H4", {}).get("trend")
        want = "up" if direction > 0 else "down"
        ctx["trend_agree"] = sum(1 for tf in ("M15", "H1", "H4")
                                 if ctx.get(f"map_{tf.lower()}_trend") == want)
    except Exception:
        pass
    try:
        mom = "up" if direction > 0 else "down"
        k = json.loads(BKNOW_F.read_text(encoding="utf-8"))
        ctx["know_keys"] = {}
        for b in ("M15", "M30", "H1", "H4", "D1"):
            v = k.get(f"{b}|{sym}|{mom}")
            if isinstance(v, dict):
                ctx["know_keys"][b] = {"n": v.get("n"), "t": v.get("t_stat"),
                                       "with_mom": v.get("mean_with_mom_atr"),
                                       "trust": v.get("trust")}
                # 🧠 فيتو المعرفة المُقاسة: اللحظة نفسها أثبتت أنّ اتّباع الزخم فيها خاسر
                if v.get("trust") == "SIGNIFICANT" and (v.get("mean_with_mom_atr") or 0) < 0:
                    return False, {**ctx, "brain_veto": f"{b}|{sym}|{mom} مُثبت سالب"}
    except Exception:
        pass
    return True, ctx


# ── حالة اللحظات النشطة: (boundary, sym) -> سعر لحظة الافتتاح ─────
_armed: dict = {}
_last_exec: dict = {}          # تبريد لكل رمز على حدة — 12 رمزاً يهاجمون باستقلال


def _arm_moments():
    """عند كل حدّ/خبر: سلّح نافذة تأكيد 3 دقائق بسعر اللحظة."""
    now = time.time()
    fired = []
    for name, secs in BOUNDARIES.items():
        if now % secs < 25:                          # بداية الفترة (حلقة 10ث)
            fired.append((name, int(now // secs)))
    news = _news_fire()
    if news:
        fired.append((f"NEWS:{news}", int(now // 300)))
    for tag, period in fired:
        for sym in SYMBOLS:
            key = (tag, sym, period)
            if key in {k[:3] for k in _armed}:
                continue
            ti = mt5.symbol_info_tick(sym)
            if ti:
                _armed[(tag, sym, period)] = {
                    "t0": now, "p0": float((ti.bid + ti.ask) / 2),
                    "atr": _atr_m5(sym)}


def _try_attack(cfg):
    now = time.time()
    for key in list(_armed):
        tag, sym, period = key
        st = _armed[key]
        if now - st["t0"] > CONFIRM_S:               # انتهت نافذة التأكيد بلا انفجار
            del _armed[key]
            continue
        atr = st["atr"]
        if atr <= 0:
            del _armed[key]
            continue
        ti = mt5.symbol_info_tick(sym)
        if not ti:
            continue
        mid = float((ti.bid + ti.ask) / 2)
        move = mid - st["p0"]
        if abs(move) < BURST_ATR * atr:              # لا انفجار بعد
            continue
        # 💥 انفجار مؤكَّد — بوّابات التنفيذ:
        del _armed[key]
        if not (cfg.get("enabled") and cfg.get("execute")):
            continue
        if KILL_F.exists() or not _is_demo():
            continue
        if now - _last_exec.get(sym, 0.0) < cfg.get("cooldown_min", 0) * 60:
            continue
        poss = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
        if len(poss) >= cfg.get("max_positions", 3):
            continue
        if any(p.symbol == sym for p in poss):        # مركز واحد لكل رمز
            continue
        net_day, n_day = _daily()
        if net_day <= -abs(cfg.get("daily_loss_usd", 5.0)) \
                or n_day >= cfg.get("max_trades_day", 12):
            continue
        spr = float(ti.ask - ti.bid)
        # ⚔️ سقف السبريد النسبيّ: يقبل العالي وقت الانفجار، يرفض القاتل
        if spr > cfg.get("spread_atr_max", 0.15) * atr:
            print(f"🛑 {sym} سبريد قاتل حتى للهجوم: {spr:.3f} > {cfg['spread_atr_max']}×ATR({atr:.2f})")
            continue
        is_buy = move > 0
        # 🧠 استشارة المخّ: خريطة الماسح + معرفة اللحظات المُقاسة
        allow, brain = _brain_context(sym, 1 if is_buy else -1)
        if not allow:
            print(f"🧠 فيتو المخّ: {brain.get('brain_veto')}")
            continue
        price = ti.ask if is_buy else ti.bid
        stop = cfg.get("stop_atr", 0.6) * atr
        targ = cfg.get("target_atr", 1.2) * atr
        sl = price - stop if is_buy else price + stop
        tp = price + targ if is_buy else price - targ
        digits = (mt5.symbol_info(sym).digits if mt5.symbol_info(sym) else 3)
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": LOT,
               "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
               "price": float(price), "sl": round(float(sl), digits),
               "tp": round(float(tp), digits), "deviation": 50, "magic": MAGIC,
               "comment": f"boundary_{tag[:12]}", "type_filling": mt5.ORDER_FILLING_IOC}
        r = mt5.order_send(req)
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            _last_exec[sym] = now
            print(f"⚔️ هجوم {tag} {sym}: {'شراء' if is_buy else 'بيع'} {LOT} @ {price:.2f} "
                  f"سبريد {spr:.3f} ({spr/atr:.2f}×ATR) وقف {sl:.2f} هدف {tp:.2f}")
            try:
                rec = {"ts": now, "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "ticket": int(getattr(r, "order", 0) or 0),
                       "engine": "boundary_pilot", "boundary": tag,
                       "side": "BUY" if is_buy else "SELL", "symbol": sym,
                       "entry": float(price), "sl": float(sl), "tp": float(tp),
                       "lot": LOT, "spread": round(spr, 5),
                       "spread_atr": round(spr / atr, 3), "atr": round(atr, 3),
                       "burst_move_atr": round(abs(move) / atr, 2),
                       "brain": brain}
                with open(ENTRIES_F, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                pass
        else:
            print(f"⏭️ {sym} لم تُنفّذ: {getattr(r,'retcode','?')}")


def _manage(cfg):
    """ترييل: بعد +1×ATR انقل الوقف خلف السعر بـ0.5×ATR (اترك الانفجار يجري)."""
    for p in (mt5.positions_get() or []):
        if p.magic != MAGIC:
            continue
        ti = mt5.symbol_info_tick(p.symbol)
        if not ti:
            continue
        atr = _atr_m5(p.symbol)
        if atr <= 0:
            continue
        cur = ti.bid if p.type == 0 else ti.ask
        fav = (cur - p.price_open) if p.type == 0 else (p.price_open - cur)
        if fav >= cfg.get("trail_arm_atr", 1.0) * atr:
            tr = cur - cfg.get("trail_atr", 0.5) * atr if p.type == 0 \
                else cur + cfg.get("trail_atr", 0.5) * atr
            better = (p.type == 0 and (not p.sl or tr > p.sl)) or \
                     (p.type == 1 and (not p.sl or tr < p.sl))
            if better:
                digits = (mt5.symbol_info(p.symbol).digits if mt5.symbol_info(p.symbol) else 3)
                mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol,
                                "position": p.ticket, "sl": round(float(tr), digits),
                                "tp": p.tp, "magic": MAGIC})


def main():
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print(f"⚔️ boundary_pilot بدأ — هجوم اللحظات · magic {MAGIC} · {SYMBOLS} · لوت {LOT}")
    while True:
        try:
            cfg = _cfg()
            if cfg.get("enabled", True):
                _arm_moments()
                _try_attack(cfg)
                _manage(cfg)
            json.dump({"ts": time.time(), "iso": time.strftime("%H:%M:%S"),
                       "magic": MAGIC, "armed_windows": len(_armed),
                       "enabled": cfg.get("enabled")},
                      open(STATUS_F, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as e:
            print(f"cycle err: {type(e).__name__}: {e}")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
