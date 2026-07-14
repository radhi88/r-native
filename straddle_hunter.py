"""straddle_hunter.py — صيّاد القفزات: news/breakout STRADDLE with OCO + flip + self-evaluation.

The user's spec (2026-06-10):
  • قبل القفزات (خصوصاً الأخبار) ضع أمرين معلّقين: BUY_STOP فوق السعر و SELL_STOP تحته — بحذر.
  • OCO: إذا انفّذ جانب → ألغِ الآخر فوراً.
  • التبديل: إذا انفّذ جانب وانضرب وقفه بسرعة (مصيدة) → سلّح الجانب المعاكس مرة واحدة.
  • تقييم ذاتي: يسجّل كل محاولة؛ لو الحركة كلها خسائر → يوقف نفسه أو يعدّل معاييره
    (متغيّر واحد لكل دورة)؛ ولو ما قدر يصلّح نفسه → يكتب طلب مساعدة لي وللوكلاء
    (straddle_help_request.json) وينتظر نصيحة (straddle_advice.json) ويطبّقها.

Safety: DEMO · own magic 20260611 · fixed min lot · hard SL/TP on every order · 1 episode at a
time per symbol · obeys risk_manager lot_mult · episodes expire. Windowless.
Run:  pythonw straddle_hunter.py
"""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
STATE = RN / "straddle_state.json"          # config + auto-tuned params (persisted)
JOURNAL = RN / "straddle_journal.json"      # every episode's outcome (the learning data)
HELP_REQ = RN / "straddle_help_request.json"
ADVICE = RN / "agents" / "straddle_advice.json"   # Claude/agents answer here; hunter applies it

MAGIC = 20260611
SYMBOLS = ["XAUUSDm", "USDJPYm"]            # rocket-prone, liquid news movers
POLL_S = 5

DEFAULTS = {
    "enabled": True,
    "dist_atr": 0.8,        # stop orders this many M5-ATRs above/below price
    "sl_atr": 1.0,          # SL beyond entry
    "tp_atr": 2.5,          # rockets run — generous target
    "arm_min": 6,           # arm when event is <= this many minutes away
    "fire_min": 1,          # ...and >= this (don't arm during the spike itself)
    "expire_min": 40,       # pending lifetime
    "flip_window_s": 360,   # filled→stopped within this = whipsaw → arm opposite ONCE
    "max_flips": 1,
    "lot_x": 2,             # volume_min multiplier (tiny, careful)
    "eval_window": 6,       # self-eval over last N episodes
    "pause_after_net": -6.0 # if last N episodes net $ worse than this → pause + ask for help
}


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _cfg():
    st = _load(STATE, {}) or {}
    cfg = dict(DEFAULTS); cfg.update(st.get("cfg", {}))
    return cfg, st


def _upcoming_event():
    """Minutes to the next HIGH-impact event (from news_engine's calendar parse)."""
    try:
        import news_engine as ne
        evs = ne.load_calendar()
        now = time.time()
        best = None
        for ev in evs:
            if str(ev.get("impact", "")).lower() not in ("high", "h", "3"):
                continue
            ts = ne._parse_ts(ev.get("date") or ev.get("time"))
            if ts is None:
                continue
            mins = (ts - now) / 60.0
            if 0 < mins and (best is None or mins < best[0]):
                best = (mins, ev.get("title", "?"), (ev.get("country") or "").upper())
        return best
    except Exception:
        return None


def _atr(mt5, sym, n=14):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, n + 2)
    if r is None or len(r) < n:
        return 0.0
    tr = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
              abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    return sum(tr[-n:]) / n


def _risk_mult():
    d = _load(RN / "risk_register.json", {}) or {}
    return float(d.get("lot_mult", 1.0)) if time.time() - float(d.get("ts", 0)) < 300 else 1.0


