"""war_room.py — 🎖️ FRIDAY WAR ROOM: غرفة عمليات تداول سينمائية تدمج كل النظام في شاشة واحدة.

http://127.0.0.1:8888

يدمج: شارت شموع حيّ (canvas) + مستويات المناطق (zone_memory) + خط مركزنا وربحه الحيّ ·
«مكدّس القرار» لكل رمز (ماكرو · بوّابة الجين · أخبار · ترابط · دلتا · منطقة · بطولة · مخاطر →
إشارة مُركّبة) · شريط التدفّق الحيّ · تنفيذ بضغطة (شراء/بيع/إغلاق) — محكوم: DEMO فقط + فحص
طوارئ المخاطر + حدّ لوت. كل البيانات من محرّكاتنا الحيّة. للقراءة + تنفيذ يبدؤه المستخدم. Windowless.

التشغيل:  pythonw war_room.py
"""
from __future__ import annotations
import json, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
V2 = MT5DIR / "r_native_v2" / "data"
PORT = 8888
MAGIC_WR = 20260615          # أوامر غرفة العمليات (= MCP اليدوي-الذكي)
MAX_LOT_UI = 0.50            # سقف أمان للتنفيذ من الواجهة
_LOCK = threading.Lock()
for p in (str(MT5DIR), str(MT5DIR / "r_native_v2")):
    if p not in sys.path:
        sys.path.insert(0, p)
import MetaTrader5 as mt5
_TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
       "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
NAMES = {0: "يدوي", 20260608: "multi", 20260611: "صياد", 20260612: "بطولة", 20260613: "هجائن",
         20260614: "أخبار", 20260615: "غرفة", 99782: "ذهب-FVG", 99792: "btc"}


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _init():
    try:
        return mt5.initialize() or mt5.initialize()
    except Exception:
        return False


def _is_demo():
    try:
        a = mt5.account_info()
        if not a:
            return False
        if a.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
            return True
        srv = (a.server or "").lower()
        return ("trial" in srv or "demo" in srv) and "real" not in srv
    except Exception:
        return False


def _emergency():
    d = _load(RN / "risk_register.json", {}) or {}
    return bool(d.get("emergency")) and time.time() - float(d.get("ts", 0)) < 300


def _session():
    try:
        from indicators import session as S
        return S.classify().name
    except Exception:
        return "?"


def _roster():
    """كل الأبطال دائماً (لا يفرغ في الجلسة المغلقة): أصحاب المجموعات + الجينات العامة + افتراضي.
    حالة الجلسة تظهر صادقةً في مكدّس القرار، لا بإخفاء الرمز."""
    import glob
    syms = set(["XAUUSDm", "BTCUSDm", "USDJPYm"])
    for f in glob.glob(str(V2 / "genomes" / "*.json")):
        syms.add(Path(f).stem)
    for f in glob.glob(str(V2 / "genomes" / "*" / "stable.json")):
        st = _load(f, {}) or {}
        if st.get("specialists"):
            syms.add(st.get("symbol") or Path(f).parent.name)
    return sorted(syms)


def _atr(rates, n=14):
    if rates is None or len(rates) < n + 1:
        return 0.0
    tr = [max(rates[i]["high"] - rates[i]["low"], abs(rates[i]["high"] - rates[i - 1]["close"]),
              abs(rates[i]["low"] - rates[i - 1]["close"])) for i in range(1, len(rates))]
    return sum(tr[-n:]) / n


def _indicators(sym, tf="M15"):
    """كل المؤشرات (33) لهذا الرمز: تصويت حيّ + وزن متعلّم + دقّة مقيسة — مرتّبة بالأهمية."""
    out = []
    try:
        import chart_read as cr
        d = cr.read_local(mt5, sym, tf) or {}
        votes = d.get("votes", {}) or {}; weights = d.get("weights", {}) or {}
        acc = (_load(V2 / f"indicator_accuracy_{sym}.json", {}) or {}).get("accuracy", {})
        for k in votes:
            hr = (acc.get(k, {}) or {}).get("hit_rate")
            out.append({"k": k, "dir": int(votes.get(k, 0)), "w": round(float(weights.get(k, 0)), 2),
                        "hit": round(hr * 100, 1) if hr is not None else None})
        out.sort(key=lambda x: -x["w"])
    except Exception:
        pass
    return out


def _decision_stack(sym):
    """مكدّس القرار: ماذا تقول كل طبقة الآن لهذا الرمز → إشارة مُركّبة."""
    layers = []
    score = 0.0
    # 1) ماكرو (chart_read)
    try:
        import chart_read as cr
        import multi_trader as mt
        d, conf = mt._macro(cr, mt5, sym)
        layers.append({"k": "ماكرو M15+H1", "dir": d, "v": f"ثقة {conf:.2f}"})
        score += d * conf
    except Exception:
        layers.append({"k": "ماكرو", "dir": 0, "v": "—"})
    # 2) genome gate present?
    g = _load(V2 / f"genomes/{sym}.json", {}) or {}
    cfg = g.get("config") or {}
    sess = _session()
    stb = _load(V2 / f"genomes/{sym}/stable.json", {}) or {}
    spec = next((s for s in stb.get("specialists", []) if s.get("session") == sess), None)
    has_edge = bool(spec) or bool(cfg)
    layers.append({"k": "بوّابة الجين", "dir": 1 if has_edge else 0,
                   "v": (f"متخصّص {sess} PF{spec.get('pf')}" if spec else (f"عام PF{(g.get('oos') or {}).get('pf','?')}" if cfg else "لا حافة هذه الجلسة"))})
    # 3) news
    ns = (_load(RN / "agents" / "news_signals.json", {}) or {}).get("symbols", {}).get(sym, {})
    nd = ns.get("news_dir", 0) or 0
    layers.append({"k": "📰 أخبار", "dir": nd, "v": ("فيتو ⛔" if ns.get("veto") else (ns.get("reason", "—") or "—")[:30])})
    score += nd * 0.5
    # 4) intermarket
    xs = (_load(V2 / "intermarket_signals.json", {}) or {}).get("signals", {}).get(sym, {})
    xd = xs.get("dir", 0) or 0
    layers.append({"k": "🔗 ترابط", "dir": xd, "v": (xs.get("why", "—") or "—")[:30]})
    score += xd * 0.4
    # 5) delta
    db = (_load(RN / "delta_state.json", {}) or {}).get(sym, {}).get("bias")
    dd = 1 if (db or 0) > 12 else -1 if (db or 0) < -12 else 0
    layers.append({"k": "📊 دلتا", "dir": dd, "v": (f"ميل {db}" if db is not None else "—") + " (سياق)"})
    # 6) zone
    zm = (_load(RN / "zone_memory.json", {}) or {}).get(sym, {}).get("zones", [])
    try:
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 20)
        mid = float(r[-1]["close"]); za = _atr(r)
        znear = next((z for z in zm if z.get("touches", 0) >= 3 and abs(z["px"] - mid) <= 0.5 * za), None)
        if znear:
            zdir = 1 if znear["net"] > 2 else -1 if znear["net"] < -2 else 0
            layers.append({"k": "🗺️ منطقة", "dir": zdir, "v": f"@{znear['px']} ${znear['net']:+.0f}/{znear['touches']}"})
            score += zdir * 0.5
        else:
            layers.append({"k": "🗺️ منطقة", "dir": 0, "v": "بعيد عن منطقة مثبتة"})
    except Exception:
        layers.append({"k": "🗺️ منطقة", "dir": 0, "v": "—"})
    # 7) tournament confirmed
    tc = (_load(RN / "tournament_confirmed.json", {}) or {}).get(sym, {})
    td = tc.get("dir", 0) or 0
    layers.append({"k": "🏆 بطولة", "dir": td, "v": ("قيمة مؤكَّدة" if td else "قيد المبارزة")})
    score += td * 0.6
    # 8) regime (Hurst) — بوّابة النظام: ترند يعزّز الزخم · ارتداد يعاكسه
    try:
        import quant_gates as qg
        r2 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 120)
        reg, H = qg.hurst_regime([float(x["close"]) for x in r2])
        layers.append({"k": "🌀 النظام", "dir": 0,
                       "v": {"trend": f"ترند H{H} (يعزّز الزخم)", "meanrev": f"ارتداد H{H} (يعاكس)",
                             "random": f"عشوائي H{H}"}.get(reg, reg)})
        # in a trending regime, amplify an already-directional score; in mean-rev, damp it
        if reg == "trend":
            score *= 1.25
        elif reg == "meanrev":
            score *= 0.7
    except Exception:
        pass
    # 8b) MACRO (مؤسسي): سياق عبر-الأصول من macro_feed
    ms = _load(RN / "macro_state.json", {}) or {}
    mb = (ms.get("bias") or {}).get(sym)
    if mb is not None:
        layers.append({"k": "🌐 ماكرو", "dir": 1 if mb > 0.2 else -1 if mb < -0.2 else 0,
                       "v": f"{ms.get('regime','?')} · ميل {mb}"})
        score += mb * 0.5
    # 9) risk
    rr = _load(RN / "risk_register.json", {}) or {}
    layers.append({"k": "🛡️ مخاطر", "dir": 0, "v": f"{rr.get('overall','?')} · لوت×{rr.get('lot_mult',1)}"})
    final = 1 if score > 0.6 else -1 if score < -0.6 else 0
    return {"layers": layers, "score": round(score, 2), "final": final}


def state():
    with _LOCK:
        if not _init():
            return {"ok": False, "error": "MT5 off"}
        a = mt5.account_info()
        pos = mt5.positions_get() or []
        bybot = {}
        bysym = {}
        for p in pos:
            b = bybot.setdefault(NAMES.get(p.magic, str(p.magic)), [0, 0.0]); b[0] += 1; b[1] += p.profit
            m = bysym.setdefault(p.symbol, {"n": 0, "profit": 0.0, "side": 0, "lot": 0.0})
            m["n"] += 1; m["profit"] += p.profit; m["side"] += (1 if p.type == 0 else -1); m["lot"] += p.volume
        truth = _load(RN / "pnl_scoreboard.json", {}) or {}
        rr = _load(RN / "risk_register.json", {}) or {}
        wd = _load(RN / "watchdog_status.json", {}) or {}
        roster = _roster()
        syms = []
        for s in roster:
            t = mt5.symbol_info_tick(s)
            m = bysym.get(s)
            syms.append({"sym": s, "bid": getattr(t, "bid", None),
                         "pos": ({"side": "buy" if m["side"] > 0 else "sell" if m["side"] < 0 else "mix",
                                  "profit": round(m["profit"], 2), "lot": round(m["lot"], 2)} if m else None)})
        return {"ok": True, "ts": time.time(), "session": _session(),
                "equity": round(a.equity, 2) if a else 0, "balance": round(a.balance, 2) if a else 0,
                "floating": round(a.equity - a.balance, 2) if a else 0, "demo": _is_demo(),
                "today": truth.get("today_net"), "d7": truth.get("d7_net"), "verdict": truth.get("verdict"),
                "risk": {"overall": rr.get("overall"), "pct": rr.get("risk_pct"),
                         "lot_mult": rr.get("lot_mult"), "emergency": rr.get("emergency")},
                "engines": f"{wd.get('n_alive','?')}/{wd.get('n_total','?')}",
                "bots": [{"name": k, "n": v[0], "profit": round(v[1], 2)} for k, v in sorted(bybot.items(), key=lambda x: x[1][1])],
                "syms": syms}


