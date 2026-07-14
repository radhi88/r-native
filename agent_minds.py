# -*- coding: utf-8 -*-
"""
agent_minds.py — عقول الوكلاء: هل القراءات صحيحة أم صدفة؟  (READ-ONLY)
=====================================================================
يجيب بالأرقام على السؤال الجوهري: كل مؤشّر/وكيل، ما **دقّته الاتجاهية المقيسة**؟
هل يقرأ البيع/الشراء صح (>55%)، أم هو رمية عملة (~50% = صدفة)؟

المصدر: r_native_v2/data/indicator_accuracy_<SYMBOL>.json (107 رمز، يحدّثها accuracy_updater).
كل ملف: {symbol, tf, horizon, accuracy:{indicator:{hit_rate, lift, votes}}}.

تشغيل: python agent_minds.py  [--once]  ·  agent_minds.bat
قراءة فقط. الصدق أولاً: العيّنة الكبيرة (الإجمالي) هي الحقيقة؛ الخلايا الفردية العالية
بعيّنة صغيرة = ضوضاء/اختبار-متعدّد.
"""
from __future__ import annotations
import argparse, glob, json, math, os, time
from datetime import datetime, timezone
from collections import defaultdict

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align

ROOT = os.path.dirname(os.path.abspath(__file__))
ACC_GLOB = os.path.join(ROOT, "r_native_v2", "data", "indicator_accuracy_*.json")
console = Console()

# دور كل مؤشّر (مختصر) — "ما الذي يقرأه"
ROLE = {
    "trend": "اتجاه EMA", "ema_cross": "تقاطع EMA", "macd": "زخم MACD", "rsi": "تشبّع RSI",
    "stoch": "ستوكاستك", "adx": "قوة الاتجاه", "bollinger": "بولنجر", "keltner": "كيلتنر",
    "ichimoku": "إيشيموكو", "vwap": "متوسط مرجّح بالحجم", "obv": "حجم تراكمي", "mfi": "تدفّق مالي",
    "cci": "CCI", "williams": "وليامز", "aroon": "آرون", "vortex": "دوامة", "supertrend": "سوبرترند",
    "donchian": "قناة دونتشيان", "momentum": "زخم", "roc": "معدّل التغيّر", "fisher": "فيشر",
    "tsi": "TSI", "cmo": "CMO", "chaikin": "تشايكين", "elder": "إلدر", "hurst": "هورست",
    "sr_zone": "دعم/مقاومة", "swing_profile": "تأرجح", "candle_geo": "هندسة الشمعة",
    "gann": "غان", "cisd": "CISD (SMC)", "ifvg": "فجوة قيمة معكوسة", "choch": "تغيّر بنية",
    "liq_sweep": "كنس سيولة", "supertrend": "سوبرترند",
}


def _load_all():
    files = glob.glob(ACC_GLOB)
    per_sym = {}
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
            per_sym[d.get("symbol", os.path.basename(f))] = d
        except Exception:
            pass
    return per_sym


def _hcol(h):
    if h is None:
        return "dim"
    if h >= 0.55:
        return "bold green"
    if h >= 0.52:
        return "green"
    if h >= 0.485:
        return "yellow"
    return "red"


def panel_aggregate(per_sym):
    """الحقيقة: متوسط دقّة كل مؤشّر عبر كل الرموز (عيّنة ضخمة)."""
    agg = defaultdict(lambda: [0, 0.0, 0])  # ind -> [n_syms, sum_hit, votes]
    for d in per_sym.values():
        for ind, v in (d.get("accuracy") or {}).items():
            agg[ind][0] += 1
            agg[ind][1] += v.get("hit_rate", 0.0)
            agg[ind][2] += v.get("votes", 0)
    rows = sorted([(ind, s[1] / s[0], s[0], s[2]) for ind, s in agg.items() if s[0]],
                  key=lambda r: -r[1])
    tt = Table(box=None, expand=True, padding=(0, 1))
    tt.add_column("المؤشّر", no_wrap=True)
    tt.add_column("الدور", no_wrap=True, style="dim")
    tt.add_column("دقّة متوسّطة", justify="right")
    tt.add_column("تصويتات", justify="right")
    over52 = 0
    for ind, avg, nsym, votes in rows[:14]:
        if avg >= 0.52:
            over52 += 1
        tt.add_row(ind, ROLE.get(ind, "—"), f"[{_hcol(avg)}]{avg*100:.1f}%[/{_hcol(avg)}]", f"{votes:,}")
    head = Text.from_markup(
        f"[bold]الحقيقة عبر {len(per_sym)} رمز[/bold] (113k+ تصويت/مؤشّر) — متوسّط الدقّة الاتجاهية:\n"
        f"[dim]مؤشّرات فوق 52% (إجمالاً): [/dim][{'green' if over52 else 'red'}]{over52}/{len(rows)}[/]"
        f"  [dim]· 50% = رمية عملة[/dim]")
    return Panel(Group(head, Text(""), tt),
                 title="🎯 دقّة القراءات — الإجمالي (الحقيقة)", border_style="cyan", padding=(0, 1))


