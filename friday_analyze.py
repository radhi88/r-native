"""
friday_analyze.py — Performance analyzer powered by the data+finance plugin mindset.

Uses pandas-style analytics on:
  - friday_orders.csv     (every order attempt)
  - MT5 deal history      (actual fills)
  - friday_brain_v2_state.json  (current agent stances)

Writes:
  - C:\\Users\\Radhi\\MT5\\plutobrain\\inbox\\<ts>-friday-performance.md
  - Console summary

Run:  python friday_analyze.py
"""
from __future__ import annotations
import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

try:
    import MetaTrader5 as mt5
    HAS_MT5 = True
except ImportError:
    HAS_MT5 = False

ROOT       = Path(r"C:\Users\Radhi\MT5")
ORDERS_LOG = ROOT / "friday_orders.csv"
STATE_F    = ROOT / "friday_brain_v2_state.json"
INBOX      = ROOT / "plutobrain" / "inbox"
MAGIC      = 20260600
SYMBOL     = "XAUUSDm"


def load_orders():
    if not ORDERS_LOG.exists(): return []
    rows = []
    with open(ORDERS_LOG, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader: rows.append(r)
    return rows


def analyze_orders(rows):
    if not rows: return {}
    kinds = Counter(r["kind"] for r in rows)
    sides = Counter(r["side"] for r in rows)
    skip_reasons = Counter()
    for r in rows:
        if r["kind"] == "SKIP":
            note = r.get("note", "")
            # Extract pattern
            if "R:R" in note:        skip_reasons["bad R:R"] += 1
            elif "tp_move" in note:  skip_reasons["TP < 3× spread"] += 1
            elif "risk" in note:     skip_reasons["risk too small"] += 1
            else:                    skip_reasons["other"] += 1

    live_orders = [r for r in rows if r["kind"] in ("LIVE", "SCALP")]
    return {
        "total_attempts": len(rows),
        "by_kind":        dict(kinds),
        "by_side":        dict(sides),
        "live_placed":    len(live_orders),
        "skip_breakdown": dict(skip_reasons),
        "live_orders":    [{"ts": r["ts"], "side": r["side"], "price": r["price"],
                            "sl": r["sl"], "tp": r["tp"]} for r in live_orders[-10:]],
    }


def analyze_deals(hours=24):
    if not HAS_MT5: return {"error": "MetaTrader5 not installed"}
    if not mt5.initialize(): return {"error": "MT5 init failed"}
    info = mt5.account_info()
    deals = mt5.history_deals_get(datetime.now() - timedelta(hours=hours), datetime.now()) or []
    xau   = [d for d in deals if d.symbol == SYMBOL]
    brain = [d for d in xau if d.magic == MAGIC]
    other = [d for d in xau if d.magic != MAGIC]

    by_magic = defaultdict(lambda: {"deals": [], "buys": 0, "sells": 0, "pl": 0.0})
    for d in xau:
        m = by_magic[d.magic]
        m["deals"].append(d)
        if d.type == 0: m["buys"]  += 1
        else:           m["sells"] += 1
        m["pl"] += d.profit

    # Brain's own win/loss
    closed = [d for d in brain if d.entry in (1, 3)]  # OUT or OUT_BY
    wins   = [d for d in closed if d.profit > 0]
    losses = [d for d in closed if d.profit < 0]

    win_rate = (len(wins) / len(closed) * 100) if closed else 0
    avg_win  = statistics.mean([d.profit for d in wins])  if wins   else 0
    avg_loss = statistics.mean([d.profit for d in losses]) if losses else 0
    profit_factor = (sum(d.profit for d in wins) / abs(sum(d.profit for d in losses))) \
                    if losses and sum(d.profit for d in losses) < 0 else 0

    mt5.shutdown()
    return {
        "account_balance": info.balance,
        "account_equity":  info.equity,
        "hours":           hours,
        "total_deals":     len(xau),
        "brain_deals":     len(brain),
        "other_ea_deals":  len(other),
        "brain_closed":    len(closed),
        "brain_wins":      len(wins),
        "brain_losses":    len(losses),
        "brain_win_rate":  round(win_rate, 1),
        "brain_avg_win":   round(avg_win, 2),
        "brain_avg_loss":  round(avg_loss, 2),
        "brain_pl":        round(sum(d.profit for d in brain), 2),
        "profit_factor":   round(profit_factor, 2) if profit_factor else None,
        "by_magic_summary": {str(m): {"deals": len(d["deals"]), "buys": d["buys"],
                                       "sells": d["sells"], "pl": round(d["pl"], 2),
                                       "is_brain": m == MAGIC}
                              for m, d in by_magic.items()},
    }


def write_report(ord_stats, deal_stats):
    INBOX.mkdir(parents=True, exist_ok=True)
    ts = datetime.now()
    fp = INBOX / f"{ts:%Y-%m-%d-%H%M}-friday-performance.md"

    lines = [
        "---",
        "type: performance-report",
        f"captured: {ts:%Y-%m-%d %H:%M:%S}",
        "source: friday_analyze",
        "---",
        "",
        f"# تقرير أداء FRIDAY — {ts:%Y-%m-%d %H:%M}",
        "",
        "## الحساب",
        f"- Balance: **{deal_stats.get('account_balance', '?')} USD**",
        f"- Equity:  {deal_stats.get('account_equity', '?')} USD",
        "",
        "## آخر 24 ساعة على XAUUSDm",
        f"- إجمالي الصفقات: {deal_stats.get('total_deals', 0)}",
        f"- صفقات الـ Brain (magic {MAGIC}): {deal_stats.get('brain_deals', 0)}",
        f"- صفقات EAs أخرى: **{deal_stats.get('other_ea_deals', 0)}** ⚠️" if deal_stats.get('other_ea_deals', 0) > 0 else f"- صفقات EAs أخرى: 0 ✓",
        "",
        "## أداء الـ Brain فقط",
        f"- صفقات مغلقة: {deal_stats.get('brain_closed', 0)}",
        f"- رابحة: {deal_stats.get('brain_wins', 0)}",
        f"- خاسرة: {deal_stats.get('brain_losses', 0)}",
        f"- **Win rate: {deal_stats.get('brain_win_rate', 0)}%**",
        f"- متوسط الربح: ${deal_stats.get('brain_avg_win', 0):+.2f}",
        f"- متوسط الخسارة: ${deal_stats.get('brain_avg_loss', 0):+.2f}",
        f"- **P/L الإجمالي: ${deal_stats.get('brain_pl', 0):+.2f}**",
        f"- Profit Factor: {deal_stats.get('profit_factor')}" if deal_stats.get('profit_factor') else "- Profit Factor: لا يكفي عينة",
        "",
        "## محاولات الـ Brain (سجلّ orders.csv)",
        f"- إجمالي المحاولات: {ord_stats.get('total_attempts', 0)}",
        f"- LIVE تم وضعها: {ord_stats.get('live_placed', 0)}",
        "",
        "### تفصيل حسب النوع:",
        "",
        "| النوع | عدد |",
        "|---|---|",
    ]
    for kind, count in (ord_stats.get('by_kind', {}) or {}).items():
        lines.append(f"| {kind} | {count} |")
    lines.append("")

    if ord_stats.get('skip_breakdown'):
        lines.append("### أسباب التخطّي (Guards التي اشتغلت):")
        lines.append("")
        for reason, count in ord_stats['skip_breakdown'].items():
            lines.append(f"- {reason}: **{count}** مرة")
        lines.append("")

    # Toxic magic detection
    rogue = [(m, d) for m, d in deal_stats.get('by_magic_summary', {}).items()
             if not d.get('is_brain') and d['pl'] < -5]
    if rogue:
        lines.append("## ⚠️ EAs مارقة كشفناها")
        lines.append("")
        for m, d in rogue:
            lines.append(f"- magic **{m}**: {d['deals']} صفقة، P/L = **${d['pl']:+.2f}**")
        lines.append("")
        lines.append("**التوصية**: أزل هذه EAs من شارت MT5 فوراً.")
        lines.append("")

    # Recommendations
    lines.append("## التوصيات")
    if deal_stats.get('brain_closed', 0) < 5:
        lines.append("- العيّنة صغيرة جداً (<5 صفقات مغلقة). انتظر مزيداً من الدورات قبل تقييم الأداء.")
    elif deal_stats.get('brain_win_rate', 0) < 40:
        lines.append("- Win rate < 40%. راجع threshold الـ R:R أو شدّد القرارات.")
    elif deal_stats.get('profit_factor') and deal_stats['profit_factor'] < 1.0:
        lines.append("- Profit Factor < 1. الـ R:R يحتاج تحسيناً.")
    else:
        lines.append("- النظام في حدود المقبول. استمرّ في المراقبة.")

    fp.write_text("\n".join(lines), encoding="utf-8")
    return fp


def main():
    print("═══ FRIDAY Performance Analyzer ═══\n")
    orders = load_orders()
    ord_stats = analyze_orders(orders)
    deal_stats = analyze_deals(24)

    print("Orders log:")
    print(f"  Total attempts: {ord_stats.get('total_attempts', 0)}")
    print(f"  By kind:        {ord_stats.get('by_kind', {})}")
    print(f"  LIVE placed:    {ord_stats.get('live_placed', 0)}")
    print()
    print("MT5 history (24h):")
    print(f"  Balance: {deal_stats.get('account_balance')} | Equity: {deal_stats.get('account_equity')}")
    print(f"  Brain deals: {deal_stats.get('brain_deals')} (P/L ${deal_stats.get('brain_pl')})")
    print(f"  Other EA deals: {deal_stats.get('other_ea_deals')}")
    print(f"  Win rate: {deal_stats.get('brain_win_rate')}%")

    fp = write_report(ord_stats, deal_stats)
    print(f"\n✓ Report written → {fp.name}")


if __name__ == "__main__":
    main()