def _ema(vals, n):
    if not vals:
        return []
    k = 2 / (n + 1); out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return [round(x, 6) for x in out]


def _swings(bars, w=3):
    """قمم/قيعان مؤكّدة (هيكل السوق) — نقاط يضعها المحترفون."""
    hi, lo = [], []
    for i in range(w, len(bars) - w):
        seg = bars[i - w:i + w + 1]
        if bars[i]["h"] == max(x["h"] for x in seg):
            hi.append({"i": i, "px": bars[i]["h"]})
        if bars[i]["l"] == min(x["l"] for x in seg):
            lo.append({"i": i, "px": bars[i]["l"]})
    return {"highs": hi[-6:], "lows": lo[-6:]}


def chart(sym, tf):
    with _LOCK:
        if not _init():
            return {"ok": False}
        mt5.symbol_select(sym, True)
        r = mt5.copy_rates_from_pos(sym, _TF.get(tf, mt5.TIMEFRAME_M15), 0, 130)
        if r is None or len(r) == 0:
            return {"ok": False}
        bars = [{"t": int(x["time"]), "o": float(x["open"]), "h": float(x["high"]),
                 "l": float(x["low"]), "c": float(x["close"])} for x in r]
        za = _atr(r)
        closes = [b["c"] for b in bars]
        zm = (_load(RN / "zone_memory.json", {}) or {}).get(sym, {}).get("zones", [])
        lo = min(b["l"] for b in bars); hi = max(b["h"] for b in bars)
        # المناطق كمربعات: نطاق ±0.25 ATR حول مركز المنطقة (Supply/Demand band)
        band = za * 0.25 if za > 0 else (hi - lo) * 0.01
        zones = [{"px": z["px"], "band": round(band, 6), "net": z.get("net", 0),
                  "touches": z.get("touches", 0)}
                 for z in zm if lo - band <= z["px"] <= hi + band and z.get("touches", 0) >= 1][:12]
        t = mt5.symbol_info_tick(sym)
        info = mt5.symbol_info(sym)
        digits = info.digits if info else 2
        # المستويات المرجعية الموضوعية ($1000 chart): قمة/قاع الأمس والأسبوع + افتتاح اليوم/الأسبوع
        levels = {}
        try:
            dg = digits
            d1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 2)
            w1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_W1, 0, 2)
            if d1 is not None and len(d1) >= 2:
                levels["pdh"] = round(float(d1[-2]["high"]), dg)
                levels["pdl"] = round(float(d1[-2]["low"]), dg)
                levels["dopen"] = round(float(d1[-1]["open"]), dg)
            if w1 is not None and len(w1) >= 2:
                levels["pwh"] = round(float(w1[-2]["high"]), dg)
                levels["pwl"] = round(float(w1[-2]["low"]), dg)
                levels["wopen"] = round(float(w1[-1]["open"]), dg)
        except Exception:
            pass
        pos = None
        for p in (mt5.positions_get(symbol=sym) or []):
            pos = {"side": "buy" if p.type == 0 else "sell", "entry": p.price_open,
                   "profit": round(p.profit, 2), "sl": p.sl, "tp": p.tp}
            break
        _PT = {2: "BUY-LIMIT", 3: "SELL-LIMIT", 4: "BUY-STOP", 5: "SELL-STOP"}
        pending = [{"ticket": o.ticket, "price": o.price_open, "type": _PT.get(o.type, str(o.type)),
                    "vol": o.volume_current, "buy": o.type in (2, 4),
                    "mine": o.magic == MAGIC_WR} for o in (mt5.orders_get(symbol=sym) or [])]
        return {"ok": True, "sym": sym, "tf": tf, "bars": bars, "zones": zones,
                "ema20": _ema(closes, 20), "ema50": _ema(closes, 50),
                "swings": _swings(bars), "atr": round(za, 6),
                "bid": getattr(t, "bid", None), "ask": getattr(t, "ask", None),
                "pos": pos, "pending": pending, "decision": _decision_stack(sym),
                "indicators": _indicators(sym, tf), "levels": levels, "digits": digits}


# أوضاع التنفيذ: سكالب (دخول/خروج سريع) · سوينق (واسع يركض) · عادي  → (SL×ATR, TP×ATR, TF)
MODES = {"scalp": (0.6, 1.2, mt5.TIMEFRAME_M1), "swing": (2.5, 6.0, mt5.TIMEFRAME_M15),
         "normal": (2.0, 3.0, mt5.TIMEFRAME_M15)}


def _vol(i, volume):
    return max(i.volume_min, min(MAX_LOT_UI, round(round(float(volume) / i.volume_step) * i.volume_step, 2)))


def bookmap(sym, minutes=40, prows=64, tcols=90):
    """🌡️ خريطة حرارية بأسلوب Bookmap من كثافة التيكات (السعر×الزمن).
    ملاحظة صادقة: البروكر لا يوفّر عمق السوق (DOM)، فهذه ليست أوامر كامنة — بل نشاط/سيولة
    متحقّقة (أين قضى السعر وقتاً وتداولاً) = عُقد حجم تكشف الدعم/المقاومة. + سعر حيّ + مناطقنا."""
    with _LOCK:
        if not _init():
            return {"ok": False}
        mt5.symbol_select(sym, True)
        now = int(time.time())
        ticks = mt5.copy_ticks_from(sym, now - minutes * 60, 200000, mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) < 20:
            return {"ok": False}
        mids = [(float(t["bid"]) + float(t["ask"])) / 2 for t in ticks if t["bid"] and t["ask"]]
        times = [int(t["time"]) for t in ticks if t["bid"] and t["ask"]]
        if not mids:
            return {"ok": False}
        lo, hi = min(mids), max(mids)
        t0, t1 = times[0], times[-1]
        if hi <= lo or t1 <= t0:
            return {"ok": False}
        grid = [[0] * tcols for _ in range(prows)]
        for m, tt in zip(mids, times):
            pr = min(prows - 1, int((hi - m) / (hi - lo) * (prows - 1)))   # 0=أعلى سعر
            tc = min(tcols - 1, int((tt - t0) / (t1 - t0) * (tcols - 1)))
            grid[pr][tc] += 1
        mx = max((max(row) for row in grid), default=1) or 1
        info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
        # عُقد الحجم: أكثر مستويات السعر نشاطاً (مجموع الصف)
        rowsum = [(sum(grid[r]), hi - (hi - lo) * r / (prows - 1)) for r in range(prows)]
        nodes = sorted(rowsum, key=lambda x: -x[0])[:5]
        zm = (_load(RN / "zone_memory.json", {}) or {}).get(sym, {}).get("zones", [])
        zones = [{"px": z["px"], "net": z.get("net", 0)} for z in zm
                 if lo <= z["px"] <= hi and z.get("touches", 0) >= 2][:8]
        # قرار شراء/بيع (نفس مكدّس القرار) + ميل تدفّق التيكات (شراء ضد بيع)
        ds = _decision_stack(sym)
        prev = None; up = dn = 0
        for m in mids:
            if prev is not None:
                if m > prev: up += 1
                elif m < prev: dn += 1
            prev = m
        flow = round((up - dn) / max(1, up + dn) * 100)      # +100 ضغط شراء · -100 بيع
        # مناطق الاهتمام = عُقد الحجم القوية (أعلى نشاط = مغناطيس سيولة)
        poi = [{"px": round(p, info.digits), "v": v, "kind": "above" if p > (tick.bid or p) else "below"}
               for v, p in nodes]
        return {"ok": True, "sym": sym, "lo": round(lo, info.digits), "hi": round(hi, info.digits),
                "grid": grid, "max": mx, "price": getattr(tick, "bid", None),
                "minutes": minutes, "nodes": [{"px": round(p, info.digits), "v": v} for v, p in nodes],
                "zones": zones, "poi": poi, "flow": flow,
                "verdict": ds["final"], "score": ds["score"],
                "verdict_txt": ("شراء" if ds["final"] > 0 else "بيع" if ds["final"] < 0 else "محايد")}


def dom_ladder(sym, minutes=5, levels=40):
    """سلّم DOM حيّ بنفس شكل طرفية إكسنس — مُعاد بناؤه من تدفّق التيكات (ضغط شراء/بيع لكل مستوى).
    صادق: إكسنس لا يعرض كتاب الأوامر الحقيقي عبر API (market_book مغلق)، فهذا ضغط متحقّق
    (upticks=شراء، downticks=بيع) مُجمّع على مستويات السعر حول السعر الحالي."""
    with _LOCK:
        if not _init():
            return {"ok": False}
        mt5.symbol_select(sym, True)
        now = int(time.time())
        ticks = mt5.copy_ticks_from(sym, now - minutes * 60, 100000, mt5.COPY_TICKS_ALL)
        info = mt5.symbol_info(sym); tk = mt5.symbol_info_tick(sym)
        if ticks is None or len(ticks) < 10 or not info or not tk:
            return {"ok": False}
        mids = [(float(t["bid"]) + float(t["ask"])) / 2 for t in ticks if t["bid"] and t["ask"]]
        lo, hi = min(mids), max(mids)
        if hi <= lo:
            return {"ok": False}
        step = (hi - lo) / levels
        lad = {}
        prev = None
        for m in mids:
            lv = round((m - lo) / step)
            px = round(lo + lv * step, info.digits)
            cell = lad.setdefault(px, {"buy": 0, "sell": 0})
            if prev is not None:
                if m > prev:
                    cell["buy"] += 1
                elif m < prev:
                    cell["sell"] += 1
            prev = m
        rows = sorted(lad.items(), key=lambda x: -x[0])      # أعلى سعر فوق (مثل الطرفية)
        mx = max((v["buy"] + v["sell"] for _, v in rows), default=1) or 1
        cur = round((tk.bid + tk.ask) / 2, info.digits)
        return {"ok": True, "sym": sym, "cur": cur, "bid": tk.bid, "ask": tk.ask, "max": mx,
                "rows": [{"px": px, "buy": v["buy"], "sell": v["sell"]} for px, v in rows]}


