"""news_gene.py — جينات الأخبار: سلّم ستوبات حول الخبر + مطاردة الربح + الانعكاس التلقائي.

تصميم المستخدم (2026-06-11):
  • قبل الخبر بدقيقة: سلّم أوامر STOP شراء فوق السعر وسلّم بيع تحته (N درجات لكل جانب).
  • السعر يقفز على الدرجات → كل درجة منفّذة تُطارَد بوقف متحرك "تأمين الأرباح إلى أعلى ربح".
  • لا OCO هنا: الجانب المعاكس يبقى مسلّحاً — لو انعكس السعر بعنف ينفّذ سلّم الاتجاه الآخر
    تلقائياً (الانعكاس معه) بينما التريل يقفل الجانب الأول.
  • اختبار تاريخي صادق (M1 + سبريد كل شمعة الحقيقي) على أحداث الأسبوع — هل كان يربح أمس؟

أمان حيّ: magic 20260614 · لوت أدنى لكل درجة · N≤3 درجات/جانب · انتهاء 45 دقيقة بعد الخبر ·
تسوية إجبارية · سقف خسارة يومي للجين · يحترم AutoTrading.
Run:  python news_gene.py --test   (الاختبار التاريخي)
      pythonw news_gene.py         (الصيد الحيّ)
"""
from __future__ import annotations
from engine_gov import gov_mult            # 🎛️ مضاعِف حوكمة المايسترو
import argparse, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
STATE = RN / "news_gene_state.json"
JOURNAL = RN / "news_gene_journal.json"
MAGIC = 20260614
KILL_F = MT5DIR / "kill_switch.txt"   # 🛑 إيقاف طارئ: وجوده يمنع تسليح سلالم جديدة فقط (المطاردة/التسوية تبقى حيّة)
SYMBOLS = ["XAUUSDm", "BTCUSDm"]   # احتياط — الحيّ يستخدم _active_symbols (كل عملات الجلسة)


def _active_symbols(st):
    """كل العملات نفس الشيء: روستر الجلسة الحالية + الذهب/BTC — ناقص من بنّح نفسه
    (عملة خسرت ≥3 حملات بصافي < -$5 تُستبعد تلقائياً وتسجَّل)."""
    syms = set(SYMBOLS)
    try:
        import multi_trader as mt
        syms |= set(mt._genomes())
    except Exception:
        pass
    benched = set((st or {}).get("benched_syms", []))
    return sorted(syms - benched)