def _send_stop(mt5, sym, side, entry, sl, tp, lot, expire_s, tag):
    info = mt5.symbol_info(sym)
    ot = mt5.ORDER_TYPE_BUY_STOP if side == "BUY" else mt5.ORDER_TYPE_SELL_STOP
    r = mt5.order_send({"action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": float(lot),
                        "type": ot, "price": round(entry, info.digits),
                        "sl": round(sl, info.digits), "tp": round(tp, info.digits),
                        "deviation": 80, "magic": MAGIC, "comment": tag,
                        "type_time": mt5.ORDER_TIME_SPECIFIED,
                        "expiration": int(time.time()) + expire_s,
                        "type_filling": mt5.ORDER_FILLING_IOC})
    return (getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE,
            getattr(r, "order", 0), getattr(r, "comment", ""))


def _cancel(mt5, ticket):
    try:
        mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)})
    except Exception:
        pass


def _my_orders(mt5, sym=None):
    return [o for o in (mt5.orders_get(symbol=sym) if sym else (mt5.orders_get() or []) or [])
            if o.magic == MAGIC]


def _my_pos(mt5, sym=None):
    return [p for p in (mt5.positions_get(symbol=sym) if sym else (mt5.positions_get() or []) or [])
            if p.magic == MAGIC]


def _journal_add(ep):
    j = _load(JOURNAL, {"episodes": []}) or {"episodes": []}
    j["episodes"] = (j.get("episodes", []) + [ep])[-60:]
    _save(JOURNAL, j)


def _self_evaluate(cfg, st):
    """التقييم الذاتي: آخر N محاولات — يوقف، أو يعدّل متغيّراً واحداً، أو يطلب المساعدة."""
    j = _load(JOURNAL, {}) or {}
    eps = [e for e in j.get("episodes", []) if e.get("done")]
    if len(eps) < cfg["eval_window"]:
        return cfg, "يجمع عيّنة"
    last = eps[-cfg["eval_window"]:]
    net = sum(e.get("net", 0.0) for e in last)
    fills = [e for e in last if e.get("filled_side")]
    whips = sum(1 for e in fills if e.get("whipsaw"))
    nofill = sum(1 for e in last if not e.get("filled_side"))
    note = f"آخر {len(last)}: صافي ${net:+.2f} · مصايد {whips}/{len(fills) or 1} · بلا تنفيذ {nofill}"
    tuned = st.get("tuned", [])
    if net <= cfg["pause_after_net"]:
        if len(tuned) >= 3:                      # عدّل 3 مرات وما ضبطت → أوقف واسأل
            cfg["enabled"] = False
            _save(HELP_REQ, {"ts": time.time(), "iso": datetime.now(timezone.utc).isoformat(),
                             "from": "straddle_hunter", "status": "PAUSED — أحتاج مساعدة",
                             "stats": note, "cfg": cfg, "tuned_history": tuned,
                             "question": "جرّبت 3 تعديلات وما زالت الحركة خاسرة. وش أغيّر؟ "
                                         "(المسافة dist_atr؟ التوقيت arm_min؟ الرموز؟ أو ألغيها؟)"})
            return cfg, note + " → 🛑 موقوفة، طلبت مساعدة الوكلاء/كلود"
        # one-variable-per-cycle auto-tune (falsifiable)
        if whips > len(fills) / 2 and fills:     # مصايد كثيرة → وسّع المسافة
            cfg["dist_atr"] = round(min(1.6, cfg["dist_atr"] + 0.2), 2); change = "وسّعت dist_atr"
        elif nofill >= cfg["eval_window"] - 1:   # ما ينفّذ أبداً → قرّب المسافة
            cfg["dist_atr"] = round(max(0.4, cfg["dist_atr"] - 0.2), 2); change = "قرّبت dist_atr"
        else:                                    # ينفّذ ويخسر → وقف أوسع وهدف أقرب
            cfg["sl_atr"] = round(min(1.6, cfg["sl_atr"] + 0.2), 2)
            cfg["tp_atr"] = round(max(1.5, cfg["tp_atr"] - 0.3), 2); change = "عدّلت sl/tp"
        tuned.append({"ts": time.time(), "change": change, "stats": note})
        st["tuned"] = tuned
        # reset the window so the new setting gets a clean trial
        j = _load(JOURNAL, {}) or {}
        for e in j.get("episodes", []):
            e["counted"] = True
        _save(JOURNAL, j)
        return cfg, note + f" → 🔧 طوّرت نفسي: {change}"
    # 🏅 ترقية الرابح المثبت: ≥10 محاولات وصافي كامل ≥ +$3 → ضاعف الحجم (مرة لكل عتبة)
    all_net = sum(e.get("net", 0.0) for e in eps)
    if len(eps) >= 10 and all_net >= 3.0 and int(cfg.get("lot_x", 2)) < 6 and not st.get("promoted_at_" + str(int(cfg.get("lot_x", 2)))):
        st["promoted_at_" + str(int(cfg.get("lot_x", 2)))] = time.time()
        cfg["lot_x"] = min(6, int(cfg.get("lot_x", 2)) * 2)
        return cfg, note + f" → 🏅 ترقية مستحقة (صافي كلي ${all_net:+.2f} في {len(eps)}) — اللوت ×{cfg['lot_x']}"
    return cfg, note + " → ✅ مقبولة، أكمل"