def heatmap():
    """🔥 شارت حراري: كل رموز نظامنا ملوّنة بـ(تغيّر اليوم% · إشارة القرار · ميل الماكرو · مركزنا)."""
    with _LOCK:
        if not _init():
            return {"ok": False}
        ms = _load(RN / "macro_state.json", {}) or {}
        mbias = ms.get("bias", {}) or {}
        pos = {}
        for p in (mt5.positions_get() or []):
            m = pos.setdefault(p.symbol, 0.0); pos[p.symbol] = m + p.profit
        cells = []
        for sym in _roster():
            mt5.symbol_select(sym, True)
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 2)
            chg = 0.0
            if r is not None and len(r) >= 2 and r[-2]["close"]:
                chg = round((r[-1]["close"] / r[-2]["close"] - 1) * 100, 2)
            elif r is not None and len(r) >= 1 and r[-1]["open"]:
                chg = round((r[-1]["close"] / r[-1]["open"] - 1) * 100, 2)
            ds = _decision_stack(sym)
            cells.append({"sym": sym, "chg": chg, "signal": ds["final"], "score": ds["score"],
                          "macro": mbias.get(sym, 0), "pos": round(pos.get(sym, 0.0), 2)})
        # مصفوفة الارتباط (من intermarket إن توفّرت)
        im = _load(V2 / "intermarket_signals.json", {}) or {}
        mi = _load(RN / "market_internals.json", {}) or {}
        return {"ok": True, "ts": time.time(), "regime": ms.get("regime"),
                "headline": ms.get("headline"), "cells": cells,
                "pairs": (im.get("pairs", []) or [])[:14],
                "leaders": mi.get("leaders", [])[:6], "laggards": mi.get("laggards", [])[:6]}


def place(sym, side, volume, mode="scalp"):
    with _LOCK:
        if not _init():
            return {"ok": False, "error": "MT5 off"}
        if not _is_demo():
            return {"ok": False, "error": "مرفوض: الحساب ليس تجريبياً"}
        if _emergency():
            return {"ok": False, "error": "مرفوض: مدير المخاطر أعلن طوارئ"}
        if side not in ("buy", "sell"):
            return {"ok": False, "error": "side?"}
        mt5.symbol_select(sym, True)
        i = mt5.symbol_info(sym); t = mt5.symbol_info_tick(sym)
        if not i or not t:
            return {"ok": False, "error": "symbol?"}
        slm, tpm, tf = MODES.get(mode, MODES["scalp"])
        vol = _vol(i, volume)
        otype = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
        price = t.ask if side == "buy" else t.bid
        atr = _atr(mt5.copy_rates_from_pos(sym, tf, 0, 20)) or (i.point * 200)
        sl = (price - slm * atr) if side == "buy" else (price + slm * atr)
        tp = (price + tpm * atr) if side == "buy" else (price - tpm * atr)
        r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(vol),
                            "type": otype, "price": float(price), "sl": round(sl, i.digits),
                            "tp": round(tp, i.digits), "deviation": 50, "magic": MAGIC_WR,
                            "comment": f"WR_{mode}"[:28], "type_filling": mt5.ORDER_FILLING_IOC})
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            return {"ok": True, "ticket": r.order, "vol": vol, "price": price, "mode": mode}
        return {"ok": False, "error": f"retcode={r.retcode if r else '?'}"}


def place_pending(sym, otype, price, volume, mode="swing"):
    """أمر معلّق عند سعر محدّد (من النقر على الشارت). يكتشف Limit/Stop تلقائياً حسب موقع السعر."""
    with _LOCK:
        if not _init():
            return {"ok": False, "error": "MT5 off"}
        if not _is_demo():
            return {"ok": False, "error": "مرفوض: ليس تجريبياً"}
        if _emergency():
            return {"ok": False, "error": "مرفوض: طوارئ"}
        mt5.symbol_select(sym, True)
        i = mt5.symbol_info(sym); t = mt5.symbol_info_tick(sym)
        if not i or not t:
            return {"ok": False, "error": "symbol?"}
        px = round(float(price), i.digits)
        side = "buy" if otype.startswith("buy") else "sell"
        cur = t.ask if side == "buy" else t.bid
        # اكتشاف النوع: شراء تحت السوق=LIMIT فوقه=STOP · بيع فوق=LIMIT تحته=STOP
        if side == "buy":
            ot = mt5.ORDER_TYPE_BUY_LIMIT if px < cur else mt5.ORDER_TYPE_BUY_STOP
        else:
            ot = mt5.ORDER_TYPE_SELL_LIMIT if px > cur else mt5.ORDER_TYPE_SELL_STOP
        slm, tpm, tf = MODES.get(mode, MODES["swing"])
        atr = _atr(mt5.copy_rates_from_pos(sym, tf, 0, 20)) or (i.point * 200)
        sl = (px - slm * atr) if side == "buy" else (px + slm * atr)
        tp = (px + tpm * atr) if side == "buy" else (px - tpm * atr)
        vol = _vol(i, volume)
        r = mt5.order_send({"action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": float(vol),
                            "type": ot, "price": px, "sl": round(sl, i.digits), "tp": round(tp, i.digits),
                            "deviation": 50, "magic": MAGIC_WR, "comment": f"WR_pend_{mode}"[:28],
                            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC})
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            return {"ok": True, "ticket": r.order, "price": px, "side": side, "vol": vol}
        return {"ok": False, "error": f"retcode={r.retcode if r else '?'} {getattr(r,'comment','')}"}


def cancel(ticket):
    with _LOCK:
        if not _init():
            return {"ok": False, "error": "MT5 off"}
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)})
        return {"ok": bool(r and r.retcode == mt5.TRADE_RETCODE_DONE), "ticket": int(ticket)}


def close_sym(sym):
    with _LOCK:
        if not _init():
            return {"ok": False, "error": "MT5 off"}
        n = 0
        for p in (mt5.positions_get(symbol=sym) or []):
            t = mt5.symbol_info_tick(p.symbol); ib = p.type == 0
            r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": p.symbol,
                                "volume": p.volume, "type": mt5.ORDER_TYPE_SELL if ib else mt5.ORDER_TYPE_BUY,
                                "price": t.bid if ib else t.ask, "deviation": 50, "magic": p.magic,
                                "comment": "WAR_ROOM close", "type_filling": mt5.ORDER_FILLING_IOC})
            if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                n += 1
        return {"ok": True, "closed": n}


