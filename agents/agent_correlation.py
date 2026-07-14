# -*- coding: utf-8 -*-
"""
agent_correlation.py — 7 وكلاء نقيّون لحظيّون لفئة الارتباط (correlation).

عقد صارم موحّد:
    def agent_NAME(ctx) -> (vote:int[-1|0|1], confidence:float[0..1], reason:str)

هذه الفئة عبر-رمزيّة: تحتاج نبض رموز أخرى. تُقرأ من:
    ctx['peers']  أو  ctx['pulse_symbols']  = { 'EURUSDm': {..pulse..}, ... }
كلّ مدخل يحوي على الأقل 'price' و(اختياريّاً) spark / momentum.trend_m5.
غياب بيانات المرتبط ⇒ (0, 0.0, "مرتبط غير متاح") — لا استثناء أبداً.
"""
import numpy as np

VETO = (0, 0.0, "بيانات ناقصة")


# ----------------------------------------------------------------------------
# أدوات داخليّة دفاعيّة
# ----------------------------------------------------------------------------
def _peers(ctx):
    for key in ("peers", "pulse_symbols", "symbols", "all_symbols"):
        p = ctx.get(key)
        if isinstance(p, dict) and p:
            return p
    return {}


def _sym(ctx):
    return ctx.get("sym") or ctx.get("symbol") or ""


def _peer_trend(peer):
    """اتجاه المرتبط: من momentum.trend_m5 أو ميل spark. يرجع (dir, mag[0..1]) أو (0,0)."""
    if not isinstance(peer, dict):
        return 0, 0.0
    mom = peer.get("momentum")
    if isinstance(mom, dict):
        t = mom.get("trend_m5")
        if t is None:
            t = mom.get("trend_m1")
        if t in (-1, 1):
            return int(t), 0.6
    spark = peer.get("spark")
    if spark:
        try:
            a = np.asarray(spark, dtype=float)
            if a.size >= 6:
                seg = a[-min(20, a.size):]
                x = np.arange(seg.size, dtype=float)
                slope = float(np.polyfit(x, seg, 1)[0])
                rng = float(np.nanmax(seg) - np.nanmin(seg)) or 1.0
                norm = slope * seg.size / rng
                if abs(norm) < 0.08:
                    return 0, 0.0
                return (1 if norm > 0 else -1), min(1.0, abs(norm))
        except Exception:
            return 0, 0.0
    return 0, 0.0


def _find_peer(peers, *cands):
    """يبحث عن أوّل رمز مطابق (بتسامح لاحقة m/pro)."""
    keys = list(peers.keys())
    for cand in cands:
        if cand in peers:
            return cand, peers[cand]
        for k in keys:
            base = k.rstrip("m").rstrip(".").upper()
            if base == cand.rstrip("m").upper() or k.upper().startswith(cand.upper()):
                return k, peers[k]
    return None, None


def _clamp(x):
    return float(max(0.0, min(1.0, x)))


def _self_trend(ctx):
    """اتجاه الرمز نفسه من ctx (trend_m5 أو ميل m5.close)."""
    mom = ctx.get("m5", {})
    try:
        c = np.asarray(ctx.get("m5", {}).get("c"), dtype=float)
        if c is not None and c.size >= 5:
            leg = float(c[-1] - c[-5])
            if leg != 0:
                return 1 if leg > 0 else -1
    except Exception:
        pass
    p = ctx.get("smc", ctx)
    if isinstance(p, dict):
        t = p.get("trend")
        if t in (-1, 1):
            return int(t)
    return 0


# ----------------------------------------------------------------------------
# 1) dxy_inverse_gold — تحيّز الذهب عكس اتّجاه الدولار (DXY)
# ----------------------------------------------------------------------------
def agent_dxy_inverse_gold(ctx):
    try:
        sym = _sym(ctx)
        peers = _peers(ctx)
        if not peers:
            return VETO
        # ينطبق على المعادن والأصول المسعّرة بالدولار عكسيّاً
        base = sym.upper()
        is_metal = base.startswith(("XAU", "XAG"))
        _, dxy = _find_peer(peers, "DXYm", "DXY")
        if dxy is None:
            return (0, 0.0, "DXY غير متاح")
        d_dir, d_mag = _peer_trend(dxy)
        if d_dir == 0:
            return (0, 0.1, "DXY بلا اتجاه واضح")
        if not is_metal:
            return (0, 0.0, "غير معدن — DXY-عكس لا ينطبق")
        direction = -d_dir  # الذهب عكس الدولار
        conf = _clamp(0.4 + 0.4 * d_mag)
        d = "صعود" if direction > 0 else "هبوط"
        return (direction, conf, f"DXY {'يصعد' if d_dir>0 else 'يهبط'} ⇒ ذهب {d}")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 2) gold_silver_lead — تقدّم/تخلّف الفضّة عن الذهب كتأكيد اتجاه المعدن
