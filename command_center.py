# -*- coding: utf-8 -*-
"""
command_center.py  —  FRIDAY Unified Command Center  (READ-ONLY)
================================================================
مركز قيادة موحّد للقراءة فقط يجمع كل مكوّنات FRIDAY في شاشة rich واحدة.

قواعد صارمة:
  * قراءة فقط مطلقاً — لا order_send، لا تعديل أي ملف قائم.
  * كل لوحة داخل try/except (لوحة معطوبة لا تُسقط الشاشة — درس الحارس).
  * يفضّل ملفات JSON المُجمَّعة الجاهزة على ضرب MT5 الثقيل / chart_read.

التشغيل:
    python command_center.py            # حلقة rich.Live حيّة (refresh ~1.5s)
    python command_center.py --once     # دورة رسم واحدة ثم خروج (للإثبات)
    python command_center.py --interval 2.0

المصادر الحيّة (كلّها قراءة فقط):
  - MetaTrader5 API (احتياطي للرأس فقط؛ نفضّل pnl_scoreboard.json)
  - data/r_native/pnl_scoreboard.json   (P&L اليوم/7أ حسب المصدر + verdict)
  - data/r_native/autopilot_status.json (رأس موحّد + safety_flag + engines)
  - data/r_native/army_scoreboard.json  (stats[sym]={n,wins,sumR} → التدرّج)
  - data/r_native/watchdog_status.json  (n_alive/n_total + restarts)
  - data/r_native/edge_guard.json       (discipline_score + violations)
  - data/r_native/manual_guard.json     (الصفقات اليدوية المكشوفة)
  - data/r_native/margin_usage.json     (قاطع الهامش)
  - data/r_native/dd_recovery_state.json(السحب + severity)
  - data/r_native/recovery_mode.json    (وضع الاسترداد)
  - data/lab_cache/UNIVERSE_SCAN_REPORT.md (الحوافّ المُثبتة OOS)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone, timedelta

# ----------------------------------------------------------------------------
# rich (لوحة العرض)
# ----------------------------------------------------------------------------
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align

# ----------------------------------------------------------------------------
# مسارات (مطلقة وآمنة)
# ----------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
RN = os.path.join(DATA, "r_native")
LAB = os.path.join(DATA, "lab_cache")

P_PNL        = os.path.join(RN, "pnl_scoreboard.json")
P_AUTOPILOT  = os.path.join(RN, "autopilot_status.json")
P_ARMY       = os.path.join(RN, "army_scoreboard.json")
P_WATCHDOG   = os.path.join(RN, "watchdog_status.json")
P_EDGEGUARD  = os.path.join(RN, "edge_guard.json")
P_MANUAL     = os.path.join(RN, "manual_guard.json")
P_MARGIN     = os.path.join(RN, "margin_usage.json")
P_DD         = os.path.join(RN, "dd_recovery_state.json")
P_RECOVERY   = os.path.join(RN, "recovery_mode.json")
P_UNIVERSE   = os.path.join(LAB, "UNIVERSE_SCAN_REPORT.md")
# مصادر هذه الجلسة الجديدة
P_FLOOR      = os.path.join(RN, "master_floor_state.json")   # القمة/الأرضية المتحركة
P_BASELINE   = os.path.join(RN, "experiment_100_baseline.json")  # تجربة الـ$100
P_KILL       = os.path.join(ROOT, "kill_switch.txt")          # مفتاح الإيقاف الطارئ
# أقفال المنفّذين الوحيدة (port لكل محرّك) — وجود LISTEN = منفّذ واحد فعّال
SINGLETON_PORTS = {"war_room": 8617, "multi_trader": 8708, "gene_tournament": 8712,
                   "news_gene": 8714, "spike_rider": 8716}

# الوضع الحالي بعد إطلاق المستخدم (لا حدود يومية/سقف صفقة — master_floor هو الفرملة الوحيدة)
AGGRESSIVE = True
MASTER_FLOOR_FRAC = 0.50   # تصفية عند هبوط الحقوق لـ50% من القمة

# ----------------------------------------------------------------------------
# خريطة المغناطيسات (من today_src/d7_src الحيّة + الذاكرة)
# ----------------------------------------------------------------------------
MAGIC_NAMES = {
    20260608: "multi_trader",
    20260612: "بطولة التوائم",
    20260613: "الهجائن 🧬",
    20260618: "war_room",
    20260605: "r_exec/pair_spec",
    20260611: "صياد القفزات",
    20260614: "جين الأخبار 🪜",
    20260616: "ORB 🎯",
    20260617: "spike_rider",
    3627:     "gold_straddle",
    99782:    "unified ذهب",
    99792:    "btc_evolver",
    0:        "يدوي (أنت)",
    2447:     "إكسبيرتك LOCK30X",
    20250418: "إكسبيرت خارجي",
    20250421: "إكسبيرت خارجي",
    20250422: "إكسبيرت خارجي",
    12345:    "إكسبيرت خارجي",
}

# عتبات التدرّج (من المواصفات)
PROVEN_MIN_N = 15
PROVEN_T     = 2.0    # (sumR/n)*sqrt(n) > 2
BANNED_MIN_N = 4
BANNED_EXPR  = -0.05  # sumR/n < -0.05
EXPLORE_MIN_CONF = 0.68

console = Console()


# ============================================================================
# أدوات مساعدة (كلّها قراءة فقط، فشلها لا يُسقط شيئاً)
# ============================================================================
def _load_json(path):
    """قراءة JSON بأمان (يدعم BOM)؛ يُرجع None عند الفشل."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def _age_str(ts=None, iso=None):
    """عمر ملف بصيغة قصيرة + لون حسب النضارة."""
    try:
        if ts is None and iso:
            ts = datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        if ts is None:
            return "—", "dim"
        age = time.time() - float(ts)
        if age < 0:
            age = 0
        if age < 90:
            txt, col = f"{age:.0f}s", "green"
        elif age < 600:
            txt, col = f"{age/60:.0f}m", "yellow"
        elif age < 7200:
            txt, col = f"{age/60:.0f}m", "yellow"
        else:
            txt, col = f"{age/3600:.1f}h", "red"
        return txt, col
    except Exception:
        return "—", "dim"


