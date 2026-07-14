"""gold_straddle_3627.py — ستادل/انعكاس الذهب المستمر (Stop-and-Reverse). يطابق الفيديوين.

طلب المستخدم (2026-06-11، من فيديوين MT5 موبايل · @HZKMT5ALGO2026):
  • الذهب XAUUSD على فريم M1، مستمر دائماً داخل السوق (ليس مرتبطاً بالأخبار).
  • «يحط ستوبات ويشكل بينهم» → دائماً صفقة واحدة مفتوحة + أمر STOP معاكس واحد
    على مسافة ثابتة (الصندوق بينهما).
  • «اكل نازل صاعد» → الـ STOP المعاكس يلعب دورين: وقف خسارة للصفقة الحالية، ودخول
    للاتجاه المعاكس. لما ينعكس السعر ويضربه → يُغلق القديم ويُفتح المعاكس (انقلاب) →
    يوضع STOP معاكس جديد → وهكذا. يركب الترند، وينقلب عند كل انعكاس بمقدار ثابت.
    (الفيديو الأول صوّر لحظة الامتلاء = BUY+SELL ظاهرين معاً قبل إغلاق القديم؛
     الفيديو الثاني صوّر الحالة النظيفة = صفقة واحدة + STOP معاكس.)
  • يبدأ بأقل لوت (volume_min) ويتطوّر ذاتياً، ويوقف نفسه عند تجاوز سقف خسارة الجلسة.

Safety: own magic 3627 · يبدأ بأقل لوت · STOP معاكس + وقف كارثي بعيد على كل ساق ·
صفقة واحدة في كل لحظة · يحترم risk_register lot_mult · سقف خسارة جلسة (flatten+pause) ·
خانق انقلابات/ساعة · يُوقَف عبر enabled=false. الحساب الحالي DEMO (Exness Trial). Windowless.
Run:  pythonw gold_straddle_3627.py
"""
from __future__ import annotations
from engine_lock import claim
import json, os, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
STATE = RN / "straddle3627_state.json"
JOURNAL = RN / "straddle3627_journal.json"
HELP_REQ = RN / "straddle3627_help_request.json"
ADVICE = RN / "agents" / "straddle3627_advice.json"

MAGIC = 3627
SYMBOL_CANDIDATES = ["XAUUSDm", "XAUUSD", "XAUUSD-STD", "GOLD", "XAUUSDc", "XAUUSD."]
POLL_S = 1.5