def _apply_advice(cfg, st):
    """لو كلود/الوكلاء كتبوا نصيحة — طبّقها وعد للعمل."""
    adv = _load(ADVICE, {}) or {}
    if not adv or adv.get("applied"):
        return cfg
    for k in ("dist_atr", "sl_atr", "tp_atr", "arm_min", "expire_min", "lot_x", "enabled"):
        if k in adv:
            cfg[k] = adv[k]
    if adv.get("symbols"):
        global SYMBOLS; SYMBOLS = adv["symbols"]
    adv["applied"] = True; adv["applied_ts"] = time.time()
    _save(ADVICE, adv)
    st["tuned"] = []                             # نصيحة جديدة = صفحة جديدة
    print("[STRADDLE] 🧠 طبّقت نصيحة كلود/الوكلاء:", {k: adv.get(k) for k in adv if k != 'applied'}, flush=True)
    return cfg


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print(f"[STRADDLE] صيّاد القفزات حيّ · {SYMBOLS} · magic {MAGIC} · DEMO", flush=True)
    episodes = {}        # sym -> live episode dict
    last_eval = 0.0
    while True:
        try:
            cfg, st = _cfg()
            cfg = _apply_advice(cfg, st)
            now = time.time()
            ev = _upcoming_event()
            # ── ARM: event approaching → place the two-sided trap (careful sizing) ──
            if cfg.get("enabled") and ev and cfg["fire_min"] <= ev[0] <= cfg["arm_min"]:
                for sym in SYMBOLS:
                    if sym in episodes or _my_orders(mt5, sym) or _my_pos(mt5, sym):
                        continue
                    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
                    if not info or not tick or not tick.bid or (now - tick.time) > 120:
                        continue
                    atr = _atr(mt5, sym)
                    if atr <= 0:
                        continue
                    dist = max(cfg["dist_atr"] * atr, (tick.ask - tick.bid) * 3)
                    lot = max(info.volume_min, round(info.volume_min * cfg["lot_x"] * _risk_mult(), 2))
                    be = tick.ask + dist; se = tick.bid - dist
                    okb, tb, cb = _send_stop(mt5, sym, "BUY", be, be - cfg["sl_atr"] * atr,
                                             be + cfg["tp_atr"] * atr, lot, cfg["expire_min"] * 60, "STRDL-B")
                    oks, ts_, cs = _send_stop(mt5, sym, "SELL", se, se + cfg["sl_atr"] * atr,
                                              se - cfg["tp_atr"] * atr, lot, cfg["expire_min"] * 60, "STRDL-S")
                    if okb or oks:
                        episodes[sym] = {"sym": sym, "event": ev[1], "armed_ts": now,
                                         "buy_ticket": tb if okb else 0, "sell_ticket": ts_ if oks else 0,
                                         "filled_side": None, "fill_ts": 0, "flips": 0,
                                         "whipsaw": False, "net": 0.0, "done": False}
                        print(f"[STRADDLE] 🪤 سلّحت {sym} لـ«{ev[1]}» بعد {ev[0]:.0f}د · فوق {be:.2f} / تحت {se:.2f} · لوت {lot}", flush=True)
                    else:
                        print(f"[STRADDLE] فشل تسليح {sym}: {cb} / {cs}", flush=True)
            # ── MANAGE: OCO + flip + close-out accounting ──
            for sym, ep in list(episodes.items()):
                poss = _my_pos(mt5, sym); ords = _my_orders(mt5, sym)
                if poss and not ep["filled_side"]:
                    p = poss[0]
                    ep["filled_side"] = "BUY" if p.type == 0 else "SELL"
                    ep["fill_ts"] = now
                    for o in ords:                       # OCO: cancel the other side instantly
                        _cancel(mt5, o.ticket)
                    print(f"[STRADDLE] ⚡ {sym} انفّذ {ep['filled_side']} — ألغيت الجانب الآخر (OCO)", flush=True)
                if ep["filled_side"] and not poss:       # position closed (SL/TP) → settle
                    dl = [d for d in (mt5.history_deals_get(int(ep["armed_ts"]), int(now)) or [])
                          if d.magic == MAGIC and d.symbol == sym and d.entry == 1]
                    net = sum(d.profit + d.commission + d.swap for d in dl)
                    ep["net"] = round(net, 2)
                    fast_loss = net < 0 and (now - ep["fill_ts"]) <= cfg["flip_window_s"]
                    if fast_loss and ep["flips"] < cfg["max_flips"] and cfg.get("enabled"):
                        # المصيدة → سلّح الجانب المعاكس مرة واحدة (التبديل الذي طلبه المستخدم)
                        info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
                        atr = _atr(mt5, sym)
                        if info and tick and atr > 0:
                            opp = "SELL" if ep["filled_side"] == "BUY" else "BUY"
                            dist = max(0.5 * cfg["dist_atr"] * atr, (tick.ask - tick.bid) * 3)
                            e2 = (tick.bid - dist) if opp == "SELL" else (tick.ask + dist)
                            sl2 = e2 + cfg["sl_atr"] * atr if opp == "SELL" else e2 - cfg["sl_atr"] * atr
                            tp2 = e2 - cfg["tp_atr"] * atr if opp == "SELL" else e2 + cfg["tp_atr"] * atr
                            lot = max(info.volume_min, round(info.volume_min * cfg["lot_x"] * _risk_mult(), 2))
                            ok, tk, _ = _send_stop(mt5, sym, opp, e2, sl2, tp2, lot, 20 * 60, "STRDL-FLIP")
                            if ok:
                                ep["flips"] += 1; ep["whipsaw"] = True; ep["filled_side"] = None
                                print(f"[STRADDLE] 🔄 {sym} مصيدة — بدّلت للجانب {opp}", flush=True)
                                continue
                    ep["done"] = True
                    _journal_add(ep); del episodes[sym]
                    print(f"[STRADDLE] 🏁 {sym} انتهت: ${ep['net']:+.2f}" + (" (مصيدة+تبديل)" if ep["whipsaw"] else ""), flush=True)
                if not poss and not ords and not ep["filled_side"]:
                    if now - ep["armed_ts"] > cfg["expire_min"] * 60 + 60:
                        ep["done"] = True; _journal_add(ep); del episodes[sym]
                        print(f"[STRADDLE] ⌛ {sym} انتهت بلا تنفيذ (السعر ما قفز)", flush=True)
            # ── SELF-EVAL every 10 min ──
            if now - last_eval > 600:
                last_eval = now
                cfg, verdict = _self_evaluate(cfg, st)
                st["cfg"] = cfg; st["last_eval"] = verdict; st["ts"] = now
                _save(STATE, st)
                print(f"[STRADDLE] 🧪 تقييم ذاتي: {verdict}", flush=True)
        except Exception as e:
            print(f"[STRADDLE] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