# ----------------------------------------------------------------------------
def agent_gold_silver_lead(ctx):
    try:
        sym = _sym(ctx).upper()
        peers = _peers(ctx)
        if not peers:
            return VETO
        if not sym.startswith(("XAU", "XAG")):
            return (0, 0.0, "غير معدن ثمين")
        # الرمز الآخر من زوج الذهب/الفضّة
        other = "XAGUSDm" if sym.startswith("XAU") else "XAUUSDm"
        _, peer = _find_peer(peers, other)
        if peer is None:
            return (0, 0.0, "المعدن المرتبط غير متاح")
        p_dir, p_mag = _peer_trend(peer)
        s_dir = _self_trend(ctx)
        if p_dir == 0:
            return (0, 0.1, "المعدن المرتبط بلا اتجاه")
        if s_dir != 0 and s_dir == p_dir:
            conf = _clamp(0.45 + 0.35 * p_mag)
            d = "صعود" if p_dir > 0 else "هبوط"
            return (p_dir, conf, f"المعدنان متّسقان ({d}) — تأكيد قياديّ")
        # المعدن المرتبط يقود ولا تأكيد بعد ⇒ تحيّز أضعف بنفس اتجاهه
        return (p_dir, _clamp(0.3 + 0.2 * p_mag), "المعدن المرتبط يقود الاتجاه")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 3) usd_pairs_align — اتّساق أزواج الدولار لتحديد قوّة الدولار الكليّة
# ----------------------------------------------------------------------------
def agent_usd_pairs_align(ctx):
    try:
        sym = _sym(ctx).upper()
        peers = _peers(ctx)
        if not peers:
            return VETO
        # مؤشّر قوّة الدولار: EURUSD/GBPUSD/AUDUSD (USD مقام ⇒ صعودها=ضعف دولار)
        usd_quote = ["EURUSDm", "GBPUSDm", "AUDUSDm", "NZDUSDm"]
        votes = []
        for name in usd_quote:
            _, pr = _find_peer(peers, name)
            if pr is None:
                continue
            d, m = _peer_trend(pr)
            if d != 0:
                votes.append(-d)  # صعود الزوج ⇒ دولار يضعف ⇒ قوّة الدولار سالبة
        if len(votes) < 2:
            return (0, 0.0, "أزواج دولار غير كافية")
        usd_strength = int(np.sign(sum(votes)))
        agree = abs(sum(votes)) / len(votes)
        if usd_strength == 0 or agree < 0.5:
            return (0, 0.15, "أزواج الدولار متضاربة")
        # ترجيح الرمز الحاليّ حسب موضع الدولار فيه
        if sym.startswith("USD"):          # USD أساس ⇒ نفس اتجاه قوّة الدولار
            direction = usd_strength
        elif sym.endswith("USDM") or sym.endswith("USD"):  # USD مقام ⇒ عكسها
            direction = -usd_strength
        elif sym.startswith(("XAU", "XAG")):
            direction = -usd_strength      # المعادن عكس الدولار
        else:
            return (0, 0.1, "الرمز لا يتأثّر مباشرة بقوّة الدولار")
        conf = _clamp(0.35 + 0.4 * agree)
        d = "قويّ" if usd_strength > 0 else "ضعيف"
        return (direction, conf, f"دولار {d} (اتّساق {agree:.0%})")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 4) jpy_risk_proxy — أزواج الين كوكيل مخاطرة (risk-on/off)
# ----------------------------------------------------------------------------
def agent_jpy_risk_proxy(ctx):
    try:
        sym = _sym(ctx).upper()
        peers = _peers(ctx)
        if not peers:
            return VETO
        # صعود أزواج الين (JPY مقام) = risk-on
        jpy = ["USDJPYm", "EURJPYm", "GBPJPYm"]
        votes = []
        for name in jpy:
            _, pr = _find_peer(peers, name)
            if pr is None:
                continue
            d, m = _peer_trend(pr)
            if d != 0:
                votes.append(d)
        if len(votes) < 2:
            return (0, 0.0, "أزواج الين غير كافية")
        risk_on = int(np.sign(sum(votes)))
        agree = abs(sum(votes)) / len(votes)
        if risk_on == 0 or agree < 0.5:
            return (0, 0.12, "نبرة المخاطرة محايدة")
        # الأصول عالية المخاطرة (مؤشّرات/كريبتو) تتماشى مع risk-on
        risky = sym.startswith(("US30", "US500", "NAS", "BTC", "ETH", "AUD", "NZD"))
        safe = sym.startswith(("XAU", "USDCHF", "USDJPY"))
        if risky:
            direction = risk_on
        elif safe:
            direction = -risk_on
        else:
            return (0, 0.1, "الرمز محايد تجاه المخاطرة")
        conf = _clamp(0.3 + 0.35 * agree)
        d = "on" if risk_on > 0 else "off"
        return (direction, conf, f"risk-{d} عبر أزواج الين (اتّساق {agree:.0%})")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 5) btc_risk_sentiment — نبرة البتكوين كمؤشّر شهيّة مخاطرة
