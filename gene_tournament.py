"""gene_tournament.py — بطولة التوائم: LIVE twin-gene duels (NO backtest, NO simulation).

The user's design (2026-06-11):
  • كل جين له توأم بنفس القيم — واحد يشتري وواحد يبيع في نفس الثانية (صفقتان حقيقيتان).
  • الفائز يُعتمد ويترقّى لمرحلة المسابقة التالية، وقيمه تُحفَظ من أول فوز.
  • فوز ثانٍ بنفس القيم → مرحلة أعلى وتأكيد القيم (قيم مؤكَّدة يستفيد منها المتداول).
  • الخاسر يُقتل، وقيمه تُعطى لجين جديد بالاتجاه المعاكس (التكاثر بالقلب).
  • كل ولادة/موت/ترقية تُسجَّل نسباً (lineage) وتُرسم شجرة تكاثر حيّة في ARENA.

Honesty: duels are REAL min-lot orders on the DEMO account (real spread, real slippage, real
fills) — forward evidence, never backtest. Costs ≈ 2×spread per duel, bounded hard.
Safety: magic 20260612 · volume_min only · max 2 duels at once · only session-validated symbols
in their active session · skips news-veto windows + AutoTrading-off · every order has SL+TP ·
4h timeout force-settle. Windowless.  Run:  pythonw gene_tournament.py
"""
from __future__ import annotations
import json, os, sys, time, random
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
STATE = RN / "tournament_state.json"
LINEAGE = RN / "tournament_lineage.jsonl"
CONFIRMED = RN / "tournament_confirmed.json"
KILL_F = MT5DIR / "kill_switch.txt"   # 🛑 إيقاف طارئ: وجوده يمنع فتح مبارزات جديدة فقط (التسوية/الإغلاق تبقى حيّة)
MAGIC = 20260612
MAX_DUELS = 2
DUEL_TIMEOUT_S = 4 * 3600
POLL_S = 10
STAGES = {1: "التصفيات", 2: "نصف النهائي", 3: "قيم مؤكَّدة 🏆"}
for p in (str(MT5DIR), str(MT5DIR / "r_native_v2")):
    if p not in sys.path:
        sys.path.insert(0, p)
import portfolio_guard as pg   # حارس التحوّط-البيني (نقي؛ يفحص المحرّكات الأخرى فقط)


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


def _kill_active():
    """🛑 مفتاح الإيقاف الطارئ: يمنع فتح مبارزات/مراكز جديدة فقط؛ تسوية وإغلاق المراكز القائمة (_close) يبقى حيّاً."""
    try:
        return KILL_F.exists()
    except Exception:
        return False


def _lin(ev, **kw):
    rec = {"ts": time.time(), "iso": datetime.now(timezone.utc).isoformat(), "ev": ev, **kw}
    try:
        with open(LINEAGE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(f"[TOURN] {ev}: {kw}", flush=True)


def _session_roster():
    """Symbols whose validated specialist is ACTIVE right now (uses the live session router)."""
    try:
        import multi_trader as mt
        roster = mt._genomes()                    # {sym: cfg} for the CURRENT session only
        # 🩸 طبقة دفاعية (الاستبعاد موروث من _genomes أصلاً): معادن/مرفوعة/نازفة لا تُبارَز أبداً.
        import re as _re
        _bleed = getattr(mt, "_BLEED_SYMS", set())
        return {s: c for s, c in roster.items()
                if not (s.upper().startswith("XAU") or s.upper().startswith("XAG")
                        or _re.search(r"_X\d+", s.upper()) or s in _bleed)}
    except Exception:
        return {}


def _veto_now(sym):
    d = _load(RN / "news_blocked_symbols.json", {}) or {}
    return sym in (d.get("blocked_symbols") or [])


def _atr(mt5, sym, tf_name, n=14):
    tfm = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    r = mt5.copy_rates_from_pos(sym, tfm.get(tf_name, mt5.TIMEFRAME_M15), 0, n + 2)
    if r is None or len(r) < n:
        return 0.0
    tr = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
              abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    return sum(tr[-n:]) / n


def _open(mt5, sym, side, lot, sl, tp, tag):
    if _kill_active():                      # 🛑 إيقاف طارئ: لا فتح جديد (التسوية عبر _close تبقى حيّة)
        return 0
    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
    if not info or not tick:
        return 0
    ot = mt5.ORDER_TYPE_BUY if side > 0 else mt5.ORDER_TYPE_SELL
    px = tick.ask if side > 0 else tick.bid
    r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lot),
                        "type": ot, "price": px, "sl": round(sl, info.digits),
                        "tp": round(tp, info.digits), "deviation": 60, "magic": MAGIC,
                        "comment": tag[:28], "type_filling": mt5.ORDER_FILLING_IOC})
    return getattr(r, "order", 0) if getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE else 0


