# -*- coding: utf-8 -*-
"""
evolution_monitor.py — FRIDAY Live EVOLUTION Monitor  (READ-ONLY)
=================================================================
شاشة حيّة تُظهر **التطوّر عبر الزمن** (لا لقطة حالة): منحنى الأرباح، نمو الجينات/الأجيال،
تقدّم التعلّم الذاتي نحو المعنوية، وتغذية أحداث التطوّر/الوكلاء الحيّة.

تكمّل command_center (الذي يعرض الحالة الآنية). هذا يعرض **المسار/التغيّر**.

تشغيل:
    python evolution_monitor.py            # حلقة حيّة (refresh ~2s)
    python evolution_monitor.py --once     # دورة واحدة
    evolution_monitor.bat

كلّه قراءة فقط — لا order_send، لا تعديل. كل لوحة داخل try/except.
المصادر: data/r_native/{pnl_history,army_scoreboard,evolution_log.jsonl,evolution_state,
         hall_of_fame/index,gene_skills,gene_hybrids, master_floor_state, agents/insights.jsonl}
"""
from __future__ import annotations
import argparse, json, math, os, time
from datetime import datetime, timezone

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align

ROOT = os.path.dirname(os.path.abspath(__file__))
RN = os.path.join(ROOT, "data", "r_native")
P_PNLHIST = os.path.join(RN, "pnl_history.json")
P_ARMY    = os.path.join(RN, "army_scoreboard.json")
P_EVOLOG  = os.path.join(RN, "evolution_log.jsonl")
P_EVOSTATE= os.path.join(RN, "evolution_state.json")
P_HOF     = os.path.join(RN, "hall_of_fame", "index.json")
P_GSKILLS = os.path.join(RN, "gene_skills.json")
P_GHYB    = os.path.join(RN, "gene_hybrids.json")
P_FLOOR   = os.path.join(RN, "master_floor_state.json")
P_INSIGHTS= os.path.join(RN, "agents", "insights.jsonl")

PROVEN_MIN_N = 15
PROVEN_T = 2.0
BANNED_MIN_N = 4
BANNED_EXPR = -0.05
SPARK = "▁▂▃▄▅▆▇█"
console = Console()


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def _tail_jsonl(path, n):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()[-n:]
        out = []
        for ln in lines:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
        return out
    except Exception:
        return []


def _spark(vals):
    """سطر شرارة من قيم."""
    vals = [v for v in vals if isinstance(v, (int, float))]
    if len(vals) < 2:
        return "—"
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    return "".join(SPARK[min(7, int((v - lo) / rng * 7))] for v in vals)


def _safe_panel(builder, title, border="cyan"):
    try:
        return builder()
    except Exception as e:
        return Panel(Text(f"⚠ {e}", style="red"), title=title, border_style="red")


# ---------------------------------------------------------------------------
# 1) منحنى الأرباح (المسار)
# ---------------------------------------------------------------------------
def panel_equity():
    d = _load_json(P_PNLHIST) or {}
    curve = d.get("curve") or []
    fl = _load_json(P_FLOOR) or {}
    peak, floor = fl.get("peak"), fl.get("floor")

    pts = [c for c in curve if isinstance(c, (list, tuple)) and len(c) == 2]
    recent = pts[-60:]
    vals = [p[1] for p in recent]
    spark = _spark(vals)
    cur = vals[-1] if vals else None
    lo = min(vals) if vals else None
    hi = max(vals) if vals else None

    lines = [f"[bold]منحنى P&L[/bold] (آخر {len(recent)} نقطة):"]
    lines.append(f"[cyan]{spark}[/cyan]")
    if cur is not None:
        lines.append(f"الآن [bold]{cur:,.1f}[/bold]   مدى [{lo:,.0f} → {hi:,.0f}]   نقاط محفوظة {len(pts)}")
    if peak is not None and floor is not None:
        lines.append(f"[dim]master_floor:[/dim] قمة [cyan]${peak:,.2f}[/cyan] · أرضية [red]${floor:,.2f}[/red] "
                     f"(تتبّع 50% — يُقفل الربح)")
    return Panel(Text.from_markup("\n".join(lines)), title="📈 مسار الأرباح/الخسائر",
                 border_style="blue", padding=(0, 1))