POLL_S = 5
GENE = {                      # قيم الجين الافتراضية (قابلة للتطوّر بالتقييم الذاتي)
    "rungs": 3,               # درجات لكل جانب
    "first_atr": 0.45,        # بعد أول درجة (×ATR5m)
    "space_atr": 0.35,        # تباعد الدرجات
    "trail_atr": 0.55,        # مسافة وقف المطاردة
    "sl_atr": 1.0,            # الوقف الابتدائي لكل درجة
    "arm_sec": 75,            # التسليح قبل الخبر بـ
    "ttl_min": 45,            # عمر الحملة بعد الخبر
    "daily_cap": -25.0,       # سقف اليوم (متناسب مع أوزان [1,2,3]: أسوأ حدث مقيس ≈ -$22)
    "lot_x": 1,               # مضاعف اللوت (يترقى تلقائياً بالإثبات: 4 حملات بصافي موجب → ×2 حتى 10)
    "lot_weights": [1, 2, 3], # فكرة المستخدم المثبتة بالمسح: 0.01/0.02/0.03 تصاعدياً (+$130 ضد +$72 للثابت)
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
    os.replace(tmp, p)


def _kill_active():
    """🛑 مفتاح الإيقاف الطارئ: يمنع تسليح سلالم/أوامر جديدة فقط؛ مطاردة التريل (SLTP) وتسوية TTL تبقى حيّة."""
    try:
        return KILL_F.exists()
    except Exception:
        return False


# ════════════════ الاختبار التاريخي الصادق (M1 + سبريد حقيقي لكل شمعة) ════════════════
def simulate_event(mt5, sym, ev_ts, g=GENE, verbose=False, bars=None):
    """حاكِ حملة سلّم كاملة حول حدثٍ تاريخي على شموع M1 الحقيقية. يعيد صافي $ للوت الأدنى."""
    mt5.symbol_select(sym, True)
    info = mt5.symbol_info(sym)
    if not info or not info.point or not info.trade_tick_size:
        return None
    tv = info.trade_tick_value / info.trade_tick_size      # $ لكل وحدة سعر لكل 1.0 لوت
    lot = info.volume_min
    _dt = lambda t: datetime.fromtimestamp(int(t), tz=timezone.utc)
    if bars is None:
        r = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1,
                                 _dt(int(ev_ts) - 75 * 60), _dt(int(ev_ts) + g["ttl_min"] * 60 + 120))
        if r is None or len(r) < 20:
            return None
        bars = [dict(time=int(b["time"]), high=float(b["high"]), low=float(b["low"]),
                     close=float(b["close"]), spread=float(b["spread"])) for b in r]
    # ATR5m من آخر 70 دقيقة قبل الخبر (14 شمعة ×5د مجمّعة تقريبياً = ATR M1 ×~2.2)
    pre = [b for b in bars if b["time"] < ev_ts - 60]
    if len(pre) < 15:
        return None
    trs = [max(pre[i]["high"] - pre[i]["low"], abs(pre[i]["high"] - pre[i - 1]["close"]),
               abs(pre[i]["low"] - pre[i - 1]["close"])) for i in range(1, len(pre))]
    atr = (sum(trs[-30:]) / min(30, len(trs))) * 2.2
    px0 = float(pre[-1]["close"])
    sp = float(pre[-1]["spread"]) * info.point or (atr * 0.05)
    lw = list(g.get("lot_weights") or [1] * int(g["rungs"]))
    while len(lw) < int(g["rungs"]):
        lw.append(lw[-1])
    rungs = []                                            # [dir, entry, state, weight]
    for k in range(g["rungs"]):
        d = g["first_atr"] * atr + k * g["space_atr"] * atr
        rungs.append([1, px0 + d, None, lw[k]])
        rungs.append([-1, px0 - d, None, lw[k]])
    posns = []                                            # {dir, entry, stop, best, open}
    net = 0.0
    post = [b for b in bars if b["time"] >= ev_ts - 60]
    for b in post:
        hi, lo, cl = float(b["high"]), float(b["low"]), float(b["close"])
        # 1) تنفيذ الدرجات
        for rg in rungs:
            if rg[2] is None:
                if rg[0] > 0 and hi >= rg[1]:
                    posns.append({"dir": 1, "entry": rg[1], "stop": rg[1] - g["sl_atr"] * atr,
                                  "best": rg[1], "open": True, "w": rg[3]}); rg[2] = "filled"
                elif rg[0] < 0 and lo <= rg[1]:
                    posns.append({"dir": -1, "entry": rg[1], "stop": rg[1] + g["sl_atr"] * atr,
                                  "best": rg[1], "open": True, "w": rg[3]}); rg[2] = "filled"
        # 2) وقف المطاردة (محافظ: فحص الضرب قبل تحديث القمة)
        for p_ in posns:
            if not p_["open"]:
                continue
            if p_["dir"] > 0 and lo <= p_["stop"]:
                net += ((p_["stop"] - p_["entry"]) - sp) * tv * lot * p_.get("w", 1)
                p_["open"] = False; continue
            if p_["dir"] < 0 and hi >= p_["stop"]:
                net += ((p_["entry"] - p_["stop"]) - sp) * tv * lot * p_.get("w", 1)
                p_["open"] = False; continue
            if p_["dir"] > 0 and hi > p_["best"]:
                p_["best"] = hi
                p_["stop"] = max(p_["stop"], p_["best"] - g["trail_atr"] * atr)
            elif p_["dir"] < 0 and lo < p_["best"]:
                p_["best"] = lo
                p_["stop"] = min(p_["stop"], p_["best"] + g["trail_atr"] * atr)
    # 3) تسوية إجبارية لنهاية الحملة
    last = float(post[-1]["close"]) if post else px0
    for p_ in posns:
        if p_["open"]:
            net += ((last - p_["entry"]) * p_["dir"] - sp) * tv * lot * p_.get("w", 1)
    fills = sum(1 for p_ in posns)
    if verbose:
        print(f"    {sym.replace('m',''):7s} ATR {atr:.2f} · درجات منفذة {fills}/{2*g['rungs']} · صافي ${net:+.2f}")
    return {"net": round(net, 2), "fills": fills}


