# -*- coding: utf-8 -*-
"""portfolio_guard.py — حارس محفظة عابر للمحرّكات: يمنع فتح صفقة جديدة بعكس اتجاه
صفقة مفتوحة لمحرّكٍ آخر من محرّكاتنا على نفس العملة.

السبب (مُثبت حيّاً): محرّكان مختلفان (مثلاً multi_trader 20260608 يشتري الذهب
بينما army_warroom 20260618 يبيعه) يفتحان عكس بعض على نفس الرمز ⇒ تحوّط-بيني =
سبريد مزدوج وغسلٌ مضمون بلا حافّة (كلا الطرفين يقعدان أحمرين). نمنع الفتح الجديد فقط.

نقي بلا حالة: يقرأ المراكز المفتوحة فقط — لا order_send، لا كتابة، لا تأثير جانبي.
fail-open: أيّ خطأ أو غياب بيانات ⇒ (False, "") فلا يَحجب التداول أبداً بسبب عطل بالحارس.

قاعدة الاستثناء: يتجاهل صفقاتي (magic == my_magic)، فمحرّكات التحوّط-الذاتي
(gene_tournament 20260612: ساقان متعاكستان بنفس magic؛ news_gene/orb: سلالم
معلّقة متعاكسة) لا تتأثّر لأن ساقَيها يحملان نفس magic = مستثناة تلقائياً.
المحميّة (يدويّ 0 / EA خارجية للمستخدم) ليست في OUR_MAGICS أبداً ⇒ لا تُلمَس ولا تُقيّد محرّكاتنا.
"""
from __future__ import annotations

# محرّكاتنا غير-المحميّة فقط. لا تُدرَج أبداً المحميّة: 0, 2447, 20250418, 20250421, 20250422, 20250618
OUR_MAGICS = frozenset({
    20260605,  # algory / orchestrator
    20260608,  # multi_trader (primary)
    20260611,  # ours
    20260612,  # gene_tournament (تحوّط ذاتي — مستثنى عبر تخطّي my_magic)
    20260613,  # multi_trader hybrid
    20260614,  # news_gene (معلّق ذاتي)
    20260616,  # orb_trader (معلّق ذاتي)
    20260617,  # spike_rider
    20260618,  # army_warroom
    20260626,  # geometric desk
    20260628,  # gold_scalper
    20260629,  # pipflow_core (per-symbol multi-TF analyzer-trader)
})


def would_hedge(mt5, symbol, order_type, my_magic, our_magics=OUR_MAGICS):
    """يرجع (True, reason) إذا كان أيّ محرّكٍ آخر من محرّكاتنا يحمل الاتجاه المعاكس
    على نفس العملة تماماً. order_type: 0=BUY, 1=SELL (ثوابت MT5 نفسها).

    آمن بالتصميم: أيّ استثناء أو غياب بيانات ⇒ (False, "") فلا يَحجب أبداً.
    """
    try:
        ot = int(order_type)
        opp_pos_type = 1 if ot == 0 else 0     # BUY(0) يصطدم بمركز SELL(type=1) والعكس
        try:
            positions = mt5.positions_get(symbol=symbol) or ()
        except Exception:
            return (False, "")
        for p in positions:
            pm = getattr(p, "magic", None)
            if pm is None or pm == my_magic:   # تجاهل صفقاتي (يشمل ساقَي التحوّط-الذاتي)
                continue
            if pm not in our_magics:           # تجاهل المحميّة/الخارجية ومحرّكات ليست لنا
                continue
            if getattr(p, "type", None) == opp_pos_type:
                my_side = "BUY" if ot == 0 else "SELL"
                opp_side = "SELL" if ot == 0 else "BUY"
                return (True, "anti-hedge: %s %s blocked — magic %s already %s (ticket %s)" %
                        (my_side, symbol, pm, opp_side, getattr(p, "ticket", "?")))
        return (False, "")
    except Exception:
        return (False, "")  # فشل آمن: لا تحجب أبداً بسبب خطأ في الحارس


if __name__ == "__main__":  # اختبار دخان سريع بكائن MT5 وهمي
    class _P:
        def __init__(s, magic, typ, ticket=1): s.magic, s.type, s.ticket = magic, typ, ticket
    class _MT5:
        def __init__(s, poss): s._poss = poss
        def positions_get(s, symbol=None): return s._poss
    # محرّك آخر (army 20260618) يحمل SELL على الذهب؛ multi (20260608) يريد BUY ⇒ يجب الحجب
    m = _MT5([_P(20260618, 1)])
    print(would_hedge(m, "XAUUSDm", 0, 20260608))   # (True, ...)
    # نفس الاتجاه ⇒ لا حجب
    print(would_hedge(_MT5([_P(20260618, 0)]), "XAUUSDm", 0, 20260608))  # (False, "")
    # صفقتي أنا (نفس magic) ⇒ لا حجب (تحوّط ذاتي مسموح)
    print(would_hedge(_MT5([_P(20260612, 1)]), "XAUUSDm", 0, 20260612))  # (False, "")
    # محميّ/خارجي ⇒ يُتجاهل
    print(would_hedge(_MT5([_P(0, 1)]), "XAUUSDm", 0, 20260608))         # (False, "")
