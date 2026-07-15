# -*- coding: utf-8 -*-
"""momentum_harvester.py — حاصد الزخم البطيء (Time-Series Momentum) على **كل أزواج العملات**.

طلب المستخدم: حافّة حقيقيّة بنيويّة على جميع الأزواج. حاصد-الحمل (السواب) مستحيل على وسيطه (Exness:
صفر سواب موجب). فهذا بديله الحقيقيّ الموثّق: **زخم السلاسل الزمنيّة** (Moskowitz/Ooi/Pedersen، AQR) —
شارب ~0.4 بعد التكلفة، موجب في 67 سوقاً وكل عقد منذ 1880. **ليس تنبّؤاً قصير المدى** (الذي أثبتنا فشله) —
بل ركوب اتجاهٍ بطيء (أسابيع) عبر **كل الأزواج** بحجم صغير مُقاس-بالتقلّب؛ الحافّة من **التنويع** لا من زوجٍ بعينه.

كيف يعمل:
  • إشارة بطيئة على D1: اتجاه السعر عبر LOOKBACK_D يوماً (عائد + موقع مقابل المتوسّط) ⇒ +1/−1/0.
  • يفتح مركزاً صغيراً في اتجاه الزخم، **يحتفظ به** (يُعاد التقييم كل دورة، لا سكالبينج)، عبر كثير أزواج.
  • حجم مُقاس-بالتقلّب (ATR) ⇒ مخاطرة متساوية لكل رهان، ثم lot_guard (السقف الصلب المُثبت).
  • خروج: انعكاس الزخم (الإشارة تنقلب) أو وقف-تقلّب (خسارة > STOP_ATR×ATR — يحدّ ذيل الانعكاس).

الأمان: ديمو فقط، lot_guard، محكوم بالمايسترو، يحترم kill_switch، لا يلمس اليدويّ/الخارجيّ، قفل مفرد،
مضادّ-تحوّط. magic 20260630. windowless تحت الوصيّ. master_floor (حاجز الهامش) يحرس الكارثة.
"""
from __future__ import annotations
import time
import re as _re
from pathlib import Path
import MetaTrader5 as mt5

try:
    from engine_lock import claim
except Exception:
    def claim(n): return True
try:
    from engine_gov import gov_mult, is_paused
except Exception:
    def gov_mult(m, lo=0.1, hi=1.5): return 1.0
    def is_paused(m): return False
try:
    import lot_guard
except Exception:
    lot_guard = None
try:
    import portfolio_guard as pg
except Exception:
    pg = None
try:
    import momentum_learn as ml          # حلقة التعلّم: تسجيل الميزات + مرشّح الدلاء النازفة
except Exception:
    ml = None
try:
    import deep_conviction as dc         # 🧬 قناعة الجين/الوكيل المُثبتة (فيتو حقيقيّ) — بوّابة دخول
except Exception:
    dc = None
try:
    import level_map as lm               # 🎯 مناطق الالتقاء — أهداف دخولٍ نثق بها (أوامر محدّدة)
except Exception:
    lm = None

CONFLUENCE_MIN = 4       # قوّة التقاءٍ كافية لوضع أمرٍ محدّد (عدد المستويات + تنوّع الأنواع)
CONFLUENCE_REACH_ATR = 2.5   # نضع المعلّق عند التقاءٍ ضمن هذا×ATR(D1) في اتجاهنا

ROOT = Path(r"C:\Users\Radhi\MT5")
KILL = ROOT / "kill_switch.txt"
STATUS = ROOT / "data" / "r_native" / "momentum_harvester.json"
LOG = ROOT / "data" / "r_native" / "momentum_harvester.log"
MAGIC = 20260630

CCY = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "SEK", "NOK",
       "SGD", "HKD", "ZAR", "MXN", "TRY", "PLN", "CZK", "HUF", "CNH", "DKK"}
