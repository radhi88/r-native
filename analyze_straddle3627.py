"""analyze_straddle3627.py — تحليل أداء بوت الذهب (magic 3627) من قاعدة SQLite.

يجيب على: هل دخولنا مبني على مؤشرات صحيحة فعلاً، أم صدفة؟
يربط كل عامل قرار (ترند/شموع/SMC/سبريد/مع-أو-ضد) بالنتيجة (الربح/نسبة الربح)،
فنعرف أي عامل يتنبّأ فعلاً بالربح ونطوّر عليه أو ندمجه في مشاريع ثانية.

Run:  python analyze_straddle3627.py
"""
import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\Radhi\MT5\data\r_native\straddle3627.db")


def _grp(con, expr, label, where="net IS NOT NULL"):
    """متوسط الربح ونسبة الربح وعدد الصفقات لكل قيمة من expr."""
    rows = list(con.execute(
        f"SELECT {expr} AS g, COUNT(*), ROUND(SUM(net),2), ROUND(AVG(net),3), "
        f"ROUND(100.0*SUM(win)/COUNT(*),0) FROM episodes WHERE {where} GROUP BY g ORDER BY SUM(net) DESC"))
    if not rows:
        return
    print(f"\n── {label} ──")
    print(f"   {'القيمة':<22}{'عدد':>5}{'صافي':>9}{'متوسط':>8}{'ربح٪':>6}")
    for g, n, s, a, wr in rows:
        print(f"   {str(g):<22}{n:>5}{s:>9.2f}{a:>8.3f}{(wr or 0):>5.0f}%")


def main():
    if not DB.exists():
        print("لا توجد قاعدة بعد:", DB); return
    con = sqlite3.connect(str(DB))
    tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]

    # ── سجلّ المال الخام ──
    if "deals" in tabs:
        r = con.execute("SELECT COUNT(*), ROUND(SUM(net),2), "
                        "ROUND(100.0*SUM(CASE WHEN net>0 THEN 1 ELSE 0 END)/COUNT(*),0) "
                        "FROM deals WHERE net<>0").fetchone()
        print("═══ سجلّ المال (كل الصفقات المغلقة) ═══")
        print(f"   صفقات {r[0]} · صافي محقّق {r[1]:+.2f} · نسبة ربح {r[2]:.0f}%")
        print("   حسب نوع الإغلاق:")
        for c, n, s in con.execute("SELECT CASE WHEN comment LIKE '%flip%' THEN 'إغلاق-سوق (flip)' "
                                   "WHEN comment LIKE '%sl%' OR comment LIKE '%[sl%' THEN 'وقف-متحرّك (SL)' "
                                   "ELSE comment END g, COUNT(*), ROUND(SUM(net),2) "
                                   "FROM deals WHERE net<>0 GROUP BY g ORDER BY SUM(net)"):
            print(f"      {c:<22} عدد {n:<4} صافي {s:+.2f}")

    # ── تحليل العوامل (هل الدخول صح أم صدفة؟) ──
    nep = con.execute("SELECT COUNT(*) FROM episodes WHERE net IS NOT NULL").fetchone()[0] if "episodes" in tabs else 0
    print(f"\n═══ تحليل العوامل (صفقات مُسجّلة بالكامل: {nep}) ═══")
    if nep < 8:
        print("   العيّنة صغيرة بعد — التحليل العاملي يحتاج تراكم (شغّل البوت أطول).")
    else:
        tot = con.execute("SELECT ROUND(SUM(net),2), ROUND(AVG(net),3), "
                          "ROUND(100.0*SUM(win)/COUNT(*),0) FROM episodes WHERE net IS NOT NULL").fetchone()
        print(f"   الإجمالي: صافي {tot[0]:+.2f} · متوسط/صفقة {tot[1]:+.3f} · نسبة ربح {tot[2]:.0f}%")
        _grp(con, "CASE with_trend WHEN 1 THEN 'مع الترند' ELSE 'ضد الترند' END", "مع/ضد ترند M5")
        _grp(con, "smc_rel", "انحياز SMC")
        _grp(con, "CASE WHEN conv>=0.6 THEN 'قناعة عالية≥0.6' WHEN conv>=0.4 THEN 'متوسطة' ELSE 'منخفضة<0.4' END", "قوة القناعة (اكيد؟)")
        _grp(con, "CASE WHEN tstr>=0.5 THEN 'ترند قوي≥0.5' WHEN tstr>=0.25 THEN 'متوسط' ELSE 'ضعيف<0.25' END", "قوة الترند")
        _grp(con, "CASE WHEN cstr>=0.55 THEN 'شمعة قوية≥0.55' WHEN cstr>=0.45 THEN 'متوسطة' ELSE 'ضعيفة<0.45' END", "قوة الشمعة")
        _grp(con, "cpat", "شكل 3 شموع")
        _grp(con, "legs_filled", "أرجل امتلأت (تعبئة)")
        _grp(con, "CASE WHEN entry_dir>0 THEN 'BUY' ELSE 'SELL' END", "الاتجاه")
        _grp(con, "exit_reason", "سبب الخروج")
        print("\n   💡 العامل الذي صافيه ومتوسطه ونسبة ربحه أعلى = إشارة حقيقية (لا صدفة).")
        print("      العامل الذي نتيجته ~صفر أو سلبية عبر كل قيمه = لا يضيف (نزيله/نطوّره).")
    con.close()


if __name__ == "__main__":
    main()