def _grade(n, sumR):
    """تدرّج الفرقة من (n, sumR). يُرجع (label, color, expR)."""
    n = n or 0
    expR = (sumR / n) if n else 0.0
    try:
        if n >= PROVEN_MIN_N and expR * math.sqrt(n) > PROVEN_T:
            return "🏅PROVEN", "bold green", expR
        if n >= BANNED_MIN_N and expR < BANNED_EXPR:
            return "🚫BANNED", "bold red", expR
    except Exception:
        pass
    return "⚪EXPLORE", "yellow", expR


def _money(v, plus=True):
    """تنسيق نقدي ملوّن (نص rich markup)."""
    try:
        v = float(v)
    except Exception:
        return "—"
    col = "green" if v > 0 else ("red" if v < 0 else "white")
    sign = "+" if (v > 0 and plus) else ""
    return f"[{col}]{sign}{v:,.2f}[/{col}]"


def _safe_panel(builder, title, border="cyan"):
    """يبني لوحة؛ إن فشل البنّاء يعرض لوحة خطأ بدل إسقاط الشاشة."""
    try:
        return builder()
    except Exception as e:
        return Panel(
            Text(f"⚠ لوحة معطوبة: {e}", style="red"),
            title=title, border_style="red",
        )


# ============================================================================
# 1) رأس الحساب
# ============================================================================
def panel_account():
    ap = _load_json(P_AUTOPILOT) or {}
    pnl = _load_json(P_PNL) or {}
    dd = _load_json(P_DD) or {}
    mg = _load_json(P_MARGIN) or {}

    equity = ap.get("equity", pnl.get("equity"))
    balance = ap.get("balance", pnl.get("balance"))
    floating = ap.get("float", pnl.get("floating"))
    margin_level = ap.get("margin_level", mg.get("margin_level"))
    open_pos = ap.get("open_positions")
    ddpct = dd.get("drawdown_pct")
    naked = ap.get("naked_manual")

    rt = ap.get("realized_today", {}) or {}
    bots_today = rt.get("bots")
    manual_today = rt.get("manual_magic0")
    # ربح اليوم الكلّي المحقّق
    today_net = pnl.get("today_net")
    user_ea_today = (ap.get("realized_7d") or {})  # placeholder; today EA غير منفصل

    safety = (ap.get("safety_flag") or "OK").upper()
    safety_reasons = ap.get("safety_reasons") or []
    flag_col = {"OK": "bold green", "WARN": "bold yellow", "CRITICAL": "bold red"}.get(safety, "white")

    age_txt, age_col = _age_str(ts=ap.get("ts"), iso=ap.get("iso"))

    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(justify="left", ratio=1)
    t.add_column(justify="left", ratio=1)
    t.add_column(justify="left", ratio=1)

    def cell(label, value):
        return Text.from_markup(f"[dim]{label}[/dim]\n{value}")

    eq_s = f"[bold cyan]${equity:,.2f}[/bold cyan]" if equity is not None else "—"
    bal_s = f"${balance:,.2f}" if balance is not None else "—"
    fl_s = _money(floating)
    ml_s = "—"
    if margin_level is not None:
        mcol = "green" if margin_level >= 200 else "red"
        ml_s = f"[{mcol}]{margin_level:,.0f}%[/{mcol}]"
    dd_s = "—"
    if ddpct is not None:
        dcol = "green" if ddpct < 10 else ("yellow" if ddpct < 15 else "red")
        dd_s = f"[{dcol}]{ddpct:.2f}%[/{dcol}]"

    t.add_row(
        cell("الحقوق (Equity)", eq_s),
        cell("الرصيد (Balance)", bal_s),
        cell("العائم (Float)", fl_s),
    )
    t.add_row(
        cell("السحب% (DD)", dd_s),
        cell("هامش% (ML)", ml_s),
        cell("مراكز مفتوحة", f"[bold]{open_pos}[/bold]" if open_pos is not None else "—"),
    )
    t.add_row(
        cell("اليوم — بوتاتنا", _money(bots_today)),
        cell("اليوم — يدوي", _money(manual_today)),
        cell("اليوم — صافٍ", _money(today_net)),
    )

    flag_line = Text.from_markup(
        f"حالة الأمان: [{flag_col}]{safety}[/{flag_col}]"
        + (f"  [dim]({'، '.join(safety_reasons)})[/dim]" if safety_reasons else "")
        + f"   ·   يدوي مكشوف: {naked if naked is not None else '—'}"
        + f"   ·   [{ age_col }]تحديث منذ {age_txt}[/{age_col}]"
    )

    body = Group(t, Text(""), flag_line)
    return Panel(body, title="💰 رأس الحساب", border_style=flag_col, padding=(0, 1))