# ----------------------------------------------------------------------------
def agent_btc_risk_sentiment(ctx):
    try:
        sym = _sym(ctx).upper()
        peers = _peers(ctx)
        if not peers:
            return VETO
        _, btc = _find_peer(peers, "BTCUSDm", "BTCUSD")
        if btc is None:
            return (0, 0.0, "BTC غير متاح")
        d, m = _peer_trend(btc)
        if d == 0:
            return (0, 0.1, "BTC بلا اتجاه")
        if sym.startswith("BTC"):
            return (0, 0.0, "الرمز هو BTC نفسه")
        risky = sym.startswith(("ETH", "US30", "US500", "NAS", "AUD", "NZD"))
        if not risky:
            return (0, 0.08, "الرمز ضعيف الارتباط بشهيّة الكريبتو")
        conf = _clamp(0.28 + 0.3 * m)
        d_txt = "صاعدة" if d > 0 else "هابطة"
        return (d, conf, f"شهيّة مخاطرة {d_txt} (BTC)")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 6) index_basket_beta — سلّة المؤشّرات كبيتا سوق ترجّح تحيّز الرمز
# ----------------------------------------------------------------------------
def agent_index_basket_beta(ctx):
    try:
        sym = _sym(ctx).upper()
        peers = _peers(ctx)
        if not peers:
            return VETO
        idx = ["US30m", "US500m", "NAS100m", "US100m"]
        votes = []
        for name in idx:
            _, pr = _find_peer(peers, name)
            if pr is None:
                continue
            d, m = _peer_trend(pr)
            if d != 0:
                votes.append(d)
        if not votes:
            return (0, 0.0, "سلّة المؤشّرات غير متاحة")
        market = int(np.sign(sum(votes)))
        agree = abs(sum(votes)) / len(votes)
        if market == 0:
            return (0, 0.1, "السوق العامّ محايد")
        # المؤشّرات نفسها + الأصول عالية البيتا تتبع السوق
        if sym.startswith(("US30", "US500", "NAS", "US100", "BTC", "ETH", "AUD", "NZD")):
            direction = market
        elif sym.startswith(("XAU", "USDCHF")):
            direction = -market  # ملاذات آمنة عكس بيتا السوق (تحيّز ضعيف)
        else:
            return (0, 0.1, "بيتا السوق ضعيفة على الرمز")
        conf = _clamp(0.28 + 0.35 * agree)
        d = "صاعد" if market > 0 else "هابط"
        return (direction, conf, f"بيتا سوق {d} (اتّساق {agree:.0%})")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# 7) corr_conflict_veto — تعارض قويّ بين رمز ومرتبطه المعاكس ⇒ يصوّت 0
# ----------------------------------------------------------------------------
def agent_corr_conflict_veto(ctx):
    try:
        sym = _sym(ctx).upper()
        peers = _peers(ctx)
        if not peers:
            return VETO
        s_dir = _self_trend(ctx)
        if s_dir == 0:
            return (0, 0.0, "الرمز بلا اتجاه — لا تعارض")
        # حدّد المرتبط المُعاكس المتوقّع
        anti = None
        if sym.startswith(("XAU", "XAG")):
            _, anti = _find_peer(peers, "DXYm", "DXY")       # الذهب عكس الدولار
            expect_same = False
        elif sym.startswith("USDJPY"):
            _, anti = _find_peer(peers, "US500m", "US30m")   # الين الآمن عكس المؤشّرات
            expect_same = False
        else:
            return (0, 0.0, "لا مرتبط معاكس معرّف لهذا الرمز")
        if anti is None:
            return (0, 0.0, "المرتبط المعاكس غير متاح")
        a_dir, a_mag = _peer_trend(anti)
        if a_dir == 0:
            return (0, 0.1, "المرتبط المعاكس بلا اتجاه")
        # التوافق السليم: الرمز والمرتبط المعاكس في اتجاهين متضادّين
        # تعارض = تحرّكا معاً بنفس الاتجاه (وهو شذوذ) ⇒ كبح
        if s_dir == a_dir and a_mag >= 0.4:
            conf = _clamp(0.5 + 0.4 * a_mag)
            return (0, conf, "تعارض مع المرتبط المعاكس ⇒ كبح (فيتو 0)")
        return (0, 0.15, "لا تعارض جوهريّ")
    except Exception:
        return VETO


# ----------------------------------------------------------------------------
# التسجيل الموحّد
# ----------------------------------------------------------------------------
AGENTS = [
    ("dxy_inverse_gold",   "correlation", agent_dxy_inverse_gold,   1.0),
    ("gold_silver_lead",   "correlation", agent_gold_silver_lead,   1.0),
    ("usd_pairs_align",    "correlation", agent_usd_pairs_align,    1.0),
    ("jpy_risk_proxy",     "correlation", agent_jpy_risk_proxy,     1.0),
    ("btc_risk_sentiment", "correlation", agent_btc_risk_sentiment, 1.0),
    ("index_basket_beta",  "correlation", agent_index_basket_beta,  1.0),
    ("corr_conflict_veto", "correlation", agent_corr_conflict_veto, 1.0),
]