HTML = r"""<!doctype html><html lang=ar dir=rtl><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>🎖️ FRIDAY WAR ROOM</title><style>
*{box-sizing:border-box;margin:0;font-family:'Segoe UI',Tahoma,sans-serif}
:root{--g:#3fe07a;--r:#ff5b52;--gold:#e8c46a;--bl:#7aa2ff;--bg:#05070e}
body{background:radial-gradient(1400px 800px at 50% -15%,#0e1730,#05070e 60%);color:#e6edf3;height:100vh;overflow:hidden}
.hud{display:flex;align-items:center;gap:14px;padding:8px 16px;background:linear-gradient(180deg,#0c1428ee,#070b16cc);border-bottom:1px solid #1f2c4a;flex-wrap:wrap}
.logo{font-size:17px;font-weight:900;color:var(--gold);text-shadow:0 0 20px #e8c46a66;letter-spacing:1px}
.orb{display:flex;flex-direction:column;align-items:center;min-width:62px}
.orb .v{font-size:16px;font-weight:900}.orb .l{font-size:8.5px;color:#7d8590}
.pos{color:var(--g)}.neg{color:var(--r)}.neu{color:#9fb0c3}
.gauge{position:relative;width:54px;height:54px;border-radius:50%;display:grid;place-items:center;font-size:10px;font-weight:900}
.gauge::before{content:'';position:absolute;inset:4px;border-radius:50%;background:var(--bg)}.gauge span{position:relative;z-index:1;text-align:center}
.pulse{animation:pl 1.4s infinite}@keyframes pl{0%,100%{filter:brightness(1)}50%{filter:brightness(1.5)}}
.wrap{display:grid;grid-template-columns:210px 1fr 290px;height:calc(100vh - 60px)}
.col{overflow-y:auto;padding:10px}
.col::-webkit-scrollbar{width:6px}.col::-webkit-scrollbar-thumb{background:#1f2c4a;border-radius:3px}
.srow{display:flex;justify-content:space-between;align-items:center;padding:8px 10px;margin-bottom:5px;border-radius:9px;background:#0d1526;border:1px solid #1a2740;cursor:pointer;transition:.2s}
.srow:hover{border-color:#e8c46a88}.srow.sel{border-color:var(--gold);background:#16213c;box-shadow:0 0 16px #e8c46a33}
.srow .s{font-weight:800;font-size:13px}.srow .p{font-size:11px;font-weight:800}
.arrow{font-size:10px}
.center{display:flex;flex-direction:column;padding:8px}
.ctop{display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap}
.csym{font-size:20px;font-weight:900;color:var(--gold)}
.tf{display:flex;gap:3px}.tf button{background:#0d1526;border:1px solid #1a2740;color:#9fb0c3;border-radius:6px;padding:3px 9px;font-size:11px;cursor:pointer}
.tf button.on{background:#16213c;border-color:var(--gold);color:var(--gold)}
#chart{flex:1;width:100%;display:block;border-radius:12px;background:#080d18;border:1px solid #16213c;cursor:crosshair}
.exec{display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap}
.exec input{width:64px;background:#0d1526;border:1px solid #1a2740;color:#e6edf3;border-radius:7px;padding:7px;font-size:13px;text-align:center}
.modes{display:flex;gap:4px}
.modes .m{background:#0d1526;border:1px solid #1a2740;color:#9fb0c3;border-radius:7px;padding:6px 11px;font-size:12px;font-weight:800;cursor:pointer}
.modes .m.on{background:#16213c;border-color:var(--gold);color:var(--gold);box-shadow:0 0 12px #e8c46a33}
.pophint{position:absolute;background:#0c1424;border:1px solid var(--gold);border-radius:10px;padding:8px;display:none;z-index:20;box-shadow:0 6px 24px #000a}
.pophint button{display:block;width:100%;margin:2px 0;border:none;border-radius:6px;padding:6px 12px;font-size:11px;font-weight:800;cursor:pointer}
.pophint .pb{background:#1f7a44;color:#caffd9}.pophint .ps{background:#9e2c28;color:#ffd2cf}
.pophint .px{font-size:10px;color:#7d8590;text-align:center;margin-bottom:4px}
.btn{border:none;border-radius:9px;padding:9px 18px;font-size:13px;font-weight:900;cursor:pointer;transition:.15s}
.btn:active{transform:scale(.95)}
.buy{background:linear-gradient(180deg,#1f7a44,#11502b);color:#caffd9;border:1px solid #2ea04388}
.sell{background:linear-gradient(180deg,#9e2c28,#5e1714);color:#ffd2cf;border:1px solid #ff5b5288}
.close{background:#1a2740;color:#cdd6f4;border:1px solid #2c3c66}
.msg{font-size:11px;color:#8fa3bd;margin-right:auto}
.panel{background:#0c1424;border:1px solid #1a2740;border-radius:12px;padding:10px;margin-bottom:10px}
.panel h3{font-size:12px;color:var(--bl);margin-bottom:8px;text-align:center}
.lyr{display:flex;justify-content:space-between;align-items:center;padding:6px 8px;margin:3px 0;border-radius:7px;background:#0d1526;font-size:11px;border-right:3px solid #2c3c66}
.lyr.up{border-right-color:var(--g)}.lyr.dn{border-right-color:var(--r)}
.lyr .k{color:#cdd6f4;font-weight:700}.lyr .v{color:#7d8590;font-size:10px;max-width:130px;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ind{display:flex;align-items:center;gap:6px;padding:3px 5px;font-size:10px}
.ind .nm{width:64px;color:#cdd6f4}
.ind .tr{flex:1;height:7px;background:#0d1526;border-radius:4px;overflow:hidden}
.ind .tr i{display:block;height:100%;border-radius:4px}
.ind .hit{width:34px;text-align:left;color:#7d8590}
.dirico{font-weight:900;margin-left:5px}
.final{text-align:center;padding:12px;border-radius:11px;font-size:18px;font-weight:900;margin-top:6px}
.final.up{background:#11301d;color:var(--g);box-shadow:0 0 22px #2ea04344}
.final.dn{background:#301414;color:var(--r);box-shadow:0 0 22px #f8514944}
.final.flat{background:#16213c;color:#9fb0c3}
.bot{display:flex;justify-content:space-between;font-size:11px;padding:3px 6px;border-bottom:1px solid #131d33}
.tape{font-size:10px;color:#8fa3bd;max-height:90px;overflow:hidden}
.tape div{padding:1px 0;border-bottom:1px solid #0e1626}
.foot{position:fixed;bottom:4px;left:0;right:0;text-align:center;font-size:9px;color:#3d4a63;pointer-events:none}
.nav{height:44px;display:flex;align-items:center;gap:8px;padding:0 16px;background:linear-gradient(180deg,#0a1124,#070b16);border-bottom:1px solid #1f2c4a}
.nav .brand{font-size:14px;font-weight:900;color:var(--gold);letter-spacing:1px}
.nav button{background:#0d1526;border:1px solid #243250;color:#9fb0c3;border-radius:10px;padding:7px 16px;font-size:13px;font-weight:800;cursor:pointer;transition:.2s}
.nav button:hover{border-color:#e8c46a88;color:var(--gold)}
.nav button.on{background:linear-gradient(180deg,#1c2a4d,#131d38);border-color:var(--gold);color:var(--gold);box-shadow:0 0 16px #e8c46a33}
.nav .url{margin-right:auto;font-size:11px;color:#3d4a63}
.tab{display:none}.tab.on{display:block}
iframe.tab{width:100%;height:calc(100vh - 44px);border:0}
.wrap{display:grid;grid-template-columns:210px 1fr 290px;height:calc(100vh - 102px)}
</style></head><body>
<div class=nav>
 <span class=brand>FRIDAY</span>
 <button class=on data-tab=war>🎖️ غرفة العمليات</button>
 <button data-tab=heat>🔥 الحراري</button>
 <button data-tab=arena>⚔️ الساحة</button>
 <button data-tab=flow>📡 التدفّق</button>
 <button data-tab=tape>📼 الشريط</button>
 <span class=url>رابط واحد دائم · http://127.0.0.1:8888</span>
</div>
<div id=t_war class="tab on">
<div class=hud>
 <span class=logo>🎖️ WAR ROOM</span>
 <div class=orb><div class="v neu" id=eq>—</div><div class=l>الحقوق</div></div>
 <div class=orb><div class=v id=fl>—</div><div class=l>عائم</div></div>
 <div class=orb><div class=v id=td>—</div><div class=l>اليوم</div></div>
 <div class=orb><div class=v id=d7>—</div><div class=l>7 أيام</div></div>
 <div class=orb><div class="v neu" id=sess>—</div><div class=l>الجلسة</div></div>
 <div class=gauge id=rg><span id=rgt>—</span></div>
 <div class=orb><div class="v neu" id=eng>—</div><div class=l>🛡️ محرّكات</div></div>
 <div class=orb><div class="v neu" id=demo>—</div><div class=l>الحساب</div></div>
</div>
<div class=wrap>
 <div class=col id=symcol></div>
 <div class="col center">
   <div class=ctop><span class=csym id=csym>—</span>
     <div class=tf id=tfbar></div>
     <span id=posline style="font-size:12px"></span></div>
   <div style="position:relative;flex:1;display:flex">
     <canvas id=chart></canvas>
     <canvas id=heatcv style="display:none;width:100%;border-radius:12px;background:#05060c;border:1px solid #16213c"></canvas>
     <div class=pophint id=pop></div></div>
   <div class=exec>
     <div class=modes id=modes>
       <button class="m on" data-m=scalp>⚡ سكالب</button>
       <button class=m data-m=swing>🌊 سوينق</button>
       <button class=m data-m=normal>⚙️ عادي</button>
     </div>
     <input id=lot value=0.01 type=number step=0.01 min=0.01 title="اللوت">
     <button class="btn buy" onclick="order('buy')" title="B">▲ شراء</button>
     <button class="btn sell" onclick="order('sell')" title="S">▼ بيع</button>
     <button class="btn close" onclick="closeSym()" title="C">✕ إغلاق</button>
     <span class=msg id=msg>اضغط الشارت لأمر معلّق · سكالب M1 سريع · سوينق يركض · B/S/C اختصارات</span>
   </div>
 </div>
 <div class=col>
   <div class=panel><h3>🧠 مكدّس القرار</h3><div id=stack></div><div class="final flat" id=final>—</div></div>
   <div class=panel><h3>📐 المؤشرات <span id=indcount style="color:#7d8590;font-size:10px"></span></h3><div id=inds></div></div>
   <div class=panel><h3>💰 البوتات الحيّة</h3><div id=bots></div></div>
   <div class=panel><h3>📡 التدفّق</h3><div class=tape id=tape></div></div>
 </div>
</div>
</div>
<div id=t_heat class=tab style="padding:14px;overflow-y:auto;height:calc(100vh - 44px)">
  <div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
    <span style="font-size:16px;font-weight:900;color:var(--gold)">🔥 الشارت الحراري</span>
    <span id=heatmode style="font-size:12px;color:#9fb0c3"></span>
    <div class=tf id=heatkeys>
      <button class="on" data-hk=signal>الإشارة المُركّبة</button>
      <button data-hk=chg>تغيّر اليوم %</button>
      <button data-hk=macro>ميل الماكرو</button>
      <button data-hk=pos>ربح مركزنا</button>
    </div>
  </div>
  <div id=heatgrid style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px"></div>
  <div style="margin-top:16px;font-size:13px;color:#9fc1ff;font-weight:800">💪 القوة النسبية المقطعية (القادة / المتخلّفون اليوم)</div>
  <div id=heatrs style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px"></div>
  <div style="margin-top:16px;font-size:13px;color:#9fc1ff;font-weight:800">🔗 مصفوفة الارتباط</div>
  <div id=heatcorr style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px"></div>
</div>
<iframe id=t_arena class=tab data-src="http://127.0.0.1:8870"></iframe>
<iframe id=t_flow class=tab data-src="http://127.0.0.1:8766"></iframe>
<div id=t_tape class=tab style="padding:14px;overflow-y:auto;height:calc(100vh - 44px)">
 <div style="display:flex;gap:14px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
  <span style="font-size:18px;font-weight:900">📼 الشريط المسجّل — قرارات الدماغ الحيّة</span>
  <span id=tapeagg style="color:#9fb0d0;font-size:13px"></span>
 </div>
 <div id=manualbanner style="margin-bottom:12px"></div>
 <div id=edgestrip style="margin-bottom:12px"></div>
 <div id=tapegrid style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px"></div>
</div>
<div class=foot>FRIDAY WAR ROOM · كل البيانات حيّة من محرّكاتنا · التنفيذ يبدؤه المستخدم · DEMO</div>
<script>
let HEATKEY='signal', heatTimer=null, tapeTimer=null;
document.querySelectorAll('.nav button').forEach(b=>b.onclick=()=>{
 const t=b.dataset.tab;
 document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('on',x===b));
 document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
 const el=document.getElementById('t_'+t);el.classList.add('on');
 if(el.tagName==='IFRAME'&&!el.src&&el.dataset.src)el.src=el.dataset.src;  // lazy-load
 if(t==='heat'){loadHeat();if(!heatTimer)heatTimer=setInterval(loadHeat,5000);}
 if(t==='tape'){loadTape();if(!tapeTimer)tapeTimer=setInterval(loadTape,4000);}
});
async function loadTape(){let d;try{d=await(await fetch('/api/tape')).json();}catch(e){return;}
 if(!d.ok){document.getElementById('tapegrid').innerHTML='<div style="color:#9fb0d0">'+(d.error||'—')+'</div>';return;}
 document.getElementById('tapeagg').textContent='الجلسة '+(d.session||'—')+' · لقطات اليوم '+d.today_snaps+' · هجومي '+d.n_aggressive+'/'+d.shown+' · سيدخل '+d.n_would_enter+'/'+d.shown;
 // 🛡️ بانر مخاطر اليدوي (مصدر النزف الحقيقي)
 const m=d.manual||{}; const mb=document.getElementById('manualbanner');
 if(m.n>0||((m.alerts||[]).length)){const danger=(m.float||0)<0||(m.alerts||[]).length;
  mb.innerHTML='<div style="background:'+(danger?'rgba(255,91,82,.14)':'rgba(46,160,67,.12)')+';border:1px solid '+(danger?'#ff5b5240':'#2ea04340')+';border-radius:11px;padding:11px 13px">'
   +'<b style="color:#fff">🛡️ التداول اليدوي</b> <span style="color:#9fb0d0;font-size:12px">('+m.n+' صفقة · عائم '+(m.float>=0?'+':'')+m.float+'$ · عارية '+(m.naked||0)+')</span>'
   +(m.alerts||[]).map(a=>'<div style="color:#ffb3ae;font-size:12px;margin-top:4px">'+a+'</div>').join('')+'</div>';}
 else{mb.innerHTML='';}
 // 🧬 شريط الحافات الحيّة المثبتة (ما تعلّمه النظام أنه يربح)
 const eg=d.edges||[]; const es=document.getElementById('edgestrip');
 if(eg.length){es.innerHTML='<div style="font-size:12px;color:#9fb0d0;margin-bottom:5px">🧬 حافات حيّة مثبتة (يطبّقها التداول):</div>'
  +'<div style="display:flex;flex-wrap:wrap;gap:7px">'+eg.map(e=>{const c=e.allow==='long'?'#2ea043':e.allow==='short'?'#ff5b52':'#5a6680';
   return '<span title="'+(e.why||'').replace(/"/g,'')+'" style="background:'+c+'22;border:1px solid '+c+'55;border-radius:7px;padding:4px 9px;font-size:11px;color:#fff">'+e.sym.replace(/m$/,'')+' · '+e.session+' → '+(e.allow==='long'?'▲ شراء':e.allow==='short'?'▼ بيع':e.allow)+'</span>';}).join('')+'</div>';}
 else{es.innerHTML='';}
 document.getElementById('tapegrid').innerHTML=(d.per_symbol||[]).map(c=>{
  const dir=c.dir>0?'▲ شراء':c.dir<0?'▼ بيع':'• محايد';
  const dc=c.dir>0?'#2ea043':c.dir<0?'#ff5b52':'#5a6680';
  const surge=c.surge||1;
  const badge=(t,col)=>'<span style="background:'+col+';border-radius:6px;padding:2px 7px;font-size:10px;margin-inline-start:4px">'+t+'</span>';
  return '<div onclick="SEL=\''+c.sym+'\';document.querySelector(\'.nav button[data-tab=war]\').click();loadChart();" style="cursor:pointer;background:#0b1020;border:1px solid #16213c;border-radius:11px;padding:11px">'
   +'<div style="display:flex;justify-content:space-between;align-items:center"><b style="font-size:14px;color:#fff">'+c.sym.replace(/m$/,'')+'</b><span style="color:'+dc+';font-weight:800;font-size:13px">'+dir+'</span></div>'
   +'<div style="margin-top:6px;height:6px;background:#16213c;border-radius:4px;overflow:hidden"><div style="height:100%;width:'+Math.round(Math.min(1,c.conf)*100)+'%;background:'+dc+'"></div></div>'
   +'<div style="margin-top:6px;font-size:11px;color:#9fb0d0">ثقة '+(c.conf*100).toFixed(0)+'% · تلاقٍ '+c.confluence+' · ×'+surge+(c.regime?' · '+c.regime:'')+'</div>'
   +'<div style="margin-top:7px">'+(c.would_enter?badge('سيدخل','rgba(46,160,67,.3)'):badge('انتظار','rgba(90,102,128,.25)'))
     +(c.aggressive?badge('🔥 هجومي','rgba(255,91,82,.3)'):'')
     +(c.zone_near?badge('منطقة قريبة','rgba(212,160,23,.3)'):'')+'</div>'
   +'</div>';}).join('')||'<div style="color:#9fb0d0">لا لقطات</div>';
}
document.querySelectorAll('#heatkeys button').forEach(b=>b.onclick=()=>{HEATKEY=b.dataset.hk;
 document.querySelectorAll('#heatkeys button').forEach(x=>x.classList.toggle('on',x===b));loadHeat();});
function heatColor(v,key){
 if(key==='signal'||key==='macro'){const t=Math.max(-1,Math.min(1,v));
   return t>0?`rgba(46,160,67,${0.18+t*0.7})`:t<0?`rgba(255,91,82,${0.18-t*0.7})`:'rgba(90,102,128,.2)';}
 // chg% / pos: scale by magnitude
 const t=Math.max(-1,Math.min(1,v/(key==='chg'?3:50)));
 return t>0?`rgba(46,160,67,${0.18+Math.abs(t)*0.7})`:t<0?`rgba(255,91,82,${0.18+Math.abs(t)*0.7})`:'rgba(90,102,128,.2)';}
async function loadHeat(){let d;try{d=await(await fetch('/api/heatmap')).json();}catch(e){return;}if(!d.ok)return;
 document.getElementById('heatmode').textContent=(d.headline||'')+' · '+(d.regime||'');
 const val=c=>({signal:c.signal,chg:c.chg,macro:c.macro,pos:c.pos}[HEATKEY]);
 const lbl=c=>({signal:(c.signal>0?'▲ شراء':c.signal<0?'▼ بيع':'• محايد')+' '+c.score,
   chg:(c.chg>=0?'+':'')+c.chg+'%',macro:'ميل '+c.macro,pos:(c.pos>=0?'+':'')+'$'+c.pos}[HEATKEY]);
 const cells=d.cells.slice().sort((a,b)=>val(b)-val(a));
 document.getElementById('heatgrid').innerHTML=cells.map(c=>
  `<div onclick="SEL='${c.sym}';document.querySelector('.nav button[data-tab=war]').click();loadChart();" style="cursor:pointer;background:${heatColor(val(c),HEATKEY)};border:1px solid #ffffff14;border-radius:10px;padding:10px 8px;text-align:center;transition:.2s">
   <div style="font-weight:900;font-size:13px;color:#fff">${c.sym.replace(/m$/,'')}</div>
   <div style="font-size:11px;color:#dfe7f5;margin-top:3px">${lbl(c)}</div>
   ${c.pos?`<div style="font-size:9px;color:${c.pos>=0?'#caffd9':'#ffd2cf'}">مركز ${c.pos>=0?'+':''}$${c.pos}</div>`:''}
  </div>`).join('');
 const rsCell=(arr,up)=>(arr||[]).map(x=>`<span style="background:${up?'rgba(46,160,67,.22)':'rgba(255,91,82,.22)'};border:1px solid #ffffff14;border-radius:7px;padding:4px 9px;font-size:11px;cursor:pointer" onclick="SEL='${x[0]}m';document.querySelector('.nav button[data-tab=war]').click();loadChart();">${up?'▲':'▼'} ${x[0]} <b>${x[1]>=0?'+':''}${x[1]}%</b></span>`).join('');
 document.getElementById('heatrs').innerHTML=rsCell(d.leaders,true)+' &nbsp; '+rsCell(d.laggards,false);
 document.getElementById('heatcorr').innerHTML=(d.pairs||[]).map(p=>
  `<span style="background:${p.r>=0?'rgba(46,160,67,.2)':'rgba(255,91,82,.2)'};border:1px solid #ffffff14;border-radius:7px;padding:4px 9px;font-size:11px">
   ${p.a.replace(/m$/,'')}${p.r>=0?'↔':'⇄'}${p.b.replace(/m$/,'')} <b>${p.r>=0?'+':''}${p.r}</b></span>`).join('')||'<span style=color:#5a6680>يقيس الارتباط…</span>';
}
let SEL='XAUUSDm', TF='M15', CH=null, ws=null;
const cv=document.getElementById('chart'), cx=cv.getContext('2d');
function sgn(v){return (v>=0?'+':'')+'$'+(v||0).toFixed(2);}
function ico(d){return d>0?'<span class=dirico style=color:#3fe07a>▲</span>':d<0?'<span class=dirico style=color:#ff5b52>▼</span>':'<span class=dirico style=color:#7d8590>•</span>';}
function resize(){cv.width=cv.clientWidth*devicePixelRatio;cv.height=cv.clientHeight*devicePixelRatio;cx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);}
window.addEventListener('resize',()=>{resize();drawChart();});
['M1','M5','M15','M30','H1','H4'].forEach(tf=>{const b=document.createElement('button');b.textContent=tf;b.onclick=()=>{TF=tf;HEAT=false;syncTF();showView();loadChart();};document.getElementById('tfbar').appendChild(b);});
let HEAT=false, heatBmTimer=null;
(function(){const b=document.createElement('button');b.textContent='🌡️ بوك-ماب';b.dataset.bm='1';
 b.onclick=()=>{HEAT=!HEAT;b.classList.toggle('on',HEAT);showView();if(HEAT)loadBookmap();};
 document.getElementById('tfbar').appendChild(b);})();
// 📊 PRO LAYERS — افتراضياً نظيف ($1000 chart): المستويات الموضوعية ON، الزحام OFF
let LAYERS=Object.assign({rounds:true,pdhl:true,pwhl:true,opens:true,zones:false,ema:false,swings:false,signal:false},
 JSON.parse(localStorage.getItem('wr_layers')||'{}'));
(function(){const NM={rounds:'أرقام مستديرة',pdhl:'قمة/قاع الأمس',pwhl:'قمة/قاع الأسبوع',opens:'افتتاح أسبوع/يوم',zones:'مناطق العرض/الطلب',ema:'EMA',swings:'الهيكل',signal:'سهم الإشارة'};
 const wrap=document.createElement('span');wrap.style.cssText='position:relative;display:inline-block';
 const btn=document.createElement('button');btn.textContent='☰ طبقات';
 const menu=document.createElement('div');menu.style.cssText='display:none;position:absolute;top:28px;right:0;z-index:30;background:#0c1424;border:1px solid #243250;border-radius:8px;padding:6px;min-width:150px';
 Object.keys(NM).forEach(k=>{const lbl=document.createElement('label');lbl.style.cssText='display:flex;gap:6px;align-items:center;font-size:11px;color:#cdd6f4;padding:3px 4px;cursor:pointer';
  const cb=document.createElement('input');cb.type='checkbox';cb.checked=LAYERS[k];
  cb.onchange=()=>{LAYERS[k]=cb.checked;localStorage.setItem('wr_layers',JSON.stringify(LAYERS));if(!HEAT)drawChart();};
  lbl.appendChild(cb);lbl.appendChild(document.createTextNode(NM[k]));menu.appendChild(lbl);});
 btn.onclick=(e)=>{e.stopPropagation();menu.style.display=menu.style.display==='none'?'block':'none';};
 document.addEventListener('click',()=>menu.style.display='none');
 wrap.appendChild(btn);wrap.appendChild(menu);document.getElementById('tfbar').appendChild(wrap);})();
function showView(){document.getElementById('chart').style.display=HEAT?'none':'block';
 document.getElementById('heatcv').style.display=HEAT?'block':'none';}
let DOM=null;
function loadBookmap(){fetch('/api/bookmap?sym='+SEL).then(r=>r.json()).then(d=>{window._bm=d;
 return fetch('/api/dom?sym='+SEL);}).then(r=>r.json()).then(dm=>{DOM=dm;drawBookmap(window._bm);}).catch(()=>{});}
function drawBookmap(d){if(!d||!d.ok)return;const cv=document.getElementById('heatcv'),x=cv.getContext('2d');
 const W=cv.width=cv.clientWidth*devicePixelRatio,H=cv.height=cv.clientHeight*devicePixelRatio;
 x.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);const w=cv.clientWidth,h=cv.clientHeight,pad=54;
 x.clearRect(0,0,w,h);const g=d.grid,rows=g.length,cols=g[0].length,cw=(w-pad)/cols,ch=h/rows;
 const heat=v=>{if(v<=0)return'#05060c';const t=Math.log(1+v)/Math.log(1+d.max);
   // أزرق غامق → سماوي → أصفر → أحمر (سلّم بوك-ماب)
   if(t<0.33)return`rgba(20,${Math.round(60+t*300)},${Math.round(120+t*200)},${0.3+t})`;
   if(t<0.66)return`rgba(${Math.round(120+t*200)},220,60,${0.6+t*0.4})`;
   return`rgba(255,${Math.round(200-(t-0.66)*400)},40,${0.85+t*0.15})`;};
 for(let r=0;r<rows;r++)for(let c=0;c<cols;c++){if(g[r][c]>0){x.fillStyle=heat(g[r][c]);x.fillRect(c*cw,r*ch,cw+0.5,ch+0.5);}}
 // محور السعر
 x.fillStyle='#9fb0c3';x.font='10px Segoe UI';x.textAlign='left';
 for(let i=0;i<=5;i++){const p=d.hi-(d.hi-d.lo)*i/5,yy=i*h/5;x.fillStyle='#3d4a63';x.fillRect(w-pad,yy,pad,1);x.fillStyle='#9fb0c3';x.fillText(p.toFixed(2),w-pad+3,yy+11);}
 // عُقد الحجم (مستويات أكثر نشاطاً = دعم/مقاومة)
 (d.nodes||[]).forEach(n=>{const yy=(d.hi-n.px)/(d.hi-d.lo)*h;x.strokeStyle='#ffffff55';x.setLineDash([2,3]);x.beginPath();x.moveTo(0,yy);x.lineTo(w-pad,yy);x.stroke();x.setLineDash([]);
   x.fillStyle='#fff';x.font='9px Segoe UI';x.fillText('● عقدة '+n.px,4,yy-2);});
 // مناطقنا المتعلّمة
 (d.zones||[]).forEach(z=>{const yy=(d.hi-z.px)/(d.hi-d.lo)*h;x.strokeStyle=z.net>0?'#3fe07a':'#ff5b52';x.globalAlpha=.7;x.beginPath();x.moveTo(0,yy);x.lineTo(w-pad,yy);x.stroke();x.globalAlpha=1;});
 // السعر الحيّ
 if(d.price){const yy=(d.hi-d.price)/(d.hi-d.lo)*h;x.fillStyle='#e8c46a';x.fillRect(w-pad,yy-8,pad,16);x.fillStyle='#05070e';x.font='bold 10px Segoe UI';x.textAlign='center';x.fillText(d.price.toFixed(2),w-pad/2,yy+3);}
 // مناطق الاهتمام (POI) — عُقد سيولة قوية تُبرز كخطوط بيضاء عريضة + وسم
 (d.poi||[]).slice(0,4).forEach(p=>{const yy=(d.hi-p.px)/(d.hi-d.lo)*h;
  x.strokeStyle='#ffffffaa';x.lineWidth=2;x.beginPath();x.moveTo(0,yy);x.lineTo(w-pad,yy);x.stroke();
  x.fillStyle='#fff';x.font='bold 9px Segoe UI';x.textAlign='left';x.fillText('◆ اهتمام '+p.px,4,yy-3);});
 // 🎯 لافتة القرار: شراء/بيع + قوة التدفّق (أعلى يسار)
 const vc=d.verdict>0?'#26a269':d.verdict<0?'#c0392b':'#5a6680';
 x.fillStyle=vc;x.fillRect(6,6,168,40);x.fillStyle='#fff';x.font='bold 16px Segoe UI';x.textAlign='left';
 x.fillText((d.verdict>0?'▲ شراء':d.verdict<0?'▼ بيع':'• محايد')+'  '+(d.score||0),14,28);
 x.font='10px Segoe UI';x.fillText('تدفّق التيكات: '+(d.flow>=0?'+':'')+d.flow+'%  '+(d.flow>15?'(ضغط شراء)':d.flow<-15?'(ضغط بيع)':''),14,41);
 x.fillStyle='#5d6b85';x.font='10px Segoe UI';x.textAlign='left';x.fillText('🌡️ كثافة النشاط '+d.minutes+'د · ◆=منطقة اهتمام · أحمر=ذروة سيولة (نشاط متحقّق لا أوامر كامنة)',6,h-6);
 // 🪜 سلّم DOM حيّ (يمين) — ضغط شراء/بيع لكل مستوى (مثل طرفية إكسنس)
 if(DOM&&DOM.ok){const lw=132,x0=w-pad-lw;const rows=DOM.rows;const rh=Math.min(15,(h-20)/Math.max(1,rows.length));
  x.fillStyle='#0a0f1c';x.fillRect(x0,0,lw,rows.length*rh+2);
  x.font='9px Segoe UI';
  rows.forEach((rw,i)=>{const yy=i*rh;const tot=rw.buy+rw.sell;const bw=tot/DOM.max*(lw/2);
   const near=Math.abs(rw.px-DOM.cur)<1e-9;
   // بيع (أحمر يسار) · شراء (أزرق يمين) حول عمود السعر
   x.fillStyle='rgba(255,91,82,.7)';x.fillRect(x0+lw/2-rw.sell/DOM.max*(lw/2),yy+1,rw.sell/DOM.max*(lw/2),rh-1);
   x.fillStyle='rgba(58,140,255,.8)';x.fillRect(x0+lw/2,yy+1,rw.buy/DOM.max*(lw/2),rh-1);
   x.fillStyle=near?'#e8c46a':'#9fb0c3';x.textAlign='center';x.fillText(rw.px.toFixed(2),x0+lw/2,yy+rh-2);
   if(near){x.strokeStyle='#e8c46a';x.strokeRect(x0,yy,lw,rh);}});
  x.fillStyle='#5d6b85';x.textAlign='center';x.fillText('🪜 DOM حيّ (تيكات)',x0+lw/2,rows.length*rh+12);}}
function syncTF(){document.querySelectorAll('#tfbar button').forEach(b=>b.classList.toggle('on',b.textContent===TF));}
syncTF();
let MODE='scalp', SC=null, MX=null, MY=null;
document.querySelectorAll('#modes .m').forEach(b=>b.onclick=()=>{MODE=b.dataset.m;
 document.querySelectorAll('#modes .m').forEach(x=>x.classList.toggle('on',x===b));});
function priceAtY(y){if(!SC)return null;return SC.hi-(y-SC.top)/SC.h*(SC.hi-SC.lo);}
async function loadState(){let d;try{d=await(await fetch('/api/state')).json();}catch(e){return;}if(!d.ok)return;
 const eq=document.getElementById('eq');eq.textContent='$'+d.equity.toFixed(0);
 const set=(id,v)=>{const e=document.getElementById(id);e.textContent=sgn(v||0);e.className='v '+((v||0)>=0?'pos':'neg');};
 set('fl',d.floating);set('td',d.today);set('d7',d.d7);
 document.getElementById('sess').textContent=d.session;
 document.getElementById('eng').textContent=d.engines;
 const dm=document.getElementById('demo');dm.textContent=d.demo?'DEMO ✓':'⚠ REAL';dm.className='v '+(d.demo?'pos':'neg');
 const p=(d.risk.pct||0),gc=p>=60?'#ff5b52':p>=35?'#ffb24d':'#3fe07a';
 const rg=document.getElementById('rg');rg.style.background='conic-gradient('+gc+' '+(p*3.6)+'deg,#16203a 0)';
 rg.classList.toggle('pulse',d.risk.emergency||d.risk.overall==='CRITICAL');
 document.getElementById('rgt').innerHTML=p+'%<br><span style="font-size:7px;color:'+gc+'">'+(d.risk.overall||'')+'</span>';
 // symbol list
 const col=document.getElementById('symcol');
 d.syms.forEach(s=>{let row=document.getElementById('sr_'+s.sym);
  if(!row){row=document.createElement('div');row.id='sr_'+s.sym;row.className='srow';row.onclick=()=>{SEL=s.sym;loadChart();document.querySelectorAll('.srow').forEach(x=>x.classList.remove('sel'));row.classList.add('sel');};col.appendChild(row);}
  if(SEL===s.sym)row.classList.add('sel');
  const pl=s.pos?(' <span class="p '+(s.pos.profit>=0?'pos':'neg')+'">'+sgn(s.pos.profit)+'</span>'):'';
  row.innerHTML='<span class=s>'+s.sym.replace(/m$/,'')+'</span><span>'+(s.pos?(s.pos.side==='buy'?'🟢':'🔴'):'')+pl+'</span>';});
 // bots
 document.getElementById('bots').innerHTML=d.bots.map(b=>'<div class=bot><span>'+b.name+' ('+b.n+')</span><span class="'+(b.profit>=0?'pos':'neg')+'">'+sgn(b.profit)+'</span></div>').join('')||'<div class=bot>لا مراكز</div>';
}
async function loadChart(){document.getElementById('csym').textContent=SEL.replace(/m$/,'');
 let d;try{d=await(await fetch('/api/chart?sym='+SEL+'&tf='+TF)).json();}catch(e){return;}if(!d.ok)return;CH=d;drawChart();
 // decision stack
 const st=d.decision;document.getElementById('stack').innerHTML=st.layers.map(l=>'<div class="lyr '+(l.dir>0?'up':l.dir<0?'dn':'')+'"><span class=k>'+l.k+ico(l.dir)+'</span><span class=v>'+l.v+'</span></div>').join('');
 const f=document.getElementById('final');f.className='final '+(st.final>0?'up':st.final<0?'dn':'flat');
 f.textContent=st.final>0?'▲ إشارة شراء مُركّبة ('+st.score+')':st.final<0?'▼ إشارة بيع مُركّبة ('+st.score+')':'• محايد ('+st.score+')';
 // كل المؤشرات: تصويت حيّ + وزن + دقّة
 const ind=d.indicators||[];document.getElementById('indcount').textContent='('+ind.length+' مؤشّر)';
 const colA=h=>h>=55?'#3fe07a':h>=52?'#e8d44d':h>=50?'#7d8590':'#ff5b52';
 document.getElementById('inds').innerHTML=ind.map(x=>{
  const di=x.dir>0?'<span style=color:#3fe07a>▲</span>':x.dir<0?'<span style=color:#ff5b52>▼</span>':'<span style=color:#5a6680>•</span>';
  const wpct=Math.min(100,x.w*60);const bc=x.hit!=null?colA(x.hit):'#3a4a66';
  return '<div class=ind><span class=nm>'+di+' '+x.k+'</span><span class=tr><i style="width:'+wpct+'%;background:'+bc+'"></i></span><span class=hit>'+(x.hit!=null?x.hit+'%':'—')+'</span></div>';}).join('')||'<div class=ind>—</div>';
 const pl=document.getElementById('posline');
 pl.innerHTML=d.pos?('مركز: '+(d.pos.side==='buy'?'🟢 شراء':'🔴 بيع')+' @'+d.pos.entry+' · <span class="'+(d.pos.profit>=0?'pos':'neg')+'">'+sgn(d.pos.profit)+'</span>'):'';
}
function drawChart(){if(!CH)return;const W=cv.clientWidth,H=cv.clientHeight;cx.clearRect(0,0,W,H);
 const b=CH.bars;if(!b||!b.length)return;const pad=52;
 const live=CH.live;  // السعر الحيّ من التيكات
 let lo=Math.min(...b.map(x=>x.l)),hi=Math.max(...b.map(x=>x.h));
 (CH.zones||[]).forEach(z=>{lo=Math.min(lo,z.px-z.band);hi=Math.max(hi,z.px+z.band);});
 if(live){lo=Math.min(lo,live);hi=Math.max(hi,live);}
 const rg=(hi-lo)||1;const Y=p=>pad*0.4+(hi-p)/rg*(H-pad);const cw=(W-pad)/b.length;
 SC={hi:hi,lo:lo,top:pad*0.4,h:H-pad,W:W,pad:pad};
 const tag=(y,txt,col)=>{cx.fillStyle=col;cx.font='9px Segoe UI';cx.textAlign='right';cx.fillText(txt,W-pad-2,y-2);};
 const hline=(p,col,dash,txt)=>{const y=Y(p);cx.strokeStyle=col;cx.lineWidth=1;if(dash)cx.setLineDash(dash);
   cx.beginPath();cx.moveTo(0,y);cx.lineTo(W-pad,y);cx.stroke();cx.setLineDash([]);if(txt)tag(y,txt,col);};
 // price axis labels (subtle)
 cx.fillStyle='#3d4a63';cx.font='9px Segoe UI';cx.textAlign='left';
 for(let i=0;i<=5;i++){const y=pad*0.4+i*(H-pad)/5;cx.fillText((hi-i*rg/5).toFixed(CH.digits||2),W-pad+3,y+3);}
 // ROUND-NUMBER levels (تُستبدل بالشبكة العشوائية) — مستويات يحترمها السوق فعلاً
 if(LAYERS.rounds){const span=hi-lo;let step=Math.pow(10,Math.floor(Math.log10(span)));if(span/step<3)step/=2;if(span/step>12)step*=2;
   for(let p=Math.ceil(lo/step)*step;p<=hi;p+=step){cx.strokeStyle='#141a26';cx.lineWidth=1;cx.beginPath();cx.moveTo(0,Y(p));cx.lineTo(W-pad,Y(p));cx.stroke();}}
 // المستويات المرجعية الموضوعية ($1000): PDH/PDL/PWH/PWL + افتتاح الأسبوع/اليوم
 const lv=CH.levels||{};
 if(LAYERS.pwhl){if(lv.pwh)hline(lv.pwh,'#5a6680',[1,3],'PWH');if(lv.pwl)hline(lv.pwl,'#5a6680',[1,3],'PWL');}
 if(LAYERS.pdhl){if(lv.pdh)hline(lv.pdh,'#7a8aa8',[2,3],'PDH');if(lv.pdl)hline(lv.pdl,'#7a8aa8',[2,3],'PDL');}
 if(LAYERS.opens){if(lv.wopen)hline(lv.wopen,'#c9a14a',null,'W.Open');if(lv.dopen)hline(lv.dopen,'#8a7a3a',[4,4],'D.Open');}
 // ZONES (طبقة اختيارية، خفيفة)
 if(LAYERS.zones)(CH.zones||[]).slice(0,3).forEach(z=>{const yt=Y(z.px+z.band),yb=Y(z.px-z.band);
  const win=z.net>2,loss=z.net<-2;const col=win?'#26a269':loss?'#c0392b':'#5a6680';
  cx.fillStyle=col+'14';cx.fillRect(0,yt,W-pad,yb-yt);});
 // EMA (طبقة اختيارية)
 function line(arr,col){if(!arr||arr.length<2)return;cx.strokeStyle=col;cx.lineWidth=1.2;cx.beginPath();
  arr.forEach((v,i)=>{const x=i*cw+cw/2,y=Y(v);i?cx.lineTo(x,y):cx.moveTo(x,y);});cx.stroke();}
 if(LAYERS.ema){line(CH.ema50,'#7aa2ff88');line(CH.ema20,'#e8c46a88');}
 // CANDLES — هادئة احترافية: صعود أجوف · هبوط مصمت
 b.forEach((c,i)=>{const x=i*cw+cw/2;const up=c.c>=c.o;const col=up?'#26a269':'#c0392b';
  cx.strokeStyle=col;cx.fillStyle=col;cx.lineWidth=1;cx.beginPath();cx.moveTo(x,Y(c.h));cx.lineTo(x,Y(c.l));cx.stroke();
  const bw=Math.max(1,cw*0.6),by=Y(Math.max(c.o,c.c)),bh=Math.max(1,Math.abs(Y(c.o)-Y(c.c)));
  if(up){cx.strokeRect(x-bw/2,by,bw,bh);}else{cx.fillRect(x-bw/2,by,bw,bh);}});
 // structure (طبقة اختيارية)
 if(LAYERS.swings){(CH.swings&&CH.swings.highs||[]).forEach(s=>{const x=s.i*cw+cw/2,y=Y(s.px);cx.fillStyle='#6b7a9c';cx.beginPath();cx.arc(x,y-4,2,0,7);cx.fill();});
 (CH.swings&&CH.swings.lows||[]).forEach(s=>{const x=s.i*cw+cw/2,y=Y(s.px);cx.fillStyle='#6b7a9c';cx.beginPath();cx.arc(x,y+4,2,0,7);cx.fill();});}
 // entry / SL / TP
 if(CH.pos){const y=Y(CH.pos.entry);cx.strokeStyle='#e8c46a';cx.lineWidth=1.4;cx.setLineDash([2,3]);cx.beginPath();cx.moveTo(0,y);cx.lineTo(W-pad,y);cx.stroke();cx.setLineDash([]);
  cx.fillStyle='#e8c46a';cx.font='bold 9px Segoe UI';cx.textAlign='left';cx.fillText('◀ دخولنا '+CH.pos.entry,4,y-3);
  if(CH.pos.sl){const ys=Y(CH.pos.sl);cx.strokeStyle='#ff5b5266';cx.setLineDash([2,4]);cx.beginPath();cx.moveTo(0,ys);cx.lineTo(W-pad,ys);cx.stroke();cx.setLineDash([]);}
  if(CH.pos.tp){const yt=Y(CH.pos.tp);cx.strokeStyle='#3fe07a66';cx.setLineDash([2,4]);cx.beginPath();cx.moveTo(0,yt);cx.lineTo(W-pad,yt);cx.stroke();cx.setLineDash([]);}}
 // LIVE price line + pulsing dot + axis label (التيكات على الشارت)
 if(live){const y=Y(live);const up=CH._lp!=null&&live>=CH._lp;const col=up?'#26a269':'#c0392b';
  cx.strokeStyle=col;cx.globalAlpha=.7;cx.lineWidth=1;cx.setLineDash([3,3]);cx.beginPath();cx.moveTo(0,y);cx.lineTo(W-pad,y);cx.stroke();cx.setLineDash([]);cx.globalAlpha=1;
  cx.fillStyle=col;cx.fillRect(W-pad,y-8,pad,16);cx.fillStyle='#fff';cx.font='bold 10px Segoe UI';cx.textAlign='center';cx.fillText(live.toFixed(CH.digits||2),W-pad/2,y+3);}
 // final signal arrow (طبقة اختيارية — الإشارة موجودة في بطاقة القرار)
 const f=LAYERS.signal&&CH.decision&&CH.decision.final;if(f){const x=(b.length-1)*cw+cw/2,c=b[b.length-1];
  if(f>0){cx.fillStyle='#3fe07a';cx.beginPath();const y=Y(c.l)+10;cx.moveTo(x,y);cx.lineTo(x-5,y+8);cx.lineTo(x+5,y+8);cx.fill();}
  else{cx.fillStyle='#ff5b52';cx.beginPath();const y=Y(c.h)-10;cx.moveTo(x,y);cx.lineTo(x-5,y-8);cx.lineTo(x+5,y-8);cx.fill();}}
 // pending orders (الأوامر المعلّقة على الشارت)
 (CH.pending||[]).forEach(o=>{const y=Y(o.price);const col=o.buy?'#3fe07a':'#ff5b52';
  cx.strokeStyle=col;cx.globalAlpha=o.mine?.95:.5;cx.lineWidth=1;cx.setLineDash([8,4]);
  cx.beginPath();cx.moveTo(0,y);cx.lineTo(W-pad,y);cx.stroke();cx.setLineDash([]);cx.globalAlpha=1;
  cx.fillStyle=col;cx.font='bold 8px Segoe UI';cx.textAlign='left';
  cx.fillText((o.buy?'⏳▲ ':'⏳▼ ')+o.type+' '+o.vol+(o.mine?' ✕':''),4,y-2);});
 // crosshair + price readout (كروس-هير احترافي)
 if(MX!=null&&MY!=null&&MX<W-pad){cx.strokeStyle='#e8c46a55';cx.lineWidth=1;cx.setLineDash([4,4]);
  cx.beginPath();cx.moveTo(MX,0);cx.lineTo(MX,H);cx.moveTo(0,MY);cx.lineTo(W-pad,MY);cx.stroke();cx.setLineDash([]);
  const pp=priceAtY(MY);if(pp!=null){cx.fillStyle='#e8c46a';cx.fillRect(W-pad,MY-8,pad,16);cx.fillStyle='#05070e';cx.font='bold 10px Segoe UI';cx.textAlign='center';cx.fillText(pp.toFixed(2),W-pad/2,MY+3);}}
}
function lotv(){return parseFloat(document.getElementById('lot').value)||0.01;}
async function order(side){const m=document.getElementById('msg');m.textContent='⚡ يُرسل '+MODE+'…';
 const r=await(await fetch('/api/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sym:SEL,side:side,volume:lotv(),mode:MODE})})).json();
 m.textContent=r.ok?('✅ '+side+' '+MODE+' '+r.vol+' @ '+r.price+' (#'+r.ticket+')'):('⛔ '+r.error);loadChart();loadState();}
async function pend(side,price){const m=document.getElementById('msg');m.textContent='⏳ يضع معلّق…';document.getElementById('pop').style.display='none';
 const r=await(await fetch('/api/pending',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sym:SEL,otype:side,price:price,volume:lotv(),mode:(MODE==='scalp'?'scalp':'swing')})})).json();
 m.textContent=r.ok?('✅ معلّق '+r.side+' @ '+r.price+' (#'+r.ticket+')'):('⛔ '+r.error);loadChart();}
async function cancelP(ticket){const m=document.getElementById('msg');document.getElementById('pop').style.display='none';
 const r=await(await fetch('/api/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket:ticket})})).json();
 m.textContent=r.ok?('✅ أُلغي #'+ticket):'⛔ فشل الإلغاء';loadChart();}
async function closeSym(){const m=document.getElementById('msg');m.textContent='يُغلق…';
 const r=await(await fetch('/api/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sym:SEL})})).json();
 m.textContent=r.ok?('✅ أُغلق '+r.closed):('⛔ '+r.error);loadChart();loadState();}
// crosshair + click-to-place
cv.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect();MX=e.clientX-r.left;MY=e.clientY-r.top;});
cv.addEventListener('mouseleave',()=>{MX=null;MY=null;});
cv.addEventListener('click',e=>{const r=cv.getBoundingClientRect();const y=e.clientY-r.top;const pp=priceAtY(y);if(pp==null)return;
 const pop=document.getElementById('pop');
 // near an existing pending of ours? → عرض إلغاء
 let near=null;if(CH&&SC){(CH.pending||[]).forEach(o=>{if(!o.mine)return;const oy=SC.top+(SC.hi-o.price)/(SC.hi-SC.lo)*SC.h;if(Math.abs(oy-y)<7)near=o;});}
 pop.style.left=Math.min(e.clientX-r.left,cv.clientWidth-150)+'px';pop.style.top=y+'px';pop.style.display='block';
 if(near){pop.innerHTML='<div class=px>'+near.type+' @'+near.price+'</div><button class=ps onclick="cancelP('+near.ticket+')">✕ إلغاء الأمر</button>';}
 else{pop.innerHTML='<div class=px>أمر معلّق @ '+pp.toFixed(2)+'</div><button class=pb onclick="pend(\'buy\','+pp+')">▲ شراء معلّق</button><button class=ps onclick="pend(\'sell\','+pp+')">▼ بيع معلّق</button>';}});
document.addEventListener('click',e=>{if(!e.target.closest('#pop')&&e.target!==cv)document.getElementById('pop').style.display='none';});
// keyboard speed: B buy · S sell · C close
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT')return;const k=e.key.toLowerCase();
 if(k==='b')order('buy');else if(k==='s')order('sell');else if(k==='c')closeSym();});
function tape(){try{ws=new WebSocket('ws://127.0.0.1:8765');ws.onmessage=ev=>{const d=JSON.parse(ev.data);const el=document.getElementById('tape');
  (d.ticks||[]).filter(t=>t.sym===SEL).forEach(t=>{
    // اعكس التدفّق على الشارت: حدّث السعر الحيّ + الشمعة المتشكّلة لحظياً
    if(CH){CH._lp=CH.live;CH.live=t.bid;const last=CH.bars[CH.bars.length-1];
      if(last){last.c=t.bid;if(t.bid>last.h)last.h=t.bid;if(t.bid<last.l)last.l=t.bid;}}
    const div=document.createElement('div');const cl=CH&&CH._lp!=null&&t.bid>=CH._lp?'pos':'neg';
    div.innerHTML=new Date(t.t*1000).toLocaleTimeString('en-GB')+'  <b class='+cl+'>'+t.bid+'</b> / '+t.ask+'  sp'+t.spread;
    el.insertBefore(div,el.firstChild);while(el.children.length>8)el.removeChild(el.lastChild);});};
  ws.onclose=()=>setTimeout(tape,3000);}catch(e){}}
resize();loadState();loadChart();tape();
setInterval(loadState,2000);setInterval(()=>{if(!HEAT)loadChart();},2500);
setInterval(()=>{if(document.getElementById('t_war').classList.contains('on')&&!HEAT)drawChart();},120);  // رسم حيّ ناعم
setInterval(()=>{if(HEAT&&document.getElementById('t_war').classList.contains('on'))loadBookmap();},3000);  // تحديث بوك-ماب
</script></body></html>"""