# ============================================================================
# 2) ملخّص التعلّم الذاتي
# ============================================================================
def panel_learning():
    army = _load_json(P_ARMY) or {}
    stats = army.get("stats", {}) or {}

    proven = explore = banned = 0
    rows = []  # (sym, n, expR, label)
    for sym, v in stats.items():
        n = v.get("n", 0)
        sumR = v.get("sumR", 0.0)
        label, _col, expR = _grade(n, sumR)
        if label.endswith("PROVEN"):
            proven += 1
        elif label.endswith("BANNED"):
            banned += 1
        else:
            explore += 1
        rows.append((sym, n, expR, label))

    total = len(stats)
    # الحافّة المجمّعة عبر كل الخلايا (نفس منطق المصوّتين) — العيّنة الكبيرة الصادقة
    pooled_n = sum(int(v.get("n", 0)) for v in stats.values())
    pooled_sumR = sum(float(v.get("sumR", 0.0)) for v in stats.values())
    pooled_exp = (pooled_sumR / pooled_n) if pooled_n else 0.0
    pooled_t = (pooled_exp * math.sqrt(pooled_n)) if pooled_n else 0.0
    top = sorted(
        [r for r in rows if r[3].endswith("PROVEN")] or rows,
        key=lambda r: r[2], reverse=True,
    )[:4]

    # عمر السبورة (mtime للملف)
    try:
        mtime = os.path.getmtime(P_ARMY)
        age_txt, age_col = _age_str(ts=mtime)
        live_txt = f"[{age_col}]حيّة (منذ {age_txt})[/{age_col}]"
    except Exception:
        live_txt = "[red]غير معروف[/red]"

    head = Text.from_markup(
        f"🏅 [bold green]PROVEN {proven}[/bold green]   "
        f"⚪ [yellow]EXPLORE {explore}[/yellow]   "
        f"🚫 [red]BANNED {banned}[/red]   "
        f"·  إجمالي الأحكام: [bold]{total}[/bold]   ·  السبورة: {live_txt}"
    )

    tt = Table(box=None, expand=True, padding=(0, 1))
    tt.add_column("أعلى المُثبتين", style="green")
    tt.add_column("n", justify="right")
    tt.add_column("expR", justify="right")
    if top:
        for sym, n, expR, label in top:
            ecol = "green" if expR > 0 else "red"
            tt.add_row(sym, str(n), f"[{ecol}]{expR:+.3f}[/{ecol}]")
    else:
        tt.add_row("[dim]لا حافّة معنوية بعد[/dim]", "", "")

    note = Text.from_markup(
        "[dim]القاعدة: PROVEN لو n≥15 و expR·√n>2 · BANNED لو n≥4 و expR<-0.05[/dim]"
    )
    _vcol = "green" if pooled_t > 2 else ("red" if pooled_t < -2 else "yellow")
    _verdict = ("حافّة معنوية ✅" if pooled_t > 2 else
                ("خاسر معنوي 🚫" if pooled_t < -2 else "لا حافّة معنوية بعد"))
    pooled_line = Text.from_markup(
        f"[bold]الحافّة المجمّعة[/bold] (كل الإشارات): n=[bold]{pooled_n}[/bold] · "
        f"expR=[{_vcol}]{pooled_exp:+.4f}R[/{_vcol}] · t≈[{_vcol}]{pooled_t:+.2f}[/{_vcol}] → "
        f"[{_vcol}]{_verdict}[/{_vcol}]   [dim](الحاجز للحقيقي: t>2 + إثبات ورقي)[/dim]"
    )
    body = Group(head, Text(""), tt, note, Text(""), pooled_line)
    return Panel(body, title="🧠 ملخّص التعلّم الذاتي", border_style="magenta", padding=(0, 1))