DEFAULTS = {
    "enabled": True,
    "step_atr": 0.5,         # مسافة الـ STOP المعاكس = هذا × M1-ATR (مسافة الانقلاب)
    "step_min_pts": 600,     # حدّ أدنى للمسافة بالنقاط (مفروض أيضاً بـ spread×3)
    "trail": True,           # تتبّع الـ STOP المعاكس لتثبيت الربح (لا يتحرك إلا لصالحنا)
    "trail_tick_pts": 50,    # لا يُعدّل الـ STOP إلا إذا تحسّن بهذا القدر (نقاط) — يقلّل الإزعاج
    # ── الطبقة الديناميكية (تكيّف لحظي مع الترند/التذبذب) ──
    "dynamic": True,
    "trend_fast": 12,        # EMA سريع على فريم الترند
    "trend_slow": 40,        # EMA بطيء
    "flat_strength": 0.12,   # |فجوة EMA|/ATR تحت هذا = تذبذب/مسطّح
    "run_mult": 1.0,         # ساق مع الترند → مسافة أولية (الركوب يجي من التتبّع لا وقف واسع)
    "cut_mult": 0.7,         # ساق عكس الترند → معاكس ضيّق (اقطع بسرعة وارجع للترند)
    "chop_widen": 1.6,       # في التذبذب → وسّع المسافة الأساس
    "be_lock": True,         # قفل التعادل: أول ما تربح be_trigger×step → الوقف لا ينزل تحت التعادل
    "be_trigger": 1.0,       # عتبة الربح (×step) لتفعيل قفل التعادل
    "be_buffer": 0.25,       # هامش فوق التعادل (×step) يغطّي السبريد ويقفل ربحاً صغيراً
    # ── دع الرابح يجري (تكبير الأرباح حسب قوة القناعة) ──
    "let_winners_run": True, # تتبّع يتّسع مع القناعة + لا إغلاق سوقي للصفقات عالية القناعة
    "trail_tight_mult": 1.0, # مسافة التتبّع عند قناعة منخفضة (×step) — خروج سريع
    "trail_wide_mult": 3.5,  # مسافة التتبّع عند قناعة عالية (×step) — يركب الموجة
    "conv_hold": 0.6,        # فوق هذه القناعة → لا إغلاق سوقي على الشموع المعاكسة (اركب)
    # ── بوابة السبريد ──
    "spread_max_pts": 450,   # فوق هذا السبريد (نقاط) → لا دخول (تكلفة عالية)
    # ── قراءة الشموع (آخر 3 على M1: الحالية + السابقة + قبلها) ──
    "candle_n": 3,           # كم شمعة نقرأ
    "candle_body_dom": 0.45, # نسبة الجسم/المدى لاعتبار الشمعة قويّة (متوسط الأجسام)
    "candle_need": 2,        # كم شمعة متوافقة الاتجاه تلزم للزخم (من candle_n)
    # ── الدخول الهجومي بسلّم ستوبات متفرّقة ──
    "momentum_mode": True,   # الزخم يقود: ادخل باتجاه شموع M1 القوية وحدها (الترند داعم لا فيتو)
    "aggressive": True,      # دخول هجومي بسلّم (وإلا ساق سوق واحدة)
    "require_align": True,   # لا دخول إلا إشارة قائمة (زخم شموع أو توافق حسب النمط) + سبريد مقبول
    "ladder_levels": 2,      # عدد الستوبات المتفرّقة في اتجاه الإشارة
    "ladder_first": 0.25,    # بُعد أول ستوب من السعر (×step)
    "ladder_spacing": 0.55,  # تباعد المستويات (×step)
    "ladder_lot_x": 1,       # لوت كل مستوى (×volume_min)
    "max_legs": 3,           # أقصى أرجل في السلّة (سقف صلب للمخاطرة — يشمل STOP+LIMIT)
    # ── أوامر LIMIT (دخول على الارتداد بسعر أفضل، مع ستوبات الاختراق) ──
    "use_limits": True,      # أضف BUY/SELL LIMIT مع ستوبات السلّم (شبكة مزدوجة)
    "limit_levels": 1,       # عدد أوامر LIMIT في اتجاه الإشارة
    "limit_first": 0.30,     # بُعد أول LIMIT من السعر (×step)
    "limit_spacing": 0.55,   # تباعد مستويات LIMIT (×step)
    # ── انحياز SMC/ICT (الفريم الأعلى M15: هيكل + خصم/علاوة + FVG) ──
    "use_smc": True,         # فعّل عامل SMC (انحياز ناعم: يكبّر مع الفريم الأعلى ويصغّر ضده)
    "smc_with_legs": 3,      # أرجل السلّم عند الاتفاق مع SMC (هجوم كامل)
    "smc_counter_legs": 1,   # أرجل السلّم عند مخالفة SMC (تصغير المخاطرة ضد الفريم الأعلى)
    "smc_block_counter": False,  # True = امنع الدخول ضد SMC تماماً (بدل التصغير)
    "catastrophe_x": 4.0,    # وقف كارثي على كل ساق = هذا × step (تأمين لو مات البوت)
    "lot_x": 1,             # مضاعف volume_min — يبدأ أدنى ما يمكن، يرتقي ذاتياً
    "max_lot_x": 6,
    "session_loss_cap": -25.0,  # لو صافي الجلسة المحقّق نزل تحت هذا → سطّح وأوقف
    "max_flips_hr": 40,      # خانق أمان: أقصى انقلابات في الساعة
    "kill_far_orders": True, # اقتل أي أمر معلّق ابتعد عنه السعر (سلّم ميت/بائت)
    "max_order_dist_x": 3.0, # أقصى بُعد للأمر المعلّق عن السعر (×step) قبل قتله
    # ── فلتر الجلسة (ذهب يربح في ساعات السيولة فقط — لا تذبذب الليل) ──
    "session_filter": False,  # فعّل قصر التداول على ساعات معيّنة (UTC)
    "allowed_hours": list(range(12, 21)),  # افتراضي تداخل لندن/نيويورك (الأكثر سيولة/ترند)
    "eval_window": 10,       # تقييم على آخر N صفقات مغلقة
    "pause_after_net": -18.0, # لو آخر N صافيها أسوأ من هذا → عدّل/أوقف
    "promote_after": 14,
    "promote_net": 4.0,
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


DB = RN / "straddle3627.db"


def _db():
    import sqlite3
    con = sqlite3.connect(str(DB), timeout=5)
    con.execute("""CREATE TABLE IF NOT EXISTS episodes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_open REAL, ts_close REAL, iso_close TEXT, duration_s REAL,
        side INTEGER, entry_dir INTEGER,
        tdir INTEGER, tstr REAL, cdir INTEGER, cstr REAL, cpat TEXT,
        smc_bias INTEGER, smc_note TEXT, with_trend INTEGER, smc_rel TEXT,
        spread_pts REAL, step REAL, conv REAL, legs_placed INTEGER, legs_filled INTEGER,
        open_price REAL, close_price REAL, net REAL, win INTEGER, exit_reason TEXT)""")
    con.commit()
    return con


def _db_episode(row):
    try:
        con = _db()
        cols = ",".join(row.keys()); qs = ",".join("?" * len(row))
        con.execute(f"INSERT INTO episodes({cols}) VALUES({qs})", list(row.values()))
        con.commit(); con.close()
    except Exception as e:
        print(f"[STRDL3627] db err {e}", flush=True)


def _pick_symbol(mt5):
    for s in SYMBOL_CANDIDATES:
        info = mt5.symbol_info(s)
        if info is not None:
            if not info.visible:
                mt5.symbol_select(s, True)
            return s
    return None


def _atr(mt5, sym, tf, n=14):
    r = mt5.copy_rates_from_pos(sym, tf, 0, n + 2)
    if r is None or len(r) < n:
        return 0.0
    tr = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
              abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    return sum(tr[-n:]) / n


def _ema(vals, n):
    k = 2.0 / (n + 1); e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def _regime(mt5, sym, fast, slow, tf):
    """اتجاه ديناميكي: (dir ∈ {-1,0,1}, strength=|EMAfast−EMAslow|/ATR)."""
    r = mt5.copy_rates_from_pos(sym, tf, 0, slow + 16)
    if r is None or len(r) < slow + 2:
        return 0, 0.0
    closes = [x["close"] for x in r]
    ef = _ema(closes[-(fast * 3):], fast)
    es = _ema(closes, slow)
    trs = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
               abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    atr = sum(trs[-14:]) / 14 if len(trs) >= 14 else (sum(trs) / len(trs) if trs else 0)
    gap = ef - es
    strength = abs(gap) / atr if atr > 0 else 0.0
    return (1 if gap > 0 else -1 if gap < 0 else 0), strength


def _candle_score(mt5, sym, n, need, body_dom):
    """قراءة شكل آخر n شمعة M1 *مغلقة* (السابقة + قبلها + ...، بلا الشمعة المتشكّلة
    لتفادي رفّ الإشارة tick-by-tick): (dir ∈ {-1,0,1}, strength=هيمنة الجسم 0..1, pattern)."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, n)   # pos=1 → مغلقة فقط
    if r is None or len(r) < n:
        return 0, 0.0, "?"
    dirs, bodies = [], []
    for c in r:
        rng = (c["high"] - c["low"]) or 1e-9
        body = c["close"] - c["open"]
        dirs.append(1 if body > 0 else -1 if body < 0 else 0)
        bodies.append(abs(body) / rng)
    up = sum(1 for d in dirs if d > 0); dn = sum(1 for d in dirs if d < 0)
    strength = sum(bodies) / len(bodies)
    cdir = 0
    if up >= need and up > dn:
        cdir = 1
    elif dn >= need and dn > up:
        cdir = -1
    pat = "".join("▲" if d > 0 else "▼" if d < 0 else "─" for d in dirs)   # أقدم→أحدث
    return cdir, strength, pat


def _smc_bias(mt5, sym, tf, n=120):
    """انحياز SMC/ICT من الفريم الأعلى: هيكل (BOS/CHoCH عبر القمم/القيعان الكسرية)
    + علاوة/خصم. يرجّع (bias ∈ {-1,0,1}, note, dr_mid, [أقرب FVG دعم, أقرب FVG مقاومة])."""
    r = mt5.copy_rates_from_pos(sym, tf, 0, n)
    if r is None or len(r) < 30:
        return 0, "?", 0.0, (None, None)
    k = 2
    sh = [(i, r[i]["high"]) for i in range(k, len(r) - k)
          if all(r[i]["high"] >= r[i - j]["high"] and r[i]["high"] >= r[i + j]["high"] for j in range(1, k + 1))]
    sl = [(i, r[i]["low"]) for i in range(k, len(r) - k)
          if all(r[i]["low"] <= r[i - j]["low"] and r[i]["low"] <= r[i + j]["low"] for j in range(1, k + 1))]
    bias = 0; note = "عرضي"
    if len(sh) >= 2 and len(sl) >= 2:
        hh = sh[-1][1] > sh[-2][1]; hl = sl[-1][1] > sl[-2][1]
        lh = sh[-1][1] < sh[-2][1]; ll = sl[-1][1] < sl[-2][1]
        if hh and hl:
            bias, note = 1, "صاعد HH+HL"
        elif lh and ll:
            bias, note = -1, "هابط LH+LL"
    hi50 = max(x["high"] for x in r[-50:]); lo50 = min(x["low"] for x in r[-50:])
    mid = (hi50 + lo50) / 2.0
    price = (mt5.symbol_info_tick(sym).bid + mt5.symbol_info_tick(sym).ask) / 2
    zone = "خصم" if price < mid else "علاوة"
    # FVG القريبة (3 شموع)
    sup = res = None
    for i in range(2, len(r)):
        if r[i]["low"] > r[i - 2]["high"] and not any(r[j]["low"] <= r[i - 2]["high"] for j in range(i + 1, len(r))):
            if r[i]["low"] < price:
                sup = (r[i - 2]["high"], r[i]["low"])
        if r[i]["high"] < r[i - 2]["low"] and not any(r[j]["high"] >= r[i - 2]["low"] for j in range(i + 1, len(r))):
            if r[i]["high"] > price:
                res = (r[i]["high"], r[i - 2]["low"])
    return bias, f"{note}/{zone}", mid, (sup, res)


def _set_pos_sl(mt5, p, sl):
    info = mt5.symbol_info(p.symbol)
    r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol,
                        "position": int(p.ticket), "sl": round(sl, info.digits), "tp": 0.0})
    return getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE


def _close_all(mt5, sym):
    n = 0
    for p in _my_pos(mt5, sym):
        if _close_pos(mt5, p):
            n += 1
    for o in _my_orders(mt5, sym):
        _cancel(mt5, o.ticket)
    return n


def _risk_mult():
    d = _load(RN / "risk_register.json", {}) or {}
    return float(d.get("lot_mult", 1.0)) if time.time() - float(d.get("ts", 0)) < 300 else 1.0


def _norm_lot(info, lot_x):
    raw = info.volume_min * float(lot_x) * _risk_mult()
    steps = max(1, round(raw / info.volume_step))
    return round(min(info.volume_max, max(info.volume_min, steps * info.volume_step)), 2)


def _send_stop(mt5, sym, side, entry, sl, lot, tag):
    info = mt5.symbol_info(sym)
    ot = mt5.ORDER_TYPE_BUY_STOP if side == "BUY" else mt5.ORDER_TYPE_SELL_STOP
    req = {"action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": float(lot),
           "type": ot, "price": round(entry, info.digits),
           "deviation": 100, "magic": MAGIC, "comment": tag,
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    if sl:
        req["sl"] = round(sl, info.digits)
    r = mt5.order_send(req)
    return (getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE,
            getattr(r, "order", 0), getattr(r, "comment", ""))


def _send_limit(mt5, sym, side, entry, sl, lot, tag):
    """أمر LIMIT (ارتداد): BUY LIMIT تحت السعر / SELL LIMIT فوقه."""
    info = mt5.symbol_info(sym)
    ot = mt5.ORDER_TYPE_BUY_LIMIT if side == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
    req = {"action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": float(lot),
           "type": ot, "price": round(entry, info.digits),
           "deviation": 100, "magic": MAGIC, "comment": tag,
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    if sl:
        req["sl"] = round(sl, info.digits)
    r = mt5.order_send(req)
    return (getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE,
            getattr(r, "order", 0), getattr(r, "comment", ""))


def _is_buy_order(mt5, o):
    return o.type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP)


def _modify_stop(mt5, sym, ticket, price, sl):
    info = mt5.symbol_info(sym)
    r = mt5.order_send({"action": mt5.TRADE_ACTION_MODIFY, "order": int(ticket),
                        "price": round(price, info.digits), "sl": round(sl, info.digits),
                        "type_time": mt5.ORDER_TIME_GTC})
    return getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE, getattr(r, "comment", "")


def _market(mt5, sym, side, lot, tag):
    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
    otype = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if side == "BUY" else tick.bid
    r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lot),
                        "type": otype, "price": price, "deviation": 100, "magic": MAGIC,
                        "comment": tag, "type_filling": mt5.ORDER_FILLING_IOC})
    return (getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE,
            getattr(r, "order", 0), getattr(r, "comment", ""))


def _close_pos(mt5, p):
    tick = mt5.symbol_info_tick(p.symbol)
    if not tick:
        return False
    otype = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    price = tick.bid if p.type == 0 else tick.ask
    r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
                        "position": int(p.ticket), "volume": float(p.volume), "type": otype,
                        "price": price, "deviation": 100, "magic": MAGIC,
                        "comment": "GS3627-flipclose", "type_filling": mt5.ORDER_FILLING_IOC})
    return getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE


def _cancel(mt5, ticket):
    try:
        mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)})
    except Exception:
        pass


def _my_orders(mt5, sym):
    return [o for o in (mt5.orders_get(symbol=sym) or []) if o.magic == MAGIC]


def _my_pos(mt5, sym):
    return [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]


def _session_deals(mt5, sym, since):
    dl = [d for d in (mt5.history_deals_get(int(since) - 5, int(time.time()) + 5) or [])
          if d.magic == MAGIC and d.symbol == sym and d.entry == 1]
    return dl


def _self_evaluate(mt5, sym, since, cfg, st):
    dl = _session_deals(mt5, sym, since)
    nets = [d.profit + d.commission + d.swap for d in dl]
    if len(nets) < cfg["eval_window"]:
        return cfg, f"يجمع عيّنة ({len(nets)}/{cfg['eval_window']})"
    last = nets[-cfg["eval_window"]:]
    net = sum(last); wins = sum(1 for x in last if x > 0)
    note = f"آخر {len(last)} صفقات: صافي ${net:+.2f} · رابحة {wins}/{len(last)}"
    tuned = st.get("tuned", [])
    if net <= cfg["pause_after_net"]:
        if len(tuned) >= 3:
            cfg["enabled"] = False
            _save(HELP_REQ, {"ts": time.time(), "iso": datetime.now(timezone.utc).isoformat(),
                             "from": "gold_straddle_3627", "status": "PAUSED — أحتاج مساعدة",
                             "stats": note, "cfg": cfg, "tuned_history": tuned,
                             "question": "جرّبت 3 تعديلات وما زال انعكاس الذهب خاسراً. وش أغيّر؟ "
                                         "(step_atr مسافة الانقلاب؟ trail؟ أوقفه نهائياً؟)"})
            return cfg, note + " → 🛑 موقوف، طلبت مساعدة الوكلاء/كلود"
        # متغيّر واحد لكل دورة: الخسارة هنا غالباً تذبذب (انقلابات كثيرة) → وسّع المسافة
        cfg["step_atr"] = round(min(3.0, cfg["step_atr"] + 0.3), 2)
        change = f"وسّعت step_atr→{cfg['step_atr']}"
        tuned.append({"ts": time.time(), "change": change, "stats": note})
        st["tuned"] = tuned
        return cfg, note + f" → 🔧 طوّرت نفسي: {change}"
    all_net = sum(nets)
    flag = "promoted_at_" + str(int(cfg.get("lot_x", 1)))
    if (len(nets) >= cfg["promote_after"] and all_net >= cfg["promote_net"]
            and int(cfg.get("lot_x", 1)) < cfg["max_lot_x"] and not st.get(flag)):
        st[flag] = time.time()
        cfg["lot_x"] = min(cfg["max_lot_x"], int(cfg.get("lot_x", 1)) * 2)
        return cfg, note + f" → 🏅 ترقية مستحقة (صافي كلي ${all_net:+.2f}/{len(nets)}) — اللوت ×{cfg['lot_x']}"
    return cfg, note + " → ✅ مقبول، أكمل"


def _apply_advice(cfg, st):
    adv = _load(ADVICE, {}) or {}
    if not adv or adv.get("applied"):
        return cfg
    for k in ("step_atr", "step_min_pts", "trail", "catastrophe_x", "lot_x",
              "session_loss_cap", "enabled"):
        if k in adv:
            cfg[k] = adv[k]
    adv["applied"] = True; adv["applied_ts"] = time.time()
    _save(ADVICE, adv)
    st["tuned"] = []
    print("[STRDL3627] 🧠 طبّقت نصيحة كلود/الوكلاء:", {k: adv.get(k) for k in adv if k != 'applied'}, flush=True)
    return cfg


def _flatten(mt5, sym):
    for o in _my_orders(mt5, sym):
        _cancel(mt5, o.ticket)
    for p in _my_pos(mt5, sym):
        _close_pos(mt5, p)


LOCK = RN / "straddle3627.lock"


def _acquire_lock():
    """قفل نسخة واحدة: امنع تشغيل بوتين معاً (تداول مزدوج خطير)."""
    old = _load(LOCK, {}) or {}
    pid = old.get("pid")
    if pid:
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return False, pid       # عملية حيّة بنفس القفل → ارفض
        except Exception:
            pass
    _save(LOCK, {"pid": os.getpid(), "ts": time.time()})
    return True, os.getpid()


def main():
    claim("gold_straddle")                      # 🔒 قفل نسخة-مفردة (لا تداول مزدوج)
    import MetaTrader5 as mt5
    ok_lock, holder = _acquire_lock()
    if not ok_lock:
        print(f"[STRDL3627] نسخة أخرى تعمل (pid {holder}) — أخرج لتفادي التداول المزدوج", flush=True)
        return 0
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed", mt5.last_error()); return 1
    sym = _pick_symbol(mt5)
    if not sym:
        print("[STRDL3627] ما لقيت رمز ذهب متاح", SYMBOL_CANDIDATES); return 1
    ai = mt5.account_info()
    info0 = mt5.symbol_info(sym)
    point = info0.point
    print(f"[STRDL3627] انعكاس الذهب المستمر حيّ · {sym} M1 · magic {MAGIC} · "
          f"حساب {ai.login} trade_mode={ai.trade_mode}(0=demo) رصيد {ai.balance}{ai.currency}", flush=True)

    session_start = time.time()
    flip_times = []          # طوابع زمنية للانقلابات (للخانق)
    last_eval = 0.0
    basket = {"side": 0, "extreme": None, "since": 0}   # حالة السلّة عبر الدورات
    smc = {"bias": 0, "note": "?", "fvg": (None, None), "ts": 0.0}   # انحياز SMC (مُخزّن)
    episode = None       # لقطة عوامل القرار الحالية (تُكتب في DB عند الإغلاق)

    while True:
        try:
            cfg, st = _cfg()
            # 🛡️ حاجز ديمو + مفتاح قتل (تدقيق C2 2026-07-08): كان بلا أيّ حاجز — ستاكر SnR يرفع اللوت ذاتيّاً.
            _acc = mt5.account_info(); _srv = str(getattr(_acc, "server", "") or "")
            _kill = os.path.exists(str(RN / "kill_switch.txt")) or os.path.exists(str(MT5DIR / "kill_switch.txt"))
            if not _acc or not ("Trial" in _srv or "Demo" in _srv) or _kill:
                time.sleep(15); continue
            cfg = _apply_advice(cfg, st)
            now = time.time()
            poss = _my_pos(mt5, sym)
            ords = _my_orders(mt5, sym)
            info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
            fresh = tick and tick.bid and (now - tick.time) < 120
            atr = _atr(mt5, sym, mt5.TIMEFRAME_M1)
            spread_px = (tick.ask - tick.bid) if fresh else 0.0
            step = max(cfg["step_atr"] * atr, cfg["step_min_pts"] * point, spread_px * 3) if atr > 0 else cfg["step_min_pts"] * point
            # ── الطبقة الديناميكية: اتجاه لحظي + توسيع المسافة في التذبذب ──
            tdir, tstr = (0, 0.0)
            if cfg.get("dynamic"):
                tdir, tstr = _regime(mt5, sym, int(cfg["trend_fast"]), int(cfg["trend_slow"]), mt5.TIMEFRAME_M5)
                flat = tstr < cfg["flat_strength"]
                if flat:
                    tdir = 0
                    step *= cfg["chop_widen"]      # تذبذب → وسّع المسافة (قلّل الـ whipsaw)
            cata = cfg["catastrophe_x"] * step

            # ── سقف خسارة الجلسة / الإيقاف ──
            if not cfg.get("enabled"):
                if poss or ords:
                    _flatten(mt5, sym)
                    print("[STRDL3627] ⏸️ موقوف (enabled=false) — سطّحت كل شيء", flush=True)
                time.sleep(POLL_S); continue
            sess_net = sum(d.profit + d.commission + d.swap for d in _session_deals(mt5, sym, session_start))
            if sess_net <= cfg["session_loss_cap"]:
                _flatten(mt5, sym)
                cfg["enabled"] = False; st["cfg"] = cfg; st["ts"] = now
                _save(STATE, st)
                _save(HELP_REQ, {"ts": now, "iso": datetime.now(timezone.utc).isoformat(),
                                 "from": "gold_straddle_3627", "status": "PAUSED — سقف خسارة الجلسة",
                                 "stats": f"صافي الجلسة ${sess_net:+.2f} ≤ سقف ${cfg['session_loss_cap']}",
                                 "question": "ضرب سقف خسارة الجلسة. أرفع السقف؟ أوسّع step؟ أوقفه؟"})
                print(f"[STRDL3627] 🛑 سقف خسارة الجلسة (${sess_net:+.2f}) — سطّحت وأوقفت", flush=True)
                time.sleep(POLL_S); continue

            if not fresh or atr <= 0:
                time.sleep(POLL_S); continue

            # ── العوامل: سبريد + شموع(3) + ترند → إشارة متوافقة ──
            spread_pts = spread_px / point if point else 9999
            spread_ok = spread_pts <= cfg["spread_max_pts"]
            cdir, cstr, cpat = _candle_score(mt5, sym, int(cfg["candle_n"]),
                                             int(cfg["candle_need"]), cfg["candle_body_dom"])
            strong_candle = cstr >= cfg["candle_body_dom"]
            # إشارة الدخول:
            #  • نمط الزخم (momentum_mode): زخم شموع M1 القوية يقود، الترند داعم لا فيتو
            #  • نمط التوافق: لا دخول إلا توافق الترند + الشموع
            if cfg.get("momentum_mode"):
                sig = cdir if (cdir != 0 and strong_candle and spread_ok) else 0
                aligned = (sig != 0)
                with_trend = (tdir == cdir and tdir != 0)   # بونص توافق (للسجل)
            else:
                aligned = (tdir != 0 and cdir == tdir and strong_candle and spread_ok)
                sig = tdir if aligned else 0
                with_trend = aligned
            sgn = lambda x: 1 if x > 0 else -1 if x < 0 else 0

            # ── اقتل الأوامر البعيدة (سلّم ميت ابتعد عنه السعر) ──
            if cfg.get("kill_far_orders") and ords:
                px = (tick.ask + tick.bid) / 2
                md = cfg["max_order_dist_x"] * step
                killed = 0
                for o in ords:
                    if abs(o.price_open - px) > md:
                        _cancel(mt5, o.ticket); killed += 1
                if killed:
                    print(f"[STRDL3627] 🗡️ قتلت {killed} أمر بعيد (>{md:.2f} عن السعر)", flush=True)
                    ords = _my_orders(mt5, sym)

            # ── انحياز SMC/ICT من M15 (يُحسب كل 30ث، مُخزّن) ──
            if cfg.get("use_smc") and now - smc["ts"] > 30:
                b, nt, _mid, fv = _smc_bias(mt5, sym, mt5.TIMEFRAME_M15)
                smc = {"bias": b, "note": nt, "fvg": fv, "ts": now}

            # ── احفظ السلّة أحادية الاتجاه: أغلق أي رِجل أقلّية معاكسة ──
            if poss:
                longs = [p for p in poss if p.type == 0]; shorts = [p for p in poss if p.type == 1]
                side = 1 if len(longs) >= len(shorts) else -1
                minority = shorts if side > 0 else longs
                for p in minority:
                    _close_pos(mt5, p)
                if minority:
                    time.sleep(0.3); continue
                if basket["side"] != side:
                    basket = {"side": side, "extreme": None, "since": now}
                # سقف صلب: لو امتلأت السلّة (max_legs) → ألغِ كل المعلّقات (امنع التعبئة الزائدة)
                if len(poss) >= int(cfg["max_legs"]) and ords:
                    for o in ords:
                        _cancel(mt5, o.ticket)
                    ords = []

                # ── إدارة السلّة: وقف متحرّك مشترك + قفل تعادل + إغلاق عند انعكاس ──
                vol = sum(p.volume for p in poss)
                avg_e = sum(p.price_open * p.volume for p in poss) / vol if vol else poss[0].price_open
                cur = tick.bid if side > 0 else tick.ask
                ext = basket["extreme"]
                ext = cur if ext is None else (max(ext, cur) if side > 0 else min(ext, cur))
                basket["extreme"] = ext
                # ── قوة القناعة (0..1): كم «دخولنا اكيد» — ترند+توافق+SMC+شمعة+تعبئة ──
                conv = 0.0
                conv += 0.35 * min(1.0, tstr / 1.0) if (tdir == side) else 0.0   # قوة الترند تُحتسب فقط لو مع الصفقة
                conv += 0.25 if (tdir == side and tdir != 0) else 0  # M5 مع الصفقة
                conv += 0.20 if (smc["bias"] == side) else 0          # الفريم الأعلى مع الصفقة
                conv += 0.10 * min(1.0, cstr / 0.7)                  # قوة الشمعة
                conv += 0.10 if len(poss) >= 2 else 0                # تعبئة = زخم مؤكّد
                conv = max(0.0, min(1.0, conv))
                # انعكاس الإشارة → إغلاق سوقي. لكن «دام دخولنا اكيد» (قناعة عالية) لا نغلق على
                # أول شمعة معاكسة — نتركه يركب ويخرج بالوقف الواسع فقط.
                if cfg.get("momentum_mode"):
                    flip = (cdir == -side and strong_candle)
                else:
                    flip = (tdir == -side and tstr >= cfg["flat_strength"]) or (cdir == -side and strong_candle)
                if cfg.get("let_winners_run") and conv >= cfg["conv_hold"]:
                    flip = False                                     # قناعة عالية → اركب، الوقف الواسع يخرجك
                if flip:
                    n = _close_all(mt5, sym)
                    if episode is not None:
                        episode["_exit"] = "flip"
                    flip_times = [t for t in flip_times if now - t < 3600] + [now]
                    basket = {"side": 0, "extreme": None, "since": 0}
                    print(f"[STRDL3627] 🔄 انعكاس الإشارة → أغلقت السلّة ({n} رِجل) · {cpat} قوة-ترند {tstr:.2f}", flush=True)
                    time.sleep(0.3); continue
                # الوقف الحامي: مسافة التتبّع تتّسع مع القناعة (دع الرابح يجري) — لا نقفل على ربح صغير
                tmult = cfg["trail_tight_mult"]
                if cfg.get("let_winners_run"):
                    tmult = cfg["trail_tight_mult"] + (cfg["trail_wide_mult"] - cfg["trail_tight_mult"]) * conv
                tdist = step * tmult
                prot = (ext - tdist) if side > 0 else (ext + tdist)
                if cfg.get("be_lock"):   # أرضية: بعد ربح be_trigger لا يعود لخسارة أبداً
                    if side > 0 and (tick.bid - avg_e) >= cfg["be_trigger"] * step:
                        prot = max(prot, avg_e + cfg["be_buffer"] * step)
                    if side < 0 and (avg_e - tick.ask) >= cfg["be_trigger"] * step:
                        prot = min(prot, avg_e - cfg["be_buffer"] * step)
                prot = round(prot, info.digits)
                tickpx = cfg["trail_tick_pts"] * point
                for p in poss:
                    better = (p.sl == 0.0) or (prot > p.sl + tickpx if side > 0 else prot < p.sl - tickpx)
                    if better:
                        _set_pos_sl(mt5, p, prot)
                # تعبئة هجومية: أبقِ سلّم الستوبات حتى السقف الفعّال (مُصغّر ضد SMC) ما دامت الإشارة قائمة
                cap = int(cfg["max_legs"])
                if cfg.get("use_smc") and smc["bias"] != 0 and smc["bias"] != side:
                    cap = int(cfg["smc_counter_legs"])
                if cfg.get("aggressive") and aligned and sgn(sig) == side and len(poss) < cap:
                    have = len(poss) + len([o for o in ords if _is_buy_order(mt5, o) == (side > 0)])
                    if have < cap:
                        i = have
                        dist = (cfg["ladder_first"] + i * cfg["ladder_spacing"]) * step
                        ot_side = "BUY" if side > 0 else "SELL"
                        entry = (tick.ask + dist) if side > 0 else (tick.bid - dist)
                        sll = (entry - cata) if side > 0 else (entry + cata)
                        _send_stop(mt5, sym, ot_side, entry, sll, _norm_lot(info, cfg["ladder_lot_x"]), "GS3627-ADD")
                time.sleep(POLL_S); continue

            # ── مسطّح → دخول هجومي بسلّم ستوبات متفرّقة (عند توافق العوامل) ──
            if not poss:
                # محاسبة الإغلاق: الصفقة انتهت → احسب النتيجة واكتبها في DB
                if episode is not None:
                    dl = _session_deals(mt5, sym, episode["ts_open"])
                    net = round(sum(d.profit + d.commission + d.swap for d in dl), 2)
                    fills = [d for d in (mt5.history_deals_get(int(episode["ts_open"]) - 2, int(now) + 5) or [])
                             if d.magic == MAGIC and d.symbol == sym and d.entry == 0]
                    exitr = episode.pop("_exit", "sl/flip")
                    if len(fills) > 0:        # صفقة حقيقية فقط (سلّم امتلأ) — تجاهل السلالم المُلغاة
                        cp = (sum(d.price for d in dl) / len(dl)) if dl else 0.0
                        episode.update({"ts_close": now, "iso_close": datetime.now(timezone.utc).isoformat(),
                                        "duration_s": round(now - episode["ts_open"], 1),
                                        "legs_filled": len(fills), "close_price": round(cp, 3),
                                        "net": net, "win": 1 if net > 0 else 0, "exit_reason": exitr})
                        _db_episode(episode)
                        print(f"[STRDL3627] 💾 سجّلت صفقة: {episode['side']:+d} net ${net:+.2f} "
                              f"أرجل {len(fills)}/{episode['legs_placed']} مدة {episode['duration_s']:.0f}ث", flush=True)
                    episode = None
                basket = {"side": 0, "extreme": None, "since": 0}
                # سلّم منتظر الاختراق: أبقِه ما دامت إشارته قائمة، وإلا ألغِه
                if ords:
                    lad_side = 1 if _is_buy_order(mt5, ords[0]) else -1
                    still = aligned and sgn(sig) == lad_side and spread_ok
                    if not still:
                        for o in ords:
                            _cancel(mt5, o.ticket)
                        print(f"[STRDL3627] ✋ ألغيت السلّم (الإشارة تغيّرت/سبريد) · {cpat} قوة-ترند {tstr:.2f}", flush=True)
                    time.sleep(POLL_S); continue          # انتظر الامتلاء أو تغيّر الإشارة
                flip_times = [t for t in flip_times if now - t < 3600]
                if len(flip_times) >= cfg["max_flips_hr"]:
                    time.sleep(POLL_S); continue
                if not spread_ok:
                    time.sleep(POLL_S); continue
                if cfg.get("session_filter"):
                    hr = datetime.now(timezone.utc).hour
                    if hr not in set(cfg.get("allowed_hours", [])):
                        time.sleep(POLL_S); continue       # خارج جلسة السيولة → لا تداول
                if cfg.get("require_align") and not aligned:
                    time.sleep(POLL_S); continue          # لا توافق → ابقَ مسطّحاً (تجنّب التذبذب)
                entry_dir = sig if sig != 0 else (tdir if tdir != 0 else cdir)
                if entry_dir == 0:
                    time.sleep(POLL_S); continue
                # ── عامل SMC: مع الفريم الأعلى → هجوم كامل؛ ضده → تصغير (أو منع) ──
                smc_rel = "محايد"; lvls = int(cfg["ladder_levels"])
                if cfg.get("use_smc") and smc["bias"] != 0:
                    if smc["bias"] == entry_dir:
                        smc_rel = "مع SMC✓"; lvls = int(cfg["smc_with_legs"])
                    else:
                        smc_rel = "ضد SMC✗"
                        if cfg.get("smc_block_counter"):
                            time.sleep(POLL_S); continue       # منع الدخول ضد الفريم الأعلى
                        lvls = int(cfg["smc_counter_legs"])     # تصغير المخاطرة ضد SMC
                ot_side = "BUY" if entry_dir > 0 else "SELL"
                if cfg.get("aggressive"):
                    placed = 0
                    for i in range(max(1, lvls)):
                        dist = (cfg["ladder_first"] + i * cfg["ladder_spacing"]) * step
                        entry = (tick.ask + dist) if entry_dir > 0 else (tick.bid - dist)
                        sll = (entry - cata) if entry_dir > 0 else (entry + cata)
                        ok, tk, cm = _send_stop(mt5, sym, ot_side, entry, sll,
                                                _norm_lot(info, cfg["ladder_lot_x"]), "GS3627-LAD")
                        placed += 1 if ok else 0
                    # ── أوامر LIMIT (ارتداد): على الجانب المعاكس للسعر بنفس اتجاه الصفقة ──
                    lim = 0
                    if cfg.get("use_limits"):
                        for i in range(int(cfg["limit_levels"])):
                            dist = (cfg["limit_first"] + i * cfg["limit_spacing"]) * step
                            # BUY LIMIT تحت السعر / SELL LIMIT فوقه
                            lentry = (tick.bid - dist) if entry_dir > 0 else (tick.ask + dist)
                            lsl = (lentry - cata) if entry_dir > 0 else (lentry + cata)
                            okl, _, _ = _send_limit(mt5, sym, ot_side, lentry, lsl,
                                                    _norm_lot(info, cfg["ladder_lot_x"]), "GS3627-LIM")
                            lim += 1 if okl else 0
                    wt = "مع الترند" if with_trend else "ضد الترند"
                    print(f"[STRDL3627] 🎯 سلّم {ot_side} · STOP×{placed} LIMIT×{lim} · {wt} · {smc_rel} (SMC: {smc['note']}) · "
                          f"مسافة {step:.3f} · شموع {cpat} · سبريد {spread_pts:.0f}", flush=True)
                    if placed or lim:
                        econv = (0.35 * min(1.0, tstr) + (0.25 if with_trend else 0)
                                 + (0.20 if smc["bias"] == entry_dir else 0) + 0.10 * min(1.0, cstr / 0.7))
                        episode = {"ts_open": now, "side": entry_dir, "entry_dir": entry_dir,
                                   "tdir": tdir, "tstr": round(tstr, 3), "cdir": cdir,
                                   "cstr": round(cstr, 3), "cpat": cpat, "smc_bias": smc["bias"],
                                   "smc_note": smc["note"], "with_trend": 1 if with_trend else 0,
                                   "smc_rel": smc_rel, "spread_pts": round(spread_pts, 1),
                                   "step": round(step, 3), "conv": round(econv, 3), "legs_placed": placed,
                                   "open_price": round((tick.ask + tick.bid) / 2, 3)}
                else:
                    ok, tk, cm = _market(mt5, sym, ot_side, _norm_lot(info, cfg["lot_x"]), "GS3627-SEED")
                    if ok:
                        print(f"[STRDL3627] 🎯 دخول سوق {ot_side} · {cpat} · سبريد {spread_pts:.0f}", flush=True)

            # ── تقييم ذاتي كل 10 دقائق ──
            if now - last_eval > 600:
                last_eval = now
                cfg, verdict = _self_evaluate(mt5, sym, session_start, cfg, st)
                st["cfg"] = cfg; st["last_eval"] = verdict; st["ts"] = now
                st["symbol"] = sym; st["session_net"] = round(sess_net, 2)
                _save(STATE, st)
                print(f"[STRDL3627] 🧪 {verdict} · صافي الجلسة ${sess_net:+.2f}", flush=True)
        except Exception as e:
            print(f"[STRDL3627] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