def tape_panel(limit=80):
    """📼 آخر لقطات الشريط المسجّل + حالة الهجومية الحيّة — يعرض للمستخدم ما يفكّر فيه الدماغ
    لكل رمز (اتجاه/ثقة/تضخيم/هجومي/سيدخل) دون أي طلب — قراءة فقط من ملف الشريط."""
    import glob
    d = RN / "tape"
    files = sorted(glob.glob(str(d / "*.jsonl")))
    if not files:
        return {"ok": False, "error": "لا يوجد شريط بعد"}
    try:
        lines = Path(files[-1]).read_text(encoding="utf-8").strip().split("\n")
    except Exception as e:
        return {"ok": False, "error": str(e)}
    rows = []
    for ln in lines[-limit:]:
        try:
            rows.append(json.loads(ln))
        except Exception:
            pass
    if not rows:
        return {"ok": False, "error": "شريط فارغ"}
    latest = {}
    for r in rows:
        latest[r.get("sym") or "?"] = r
    per = []
    for s, r in latest.items():
        per.append({"sym": s, "session": r.get("session"), "dir": r.get("dir"),
                    "conf": round(float(r.get("conf") or 0), 3), "surge": r.get("surge"),
                    "aggressive": bool(r.get("aggressive")), "would_enter": bool(r.get("would_enter")),
                    "confluence": round(float(r.get("confluence") or 0), 2),
                    "regime": r.get("regime"), "zone_near": r.get("zone_near")})
    per.sort(key=lambda x: -(x["surge"] or 0) * 10 - x["conf"])
    # 🛡️ مخاطر اليدوي (من manual_guard) — مصدر النزف الحقيقي يُعرض للمستخدم
    manual = {}
    try:
        manual = json.loads((RN / "manual_guard.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    # 🧬 الحافات الحيّة المثبتة (gene_hybrids) — ما تعلّمه النظام أنه يربح فعلاً لكل رمز×جلسة
    edges = []
    try:
        hb = json.loads((RN / "gene_hybrids.json").read_text(encoding="utf-8"))
        for sym, sessdict in hb.items():
            if sym.startswith("_") or not isinstance(sessdict, dict):
                continue
            for sess, e in sessdict.items():
                edges.append({"sym": sym, "session": sess, "allow": e.get("allow"), "why": e.get("why", "")})
    except Exception:
        pass
    return {"ok": True, "session": rows[-1].get("session"), "today_snaps": len(lines),
            "shown": len(rows),
            "n_aggressive": sum(1 for r in rows if r.get("aggressive")),
            "n_would_enter": sum(1 for r in rows if r.get("would_enter")),
            "per_symbol": per,
            "manual": {"n": manual.get("n_manual", 0), "float": manual.get("float", 0),
                       "naked": manual.get("naked", 0), "alerts": manual.get("alerts", [])},
            "edges": edges}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, obj, ctype="application/json"):
        body = (obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        self.send_response(200); self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/api/state":
            self._send(state())
        elif u.path == "/api/chart":
            self._send(chart(q.get("sym", ["XAUUSDm"])[0], q.get("tf", ["M15"])[0]))
        elif u.path == "/api/heatmap":
            self._send(heatmap())
        elif u.path == "/api/bookmap":
            self._send(bookmap(q.get("sym", ["XAUUSDm"])[0]))
        elif u.path == "/api/dom":
            self._send(dom_ladder(q.get("sym", ["XAUUSDm"])[0]))
        elif u.path == "/api/tape":
            self._send(tape_panel())
        else:
            self._send(HTML.encode("utf-8"), "text/html")

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(ln) or b"{}")
        except Exception:
            data = {}
        u = urlparse(self.path)
        if u.path == "/api/order":
            self._send(place(data.get("sym", ""), data.get("side", ""),
                             data.get("volume", 0.01), data.get("mode", "scalp")))
        elif u.path == "/api/pending":
            self._send(place_pending(data.get("sym", ""), data.get("otype", "buy"),
                                     data.get("price", 0), data.get("volume", 0.01),
                                     data.get("mode", "swing")))
        elif u.path == "/api/cancel":
            self._send(cancel(data.get("ticket", 0)))
        elif u.path == "/api/close":
            self._send(close_sym(data.get("sym", "")))
        else:
            self._send({"ok": False})


if __name__ == "__main__":
    _init()
    print(f"[WARROOM] 🎖️ http://127.0.0.1:{PORT}", flush=True)
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