# ============================================================================
# 3) جدول الفِرق  (PROVEN أولاً)
# ============================================================================
def panel_teams():
    army = _load_json(P_ARMY) or {}
    stats = army.get("stats", {}) or {}
    pending = army.get("pending", []) or {}

    # خريطة أحدث إشارة/سعر من pending (لا نضرب MT5 ولا chart_read)
    sig = {}
    for p in pending:
        s = p.get("sym")
        if not s:
            continue
        sig[s] = {
            "dir": p.get("dir"),
            "entry": p.get("entry"),
            "risk": p.get("risk"),
        }

    rows = []
    for sym, v in stats.items():
        n = v.get("n", 0)
        wins = v.get("wins", 0)
        sumR = v.get("sumR", 0.0)
        label, col, expR = _grade(n, sumR)
        order = {"🏅PROVEN": 0, "⚪EXPLORE": 1, "🚫BANNED": 2}.get(label, 1)
        sg = sig.get(sym, {})
        d = sg.get("dir")
        side = "BUY" if d == 1 else ("SELL" if d == -1 else "—")
        side_col = "green" if d == 1 else ("red" if d == -1 else "dim")
        price = sg.get("entry")
        wr = (wins / n * 100) if n else 0.0
        rows.append((order, label, col, sym, side, side_col, price, wr, expR, n))

    rows.sort(key=lambda r: (r[0], -r[8]))

    tt = Table(box=None, expand=True, padding=(0, 1))
    tt.add_column("الفرقة", no_wrap=True)
    tt.add_column("السعر", justify="right")
    tt.add_column("إشارة", justify="center")
    tt.add_column("التدرّج", justify="center")
    tt.add_column("expR", justify="right")
    tt.add_column("WR%", justify="right")
    tt.add_column("n", justify="right")

    shown = 0
    for order, label, col, sym, side, side_col, price, wr, expR, n in rows:
        if shown >= 18:
            break
        price_s = f"{price:,.4f}".rstrip("0").rstrip(".") if isinstance(price, (int, float)) else "—"
        ecol = "green" if expR > 0 else ("red" if expR < 0 else "white")
        tt.add_row(
            sym,
            price_s,
            f"[{side_col}]{side}[/{side_col}]",
            f"[{col}]{label}[/{col}]",
            f"[{ecol}]{expR:+.3f}[/{ecol}]",
            f"{wr:.0f}",
            str(n),
        )
        shown += 1

    if not rows:
        tt.add_row("[dim]لا فِرق بعد[/dim]", "", "", "", "", "", "")

    cap = Text.from_markup(
        f"[dim]يُعرض {shown}/{len(rows)} فرقة · السعر/الإشارة من army pending (خفيف — بلا chart_read)[/dim]"
    )
    return Panel(Group(tt, cap), title="⚔ جدول الفِرق", border_style="cyan", padding=(0, 1))