# 🩺 علاج 2026-07-15 (أمر المستخدم «ما نقتل نعالج»): التشخيص أثبت أن النزيف كلّه من المعادن
# (الفضّة −$27.75) بينما فوركس TSM موجب (~+$5) ⇒ نستأصل المعادن ونُبقي الفوركس. للرجوع: أعد الرمزين.
GOLD_FOCUS = []                           # كان ["XAUUSDm", "XAGUSDm"] — مصدر النزيف المُثبت
GOLD_RISK_MULT = 1.6                      # تركيزٌ على الذهب: حصّة أكبر (مقيّدة بـlot_guard 2% — لا كارثة)
EXT = {2447, 20250418, 20250421, 20250422, 20250618}     # خبراء المستخدم — لا نلمس
LOOKBACK_D   = 40        # أيام النظر للزخم البطيء (~8 أسابيع — مدى TSM الكلاسيكيّ المُصغّر)
SMA_D        = 40        # متوسّط الاتجاه
STRENGTH_MIN = 1.5       # 🎯 دقّة متناهية: |عائد النافذة| ≥ هذا×ATR(D1) = اتجاه قويّ حقيقيّ لا انجراف ضعيف
H4_LOOK      = 30        # تأكيد متعدّد-الفريمات: H4 يجب أن يوافق اتجاه D1 (دقّة)
RISK_PCT     = 1.5       # ⬆️ لوت عالٍ (طلب المستخدم) — لكنّه **مقيّد** بـlot_guard 2% + وقف-تقلّب (خسارة محدودة دائماً)
STOP_ATR     = 2.5       # وقف-تقلّب أضيق (لوت عالٍ ⇒ نحدّ الذيل أبكر): أغلق إن تجاوزت الخسارة 2.5×ATR(D1)
MAX_POS      = 25        # ⬆️ رُفِع (طلب «اجعله يدخل»): تنويعٌ أوسع = دخولٌ أكثر (متوافق مع TSM)، والهامش يحتمل + lot_guard/أرضية يحرسان
MAX_PER_CCY  = 4         # سقف تعرّض لكل عملة (الأزواج مترابطة عبر الدولار)
SPREAD_MAX_ATRD = 0.12   # دقّة: تجاهل غالي السبريد بصرامة أكثر
POLL_S       = 300.0     # دورة بطيئة (5د) — TSM يحتفظ أياماً، لا يطارد


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _is_demo():
    a = mt5.account_info()
    if not a:
        return False
    srv = (a.server or "")
    return ("Trial" in srv) or ("Demo" in srv) or (a.login == 262998147)


def _fx_universe():
    out = []
    avail = {s.name for s in (mt5.symbols_get() or [])}
    for g in GOLD_FOCUS:                     # 🥇 الذهب أوّلاً (تركيز): يُمسح ويُدخَل قبل الفوركس
        if g in avail:
            out.append(g)
    for s in (mt5.symbols_get() or []):
        b = s.name.upper().rstrip("M")
        if len(b) == 6 and b[:3] in CCY and b[3:] in CCY and s.name not in out:
            out.append(s.name)
    return out


def _atr_d1(sym, n=14):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, n + 2)
    if r is None or len(r) < n + 1:
        return 0.0
    h, l, c = r["high"], r["low"], r["close"]
    trs = [max(float(h[i] - l[i]), abs(float(h[i] - c[i - 1])), abs(float(l[i] - c[i - 1])))
           for i in range(len(r) - n, len(r))]
    return sum(trs) / len(trs) if trs else 0.0