# ---------------------------------------------------------------------------
# 2) تطوّر الجينات (قاعة الشرف)
# ---------------------------------------------------------------------------
def panel_genes():
    hof = _load_json(P_HOF) or {}
    genomes = list(hof.values()) if isinstance(hof, dict) else (hof if isinstance(hof, list) else [])
    n = len(genomes)
    gens = [g.get("generation", 0) for g in genomes if isinstance(g, dict)]
    max_gen = max(gens) if gens else 0
    # archetype mix
    from collections import Counter
    arch = Counter(g.get("archetype", "?") for g in genomes if isinstance(g, dict))
    # top by score
    scored = sorted([g for g in genomes if isinstance(g, dict)],
                    key=lambda g: g.get("score", 0) or 0, reverse=True)[:5]
    # recent births
    def _born(g):
        try:
            return datetime.fromisoformat(str(g.get("born_at", "")).replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0
    recent = sorted([g for g in genomes if isinstance(g, dict)], key=_born, reverse=True)[:3]

    head = Text.from_markup(
        f"🧬 جينومات: [bold]{n}[/bold]   ·  أقصى جيل: [bold]{max_gen}[/bold]   ·  "
        f"أنماط: " + " ".join(f"{k}={v}" for k, v in arch.most_common(4))
    )
    tt = Table(box=None, expand=True, padding=(0, 1))
    tt.add_column("أفضل الجينات", style="green", no_wrap=True)
    tt.add_column("رمز", justify="center")
    tt.add_column("جيل", justify="right")
    tt.add_column("score", justify="right")
    tt.add_column("صفقات", justify="right")
    for g in scored:
        st = g.get("stats", {}) or {}
        nick = (g.get("nickname") or g.get("id", "?"))[:22]
        sc = g.get("score", 0) or 0
        scol = "green" if sc > 0 else "red"
        tt.add_row(nick, g.get("symbol", "?"), str(g.get("generation", "?")),
                   f"[{scol}]{sc:.1f}[/{scol}]", str(st.get("trades", "?")))
    births = " · ".join(f"{(g.get('nickname') or g.get('id',''))[:16]}(ج{g.get('generation','?')})" for g in recent)
    foot = Text.from_markup(f"[dim]أحدث المواليد: {births}[/dim]")
    return Panel(Group(head, Text(""), tt, foot), title="🧬 تطوّر الجينات (قاعة الشرف)",
                 border_style="magenta", padding=(0, 1))


# ---------------------------------------------------------------------------
# 3) تقدّم التعلّم الذاتي نحو المعنوية
# ---------------------------------------------------------------------------
def panel_learning():
    army = _load_json(P_ARMY) or {}
    stats = army.get("stats", {}) or {}
    proven = explore = banned = 0
    rows = []
    pooled_n = pooled_sumR = 0.0
    for sym, v in stats.items():
        nn = v.get("n", 0); sumR = v.get("sumR", 0.0)
        pooled_n += nn; pooled_sumR += sumR
        expR = (sumR / nn) if nn else 0.0
        if nn >= PROVEN_MIN_N and expR * math.sqrt(nn) > PROVEN_T:
            proven += 1; lab = "🏅"
        elif nn >= BANNED_MIN_N and expR < BANNED_EXPR:
            banned += 1; lab = "🚫"
        else:
            explore += 1; lab = "⚪"
        rows.append((sym, nn, expR, lab))
    pe = (pooled_sumR / pooled_n) if pooled_n else 0.0
    pt = pe * math.sqrt(pooled_n) if pooled_n else 0.0
    vcol = "green" if pt > 2 else ("red" if pt < -2 else "yellow")
    verdict = ("حافّة معنوية ✅" if pt > 2 else ("خاسر معنوي 🚫" if pt < -2 else "لا حافّة بعد"))

    head = Text.from_markup(
        f"🏅[green]{proven}[/green]  ⚪[yellow]{explore}[/yellow]  🚫[red]{banned}[/red]   ·  "
        f"أحكام: [bold]{int(pooled_n)}[/bold]"
    )
    pooled = Text.from_markup(
        f"الحافّة المجمّعة: n=[bold]{int(pooled_n)}[/bold] · expR=[{vcol}]{pe:+.4f}R[/{vcol}] · "
        f"t≈[{vcol}]{pt:+.2f}[/{vcol}] → [{vcol}]{verdict}[/{vcol}]"
    )
    top = sorted(rows, key=lambda r: -r[2])[:5]
    tt = Table(box=None, expand=True, padding=(0, 1))
    tt.add_column("أعلى الفرق", no_wrap=True)
    tt.add_column("n", justify="right")
    tt.add_column("expR", justify="right")
    for sym, nn, expR, lab in top:
        ecol = "green" if expR > 0 else "red"
        tt.add_row(f"{lab} {sym}", str(nn), f"[{ecol}]{expR:+.3f}[/{ecol}]")
    foot = Text.from_markup("[dim]معنوي للحقيقي: t>2 + إثبات ورقي · الهدف n≥100/فرقة[/dim]")
    return Panel(Group(head, pooled, Text(""), tt, foot),
                 title="🧠 تقدّم التعلّم الذاتي", border_style="green", padding=(0, 1))


# ---------------------------------------------------------------------------
# 4) تغذية أحداث التطوّر + الوكلاء (الحيّة)
# ---------------------------------------------------------------------------
def _age(ts):
    try:
        a = time.time() - float(ts)
        if a < 90: return f"{a:.0f}s"
        if a < 5400: return f"{a/60:.0f}m"
        return f"{a/3600:.1f}h"
    except Exception:
        return "—"


def panel_feed():
    evo = _tail_jsonl(P_EVOLOG, 5)
    ins = _tail_jsonl(P_INSIGHTS, 6)

    lines = ["[bold]أحداث التطوّر (المدير):[/bold]"]
    for e in evo[-4:]:
        ts = e.get("ts")
        kind = e.get("kind", "?")
        msg = (e.get("msg", "") or "")[:60]
        lines.append(f"  [dim]{_age(ts)}[/dim] [cyan]{kind}[/cyan] {msg}")
    lines.append("")
    lines.append("[bold]تغذية الوكلاء (insights):[/bold]")
    for it in ins[-6:]:
        ts = it.get("ts")
        try:
            tsv = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        except Exception:
            tsv = None
        ag = (it.get("agent", "?") or "?")[:14]
        lvl = it.get("level", "")
        lcol = {"ACT": "yellow", "WARN": "red", "INFO": "dim"}.get(lvl, "white")
        msg = (it.get("message", "") or "")[:54]
        lines.append(f"  [dim]{_age(tsv) if tsv else '—'}[/dim] [{lcol}]{ag}[/{lcol}] {msg}")
    return Panel(Text.from_markup("\n".join(lines)), title="🌊 تغذية التطوّر الحيّة",
                 border_style="cyan", padding=(0, 1))


def build_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="equity", size=7),
        Layout(name="mid"),
        Layout(name="feed", size=14),
    )
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    es = _load_json(P_EVOSTATE) or {}
    evo_age = _age(es.get("ts"))
    layout["header"].update(Panel(
        Align.center(Text.from_markup(
            f"[bold magenta]FRIDAY — مراقب التطوّر الحيّ[/bold magenta]   "
            f"[dim]قراءة فقط · {ts} · مدير التطوّر منذ {evo_age}[/dim]")),
        border_style="magenta"))
    layout["equity"].update(_safe_panel(panel_equity, "📈 الأرباح"))
    layout["mid"].split_row(
        Layout(_safe_panel(panel_genes, "🧬 الجينات"), name="genes"),
        Layout(_safe_panel(panel_learning, "🧠 التعلّم"), name="learn"),
    )
    layout["feed"].update(_safe_panel(panel_feed, "🌊 التغذية"))
    return layout


def main():
    ap = argparse.ArgumentParser(description="FRIDAY Evolution Monitor (READ-ONLY)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()
    if args.once:
        console.print(build_layout()); return
    refresh = max(1.0, args.interval)
    try:
        with Live(build_layout(), console=console, screen=True,
                  refresh_per_second=max(1, int(1 / refresh))) as live:
            while True:
                time.sleep(refresh)
                live.update(build_layout())
    except KeyboardInterrupt:
        console.print("[dim]تم الإيقاف (قراءة فقط).[/dim]")


if __name__ == "__main__":
    main()