# ============================================================================
# 4) لوحة الحُرّاس
# ============================================================================
def panel_guards():
    eg = _load_json(P_EDGEGUARD) or {}
    mg = _load_json(P_MARGIN) or {}
    dd = _load_json(P_DD) or {}
    rec = _load_json(P_RECOVERY) or {}

    ml = mg.get("margin_level")
    ddpct = dd.get("drawdown_pct")
    blocks = dd.get("blocks_new_entries")
    disc = eg.get("discipline_score")

    tt = Table(box=None, expand=True, padding=(0, 0))
    tt.add_column("الحارس", no_wrap=True)
    tt.add_column("الحالة")

    def stat(active, detail):
        col = "green" if active else "yellow"
        mark = "✓" if active else "•"
        return f"[{col}]{mark} {detail}[/{col}]"

    margin_ok = (ml is None) or (ml >= 120)
    kill_on = os.path.exists(P_KILL)

    def off(detail):   # فرملة أُزيلت عمداً (وضع عدواني)
        return f"[dim]✗ {detail}[/dim]"

    # الوضع العدواني الذي طلبه المستخدم: لا حد يومي / لا سقف صفقة — master_floor هو الفرملة الوحيدة
    tt.add_row("الحد اليومي", off("مُلغى (طلب المستخدم)"))
    tt.add_row("سقف الصفقة", "[yellow]• 12% (كان 2%)[/yellow]")
    tt.add_row("حارس المحفظة", "[yellow]• 90% (كان 15%)[/yellow]")
    tt.add_row(
        "قاطع الهامش <120%",
        stat(margin_ok, f"ML {ml:,.0f}% — {'OK' if margin_ok else 'تحت العتبة!'}" if ml is not None else "—"),
    )
    tt.add_row("🛑 master_floor (−50%)", stat(True, "الفرملة الوحيدة — تصفية+kill عند −50% من القمة"))
    tt.add_row("مفتاح الإيقاف", (f"[red]✓ مفعّل (kill_switch.txt)[/red]" if kill_on
                                  else "[green]• خامل — يحترمه الخمسة[/green]"))
    tt.add_row("الذهب/المعادن", stat(True, "12% · تكديس 3 · مع-الاتجاه فقط"))
    tt.add_row("حارس الذيل HTF", stat(True, "نشط — منع عكس اتجاه HTF (المتقلّبات)"))

    disc_line = ""
    if disc is not None:
        dcol = "green" if disc >= 70 else ("yellow" if disc >= 40 else "red")
        viol = eg.get("active_violations") or []
        disc_line = f"\n[dim]انضباطك:[/dim] [{dcol}]{disc}/100[/{dcol}]  [dim]· مخالفات نشطة: {len(viol)}[/dim]"

    rec_line = ""
    if rec.get("active"):
        rec_line = f"\n[red]⚠ وضع الاسترداد فعّال[/red] (lot_cap {rec.get('lot_cap')})"

    return Panel(
        Group(tt, Text.from_markup(disc_line + rec_line) if (disc_line or rec_line) else tt),
        title="🛡 لوحة الحُرّاس", border_style="green", padding=(0, 1),
    )