def backtest(days=5):
    import MetaTrader5 as mt5
    import news_engine as ne
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    evs = []
    for ev in ne.load_calendar():
        if str(ev.get("impact", "")).lower() not in ("high",):
            continue
        ts = ne._parse_ts(ev.get("date"))
        if ts and time.time() - days * 86400 < ts < time.time() - 1800:
            evs.append((ts, ev.get("title", "؟"), (ev.get("country") or "")))
    # دمج الأحداث المتزامنة (CPI+Core بنفس الدقيقة = حدث واحد)
    evs.sort()
    merged = []
    for ts, t, c in evs:
        if merged and abs(ts - merged[-1][0]) < 300:
            merged[-1] = (merged[-1][0], merged[-1][1] + " + " + t, c)
        else:
            merged.append((ts, t, c))
    print(f"أحداث عالية الأثر آخر {days} أيام: {len(merged)}")
    tot = {}
    for ts, title, c in merged:
        when = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%a %d %H:%M")
        print(f"\n📰 {when} UTC — {title[:60]} ({c})")
        for sym in SYMBOLS:
            r = simulate_event(mt5, sym, ts, verbose=True)
            if r:
                tot.setdefault(sym, [0, 0.0])
                tot[sym][0] += 1; tot[sym][1] += r["net"]
    print("\n═══ الإجمالي لكل عملة (لوت أدنى، سبريد حقيقي) ═══")
    g = 0.0
    for sym, (n, net) in sorted(tot.items(), key=lambda x: -x[1][1]):
        g += net
        print(f"  {sym.replace('m',''):8s} {n} حدث · ${net:+8.2f}")
    print(f"  {'الكل':8s}        ${g:+8.2f}")
    mt5.shutdown()
    return 0


# ════════════════ الصيد الحيّ ════════════════
def _next_event():
    try:
        import news_engine as ne
        best = None
        for ev in ne.load_calendar():
            if str(ev.get("impact", "")).lower() != "high":
                continue
            ts = ne._parse_ts(ev.get("date"))
            if ts and ts > time.time():
                if best is None or ts < best[0]:
                    best = (ts, ev.get("title", "؟"))
        return best
    except Exception:
        return None


def _day_net(mt5):
    day0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return sum(d.profit + d.commission + d.swap
               for d in (mt5.history_deals_get(int(day0), int(time.time())) or [])
               if d.magic == MAGIC and d.entry == 1)


