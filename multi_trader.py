"""multi_trader.py — trade ALL deployed F2-b genomes at once (magic 20260608).

Generalises btc_live's proven logic to every symbol that has a factory genome: reads the
higher-TF trend (M15+H1 macro via chart_read), gates on the genome's conf_gate, respects the
CLAUDE_SIGNAL panel veto, sizes tiny (risk-based, scaled for a small account), opens with the
genome's ATR stop/target (vol-regime scaled), and protect-profit manages (trail, never close a
loser, lock breakeven fast). Caps total concurrent positions. DEMO.

Run:  python multi_trader.py --loop
"""
from __future__ import annotations
import argparse, json, time, glob
from pathlib import Path
import microstructure as ms
import broker_calc as bc
import dynamic_stop as dstop
import portfolio_guard as pg

MAGIC = 20260608
HYB_MAGIC = 20260613           # 🧬 الهجائن: رقم سحري مميز ليراها المستخدم في MT5 مباشرة
RISK_PCT = 0.3                 # tiny per-trade risk (small account)
MAX_TRADE_RISK = 2.0           # 🛑 سقف صارم: مهما تراكمت المضاعفات، لا صفقة تخاطر بأكثر من %2 من الحقوق
                               # (TSLA خسر -$124≈8% بصفقة واحدة 2026-06-15 — قطع الذيل = ربحية أعلى)
MAX_TOTAL_POS = 6              # تشديد (طلب المستخدم): تعرّض متزامن أقل
# 🩸 رموز نازفة صريحة مُستبعَدة من الروستر (غير المعادن — المعادن تُغطَّى بفلتر XAU/XAG):
_BLEED_SYMS = {"JP225m", "USDJPYm", "BTCUSDTm", "GBPCHFm", "EURNZDm", "GBPNZDm"}
DAILY_KILL_PCT = 15.0
POLL = 1                       # ⚡ السوق سريع: ردّ فعل خلال ~1.6ث (القرار نفسه 567ms فقط — كان 3ث)
COOLDOWN_S = 90                # تشديد: تهدئة أطول بين الدخولات الجديدة (تداول أندر). الحماية: سقف
                               # الخسارة 2%/صفقة + mode-evolution يوقف ما يتشرذم لخسارة + بوّابة الثقة
MIN_CONF_BUFFER = 0.02         # توازن (تنفيذ الآن): فوق بوّابة الجين بهامش صغير = دخول أكثر على رموز منخفضة التكلفة
LOT_PER_1K = 1.0               # lot-cap growth: ~1 lot per $1000 equity (compounding headroom)
LIVE_LOSS_CUT = -8.0           # SELF-IMPROVE: bench a symbol that's lost more than this LIVE (>=4 trades)
MAX_STACK_PER_SYM = 2          # تشديد: تكديس أقل بكثير على رمز واحد (كان 6 = رشّاش)
PYRAMID_CONF = 0.80            # only stack more when confidence is THIS high (into strength)
CONV_MAX_MULT = 2.5
DIVE_LOT_MULT = 2.0            # MOMENTUM-DIVE: multiply lot when a strong impulse fires (high-lot, one-direction)
DIVE_STR = 1.3                 # impulse body (in ATRs) that counts as a dive
GAP_PEND_ATR = 0.6            # min FVG size (ATR) to arm a pending order on the gap
MAX_PENDING = 6               # cap pending STOP orders (أوامر معلقة) alongside direct trades
INTERMARKET_BOOST = 0.15      # add to confluence when the cross-asset brain agrees on direction
WICK_REV_CONF = 0.70          # confidence assigned to a liquidity-sweep wick-reversal entry
_DD = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
GENO = _DD / "genomes"
_COMMON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
KILL_F = Path(r"C:\Users\Radhi\MT5\kill_switch.txt")   # 🛑 إيقاف طارئ: وجوده يمنع فتح صفقات جديدة فقط (الإدارة/الإغلاق تبقى حيّة)


def _kill_active():
    """🛑 مفتاح الإيقاف الطارئ: يمنع الدخول الجديد فقط (DEAL entries + PENDING). تعديل/إغلاق/سحب المراكز يبقى حيّاً."""
    try:
        return KILL_F.exists()
    except Exception:
        return False


def _session_now():
    """Current session window — matches the classifier the specialists were TRAINED on."""
    try:
        import sys as _sys
        if r"C:\Users\Radhi\MT5\r_native_v2" not in _sys.path:
            _sys.path.insert(0, r"C:\Users\Radhi\MT5\r_native_v2")
        from indicators import session as _S
        return _S.classify().name
    except Exception:
        import datetime
        h = datetime.datetime.now(datetime.timezone.utc).hour
        return ("NY_OVERLAP" if 13 <= h < 17 else "LONDON" if 8 <= h < 13 else
                "NY_LATE" if 17 <= h < 21 else "ASIAN" if (h >= 22 or h < 8) else "TRANSITION")


# 📼 الشريط (30 يوماً, 1001 صفقة): london الجلسة الرابحة الوحيدة (+$7.98)؛ asia −$184 و ny −$196 تنزفان.
# بوّابة دخول بالجلسة: نسمح بالدخول الجديد فقط في لندن + تداخل نيويورك المبكّر (الذروة 13-17 UTC).
# آسيا/نيويورك-المتأخّرة/الانتقال/المغلق = لا دخول جديد. (إدارة/إغلاق المراكز القائمة تبقى حيّة — كالـkill_switch.)
_ENTRY_SESSIONS = {"LONDON", "NY_OVERLAP"}


def _session_blocks_entry():
    """True لو الجلسة الحالية تمنع الدخول الجديد. مدفوعة بالبيانات عبر session_gate
    (الجلسة المُثبتة تتداول حيّاً، غير المُثبتة ظلّ)؛ الاحتياط: لندن/تداخل نيويورك. يمنع الفتح الجديد فقط."""
    try:
        import session_gate as _sg
        return not _sg.session_allows_entry()
    except Exception:
        try:
            return _session_now() not in _ENTRY_SESSIONS
        except Exception:
            return False   # عند الشكّ لا نُجمّد المحرّك (فشل آمن نحو السلوك القديم)


_CRYPTO_PFX = ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LTC", "TRX", "DOT", "AVAX", "LINK")


def _is_crypto(sym):
    """الكريبتو يتداول 24/7 — لا تنطبق عليه بوّابة جلسات الفوركس (لندن/نيويورك)."""
    return str(sym).upper().startswith(_CRYPTO_PFX)


def _mkt_open(mt5, sym):
    """السوق مفتوح فعلاً: تنفيذ كامل + تيك حديث (<180ث) — يستبعد المغلق بعطلة/جلسة
    (الفوركس/المؤشرات/المعادن تيكها راكد في الويكند) فيُتداوَل ما هو مفتوح حقاً."""
    try:
        info = mt5.symbol_info(sym)
        if not info or info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            return False
        tk = mt5.symbol_info_tick(sym)
        return bool(tk and (time.time() - tk.time) < 180)
    except Exception:
        return False