# ============================================================================
# 5) لوحة الحوافّ المُثبتة OOS
# ============================================================================
def panel_edges():
    tt = Table(box=None, expand=True, padding=(0, 1))
    tt.add_column("الرمز", no_wrap=True)
    tt.add_column("TF", justify="center")
    tt.add_column("Setup")
    tt.add_column("OOS PF", justify="right")
    tt.add_column("expR", justify="right")
    tt.add_column("n", justify="right")

    # الثلاثة المُثبتة من UNIVERSE_SCAN_REPORT (3/26 نجت من 3 بوّابات)
    edges = [
        ("XAUUSDm", "H1", "BREAKOUT_long", 2.21, 0.499, 515),
        ("XAUEURm", "H1", "BREAKOUT_long", 1.91, 0.439, 56),
        ("USOILm",  "M15", "BREAKOUT_long", 1.44, 0.227, 590),
    ]
    have_report = os.path.exists(P_UNIVERSE)
    for sym, tf, setup, pf, exp, n in edges:
        tt.add_row(sym, tf, setup, f"[green]{pf:.2f}[/green]", f"[green]+{exp:.3f}[/green]", str(n))

    src = "[green]✓ التقرير موجود[/green]" if have_report else "[yellow]التقرير غير موجود[/yellow]"
    db = "[green]✓ proven_edges.db[/green]" if os.path.exists(os.path.join(DATA, "proven_edges.db")) else "[dim]لا db[/dim]"

    honest = Text.from_markup(
        "[yellow]صدق:[/yellow] 3 من 26 مرشّحاً فقط نجت من البوّابات الثلاث (≈88% إيجابيات كاذبة).\n"
        "[dim]الحالة: ورقي / [bold]لم تُوصَّل[/bold] كمنفّذ مباشر — تحذير: خاسرة في النظام الحالي إن دُمجت بلا حذر.[/dim]\n"
        f"[dim]المصدر: {src} · {db}[/dim]"
    )
    return Panel(Group(tt, honest), title="📈 الحوافّ المُثبتة OOS", border_style="blue", padding=(0, 1))


# ============================================================================
# 6) سلسلة القرار (if-then-else)
# ============================================================================
def panel_decision():
    lines = [
        "[bold cyan]إشارة[/bold cyan] (dir/confluence من chart_read/army)",
        "  └─ [yellow]if[/yellow] الثقة ≥ عتبة (EXPLORE_MIN_CONF = 0.68)؟",
        "       ├─ [red]else → تخطّي[/red] (ثقة ضعيفة)",
        "       └─ [yellow]if[/yellow] اتجاه HTF موافق؟ (حارس الذيل)",
        "            ├─ [red]else → تخطّي[/red] (عكس اتجاه المتقلّبات ممنوع)",
        "            └─ [yellow]switch[/yellow] تدرّج الفرقة:",
        "                 ├─ 🚫 BANNED  → [red]تخطّي[/red]",
        "                 ├─ ⚪ EXPLORE → سماح بحجم استكشافي صغير",
        "                 └─ 🏅 PROVEN  → سماح بحجم كامل",
        "                      └─ [yellow]if[/yellow] سقف 2%/صفقة و محفظة<15% و هامش>200%؟",
        "                           ├─ [red]else → تخطّي/تقليص[/red]",
        "                           └─ [green]→ تنفيذ (ضمن الحُرّاس)[/green]",
    ]
    return Panel(
        Text.from_markup("\n".join(lines)),
        title="🔀 سلسلة القرار (if-then-else)", border_style="yellow", padding=(0, 1),
    )