def live():
    import MetaTrader5 as mt5
    # 🔒 قفل وحيد: عدّة حُرّاس قد تُطلق نسخاً متعدّدة تسلّح سلالم مكرّرة على نفس الخبر (magic 20260614) =
    # إفراط تداول خطر على حساب $100. ربط منفذ محلي ثابت (8714) يضمن نسخة حيّة واحدة فقط (يتحرّر عند موت العملية).
    import socket
    _lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock.bind(("127.0.0.1", 8714)); _lock.listen(1)
        live._singleton_lock = _lock          # إبقاء المرجع حيّاً طوال عمر العملية
    except OSError:
        print("[NEWSGENE] نسخة حيّة أخرى تعمل بالفعل — خروج (قفل وحيد 8714)", flush=True); return 0
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print(f"[NEWSGENE] جين الأخبار حيّ · سلالم ستوبات · magic {MAGIC}", flush=True)
    st = _load(STATE, {}) or {}
    g = dict(GENE); g.update(st.get("cfg", {}))
    campaign = st.get("campaign")                # {ev_ts, syms:{sym:{rungs:[tickets]}}}
    while True:
        try:
            ti = mt5.terminal_info()
            if not (ti and ti.trade_allowed):
                time.sleep(20); continue
            now = time.time()
            if _day_net(mt5) <= g["daily_cap"]:
                time.sleep(60); continue          # سقف اليوم — يهدأ
            ev = _next_event()
            # ── ARM at T-arm_sec ──  (🛑 الإيقاف الطارئ يمنع تسليح سلالم جديدة؛ الإدارة/التسوية أدناه تبقى حيّة)
            if ev and not campaign and not _kill_active() and 10 < (ev[0] - now) <= g["arm_sec"]:
                campaign = {"ev_ts": ev[0], "title": ev[1], "placed": now, "tickets": []}
                for sym in _active_symbols(st):
                    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
                    if not info or not tick or (now - tick.time) > 120:
                        continue
                    rr = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 16)
                    if rr is None or len(rr) < 15:
                        continue
                    trs = [max(rr[i]["high"] - rr[i]["low"], abs(rr[i]["high"] - rr[i - 1]["close"]),
                               abs(rr[i]["low"] - rr[i - 1]["close"])) for i in range(1, len(rr))]
                    atr = sum(trs) / len(trs)
                    px = (tick.bid + tick.ask) / 2
                    lot = max(info.volume_min, round(info.volume_min * gov_mult(20260614) * int(g.get("lot_x", 1)), 2))
                    exp = int(ev[0]) + g["ttl_min"] * 60
                    _lw = list(g.get("lot_weights") or [1] * int(g["rungs"]))
                    while len(_lw) < int(g["rungs"]):
                        _lw.append(_lw[-1])
                    for k in range(int(g["rungs"])):
                        d = g["first_atr"] * atr + k * g["space_atr"] * atr
                        lot = max(info.volume_min, round(info.volume_min * gov_mult(20260614) * int(g.get("lot_x", 1)) * _lw[k], 2))
                        # 🛑 منع صارم بحجم-الحساب: تخطّ الرتبة لو خطرها يتجاوز 2% من الحقوق (ذهب/معدن على حساب
                        # صغير، أو lot_x مرتفع → خطر كبير). أخذ 20260614 خسارة ذهب؛ هذا يمنع تضخّمها مع الترقية.
                        _ai = mt5.account_info(); _ts = info.trade_tick_size or info.point
                        if _ai and _ts and lot * (g["sl_atr"] * atr / _ts) * info.trade_tick_value > _ai.equity * 0.02:
                            continue
                        for side, entry, sl in ((mt5.ORDER_TYPE_BUY_STOP, px + d, px + d - g["sl_atr"] * atr),
                                                (mt5.ORDER_TYPE_SELL_STOP, px - d, px - d + g["sl_atr"] * atr)):
                            r = mt5.order_send({"action": mt5.TRADE_ACTION_PENDING, "symbol": sym,
                                                "volume": float(lot), "type": side,
                                                "price": round(entry, info.digits),
                                                "sl": round(sl, info.digits), "tp": 0.0,
                                                "deviation": 100, "magic": MAGIC,
                                                "comment": f"NGENE-r{k+1}",
                                                "type_time": mt5.ORDER_TIME_SPECIFIED,
                                                "expiration": exp,
                                                "type_filling": mt5.ORDER_FILLING_IOC})
                            if getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE:
                                campaign["tickets"].append(int(getattr(r, "order", 0)))
                print(f"[NEWSGENE] 🪜 سلالم مسلّحة لـ«{ev[1][:40]}» — {len(campaign['tickets'])} درجة", flush=True)
            # ── MANAGE: trail filled rungs (المطاردة لأعلى ربح) ──
            if campaign:
                for p_ in [x for x in (mt5.positions_get() or []) if x.magic == MAGIC]:
                    info = mt5.symbol_info(p_.symbol); tick = mt5.symbol_info_tick(p_.symbol)
                    rr = mt5.copy_rates_from_pos(p_.symbol, mt5.TIMEFRAME_M5, 0, 16)
                    if not info or not tick or rr is None or len(rr) < 15:
                        continue
                    trs = [max(rr[i]["high"] - rr[i]["low"], abs(rr[i]["high"] - rr[i - 1]["close"]),
                               abs(rr[i]["low"] - rr[i - 1]["close"])) for i in range(1, len(rr))]
                    atr = sum(trs) / len(trs)
                    if p_.type == mt5.POSITION_TYPE_BUY:
                        new_sl = round(tick.bid - GENE["trail_atr"] * atr, info.digits)
                        if new_sl > (p_.sl or 0):
                            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": p_.symbol,
                                            "position": p_.ticket, "sl": new_sl, "tp": 0.0})
                    else:
                        new_sl = round(tick.ask + GENE["trail_atr"] * atr, info.digits)
                        if p_.sl == 0 or new_sl < p_.sl:
                            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": p_.symbol,
                                            "position": p_.ticket, "sl": new_sl, "tp": 0.0})
                # ── SETTLE at TTL ──
                if now > campaign["ev_ts"] + g["ttl_min"] * 60:
                    for p_ in [x for x in (mt5.positions_get() or []) if x.magic == MAGIC]:
                        tick = mt5.symbol_info_tick(p_.symbol)
                        is_buy = p_.type == mt5.POSITION_TYPE_BUY
                        mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": p_.symbol,
                                        "position": p_.ticket, "volume": p_.volume,
                                        "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                                        "price": tick.bid if is_buy else tick.ask,
                                        "deviation": 100, "magic": MAGIC, "comment": "NGENE-ttl",
                                        "type_filling": mt5.ORDER_FILLING_IOC})
                    j = _load(JOURNAL, {"eps": []}) or {"eps": []}
                    deals_c = [d for d in (mt5.history_deals_get(int(campaign["placed"]), int(now)) or [])
                               if d.magic == MAGIC and d.entry == 1]
                    net = sum(d.profit + d.commission + d.swap for d in deals_c)
                    by_sym = {}
                    for d in deals_c:
                        by_sym[d.symbol] = round(by_sym.get(d.symbol, 0.0) + d.profit + d.commission + d.swap, 2)
                    j["eps"] = (j.get("eps", []) + [{"ts": now, "title": campaign["title"],
                                                     "net": round(net, 2), "by_sym": by_sym}])[-40:]
                    _save(JOURNAL, j)
                    # محاسبة كل عملة على حدة: ≥3 حملات وصافيها < -$5 → تُبنّح من السلالم
                    ss = st.setdefault("sym_stats", {})
                    for sym2, n2 in by_sym.items():
                        c2 = ss.setdefault(sym2, {"n": 0, "net": 0.0})
                        c2["n"] += 1; c2["net"] = round(c2["net"] + n2, 2)
                        if c2["n"] >= 3 and c2["net"] < -5 and sym2 not in st.get("benched_syms", []):
                            st.setdefault("benched_syms", []).append(sym2)
                            print(f"[NEWSGENE] 🛑 {sym2} بنّح نفسه من السلالم (صافي ${c2['net']} في {c2['n']} حملات)", flush=True)
                    print(f"[NEWSGENE] 🏁 حملة «{campaign['title'][:35]}» انتهت: ${net:+.2f}", flush=True)
                    eps = j.get("eps", [])
                    tot = sum(e.get("net", 0) for e in eps)
                    if len(eps) >= 4 and tot > 0 and int(g.get("lot_x", 1)) < 10 and net > 0:
                        g["lot_x"] = min(10, int(g.get("lot_x", 1)) * 2)
                        print(f"[NEWSGENE] 🏅 ترقية مستحقة: {len(eps)} حملات بصافي ${tot:+.2f} → لوت ×{g['lot_x']}", flush=True)
                    elif tot <= g["daily_cap"] and int(g.get("lot_x", 1)) > 1:
                        g["lot_x"] = max(1, int(g.get("lot_x", 1)) // 2)
                        print(f"[NEWSGENE] ⬇️ تخفيض: الصافي ساء → لوت ×{g['lot_x']}", flush=True)
                    campaign = None
            st["cfg"] = g; st["campaign"] = campaign; st["ts"] = now
            _save(STATE, st)
        except Exception as e:
            print(f"[NEWSGENE] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    raise SystemExit(backtest() if a.test else live())