def _close(mt5, pos):
    tick = mt5.symbol_info_tick(pos.symbol)
    if not tick:
        return
    is_buy = pos.type == mt5.POSITION_TYPE_BUY
    mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "position": pos.ticket,
                    "volume": pos.volume, "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                    "price": tick.bid if is_buy else tick.ask, "deviation": 60, "magic": MAGIC,
                    "comment": "DUEL-settle", "type_filling": mt5.ORDER_FILLING_IOC})


def _pnl_of(mt5, sym, since, tag):
    now = int(time.time())
    net = 0.0; closed = False
    for d in (mt5.history_deals_get(int(since) - 5, now) or []):
        if d.magic != MAGIC or d.symbol != sym:
            continue
        if d.entry == 1 and tag in (d.comment or ""):
            net += d.profit + d.commission + d.swap; closed = True
        elif d.entry == 0 and tag in (d.comment or ""):
            pass
    # position comments on exits may be broker-replaced; fall back to position scan
    return net, closed


def new_contestant(st, sym, values, direction, parent=None, stage=1):
    cid = f"G{int(time.time()) % 100000}{random.randint(10, 99)}"
    c = {"id": cid, "sym": sym, "values": values, "dir": direction, "stage": stage,
         "wins": 0, "born": time.time(), "parent": parent, "alive": True}
    st["contestants"][cid] = c
    _lin("ولادة", id=cid, sym=sym, dir=("شراء" if direction > 0 else "بيع"), stage=stage, parent=parent)
    return c