# ============================================================================
# 7) الأسطول
# ============================================================================
def panel_fleet():
    wd = _load_json(P_WATCHDOG) or {}
    ap = _load_json(P_AUTOPILOT) or {}
    pnl = _load_json(P_PNL) or {}

    n_alive = wd.get("n_alive", (ap.get("engines") or {}).get("alive"))
    n_total = wd.get("n_total", (ap.get("engines") or {}).get("total"))
    restarts = wd.get("restarts", {}) or {}
    age_txt, age_col = _age_str(ts=wd.get("ts"), iso=wd.get("iso"))

    alive_col = "green" if (n_alive is not None and n_total is not None and n_alive >= n_total) else "yellow"
    head = Text.from_markup(
        f"محرّكات حيّة: [{alive_col}]{n_alive}/{n_total}[/{alive_col}]   "
        f"·  [{age_col}]تحديث منذ {age_txt}[/{age_col}]"
    )

    # btc_live + يدوي عارٍ
    naked = ap.get("naked_manual")
    btc = "btc_live (99792): "
    # هل btc_evolver في watchdog؟ (مطفأ غالباً)
    alive_map = wd.get("alive", {}) or {}
    btc_on = any("btc" in k.lower() for k in alive_map)
    btc += "[yellow]مطفأ[/yellow]" if not btc_on else "[green]حيّ[/green]"
    manual_line = f"يدوي عارٍ: [{'red' if naked else 'green'}]{naked if naked is not None else '—'}[/{'red' if naked else 'green'}]"

    # أكثر العمليات إعادة تشغيل
    top_restarts = sorted(restarts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    rt = Table(box=None, expand=True, padding=(0, 1))
    rt.add_column("إعادة تشغيل (أعلى)", style="dim")
    rt.add_column("×", justify="right")
    if top_restarts:
        for name, cnt in top_restarts:
            ccol = "red" if cnt >= 5 else ("yellow" if cnt >= 2 else "dim")
            rt.add_row(name, f"[{ccol}]{cnt}[/{ccol}]")
    else:
        rt.add_row("[green]لا إعادات تشغيل[/green]", "")

    verdict = pnl.get("verdict")
    vline = f"[dim]حُكم السبورة:[/dim] {verdict}" if verdict else ""

    body = Group(head, Text.from_markup(f"{btc}   ·   {manual_line}"),
                 Text(""), rt,
                 Text.from_markup(vline) if vline else Text(""))
    return Panel(body, title="🚀 الأسطول", border_style="cyan", padding=(0, 1))


# ============================================================================
# 8) حاجز الكارثة master_floor (الفرملة الوحيدة في الوضع العدواني)
# ============================================================================
def panel_floor():
    fl = _load_json(P_FLOOR) or {}
    ap = _load_json(P_AUTOPILOT) or {}
    base = _load_json(P_BASELINE) or {}

    equity = ap.get("equity", (_load_json(P_PNL) or {}).get("equity"))
    peak = fl.get("peak")
    floor = fl.get("floor")
    if floor is None and peak is not None:
        floor = MASTER_FLOOR_FRAC * peak
    kill_on = os.path.exists(P_KILL)

    # نضارة عملية الحاجز (mtime لملف الحالة = نبض master_floor كل 4ث)
    try:
        age_txt, age_col = _age_str(ts=os.path.getmtime(P_FLOOR))
        alive = (time.time() - os.path.getmtime(P_FLOOR)) < 60
    except Exception:
        age_txt, age_col, alive = "—", "red", False

    lines = []
    if peak is not None and floor is not None and equity is not None:
        dist = equity - floor
        dist_pct = 100.0 * dist / equity if equity else 0
        room = 100.0 * (equity - floor) / (peak - floor) if (peak - floor) > 0 else 0
        breached = equity <= floor
        col = "red" if breached else ("yellow" if dist_pct < 10 else "green")
        bar_n = max(0, min(20, int(room / 5)))
        bar = "█" * bar_n + "░" * (20 - bar_n)
        lines.append(f"الحقوق [bold]${equity:,.2f}[/bold]   القمة [cyan]${peak:,.2f}[/cyan]   "
                     f"الأرضية [bold red]${floor:,.2f}[/bold red]")
        lines.append(f"المسافة للأرضية: [{col}]${dist:,.2f} ({dist_pct:+.1f}%)[/{col}]   "
                     f"[dim]({room:.0f}% من المدى فوق الأرضية)[/dim]")
        lines.append(f"[{col}]{bar}[/{col}]")
        if breached:
            lines.append("[bold red]*** اخترق الأرضية — صفّى وأوقف ***[/bold red]")
    else:
        lines.append("[dim]بانتظار حالة master_floor (master_floor_state.json)...[/dim]")

    status = (f"[{age_col}]حيّ (نبض {age_txt})[/{age_col}]" if alive
              else f"[red]⚠ لا نبض ({age_txt}) — تحقّق من العملية[/red]")
    kill_s = "[red]مفعّل[/red]" if kill_on else "[green]خامل[/green]"
    start_s = f"${base.get('start_balance'):,.0f}" if base.get("start_balance") else "—"
    lines.append(f"[dim]master_floor: {status} · kill_switch: {kill_s} · "
                 f"بداية التجربة {start_s} · تتبّع 50% من القمة · يحمي اليدوي/الخبراء[/dim]")

    border = "red" if kill_on else "bright_red"
    return Panel(Text.from_markup("\n".join(lines)),
                 title="🛑 حاجز الكارثة (master_floor — الفرملة الوحيدة)",
                 border_style=border, padding=(0, 1))


# ============================================================================
# تجميع التخطيط
# ============================================================================
def build_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="account", size=9),
        Layout(name="floor", size=7),
        Layout(name="mid"),
        Layout(name="bottom", size=16),
    )

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    # حالة ruflo: مهارات skills.sh المثبّتة (المسار الذي عمل فعلاً — لا MCP/إعادة تشغيل)
    try:
        _sk = os.path.join(os.path.expanduser("~"), ".claude", "skills")
        _ruflo_skills = [s for s in ("agent-workflow", "workflow-automation", "security-audit",
                                     "github-workflow-automation", "memory-management", "github-automation")
                         if os.path.isdir(os.path.join(_sk, s))]
        _n_ruflo = len(_ruflo_skills)
    except Exception:
        _n_ruflo = 0
    ruflo_s = (f"[green]ruflo: {_n_ruflo} مهارة موصولة[/green]" if _n_ruflo
               else "[dim]ruflo: غير مثبّت (npx skills add ruvnet/ruflo@<skill>)[/dim]")
    mode_s = "[bold red]عدواني (لا حدود — master_floor فقط)[/bold red]" if AGGRESSIVE else "[green]محافظ[/green]"
    layout["header"].update(
        Panel(
            Align.center(Text.from_markup(
                f"[bold cyan]FRIDAY — مركز القيادة الموحّد[/bold cyan]   "
                f"[dim]قراءة فقط · {ts}[/dim]   ·   الوضع: {mode_s}   ·   {ruflo_s}"
            )),
            border_style="bright_blue",
        )
    )

    layout["account"].update(_safe_panel(panel_account, "💰 رأس الحساب"))
    layout["floor"].update(_safe_panel(panel_floor, "🛑 حاجز الكارثة"))

    layout["mid"].split_row(
        Layout(name="mid_left"),
        Layout(name="mid_right"),
    )
    layout["mid_left"].split_column(
        Layout(_safe_panel(panel_learning, "🧠 التعلّم الذاتي"), name="learn", size=11),
        Layout(_safe_panel(panel_teams, "⚔ الفِرق"), name="teams"),
    )
    layout["mid_right"].split_column(
        Layout(_safe_panel(panel_guards, "🛡 الحُرّاس"), name="guards"),
        Layout(_safe_panel(panel_edges, "📈 الحوافّ"), name="edges", size=11),
    )

    layout["bottom"].split_row(
        Layout(_safe_panel(panel_decision, "🔀 القرار"), name="decision"),
        Layout(_safe_panel(panel_fleet, "🚀 الأسطول"), name="fleet"),
    )
    return layout


# ============================================================================
# main
# ============================================================================
def main():
    ap = argparse.ArgumentParser(description="FRIDAY Command Center (READ-ONLY)")
    ap.add_argument("--once", action="store_true", help="دورة رسم واحدة ثم خروج")
    ap.add_argument("--interval", type=float, default=1.5, help="فترة التحديث بالثواني")
    args = ap.parse_args()

    if args.once:
        console.print(build_layout())
        return

    refresh = max(0.5, args.interval)
    try:
        with Live(build_layout(), console=console, screen=True,
                  refresh_per_second=max(1, int(1 / refresh))) as live:
            while True:
                time.sleep(refresh)
                live.update(build_layout())
    except KeyboardInterrupt:
        console.print("[dim]تم الإيقاف (قراءة فقط — لم يُمسّ شيء).[/dim]")


if __name__ == "__main__":
    main()