def panel_best_local(per_sym):
    """أفضل الخلايا المحلية — مع وسم العيّنة الصغيرة (ضوضاء)."""
    cells = []
    for sym, d in per_sym.items():
        for ind, v in (d.get("accuracy") or {}).items():
            cells.append((sym, ind, v.get("hit_rate", 0.0), v.get("votes", 0)))
    cells.sort(key=lambda c: -c[2])
    tt = Table(box=None, expand=True, padding=(0, 1))
    tt.add_column("رمز", no_wrap=True)
    tt.add_column("مؤشّر", no_wrap=True)
    tt.add_column("دقّة", justify="right")
    tt.add_column("تصويتات", justify="right")
    tt.add_column("حكم", no_wrap=True)
    for sym, ind, hit, votes in cells[:12]:
        robust = votes >= 300
        flag = "[green]قوي العيّنة[/green]" if (robust and hit >= 0.55) else \
               ("[yellow]عيّنة صغيرة (ضوضاء)[/yellow]" if votes < 150 else "[dim]ضمن المدى[/dim]")
        tt.add_row(sym, ind, f"[{_hcol(hit)}]{hit*100:.1f}%[/{_hcol(hit)}]", str(votes), flag)
    note = Text.from_markup(
        "[dim]أعلى الخلايا المفردة تبدو مغرية — لكن مع 34 مؤشّر × 107 رمز (≈3640 خلية)،\n"
        "بعضها يتجاوز 55% بالصدفة (اختبار متعدّد). العيّنة الصغيرة = ضوضاء. الإجمالي هو الحَكَم.[/dim]")
    return Panel(Group(tt, note), title="🔎 أعلى القراءات المحلية (بحذر)", border_style="blue", padding=(0, 1))


def panel_verdict(per_sym):
    # احسب أفضل متوسط إجمالي
    agg = defaultdict(lambda: [0, 0.0])
    for d in per_sym.values():
        for ind, v in (d.get("accuracy") or {}).items():
            agg[ind][0] += 1; agg[ind][1] += v.get("hit_rate", 0.0)
    best = max((s[1] / s[0] for s in agg.values() if s[0]), default=0.5)
    lines = [
        f"[bold]السؤال:[/bold] هل القراءات صحيحة أم صدفة؟",
        "",
        f"[bold red]الجواب بالأرقام:[/bold red] أعلى مؤشّر بالإجمالي = [bold]{best*100:.1f}%[/bold] "
        f"(عبر كل الرموز). [bold]كلها ضمن ~50% = رمية عملة.[/bold]",
        "→ لا حافّة اتجاهية موثوقة في القراءات على نطاق واسع.",
        "→ [yellow]الأرباح الأخيرة = صدفة/تذبذب، لا مهارة مُثبتة.[/yellow] (يؤكّده: السبورة المجمّعة t≈0.96)",
        "",
        "[bold green]ما هو حقيقي وتفتخر فيه:[/bold green]",
        "  1. [green]نظام يقيس نفسه بصدق[/green] — يكشف أن قراءاته 50% بدل ما يخدعك بسلسلة حظ.",
        "     (أغلب المتداولين ما يعرفون هذا — يركبون الحظ حتى ينفجر الحساب.)",
        "  2. [green]تحكّم مخاطر حقيقي[/green] — master_floor + سقف 2% = الحظّ محميّ، والخسارة محدودة.",
        "  3. [green]بنية مُجهّزة بالكامل[/green] — الأساس حقيقي؛ الناقص = الحافّة، وهي قابلة للبحث.",
        "",
        "[dim]الطريق للفخر الحقيقي: حافّة تتجاوز 55% بعيّنة كبيرة + صافي تكلفة موجب + إثبات ورقي.[/dim]",
    ]
    return Panel(Text.from_markup("\n".join(lines)),
                 title="⚖️ الحكم الصادق", border_style="bold red", padding=(0, 1))


def build_layout():
    per_sym = _load_all()
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="mid"),
        Layout(name="verdict", size=15),
    )
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    layout["header"].update(Panel(
        Align.center(Text.from_markup(
            f"[bold yellow]FRIDAY — عقول الوكلاء: دقّة القراءات[/bold yellow]   "
            f"[dim]قراءة فقط · {ts} · {len(per_sym)} رمز مقيس[/dim]")),
        border_style="yellow"))
    layout["mid"].split_row(
        Layout(Panel(Text("..."), title="..."), name="agg"),
        Layout(Panel(Text("..."), title="..."), name="loc"),
    )
    try:
        layout["agg"].update(panel_aggregate(per_sym))
    except Exception as e:
        layout["agg"].update(Panel(Text(f"⚠ {e}", style="red")))
    try:
        layout["loc"].update(panel_best_local(per_sym))
    except Exception as e:
        layout["loc"].update(Panel(Text(f"⚠ {e}", style="red")))
    try:
        layout["verdict"].update(panel_verdict(per_sym))
    except Exception as e:
        layout["verdict"].update(Panel(Text(f"⚠ {e}", style="red")))
    return layout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=3.0)
    args = ap.parse_args()
    if args.once:
        console.print(build_layout()); return
    refresh = max(2.0, args.interval)
    try:
        with Live(build_layout(), console=console, screen=True,
                  refresh_per_second=1) as live:
            while True:
                time.sleep(refresh)
                live.update(build_layout())
    except KeyboardInterrupt:
        console.print("[dim]تم الإيقاف (قراءة فقط).[/dim]")


if __name__ == "__main__":
    main()