def _is_volatile(sym):
    """رموز يصنع فيها الدخول عكس الاتجاه خسائر ذيل كارثية (مُثبت OOS 2026-06-18): معادن/نفط/مؤشرات/كريبتو.
    FX المتقلّبة أقلّ تُترك بلا فلتر (الارتداد عكس الاتجاه يربح فيها 79%)."""
    s = sym.upper()
    if s.startswith("XAU") or s.startswith("XAG"):
        return True
    if "OIL" in s or "BTC" in s or "ETH" in s:
        return True
    return any(ix in s for ix in ("US30", "US500", "USTEC", "JP225", "DE30", "GER40", "UK100", "US2000", "HK50", "NAS"))


def _htf_opposes(mt5, sym, cdir):
    """فلتر اتجاه HTF السببي (مُثبت OOS): True لو الاتجاه cdir يعاكس ميل EMA50 على M15 (شموع مغلقة فقط).
    يمنع 'اصطياد السكين الساقط' — شراء/بيع عكس الاتجاه الأعلى على رمز متقلّب."""
    try:
        m15 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 1, 85)   # 1 = تخطّ الشمعة الجارية → سببي
        if m15 is None or len(m15) < 60:
            return False
        k = 2.0 / 51.0; ema = float(m15[0]["close"]); es = []
        for b in m15:
            ema = float(b["close"]) * k + ema * (1 - k); es.append(ema)
        slope = 1 if es[-1] > es[-6] else -1
        return cdir * slope < 0
    except Exception:
        return False


def _genomes():
    """SESSION ROUTER: for a symbol with a session stable, trade the specialist for the CURRENT
    session (or DON'T trade it this session if it has no edge there — discipline, not a halt).
    Symbols without a stable fall back to their single full-session genome (safety)."""
    sess = _session_now()
    out = {}
    for f in glob.glob(str(GENO / "*.json")):                 # single genomes (fallback)
        try:
            g = json.loads(Path(f).read_text(encoding="utf-8"))
            out[g["symbol"]] = g["config"]
        except Exception:
            pass
    for sf in glob.glob(str(GENO / "*" / "stable.json")):     # session stables override
        try:
            st = json.loads(Path(sf).read_text(encoding="utf-8"))
            sym = st.get("symbol") or Path(sf).parent.name
            spec = next((s for s in st.get("specialists", []) if s.get("session") == sess), None)
            if spec:
                out[sym] = {"tf": spec["tf"], "stop_atr": spec["stop_atr"],
                            "target_atr": spec["target_atr"], "conf_gate": spec["conf_gate"]}
            else:
                out.pop(sym, None)        # has a stable but NO specialist for this session → skip now
        except Exception:
            pass
    # 🛑 فلتر بحجم-الحساب يغطّي كل مسارات الدخول (مباشر + معلّقات gap/S-R التي تتجاوز فحص 2% الفردي):
    #   • الأسهم المفردة: تقفز فوق الوقف (فجوات) → تصفية [so]/خسائر >10% (NVDA −$14، UNH −$17).
    #   • المعادن (ذهب/فضة): أصغر لوت يخاطر 6-27% على حساب صغير (خسائر 2026-06-18: XAG −$27، XAU −$19)
    #     → استبعدها حتى تبلغ الحقوق $1500 (تُعاد تلقائياً متى كبر الحساب). FX/مؤشرات/كريبتو تبقى.
    _eq = 0.0
    try:
        _ai = mt5.account_info(); _eq = (_ai.equity if _ai else 0.0)
    except Exception:
        pass
    for sym in list(out):
        try:
            si = mt5.symbol_info(sym)
            if si and "\\Stocks\\" in (si.path or ""):
                out.pop(sym, None); continue
            # 🩸 استبعاد النزيف (30 يوماً): معادن XAU*/XAG* دائماً (سبريد مدموج: ذهب −$99/82%فوز،
            # فضة −$56) + مرفوعة x10/x100 + رموز نازفة صريحة مُثبتة.
            _su = sym.upper()
            if (_su.startswith("XAU") or _su.startswith("XAG")
                    or __import__("re").search(r"_X\d+", _su)
                    or sym in _BLEED_SYMS):
                out.pop(sym, None); continue
        except Exception:
            pass
    return out


def _genomes_OLD():
    out = {}
    for f in glob.glob(str(GENO / "*.json")):
        try:
            g = json.loads(Path(f).read_text(encoding="utf-8"))
            out[g["symbol"]] = g["config"]
        except Exception:
            pass
    return out


def _tf(mt5, s):
    return {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4}.get(s, mt5.TIMEFRAME_M15)


def _atr(r, n=14):
    t = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
            abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    return sum(t[-n:]) / n if t else 0.0