def main():
    import MetaTrader5 as mt5
    # 🔒 قفل وحيد: عدّة حُرّاس قد تُطلق نسخاً متعدّدة تتسابق على نفس مبارزات magic 20260612 = إفراط
    # تداول خطر على حساب $100. ربط منفذ محلي ثابت (8712) يضمن نسخة واحدة (يتحرّر تلقائياً عند موت العملية).
    import socket
    _lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock.bind(("127.0.0.1", 8712)); _lock.listen(1)
        main._singleton_lock = _lock          # إبقاء المرجع حيّاً طوال عمر العملية
    except OSError:
        print("[TOURN] نسخة أخرى تعمل بالفعل — خروج (قفل وحيد 8712)", flush=True); return 0
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print(f"[TOURN] بطولة التوائم حيّة · magic {MAGIC} · مبارزات حقيقية بلا باكتيست", flush=True)
    st = _load(STATE, {}) or {}
    st.setdefault("contestants", {})
    st.setdefault("duels", {})
    while True:
        try:
            ti = mt5.terminal_info()
            if not (ti and ti.trade_allowed):
                time.sleep(30); continue
            roster = _session_roster()
            now = time.time()
            # ── settle running duels ──────────────────────────────────────────
            for did, du in list(st["duels"].items()):
                sym = du["sym"]
                poss = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
                if poss and now - du["t0"] > DUEL_TIMEOUT_S:
                    for p in poss:
                        _close(mt5, p)
                    time.sleep(3)
                    poss = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
                if poss:
                    continue                       # still fighting
                # both sides closed → judge by realized P&L per side
                deals = [d for d in (mt5.history_deals_get(int(du["t0"]) - 5, int(now)) or [])
                         if d.magic == MAGIC and d.symbol == sym and d.entry == 1]
                netL = sum(d.profit + d.commission + d.swap for d in deals
                           if d.position_id == du["pos_long"])
                netS = sum(d.profit + d.commission + d.swap for d in deals
                           if d.position_id == du["pos_short"])
                win_dir = 1 if netL > netS else -1 if netS > netL else 0
                cw = st["contestants"].get(du["long" if win_dir > 0 else "short"]) if win_dir else None
                cl = st["contestants"].get(du["short" if win_dir > 0 else "long"]) if win_dir else None
                if cw:
                    cw["wins"] += 1; cw["stage"] += 1
                    cw["best_net"] = round(max(cw.get("best_net", -9e9), netL if win_dir > 0 else netS), 2)
                    _lin("فوز", id=cw["id"], sym=sym, net=round(netL if win_dir > 0 else netS, 2),
                         stage=cw["stage"], title=STAGES.get(min(cw["stage"], 3), str(cw["stage"])))
                    if cw["stage"] >= 3:           # قيم مؤكَّدة → يستفيد منها المتداول كميل اتجاهي
                        conf = _load(CONFIRMED, {}) or {}
                        conf[sym] = {"dir": cw["dir"], "values": cw["values"], "id": cw["id"],
                                     "wins": cw["wins"], "ts": now}
                        _save(CONFIRMED, conf)
                        _lin("تتويج", id=cw["id"], sym=sym, dir=("شراء" if cw["dir"] > 0 else "بيع"))
                if cl:
                    cl["alive"] = False
                    _lin("موت", id=cl["id"], sym=sym, net=round(netS if win_dir > 0 else netL, 2))
                    # التكاثر بالقلب: قيم الميت تُعطى لجين جديد بالاتجاه المعاكس
                    new_contestant(st, sym, cl["values"], -cl["dir"], parent=cl["id"])
                if not win_dir:
                    _lin("تعادل", sym=sym)
                del st["duels"][did]
            # ── start new duels (bounded, real, careful) ──────────────────────
            if len(st["duels"]) < MAX_DUELS and not _kill_active():   # 🛑 الإيقاف الطارئ يمنع مبارزات جديدة (التسوية أعلاه تبقى حيّة)
                for sym, cfg in roster.items():
                    if len(st["duels"]) >= MAX_DUELS:
                        break
                    if any(d["sym"] == sym for d in st["duels"].values()) or _veto_now(sym):
                        continue
                    if [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]:
                        continue
                    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
                    if not info or not tick or (now - tick.time) > 120:
                        continue
                    atr = _atr(mt5, sym, cfg.get("tf", "M15"))
                    if atr <= 0:
                        continue
                    values = {"tf": cfg.get("tf"), "stop_atr": cfg.get("stop_atr"),
                              "target_atr": cfg.get("target_atr"), "conf_gate": cfg.get("conf_gate")}
                    # find/create the twin pair for this symbol (stage progression preserved)
                    alive = [c for c in st["contestants"].values()
                             if c["sym"] == sym and c["alive"]]
                    cL = next((c for c in alive if c["dir"] > 0), None) or new_contestant(st, sym, values, 1)
                    cS = next((c for c in alive if c["dir"] < 0), None) or new_contestant(st, sym, values, -1)
                    lot = info.volume_min
                    sd = float(values["stop_atr"] or 2.0) * atr
                    td = float(values["target_atr"] or 3.0) * atr
                    # 🛑 منع صارم بحجم-الحساب: لا نزال لو أصغر لوت يتجاوز 2% من الحقوق (ذهب 6.4%/فضة 8%
                    # على حساب صغير = سبب خسارة الذهب −$23.37). يُعاد تلقائياً متى كبر الحساب.
                    _ai = mt5.account_info(); _ts = info.trade_tick_size or info.point; _tv = info.trade_tick_value
                    if _ai and _ts and _tv and info.volume_min * (sd / _ts) * _tv > _ai.equity * 0.02:
                        continue
                    # 🚫 لا تبدأ مبارزة على رمزٍ يحمل فيه محرّكٌ آخر منّا اتجاهاً (ساقا التوأم سيُحوّطانه = ضجيج).
                    # ساقا التوأم نفسهما (نفس MAGIC) مستثنيان تلقائياً (الحارس يتجاهل my_magic).
                    _hb, _hbr = pg.would_hedge(mt5, sym, mt5.ORDER_TYPE_BUY, MAGIC)
                    _hs, _hsr = pg.would_hedge(mt5, sym, mt5.ORDER_TYPE_SELL, MAGIC)
                    if _hb or _hs:
                        print(f"[TOURNAMENT] skip duel {sym}: {_hbr or _hsr}", flush=True)
                        continue
                    oL = _open(mt5, sym, 1, lot, tick.ask - sd, tick.ask + td, f"DUEL-{cL['id']}")
                    oS = _open(mt5, sym, -1, lot, tick.bid + sd, tick.bid - td, f"DUEL-{cS['id']}")
                    time.sleep(2)
                    poss = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
                    pl = next((p.ticket for p in poss if p.type == mt5.POSITION_TYPE_BUY), 0)
                    ps = next((p.ticket for p in poss if p.type == mt5.POSITION_TYPE_SELL), 0)
                    if pl and ps:
                        st["duels"][f"D{int(now)}"] = {"sym": sym, "t0": now, "long": cL["id"],
                                                       "short": cS["id"], "pos_long": pl, "pos_short": ps}
                        _lin("مبارزة", sym=sym, long=cL["id"], short=cS["id"],
                             stage=max(cL["stage"], cS["stage"]))
                    else:                          # one leg failed → settle whatever opened
                        for p in poss:
                            _close(mt5, p)
            st["ts"] = now
            _save(STATE, st)
        except Exception as e:
            print(f"[TOURN] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