def _trend(sym):
    """🎯 إشارة الزخم البطيء فائقة-الدقّة (TSM متعدّد التأكيد): تتطلّب **كل** الشروط معاً ⇒ +1/−1، وإلا 0:
    (1) عائد LOOKBACK_D **قويّ** (≥ STRENGTH_MIN×ATR — لا انجراف ضعيف)، (2) السعر فوق/تحت متوسّطه،
    (3) H4 يوافق اتجاه D1 (تأكيد فريم أعلى). هذه «الدقّة المتناهية» التي تبرّر اللوت العالي."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, max(LOOKBACK_D, SMA_D) + 2)
    if r is None or len(r) < max(LOOKBACK_D, SMA_D) + 1:
        return 0
    c = r["close"]
    ret = float(c[-1] - c[-1 - LOOKBACK_D])                # عائد النافذة (إشارة الزخم الأساسيّة)
    sma = sum(float(c[-i]) for i in range(1, SMA_D + 1)) / SMA_D
    price = float(c[-1])
    atrd = _atr_d1(sym)
    if atrd <= 0:
        return 0
    if abs(ret) < STRENGTH_MIN * atrd:                     # (1) قوّة: اتجاه ضعيف ⇒ لا دقّة ⇒ تجاهل
        return 0
    up = ret > 0 and price > sma                           # (2) موقع السعر
    dn = ret < 0 and price < sma
    if not (up or dn):
        return 0
    d = 1 if up else -1
    rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, H4_LOOK + 2)   # (3) تأكيد H4
    if rh is not None and len(rh) >= H4_LOOK + 1:
        h4ret = float(rh["close"][-1] - rh["close"][-1 - H4_LOOK])
        if (1 if h4ret > 0 else -1) != d:                  # H4 يخالف D1 ⇒ لا دقّة ⇒ تجاهل
            return 0
    return d


def _vol_lot(sym, eq, atrd, info):
    """حجم مُقاس-بالتقلّب: مخاطرة RISK_PCT% على حركة ATR(D1) ⇒ مخاطرة متساوية لكل رهان. ثم lot_guard."""
    ts = info.trade_tick_size or info.point
    tv = info.trade_tick_value
    step = info.volume_step or 0.01
    if not ts or not tv or atrd <= 0:
        return 0.0
    risk_per_lot = (atrd / ts) * tv                        # خسارة 1 لوت على حركة ATR يوميّ
    if risk_per_lot <= 0:
        return 0.0
    lot = (eq * RISK_PCT / 100.0) / risk_per_lot
    lot *= gov_mult(MAGIC)
    if sym in GOLD_FOCUS:
        lot *= GOLD_RISK_MULT                              # 🥇 تركيز الذهب: حصّة أكبر (يبقى مقيّداً بـlot_guard)
    lot = max(info.volume_min, round(lot / step) * step)
    lot = min(lot, info.volume_max or lot)
    if lot_guard:
        lot, _ = lot_guard.cap(mt5, sym, lot, eq)          # 🛑 السقف الصلب المُثبت (الحجم = الرافعة)
    return float(lot)


def _ccy(sym):
    return set(_re.findall(r"[A-Z]{3}", sym.upper()[:6]))


def _confluence_entry(sym, d, price, atrd):
    """🎯 أقوى منطقة التقاء في اتجاه الدخول ضمن المدى (دعمٌ تحت السعر لشراء / مقاومةٌ فوقه لبيع) — أمرٌ محدّد
    عندها = «هدفٌ نثق به». يرجع منطقة الالتقاء (center/strength/labels) أو None."""
    if lm is None or atrd <= 0:
        return None
    try:
        zones = lm.confluence_zones(sym, band_atr=0.30, min_levels=2)
    except Exception:
        return None
    cands = []
    for z in (zones or []):
        c = z.get("center")
        if not c:
            continue
        if d > 0 and c < price and (price - c) <= CONFLUENCE_REACH_ATR * atrd:      # دعم لشراء
            cands.append(z)
        elif d < 0 and c > price and (c - price) <= CONFLUENCE_REACH_ATR * atrd:    # مقاومة لبيع
            cands.append(z)
    cands = [z for z in cands if z.get("strength", 0) >= CONFLUENCE_MIN]
    return max(cands, key=lambda z: z.get("strength", 0)) if cands else None


def _open(sym, d, eq):
    info = mt5.symbol_info(sym); tk = mt5.symbol_info_tick(sym)
    atrd = _atr_d1(sym)
    if not info or not tk or atrd <= 0:
        return False
    if (tk.ask - tk.bid) > SPREAD_MAX_ATRD * atrd:         # سبريد غالٍ نسبةً للمدى اليوميّ ⇒ تجاهل
        return False
    if pg is not None:
        hed, _ = pg.would_hedge(mt5, sym, mt5.ORDER_TYPE_BUY if d > 0 else mt5.ORDER_TYPE_SELL, MAGIC)
        if hed:
            return False
    # 🧠 حلقة التعلّم: قوّة الاتجاه = |عائد النافذة|/ATR(D1) — ميزة الدلو
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, LOOKBACK_D + 2)
    strength = 0.0
    if r is not None and len(r) >= LOOKBACK_D + 1 and atrd > 0:
        strength = abs(float(r["close"][-1] - r["close"][-1 - LOOKBACK_D])) / atrd
    feats = {"strength": strength, "atr": atrd, "ts": time.time()}
    if ml is not None and not ml.edge_filter(sym, feats):    # تخطَّ الدلاء المُثبَت نزيفها (n>=20)
        return False
    # 🧬 بوّابة قناعة الجين/الوكيل: لا ندخل إن كان هناك فيتو مُثبت — **عدا الذهب/الفضّة** (تركيز المستخدم؛
    # الفيتو من سكالبينج الذهب القديم لا من TSM البطيء؛ يبقى محميّاً بـlot_guard + وقف-تقلّب + الأرضية).
    if dc is not None and sym not in GOLD_FOCUS:
        try:
            _m, _t, _ok = dc.conviction(sym, "BUY" if d > 0 else "SELL")
            if not _ok:
                return False
        except Exception:
            pass
    # 🚫 لدينا معلّق على الرمز؟ ⇒ مُغطّى، لا نكرّر
    if any(getattr(o, "magic", None) == MAGIC for o in (mt5.orders_get(symbol=sym) or [])):
        return False
    lot = _vol_lot(sym, eq, atrd, info)
    if lot <= 0:
        return False
    price = (tk.ask + tk.bid) / 2.0
    # 🎯 أمر محدّد عند أقوى منطقة التقاء في اتجاهنا (هدفٌ نثق به) — وإلا سوق (لا نفوّت الاتجاه)
    zone = _confluence_entry(sym, d, price, atrd)
    if zone is not None:
        plimit = round(float(zone["center"]), info.digits)
        res = mt5.order_send({"action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": float(lot),
                              "type": mt5.ORDER_TYPE_BUY_LIMIT if d > 0 else mt5.ORDER_TYPE_SELL_LIMIT,
                              "price": plimit, "sl": 0.0, "tp": 0.0, "magic": MAGIC, "comment": "tsm-confl",
                              "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC})
        if getattr(res, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            _log(f"🎯 أمر محدّد {sym} {'شراء' if d>0 else 'بيع'} {lot} @{plimit} (التقاء قوّة {zone.get('strength')}: {zone.get('labels')})")
            if ml is not None:
                ml.record(sym, d, feats)
            return True                                       # فشل المعلّق ⇒ نكمل للسوق
    entry = tk.ask if d > 0 else tk.bid
    res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lot),
                          "type": mt5.ORDER_TYPE_BUY if d > 0 else mt5.ORDER_TYPE_SELL,
                          "price": entry, "sl": 0.0, "tp": 0.0, "deviation": 30, "magic": MAGIC,
                          "comment": "tsm", "type_filling": mt5.ORDER_FILLING_IOC})
    ok = getattr(res, "retcode", None) == mt5.TRADE_RETCODE_DONE
    if ok:
        _log(f"فتح زخم {sym} {'شراء' if d>0 else 'بيع'} {lot} @{entry:.5f} (اتجاه بطيء {LOOKBACK_D}ي)")
        if ml is not None:
            ml.record(sym, d, feats)                          # 🧠 سجّل ميزات الصفقة (إغلاق الحلقة)
    return ok


def _close(p, reason):
    tk = mt5.symbol_info_tick(p.symbol)
    if not tk:
        return
    price = tk.bid if p.type == 0 else tk.ask
    mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
                    "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
                    "position": p.ticket, "price": price, "deviation": 50, "magic": MAGIC,
                    "comment": f"tsm-{reason}", "type_filling": mt5.ORDER_FILLING_IOC})
    _log(f"إغلاق زخم {p.symbol} ({reason}) pnl {p.profit:+.2f}")


def _manage():
    """خروج: انعكاس الزخم (الإشارة انقلبت) أو وقف-تقلّب (خسارة > STOP_ATR×ATR يوميّ)."""
    for p in (mt5.positions_get() or []):
        if p.magic != MAGIC:
            continue
        d = 1 if p.type == 0 else -1
        sig = _trend(p.symbol)
        atrd = _atr_d1(p.symbol)
        info = mt5.symbol_info(p.symbol)
        if sig != 0 and sig != d:                          # الزخم انقلب ضدّنا ⇒ اخرج (جوهر TSM)
            _close(p, "انعكاس-زخم"); continue
        if atrd > 0 and info:                              # وقف-تقلّب: يحدّ ذيل الانعكاس (Aug-2024 lesson)
            ts = info.trade_tick_size or info.point; tv = info.trade_tick_value
            if ts and tv:
                loss_atr = (-p.profit) / ((atrd / ts) * tv * p.volume) if p.volume else 0
                if loss_atr >= STOP_ATR:
                    _close(p, f"وقف-تقلّب {loss_atr:.1f}ATR")


def _cleanup_pendings():
    """يلغي معلّقاتنا التي لم تَعُد ذات صلة: انقلب اتجاه الزخم عن اتجاه المعلّق، أو ابتعد السعر كثيراً (لن يُعبّأ)."""
    for o in (mt5.orders_get() or []):
        if getattr(o, "magic", None) != MAGIC:
            continue
        sym = o.symbol
        odir = 1 if o.type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP) else -1
        d = _trend(sym)
        cancel = (d == 0 or d != odir)                         # الزخم انقلب/ضعف ⇒ خارج اتجاهنا
        if not cancel:
            atrd = _atr_d1(sym); tk = mt5.symbol_info_tick(sym)
            if tk and atrd > 0 and abs((tk.ask + tk.bid) / 2.0 - o.price_open) > 4.0 * atrd:
                cancel = True                                  # ابتعد كثيراً ⇒ لن يُعبّأ
        if cancel:
            mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
            _log(f"إلغاء معلّق {sym} ({'انقلاب زخم' if d != odir else 'سعرٌ بعيد'})")


def main():
    claim("momentum_harvester")
    for _ in range(3):
        if mt5.initialize():
            break
        time.sleep(2)
    if not _is_demo():
        _log("ليس ديمو — خروج (أمان)"); return
    _log(f"momentum_harvester start — TSM على كل FX، magic {MAGIC} (lookback {LOOKBACK_D}ي، risk {RISK_PCT}%)")
    fx = _fx_universe()
    _log(f"universe: {len(fx)} زوج عملات")
    while True:
        try:
            st = {"ts": time.time(), "magic": MAGIC, "universe": len(fx)}
            if KILL.exists():
                st["state"] = "kill_switch"; _save(st); time.sleep(POLL_S); continue
            acct = mt5.account_info()
            if not acct:
                time.sleep(POLL_S); continue
            eq = acct.equity
            _manage()                                       # أوّلاً: أدِر المفتوح (خروج على الانعكاس/الوقف)
            _cleanup_pendings()                             # ألغِ المعلّقات التي انقلب زخمها أو ابتعد سعرها
            mine = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
            st["open"] = len(mine)
            if is_paused(MAGIC):
                st["state"] = "مُقال (المايسترو) — إدارة فقط"; _save(st); time.sleep(POLL_S); continue
            if len(mine) >= MAX_POS:
                st["state"] = f"سقف المراكز {MAX_POS} — إدارة فقط"; _save(st); time.sleep(POLL_S); continue
            held = {p.symbol for p in mine}
            ccy_count = {}
            for p in mine:
                for c in _ccy(p.symbol):
                    ccy_count[c] = ccy_count.get(c, 0) + 1
            opened = 0
            for sym in fx:                                  # امسح كل الأزواج، افتح حيث زخمٌ واضح + لا تكدّس عملة
                if sym in held or len(mine) + opened >= MAX_POS:
                    continue
                if any(ccy_count.get(c, 0) >= MAX_PER_CCY for c in _ccy(sym)):
                    continue
                d = _trend(sym)
                if d == 0:
                    continue
                if _open(sym, d, eq):
                    opened += 1
                    for c in _ccy(sym):
                        ccy_count[c] = ccy_count.get(c, 0) + 1
                    if opened >= 5:                         # حدّ فتحٍ لكل دورة (دخول تدريجيّ، لا دفعة)
                        break
            st["state"] = f"نشط — {len(mine)+opened} مركز زخم عبر {len(fx)} زوج (تنويع)"
            _save(st)
        except Exception as e:
            _log(f"loop err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


def _save(st):
    try:
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        import json
        STATUS.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    main()