def _panel_veto(sym, cdir, max_age=180):
    try:
        d = json.loads((_COMMON / f"signal_{sym}.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) > max_age:
            return False
        act = d.get("action")
        if act in ("BUY", "SELL"):
            return (1 if act == "BUY" else -1) != cdir
    except Exception:
        pass
    return False


def _vmult(sym):
    try:
        import vol_regime as vr; return vr.target_mult(sym)
    except Exception:
        return 1.0


def _macro(cr, mt5, sym):
    """AGGRESSIVE: enter on the HIGHER-TF trend (M15+H1 agree) — many trades, every market.
    (M5 noise no longer required; user wants it firing freely like before.) Returns (dir, conf)."""
    dirs, confs = [], []
    for tf in ("M15", "H1"):
        d = cr.read_local(mt5, sym, tf) or {}
        dirs.append(int(d.get("dir", 0) or 0)); confs.append(float(d.get("confluence", 0.0)))
    macro = dirs[0] if (dirs and all(x == dirs[0] and x != 0 for x in dirs)) else 0
    return macro, (sum(confs) / len(confs) if confs else 0.0)


_RN = Path(r"C:\Users\Radhi\MT5\data\r_native")


def _agent_inputs():
    """Read the AGENTS' live outputs so the bots evolve WITH the agents:
    news_blocker → symbols to skip · winner_booster/regime_scaler → per-symbol lot multiplier."""
    blocked = set(); lotmult = {}
    try:
        blocked = set(json.loads((_RN / "news_blocked_symbols.json").read_text(encoding="utf-8")).get("blocked_symbols", []))
    except Exception: pass
    try:
        d = json.loads((_RN / "lot_multipliers.json").read_text(encoding="utf-8"))
        lotmult = d.get("multipliers", d) if isinstance(d, dict) else {}
    except Exception: pass
    return blocked, lotmult


def _intermarket():
    """The cross-asset brain's catch-up signals (intermarket.py). {SYM:{dir,conf,partner,why}}."""
    try:
        d = json.loads((_DD / "intermarket_signals.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) > 300:
            return {}
        return d.get("signals", {}) or {}
    except Exception:
        return {}


def _ledger_log(rec):
    """سجل صفقات الجينات: كل دخول يُدوَّن بكامل سياقه (الجين، الاتجاه، القيم، الجلسة، الوضع،
    الثقة، الساعة) — هذا ما يسمح لاحقاً بمعرفة متى يشتري ومتى يبيع كل جين ودمج المهارات."""
    try:
        import datetime
        rec["ts"] = time.time()
        rec["iso"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(_RN / "trade_ledger.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _delta_bias(sym):
    """دلتا قاعدة-التيك الحالية (سياق مقيس ~50% — تُسجَّل مع كل صفقة ليُحاكمها السجل لاحقاً)."""
    try:
        d = json.loads((_RN / "delta_state.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("_ts", 0)) > 180:
            return None
        return (d.get(sym) or {}).get("bias")
    except Exception:
        return None


def _hybrids():
    """🧬 الجينات المهجَّنة (evolution_director): لكل رمز+جلسة — مهارة الشراء من جين ومهارة
    البيع من جين آخر، أو بوّابة اتجاه لو جانب واحد فقط شاطر."""
    try:
        d = json.loads((_RN / "gene_hybrids.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("_ts", 0)) > 12 * 3600:
            return {}
        return d
    except Exception:
        return {}


def _zone_mem(sym):
    """ذاكرة المناطق المتعلِّمة (zone_memory): [(px, net, touches, score)] للرمز."""
    try:
        d = json.loads((_RN / "zone_memory.json").read_text(encoding="utf-8"))
        if time.time() - float((d.get("_meta") or {}).get("ts", 0)) > 1800:
            return []
        return [(z["px"], z["net"], z["touches"], z.get("score", 0))
                for z in (d.get(sym, {}) or {}).get("zones", [])]
    except Exception:
        return []


def _vol_factor(sym):
    """تحجيم بالتقلّب المتوقّع (vol_forecast/GARCH): لوت ∝ 1/التقلّب — مخاطرة ثابتة عبر الأنظمة."""
    try:
        d = json.loads((_RN / "vol_forecast.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("_ts", 0)) > 1800:
            return 1.0
        return float((d.get(sym) or {}).get("lot_factor", 1.0))
    except Exception:
        return 1.0


def _rs_gate(sym, cdir):
    """بوّابة القوة النسبية المقطعية (market_internals): لا تشترِ أضعف الربع (RS≤15) ولا تبع
    أقوى الربع (RS≥85) — لا تصارع تيار السوق العرضي. تعيد True لو يجب التخطّي."""
    try:
        d = json.loads((_RN / "market_internals.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("_ts", 0)) > 300:
            return False
        rs = (d.get(sym) or {}).get("rs")
        if rs is None:
            return False
        if cdir > 0 and rs <= 15:
            return True
        if cdir < 0 and rs >= 85:
            return True
    except Exception:
        pass
    return False


def _forecast_lot(session, conf, surge):
    """قاعدة مُثبتة أمامياً (forecast_lab): لو السياق الحالي يطابق شرطاً أثبت دقّة تنبؤ عالية،
    ارفع اللوت بمضاعفه المُكتسب. وإلا 1.0 (لا رفع بلا إثبات)."""
    try:
        d = json.loads((_RN / "forecast_rules.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) > 6 * 3600:
            return 1.0
        cb = "hi" if conf >= 0.75 else "mid" if conf >= 0.6 else "lo"
        sb = "agg" if surge >= 1.9 else "med" if surge >= 1.4 else "norm"
        return float((d.get("rules", {}).get(f"{session}|c-{cb}|s-{sb}") or {}).get("lot_mult", 1.0))
    except Exception:
        return 1.0


def _macro_bias(sym):
    """ميل الماكرو (macro_feed): سياق عبر-الأصول المؤسسي. يعيد −1..+1 (0 لو غير متاح/قديم)."""
    try:
        d = json.loads((_RN / "macro_state.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) > 3600:
            return 0.0
        return float((d.get("bias") or {}).get(sym, 0.0))
    except Exception:
        return 0.0


def _tournament_tilt():
    """🏆 بطولة التوائم: قيم مؤكَّدة (فازت مرتين بمبارزات حيّة) → ميل اتجاهي per-symbol."""
    try:
        d = json.loads((_RN / "tournament_confirmed.json").read_text(encoding="utf-8"))
        return {s: int(v.get("dir", 0)) for s, v in d.items()
                if time.time() - float(v.get("ts", 0)) < 48 * 3600}
    except Exception:
        return {}


def _mode_weights():
    """STRATEGY EVOLUTION (evolution_director): live-P&L-judged entry modes. A mode that keeps
    losing live is disabled; a winner gets a lot boost. {mode:{disabled,mult}}."""
    try:
        d = json.loads((_RN / "mode_weights.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) > 3600:
            return {}
        return d.get("modes", {}) or {}
    except Exception:
        return {}


def _risk_mult():
    """TREATMENT hook from risk_manager (ICA step 5): when overall risk is HIGH/CRITICAL the
    register orders smaller lots — risk-aware sizing the trader OBEYS."""
    try:
        d = json.loads((_RN / "risk_register.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) > 300:
            return 1.0
        return float(d.get("lot_mult", 1.0))
    except Exception:
        return 1.0


def _emergency():
    try:
        d = json.loads((_RN / "risk_register.json").read_text(encoding="utf-8"))
        return bool(d.get("emergency")) and time.time() - float(d.get("ts", 0)) < 300
    except Exception:
        return False


def _directive():
    """The LLM analyst's per-symbol order the bot OBEYS (llm_analyst.py). DISCIPLINE gate:
    only symbols it greenlights (TRADE / TRADE_LIGHT) may open; WAIT/AVOID are skipped."""
    try:
        d = json.loads((_RN / "market_directive.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) > 300:
            return {}
        return d.get("symbols", {}) or {}
    except Exception:
        return {}


def _place_pending(mt5, sym, cdir, info, lot, level, stop_d, tgt_d):
    """Arm a STOP pending order beyond a sweep level / gap edge (catch the breakout/refill)."""
    if level is None or stop_d <= 0:
        return None
    if cdir > 0:
        ot = mt5.ORDER_TYPE_BUY_STOP; price = round(level + info.point * 5, info.digits)
        sl = round(price - stop_d, info.digits); tp = round(price + tgt_d, info.digits)
    else:
        ot = mt5.ORDER_TYPE_SELL_STOP; price = round(level - info.point * 5, info.digits)
        sl = round(price + stop_d, info.digits); tp = round(price - tgt_d, info.digits)
    res = mt5.order_send({"action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": float(lot),
                          "type": ot, "price": price, "sl": sl, "tp": tp, "deviation": 50,
                          "magic": MAGIC, "comment": "F2B-PEND",
                          "type_time": mt5.ORDER_TIME_SPECIFIED, "expiration": int(time.time()) + 1800,
                          "type_filling": mt5.ORDER_FILLING_IOC})
    return getattr(res, "retcode", None)


def _sr_levels(mt5, sym, info):
    """Objective multi-TF S/R: confirmed pivots on H1(300)+D1(120), supports below / resistances
    above current price, plus H1 ATR. The user's 'مستويات سعرية على جميع الفريمات'."""
    rH = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 300)
    rD = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 120)
    tick = mt5.symbol_info_tick(sym)
    if rH is None or len(rH) < 60 or not tick:
        return None
    price = (tick.bid + tick.ask) / 2
    atr = _atr(rH)
    H, L = [], []
    for r, w in ((rH, 4), (rD, 3)):
        if r is None or len(r) < 2 * w + 3:
            continue
        for i in range(w, len(r) - w):
            seg = r[i - w:i + w + 1]
            if r[i]["high"] == max(x["high"] for x in seg):
                H.append(float(r[i]["high"]))
            if r[i]["low"] == min(x["low"] for x in seg):
                L.append(float(r[i]["low"]))
    sups = sorted({round(x, info.digits) for x in L if x < price}, reverse=True)
    ress = sorted({round(x, info.digits) for x in H if x > price})
    return price, atr, sups, ress


def _place_sr_limits(mt5, sym, info, n_pend):
    """أوامر معلقة عند المستويات: BUY_LIMIT at the nearest strong support (target = next
    resistance) + SELL_LIMIT at the nearest resistance (target = next support). DISCIPLINED:
    fixed minimum lot, hard SL beyond the level, R:R >= 1.3, 4h expiry, one per side per symbol."""
    lv = _sr_levels(mt5, sym, info)
    if not lv:
        return [], n_pend
    price, atr, sups, ress = lv
    if atr <= 0:
        return [], n_pend
    existing = [o for o in (mt5.orders_get(symbol=sym) or [])
                if o.magic == MAGIC and "SRLIM" in (o.comment or "")]
    if existing:
        return [], n_pend
    placed = []
    lot = info.volume_min
    exp = int(time.time()) + 4 * 3600
    sup = next((s for s in sups if 0.5 * atr <= price - s <= 3 * atr), None)
    res = next((x for x in ress if 0.5 * atr <= x - price <= 3 * atr), None)
    def _send(ot, entry, sl, tp, tag):
        nonlocal n_pend
        if n_pend >= MAX_PENDING or (tp - entry) == 0:
            return
        rr = abs(tp - entry) / max(1e-9, abs(entry - sl))
        if rr < 1.3:
            return
        r = mt5.order_send({"action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": float(lot),
                            "type": ot, "price": round(entry, info.digits),
                            "sl": round(sl, info.digits), "tp": round(tp, info.digits),
                            "deviation": 50, "magic": MAGIC, "comment": "F2B-SRLIM",
                            "type_time": mt5.ORDER_TIME_SPECIFIED, "expiration": exp,
                            "type_filling": mt5.ORDER_FILLING_IOC})
        if getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            n_pend += 1; placed.append(f"{sym}:{tag}@{round(entry, info.digits)}")
    # ذاكرة المناطق: تجنّب مستوى ثبت أنه خاسر (net<-2 بعد >=3 لمسات) — تعلّم من صفقاتنا نحن
    zm = _zone_mem(sym)
    def _zone_bad(level):
        return any(abs(px - level) <= 0.5 * atr and t >= 3 and net < -2 for px, net, t, _ in zm)
    if sup and not _zone_bad(sup):              # السعر يلمس الدعم → شراء، الهدف المقاومة التالية
        tp_lvl = next((x for x in ress if x > sup + 1.3 * atr), sup + 2 * atr)
        _send(mt5.ORDER_TYPE_BUY_LIMIT, sup, sup - 1.0 * atr, tp_lvl, "BUYLIM")
    if res and not _zone_bad(res):              # السعر يلمس المقاومة → بيع، الهدف الدعم التالي
        tp_lvl = next((x for x in sups if x < res - 1.3 * atr), res - 2 * atr)
        _send(mt5.ORDER_TYPE_SELL_LIMIT, res, res + 1.0 * atr, tp_lvl, "SELLLIM")
    return placed, n_pend


def _cancel_stale_pendings(mt5):
    """برو-أكتيف: نحذف فقط معلّقات الاختراق (STOP) الأقدم من 30د (السيق فات). أما الحدود السعرية
    (LIMIT) عند المناطق فهي تموضع مسبق مقصود — نتركها تنتظر وصول السعر حتى انتهاء صلاحيتها (4س).
    (الخطأ السابق: كان يلغي تموضعنا المسبق قبل ما يصله السعر = دخول متأخّر بدل البرو-أكتيف.)"""
    try:
        _LIMITS = (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT)
        for o in (mt5.orders_get() or []):
            if (o.magic == MAGIC and o.type not in _LIMITS
                    and o.time_setup and time.time() - o.time_setup > 1800):
                mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
    except Exception:
        pass


def _live_pnl(mt5, hours=12):
    """Each symbol's REAL live P&L for this bot — so it can LEARN FROM ITS OWN RESULTS."""
    out = {}
    try:
        dl = [d for d in (mt5.history_deals_get(int(time.time() - hours * 3600), int(time.time())) or [])
              if d.entry == 1 and d.magic in (MAGIC, HYB_MAGIC)]
        for d in dl:
            t = out.setdefault(d.symbol, [0, 0.0]); t[0] += 1; t[1] += d.profit + d.commission + d.swap
    except Exception:
        pass
    return out


# 🩸 استبعاد بنيوي طويل المدى: رموز أثبت هذا البوت حياً (عيّنة كافية) أنه بلا حافّة عليها —
# win-rate منخفض + صافي سالب عبر 30 يوماً. حارس الـ12h الردّي يفوته الخاسر البطيء (لا يجمع
# 4-في-12h أبداً)؛ هذا يسدّ تلك الثغرة. يُطبَّق على مسار الترابط المضاربي فقط (بلا جين) — لا يمسّ
# الروستر الأساسي. مُثبَت OOS: النفط 101 صفقة، 18% فوز، سالب في 3/3 كتل تداولها. (مُخبّأ 30د.)
_NOEDGE_CACHE = {"ts": 0.0, "set": set()}


def _structural_noedge(mt5, days=30, min_n=15, max_wr=0.30, refresh=1800):
    now = time.time()
    if now - _NOEDGE_CACHE["ts"] < refresh and _NOEDGE_CACHE["ts"] > 0:
        return _NOEDGE_CACHE["set"]
    bad = set()
    try:
        agg = {}
        for d in (mt5.history_deals_get(int(now - days * 86400), int(now)) or []):
            if d.entry == 1 and d.magic in (MAGIC, HYB_MAGIC):
                a = agg.setdefault(d.symbol, [0, 0, 0.0])
                a[0] += 1; a[1] += (d.profit + d.commission + d.swap > 0); a[2] += d.profit + d.commission + d.swap
        for s, (n, w, net) in agg.items():
            if n >= min_n and (w / n) < max_wr and net < 0:
                bad.add(s)
    except Exception:
        pass
    _NOEDGE_CACHE["ts"] = now; _NOEDGE_CACHE["set"] = bad
    return bad


def _secure_cfg(sym):
    """Per-symbol LEARNED profit-securing speed (from secure_learner). Reversal-prone symbols
    lock fast + trail tight; trending symbols let winners run."""
    try:
        d = json.loads((_DD / f"secure_config_{sym}.json").read_text(encoding="utf-8"))
        return float(d.get("be_atr", 0.10)), float(d.get("trail_tight", 1.0))
    except Exception:
        return 0.10, 1.0


def _manage(mt5, sym, poss):
    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 30)
    atr = _atr(r) if r is not None and len(r) > 2 else 0.0
    if atr <= 0 or not info or not tick:
        return
    be_atr, trail_atr = _secure_cfg(sym)      # LEARNED per-symbol secure speed
    _mom = 1.0; _tdir = 0
    try:                                       # ديناميكي: زخم قوي → تأمين أصبر وتريل أوسع
        _h2 = [float(x["high"]) for x in r]; _l2 = [float(x["low"]) for x in r]; _c2 = [float(x["close"]) for x in r]
        be_atr, trail_atr = dstop.dynamic_manage(_h2, _l2, _c2, be_atr, trail_atr, atr)
        _mom = dstop.momentum_mult(_h2, _l2, _c2, atr)
        _tdir = 1 if _c2[-1] > _c2[-6] else -1
    except Exception:
        pass
    for p in poss:
        is_buy = (p.type == mt5.POSITION_TYPE_BUY)
        cur = tick.bid if is_buy else tick.ask
        prof = (cur - p.price_open) if is_buy else (p.price_open - cur)
        _favor = (_tdir == (1 if is_buy else -1))
        _runner = _favor and _mom >= 1.25 and prof > 1.0 * atr
        # 🏃 RUNNER MODE (طلب المستخدم: «ليه نخاف ونغلق بدري؟»): الترند معنا بزخم + ربح ≥1×ATR
        # → نحرّر سقف الربح (TP→0) ونترك التريل الديناميكي يركض معه لأقصى الحركة
        if _runner and p.tp:
            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": sym,
                            "position": p.ticket, "sl": p.sl, "tp": 0.0})
        # DIVE EXIT: a strong rejection wick AGAINST us while in profit → lock the dive at market now
        # (إلا في وضع الرانر — ذيل واحد لا يطرد صفقة راكضة مع ترند قوي)
        if prof > 0 and ms.opposing_wick(r, is_buy) and not _runner:
            lock = round(cur - (info.point * 3 if is_buy else -info.point * 3), info.digits)
            improve = (lock > (p.sl or 0)) if is_buy else ((p.sl == 0) or (lock < p.sl))
            if improve:
                mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": sym,
                                "position": p.ticket, "sl": lock, "tp": p.tp})
            continue
        if prof < be_atr * atr:               # lock breakeven at the LEARNED speed for this symbol
            continue
        be = round(p.price_open, info.digits)
        trail = round((cur - trail_atr * atr) if is_buy else (cur + trail_atr * atr), info.digits)
        new_sl = max(be, trail) if is_buy else min(be, trail)
        improve = (new_sl > (p.sl or 0)) if is_buy else ((p.sl == 0) or (new_sl < p.sl))
        if improve:
            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": sym,
                            "position": p.ticket, "sl": new_sl, "tp": p.tp})


def cycle(mt5, cr):
    acct = mt5.account_info()
    if not acct:
        return "no acct"
    genomes = _genomes()
    allpos = [p for p in (mt5.positions_get() or []) if p.magic in (MAGIC, HYB_MAGIC)]
    bysym = {}
    for p in allpos:
        bysym.setdefault(p.symbol, []).append(p)
    # manage everything we hold
    for sym, ps in bysym.items():
        try: _manage(mt5, sym, ps)
        except Exception: pass
    # daily kill
    import datetime
    start = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    dl = [d for d in (mt5.history_deals_get(int(start), int(time.time())) or []) if d.magic in (MAGIC, HYB_MAGIC) and d.entry == 1]
    if sum(d.profit + d.commission + d.swap for d in dl) <= -DAILY_KILL_PCT / 100.0 * acct.equity:
        return f"DAILY KILL · holding {len(allpos)}"
    opened = []
    cd = {}
    try: cd = json.loads((_DD / "multi_cooldown.json").read_text(encoding="utf-8"))
    except Exception: pass
    nowt = time.time()
    blocked, lotmult = _agent_inputs()           # work WITH the agents (news block + lot boost)
    livepnl = _live_pnl(mt5)                      # SELF-IMPROVE: learn from this bot's own results
    imkt = _intermarket()                         # CROSS-ASSET brain: catch-up + paired signals
    if _emergency():
        return f"EMERGENCY - no new entries; managing {len(allpos)} positions"
    directive = _directive()                      # LLM analyst: the discipline gate the bot OBEYS
    _cancel_stale_pendings(mt5)
    n_pend = len([o for o in (mt5.orders_get() or []) if o.magic == MAGIC])
    pended = []
    # أوامر معلقة عند المستويات (S/R limits) — منضبطة: لوت أدنى، وقف صارم، R:R>=1.3، تنتهي بـ4س
    if len(allpos) < MAX_TOTAL_POS and not _kill_active() and not _mode_weights().get("srlim", {}).get("disabled"):
        for sym in genomes:
            if sym in blocked:
                continue
            drv0 = directive.get(sym)
            if drv0 and drv0.get("action") in ("WAIT", "AVOID"):
                continue
            info0 = mt5.symbol_info(sym)
            t0 = mt5.symbol_info_tick(sym)
            if not info0 or not t0 or not t0.bid:
                continue
            try:
                pl, n_pend = _place_sr_limits(mt5, sym, info0, n_pend)
                pended += pl
            except Exception:
                pass
    _sblock = _session_blocks_entry()                    # بوّابة جلسة الفوركس (لندن/نيويورك)
    if len(allpos) < MAX_TOTAL_POS and not _kill_active():   # 🛑 الإيقاف الطارئ يمنع الفتح؛ الجلسة تُطبَّق per-symbol أدناه
        for sym, cfg in genomes.items():
            if not _mkt_open(mt5, sym):                  # 🟢 تداول المفتوح فعلاً فقط (كريبتو بالعطلة، الكل بالأسبوع)
                continue
            if _sblock and not _is_crypto(sym):          # بوّابة الجلسة للفوركس/المؤشرات؛ الكريبتو 24/7 يتجاوزها
                continue
            held = bysym.get(sym, [])
            is_pyr = bool(held)
            if is_pyr and len(held) >= MAX_STACK_PER_SYM:
                continue                          # only cap is per-symbol exposure (risk)
            if is_pyr and _risk_mult() < 1.0 and sum(x.profit for x in held) <= 0:
                continue                          # RISK TREATMENT: الخطر العالي يمنع التكديس على
                                                  # المتعادل/الخاسر فقط — الإضافة على رابحٍ بترند
                                                  # تبقى مسموحة (الأرباح المقفولة تحمينا)
            if sym in blocked:                    # AGENT: news_blocker says stay out
                continue
            drv = directive.get(sym)              # OBEY the LLM analyst (discipline: trade only greenlit)
            if drv and drv.get("action") in ("WAIT", "AVOID"):
                continue
            lp = livepnl.get(sym)                 # SELF-IMPROVE: bench symbols bleeding LIVE
            if lp and lp[0] >= 4 and lp[1] < LIVE_LOSS_CUT:
                continue                          # this symbol keeps losing real money -> stop trading it
            cd_need = 30 if is_pyr else COOLDOWN_S   # machine-gun adds every ~30s; fresh entries slower
            if nowt - float(cd.get(sym, 0)) < cd_need:
                continue
            if len(allpos) + len(opened) >= MAX_TOTAL_POS:
                break
            info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
            if not info or not tick or not tick.bid:
                continue
            cdir, conf = _macro(cr, mt5, sym)
            # 🧬 HYBRID GENES: مهارة الشراء من جين + مهارة البيع من جين آخر (لكل رمز+جلسة)
            _sess_now = _session_now()
            _hyb = _hybrids().get(sym, {}).get(_sess_now)
            if _hyb and cdir != 0:
                if _hyb.get("allow") == "long" and cdir < 0:
                    continue                      # هذا الجين أثبت أنه يخسر بالبيع → شراء فقط
                if _hyb.get("allow") == "short" and cdir > 0:
                    continue                      # أثبت أنه يخسر بالشراء → بيع فقط
                _side_vals = _hyb.get("long" if cdir > 0 else "short")
                if _side_vals:
                    cfg = {**cfg, **_side_vals}   # قيم الجانب من الجين الشاطر فيه
            cg = float(cfg.get("conf_gate", 0.6))
            if cdir != 0 and _rs_gate(sym, cdir):  # 📊 لا تصارع المقطع العرضي (أضعف الربع/أقوى الربع)
                continue
            if cdir != 0:                          # 💱 فلتر السوب: كاري ليلي مكلف على السوينق يخصم ثقة
                conf = max(0.0, conf - bc.swap_penalty(mt5, sym, cdir, cfg.get("tf", "M15")))
            # === fast microstructure (M5) for the AGGRESSIVE modes: dive / gap / wick-reversal ===
            rf = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 80)
            mdir, mstr = ms.detect_momentum(rf)
            wdir, _wd = ms.detect_wick_rev(rf)
            gdir, gsz, _glvl = ms.detect_gap(rf)
            reason = "macro"
            # 🏆 TOURNAMENT: live-duel-confirmed direction agrees → boost; disagrees → lighter
            _tt = _tournament_tilt().get(sym, 0)
            if _tt and cdir == _tt:
                conf = min(0.99, conf + 0.10)
            # 🌐 MACRO (مؤسسي): ميل عبر-الأصول يوافق الاتجاه → ثقة أعلى؛ يعاكسه بقوة → تخطّ
            _mb = _macro_bias(sym)
            if _mb and cdir != 0:
                if (_mb > 0) == (cdir > 0):
                    conf = min(0.99, conf + 0.06 * abs(_mb))
                elif abs(_mb) >= 1.0:
                    continue                      # الماكرو يعاكس بقوة كاملة → لا تدخل ضدّ التيار
            # CROSS-ASSET catch-up: agree → boost confluence; macro-flat → adopt intermarket direction
            sig = imkt.get(sym)
            if sig:
                if cdir == sig["dir"]:
                    conf = min(0.99, conf + INTERMARKET_BOOST); reason = "macro+xasset"
                elif cdir == 0:
                    cdir = sig["dir"]; conf = max(conf, float(sig["conf"])); reason = "xasset"
            # LIQUIDITY-SWEEP wick reversal (ظهور الذيل → ادخل عكس) — standalone reverse trigger
            if cdir == 0 and wdir != 0:
                cdir = wdir; conf = max(conf, WICK_REV_CONF); reason = "wick-rev"
            # MOMENTUM DIVE (الغوص مع القفزة) — jump in WITH a strong impulse even if macro is flat
            if cdir == 0 and mstr >= 1.5:
                cdir = mdir; conf = max(conf, cg + 0.05); reason = "dive"
            # PENDING STOP on a fresh gap (أمر معلّق) — armed even with no direct entry, catches the continuation
            if (gdir != 0 and gsz >= GAP_PEND_ATR and not is_pyr and n_pend < MAX_PENDING
                    and not _mode_weights().get("gap_pend", {}).get("disabled")
                    and not any(o.symbol == sym for o in (mt5.orders_get() or []) if o.magic == MAGIC)):
                fatr = ms._atr(rf)
                if fatr > 0:
                    rc = _place_pending(mt5, sym, gdir, info, max(info.volume_min, info.volume_min * 2),
                                        ms.sweep_level(rf, gdir),
                                        float(cfg.get("stop_atr", 2.0)) * fatr, float(cfg.get("target_atr", 3.0)) * fatr)
                    if rc == mt5.TRADE_RETCODE_DONE:
                        n_pend += 1; pended.append(f"{sym}:{'BUY' if gdir>0 else 'SELL'}STOP")
            if cdir == 0 or conf < cg + MIN_CONF_BUFFER:
                continue
            # 🧭 حارس الذيل (مُثبت OOS): على الرموز المتقلّبة فقط، امنع الدخول عكس ميل EMA50/M15 — هذا ما
            # صنع خسائر −$27 فضة/−$19 ذهب (شراء سكين ساقط). FX تُترك (الارتداد يربح فيها). سببي تماماً.
            if _is_volatile(sym) and _htf_opposes(mt5, sym, cdir):
                continue
            if is_pyr:
                # CONCURRENT ENTRIES: add on a FRESH signal even while holding (don't wait to close).
                # Same-direction only (a counter-signal is handled by wick-reversal management); the
                # normal conf_gate + LLM directive + live-loss bench keep quality. (Was: needed 0.80
                # conviction + winning to stack — now any fresh gated signal in the held direction.)
                same = all((p.type == mt5.POSITION_TYPE_BUY) == (cdir > 0) for p in held)
                if not same:
                    continue
            if _panel_veto(sym, cdir):
                continue
            r = mt5.copy_rates_from_pos(sym, _tf(mt5, cfg.get("tf", "M15")), 0, 60)
            if r is None or len(r) < 30:
                continue
            atr = _atr(r)
            if atr <= 0:
                continue
            # 🗺️ ZONE MEMORY: تعلّم المناطق من صفقاتنا — قرب منطقة رابحة مثبتة = مكافأة ثقة،
            # وقرب منطقة خاسرة مثبتة (>=3 لمسات و net<-2) = تخطَّ الدخول
            _zskip = False
            _mid = (tick.bid + tick.ask) / 2
            for _px, _net, _t, _sc in _zone_mem(sym):
                if _t >= 3 and abs(_px - _mid) <= 0.5 * atr:
                    if _net < -2:
                        _zskip = True              # منطقة مثبتة الخسارة من صفقاتنا → لا تدخل هنا
                    elif _net > 2:
                        conf = min(0.99, conf + 0.05)   # منطقة مثبتة الربح → ثقة إضافية
                    break
            if _zskip:
                continue
            vm = _vmult(sym)
            _hi = [float(x["high"]) for x in r]; _lo = [float(x["low"]) for x in r]; _cl = [float(x["close"]) for x in r]
            _entry_px = (tick.ask if cdir > 0 else tick.bid)
            stop_d, _slwhy = dstop.dynamic_sl_distance(_hi, _lo, _cl, cdir, _entry_px,
                                                       float(cfg.get("stop_atr", 2.0)), atr)
            if not stop_d:
                stop_d = float(cfg.get("stop_atr", 2.0)) * atr
            tgt_d = max(float(cfg.get("target_atr", 3.0)) * atr * vm, stop_d * 1.3)
            tv = info.trade_tick_value / info.trade_tick_size if info.trade_tick_size else 1.0
            conv = 1.0 + (CONV_MAX_MULT - 1.0) * max(0.0, (conf - cg) / max(1e-9, 1 - cg))
            # COMPOUNDING: lot grows with EQUITY (compound) × CONFIDENCE (conv) × EARNED tier
            # (the more the balance grows, the more it's earned the right to risk — up to 3x).
            earn = max(1.0, min(3.0, acct.equity / 100.0))
            lot = (RISK_PCT / 100.0 * acct.equity * conv * earn) / (stop_d * tv) if stop_d * tv > 0 else info.volume_min
            lot *= float(lotmult.get(sym, 1.0))   # AGENT: winner_booster/regime_scaler lot multiplier
            try:                                  # 🎛️ حوكمة المايسترو (خنق الفرقة النزّافة، fail-safe 1.0)
                import json as _j
                _gm = float(_j.load(open(r"C:\Users\Radhi\MT5\data\r_native\engine_governance.json", encoding="utf-8"))
                            .get("mults", {}).get("20260608", 1.0))
                lot *= max(0.1, min(1.5, _gm))
            except Exception:
                pass
            if mdir == cdir and mstr >= DIVE_STR:  # MOMENTUM DIVE: high-lot, one-direction with the impulse
                lot *= DIVE_LOT_MULT; reason = "dive" if reason == "macro" else reason + "+dive"
            if is_pyr and sum(x.profit for x in held) > 0 and conf >= 0.75:
                lot *= 1.3                        # 🏃 التكبير على القوة: رابح + ثقة عالية → إضافة أكبر
            # 🔥 CONVICTION SURGE (هجومي): كل ما اتفقت طبقات أكثر = اللوت أكبر (حتى ×2.5)
            _agree = 1
            if conf >= cg + 0.10:
                _agree += 1                       # ثقة عالية جداً فوق البوّابة
            if _tt and _tt == cdir:
                _agree += 1                       # 🏆 البطولة تؤكّد الاتجاه
            _dlt = _delta_bias(sym)
            if _dlt is not None and ((_dlt > 15 and cdir > 0) or (_dlt < -15 and cdir < 0)):
                _agree += 1                       # 📊 الدلتا توافق
            sig = imkt.get(sym) or {}
            if int(sig.get("dir", 0) or 0) == cdir:
                _agree += 1                       # 🔗 الترابط يوافق
            surge = {1: 1.0, 2: 1.4, 3: 1.9, 4: 2.3, 5: 2.5}.get(min(5, _agree), 1.0)
            if _session_now() == "ASIAN":        # 📼 الشريط (2026-06-15): آسيا تخسر في كل التقطيعات
                # would_enter 21% فوز -10R · confluence>=0.7 فقط 5% فوز = فخّ (الثقة العالية أسوأ).
                # لذا في آسيا نقلّص التضخيم لأدنى حد (1.2) — لا نكافئ التوافق في جلسة مثبتة الضعف.
                surge = min(surge, 1.2)
            lot *= surge
            if surge >= 1.9:
                reason = (reason + "+surge").replace("macro+surge", "surge")
            # STRATEGY EVOLUTION: obey mode_weights — a live-losing mode is benched, a winner boosted
            _mw = _mode_weights()
            _mode = {"wick-rev": "wick_rev"}.get(reason.split("+")[0], reason.split("+")[0])
            _ms = _mw.get(_mode, {})
            if _ms.get("disabled"):
                continue
            lot *= float(_ms.get("mult", 1.0))
            if drv and drv.get("action") == "TRADE_LIGHT":   # OBEY: partial agreement → lighter size
                lot *= 0.5
            lot *= _risk_mult()                  # OBEY risk_manager: HIGH→×0.7 · CRITICAL→×0.4
            lot *= _vol_factor(sym)              # 📉 vol-targeting بـGARCH: لوت أصغر وقت العاصفة المتوقّعة
            lot *= _forecast_lot(_session_now(), conf, surge)  # 🔮 رفع اللوت على شرط أثبت دقّته أمامياً
            # cap GROWS with equity (≈ LOT_PER_1K lots per $1000) so it never gets stuck at a fixed cap
            cap = max(info.volume_min * 5, (acct.equity / 1000.0) * LOT_PER_1K)
            lot = max(info.volume_min, min(cap, round(lot / info.volume_step) * info.volume_step))
            # 🛑 سقف الخسارة الصارم: بعد كل المضاعفات، اخسر صفقة ≤ %MAX_TRADE_RISK من الحقوق مهما كان.
            _maxloss = MAX_TRADE_RISK / 100.0 * acct.equity
            if stop_d * tv > 0:
                if info.volume_min * stop_d * tv > _maxloss:
                    continue                              # حتى أدنى لوت يتجاوز السقف → تخطّ (لا يناسب الحساب)
                if lot * stop_d * tv > _maxloss:
                    lot = max(info.volume_min, round((_maxloss / (stop_d * tv)) / info.volume_step) * info.volume_step)
            if cdir > 0:
                side = "BUY"; entry = tick.ask; sl = round(entry - stop_d, info.digits); tp = round(entry + tgt_d, info.digits); ot = mt5.ORDER_TYPE_BUY
            else:
                side = "SELL"; entry = tick.bid; sl = round(entry + stop_d, info.digits); tp = round(entry - tgt_d, info.digits); ot = mt5.ORDER_TYPE_SELL
            _omagic = HYB_MAGIC if _hyb else MAGIC          # 🧬 الهجين برقمه المميز ليُرى في MT5
            _ocomment = ("HYB-" + reason[:5]) if _hyb else f"F2B-{reason[:9]}"
            if not bc.margin_ok(mt5, sym, lot, entry, side.lower()):   # 🛡️ حارس الهامش الدقيق (order_calc_margin)
                continue
            _hedge, _hr = pg.would_hedge(mt5, sym, ot, _omagic)        # 🚫 لا تفتح عكس محرّكٍ آخر منّا
            if _hedge:
                print(f"[MULTI] skip {sym}: {_hr}", flush=True)
                continue
            # ⚡ تنفيذ سريع ودقيق: السوق سريع — عند requote/تغيّر السعر أعد المحاولة بسعر طازج فوراً
            # (3 محاولات) بدل إسقاط القرار صامتاً = القرار يُنفَّذ ولا تفوت الفرصة، وبسعر حالي دقيق.
            _RQ = {getattr(mt5, "TRADE_RETCODE_REQUOTE", 10004), getattr(mt5, "TRADE_RETCODE_PRICE_CHANGED", 10020),
                   getattr(mt5, "TRADE_RETCODE_PRICE_OFF", 10021)}
            try:
                import lot_guard                           # 🛑 السقف الصلب المُثبت OOS (الحجم = الرافعة الوحيدة)
                lot, _ = lot_guard.cap(mt5, sym, lot, acct.equity)
            except Exception:
                pass
            res = None; rc = None
            for _try in range(3):
                res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lot),
                                      "type": ot, "price": entry, "sl": sl, "tp": tp, "deviation": 50,
                                      "magic": _omagic, "comment": _ocomment, "type_filling": mt5.ORDER_FILLING_IOC})
                rc = getattr(res, "retcode", None)
                if rc not in _RQ:
                    break                                   # نجح أو خطأ حقيقي (مال/سوق) — لا تعِد
                _tk = mt5.symbol_info_tick(sym)              # سعر طازج وأعد المحاولة
                if not _tk:
                    break
                entry = _tk.ask if cdir > 0 else _tk.bid
                sl = round(entry - stop_d if cdir > 0 else entry + stop_d, info.digits)
                tp = round(entry + tgt_d if cdir > 0 else entry - tgt_d, info.digits)
            if rc == mt5.TRADE_RETCODE_DONE:
                opened.append(f"{sym}:{side}"); cd[sym] = nowt
                _ledger_log({"ticket": int(getattr(res, "order", 0) or 0), "sym": sym,
                             "dir": int(cdir), "side": side, "mode": reason.split("+")[0],
                             "conf": round(conf, 3), "session": _sess_now,
                             "values": {"tf": cfg.get("tf"), "stop_atr": cfg.get("stop_atr"),
                                        "target_atr": cfg.get("target_atr"),
                                        "conf_gate": cfg.get("conf_gate")},
                             "lot": float(lot), "hybrid": bool(_hyb), "magic": _omagic,
                             "delta": _delta_bias(sym)})
    # 🔗 دخول الترابط: أزواج نشطة خارج الروستر (مثل USOIL عبر الذهب/الفضة العكسي) — لا نترك شيئاً.
    # إشارة لحاق قوية + لا جين لها هذه الجلسة → ندخل بإعداد محافظ (لوت أدنى، وقف ATR، محكوم).
    if len(allpos) < MAX_TOTAL_POS and not _emergency() and not _kill_active() and not _session_blocks_entry():
        _noedge = _structural_noedge(mt5)             # 🩸 رموز بلا حافّة مُثبتة (النفط 18% فوز/101) — لا تُضارب بها
        for xsym, sig in imkt.items():
            if xsym in genomes or xsym in blocked:
                continue
            if xsym in _noedge:                       # استبعاد بنيوي 30د (يسدّ ثغرة حارس الـ12h)
                continue
            if float(sig.get("conf", 0)) < 0.65 or not sig.get("dir"):
                continue
            lp = livepnl.get(xsym)                         # 🩸 نفس انضباط الخسارة الحيّ للمسار الأساسي:
            if lp and lp[0] >= 4 and lp[1] < LIVE_LOSS_CUT:  # رمز ينزف حياً (USOIL نزف -$221) → لا تدخله عبر الترابط
                continue
            if any(p.symbol == xsym for p in allpos):     # مركز قائم على الرمز
                continue
            info2 = mt5.symbol_info(xsym); t2 = mt5.symbol_info_tick(xsym)
            if not info2 or not t2 or not t2.bid or (time.time() - t2.time) > 120:
                continue
            xdir = int(sig["dir"])
            if _rs_gate(xsym, xdir):                       # لا تصارع المقطع العرضي
                continue
            r2 = mt5.copy_rates_from_pos(xsym, mt5.TIMEFRAME_M15, 0, 30)
            if r2 is None or len(r2) < 20:
                continue
            atr2 = _atr(r2)
            if atr2 <= 0:
                continue
            lot2 = info2.volume_min
            entry2 = t2.ask if xdir > 0 else t2.bid
            sl2 = round(entry2 - 2.0 * atr2 if xdir > 0 else entry2 + 2.0 * atr2, info2.digits)
            tp2 = round(entry2 + 3.0 * atr2 if xdir > 0 else entry2 - 3.0 * atr2, info2.digits)
            if not bc.margin_ok(mt5, xsym, lot2, entry2, "buy" if xdir > 0 else "sell"):
                continue
            _hedge, _hr = pg.would_hedge(mt5, xsym, mt5.ORDER_TYPE_BUY if xdir > 0 else mt5.ORDER_TYPE_SELL, MAGIC)
            if _hedge:                                     # 🚫 لا تصارع محرّكاً آخر منّا على نفس الرمز
                print(f"[MULTI] skip xcorr {xsym}: {_hr}", flush=True)
                continue
            rr2 = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": xsym, "volume": float(lot2),
                                  "type": mt5.ORDER_TYPE_BUY if xdir > 0 else mt5.ORDER_TYPE_SELL,
                                  "price": entry2, "sl": sl2, "tp": tp2, "deviation": 50,
                                  "magic": MAGIC, "comment": f"F2B-xcorr-{(sig.get('partner') or '')[:4]}"[:28],
                                  "type_filling": mt5.ORDER_FILLING_IOC})
            if getattr(rr2, "retcode", None) == mt5.TRADE_RETCODE_DONE:
                opened.append(f"{xsym}:xcorr")
                allpos = [p for p in (mt5.positions_get() or []) if p.magic in (MAGIC, HYB_MAGIC)]
                if len(allpos) >= MAX_TOTAL_POS:
                    break
    if opened:
        try: (_DD / "multi_cooldown.json").write_text(json.dumps(cd), encoding="utf-8")
        except Exception: pass
    flt = sum(p.profit for p in allpos)
    return (f"holding {len(allpos)} float {flt:+.2f} · xasset {len(imkt)} sig · pend {n_pend}"
            + (f" | OPENED {opened}" if opened else "")
            + (f" | PENDING {pended}" if pended else ""))


def main(argv=None):
    import MetaTrader5 as mt5, chart_read as cr
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", action="store_true"); a = ap.parse_args(argv)
    # 🔒 قفل وحيد: عدّة حُرّاس (watchdog/autopilot/keepalive) قد تُطلق نسخاً متعدّدة تتسابق على نفس
    # إشارات magic 20260608 (تتجاوز سقف العملة والتهدئة) = إفراط تداول خطر على حساب $100. ربط منفذ محلي
    # ثابت (8708) يضمن نسخة منفّذة واحدة فقط (يتحرّر تلقائياً عند موت العملية).
    import socket
    _lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock.bind(("127.0.0.1", 8708)); _lock.listen(1)
        main._singleton_lock = _lock          # إبقاء المرجع حيّاً طوال عمر العملية
    except OSError:
        print("[MULTI] نسخة منفّذة أخرى تعمل بالفعل — خروج (قفل وحيد 8708)", flush=True); return 0
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print(f"[MULTI] trading {len(_genomes())} deployed genomes · magic {MAGIC} · max {MAX_TOTAL_POS} pos · risk {RISK_PCT}% · DEMO", flush=True)
    try:
        while True:
            try: print(f"[MULTI] {cycle(mt5, cr)}", flush=True)
            except Exception as e: print(f"[MULTI] err {e}", flush=True)
            if not a.loop: break
            time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
