"""
dashboard_pixel.py — GADER / قادر  Pixel Art Operations Center
مركز عمليات قادر — pixel art ريترو + شخصيات متحركة + متعدد الرموز
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING

try:
    from rich.console import Console, Group
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    _RICH_OK = True
except ImportError:
    _RICH_OK = False

if TYPE_CHECKING:
    from .orchestrator import FridayOrchestrator
    from ..mt5_gateway import MT5Gateway

# ── Pixel Art Utilities ───────────────────────────────────────────────────────

def _pbar(value: float, total: float = 1.0, width: int = 10,
          full: str = "█", empty: str = "░") -> str:
    ratio  = max(0.0, min(1.0, value / max(total, 1e-9)))
    filled = int(ratio * width)
    return full * filled + empty * (width - filled)

def _sparkline(values: list[float], width: int = 20) -> str:
    chars = " ▁▂▃▄▅▆▇█"
    if not values:
        return "─" * width
    mn, mx = min(values), max(values)
    rng = mx - mn or 1
    return "".join(chars[int((v - mn) / rng * 8)] for v in values[-width:])

# ── شخصيات pixel art متحركة — 4 إطارات لكل وكيل (3 أسطر × 6 حرف) ───────────
_SPRITES: dict[str, list[list[str]]] = {
    "ceo": [
        [" ╭o╮ ", " |>║ ", " / \\ "],   # يكتب
        [" ╭o╮ ", " ║|  ", " / \\ "],   # يفكّر
        ["\\╭o╮/", "  ║  ", " / \\ "],  # يحتفل
        [" ╭o╮ ", " |<║ ", " / \\ "],   # يراجع
    ],
    "risk": [
        [" ╭o╮ ", " |>= ", " / \\ "],
        [" ╭!╮ ", " /|\\ ", " / \\ "],
        [" ╭o╮ ", " =|  ", " / \\ "],
        [" ╭!╮ ", "\\|/  ", " / \\ "],
    ],
    "ana": [
        [" ╭o╮ ", " |~~ ", " / \\ "],
        [" ╭@╮ ", " ║|  ", " / \\ "],
        [" ╭o╮ ", " ~~| ", " / \\ "],
        [" ╭o╮ ", " |>~ ", " / \\ "],
    ],
    "mon": [
        [" (o) ", " /|> ", " / \\ "],
        [" (·) ", " /|  ", " / \\ "],
        [" (!) ", " /|\\ ", " / \\ "],
        [" (o) ", "  |  ", " /|  "],
    ],
    "lrn": [
        [" ╭o╮ ", " ~|~ ", " / \\ "],
        [" ╭*╮ ", " /|\\ ", " / \\ "],
        [" ╭o╮ ", " |~> ", " / \\ "],
        [" ╭~╮ ", " /|  ", " / \\ "],
    ],
    "drw": [
        [" [O] ", " |>> ", " /|\\ "],
        [" [!] ", " /O\\ ", " /|\\ "],
        [" [O] ", " <<| ", " /|\\ "],
        [" [O] ", "  |  ", " /|\\ "],
    ],
    "wck": [
        [" ╭o╮ ", " |>< ", " / \\ "],
        [" ╭o╮ ", " <|  ", " / \\ "],
        [" ╭o╮ ", " |<< ", " / \\ "],
        [" ╭o╮ ", " ><| ", " / \\ "],
    ],
}

# ── أسماء ورموز الوكلاء ───────────────────────────────────────────────────────
_CEO = ("▣", "المدير",        "bold green")
_CRO = ("▲", "المخاطر CRO",  "bold red")
_ANA = ("◈", "المحلل",       "bold cyan")
_LIQ = ("◉", "السيولة",      "cyan")
_MON = ("◎", "المراقب",      "bold yellow")
_DRW = ("■", "حارس الخسائر", "bold red")
_LRN = ("◆", "التعلم",       "bold magenta")
_WCK = ("◇", "الذيول",       "cyan")

# ── Event Bus المشترك بين كل الرموز ──────────────────────────────────────────

class _EventBus:
    def __init__(self, maxlen: int = 120):
        self._q: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, sender: str, recipient: str, msg: str,
             level: str = "info", symbol: str = ""):
        with self._lock:
            self._q.appendleft({
                "time":      datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "sender":    sender,
                "recipient": recipient,
                "msg":       msg,
                "level":     level,
                "symbol":    symbol,
            })

    def recent(self, n: int = 20) -> list[dict]:
        with self._lock:
            return list(self._q)[:n]

event_bus = _EventBus()


# ── الداشبورد الرئيسي ────────────────────────────────────────────────────────

class GaderDashboard:
    """
    مركز عمليات قادر — pixel art ريترو + شخصيات متحركة
    يدعم رمزاً واحداً أو متعدد الرموز.

    التشغيل:
        python scripts/run_gader.py
    """

    REFRESH = 2.0

    def __init__(
        self,
        orchestrator:  "FridayOrchestrator | None"          = None,
        gateway:       "MT5Gateway | None"                   = None,
        symbol:        str                                   = "XAUUSDm",
        all_orchs:     "dict[str, FridayOrchestrator] | None" = None,
        ceo=None,
    ):
        if not _RICH_OK:
            raise ImportError("pip install rich")

        self.orch      = orchestrator
        self.gw        = gateway
        self.symbol    = symbol or (orchestrator.symbol if orchestrator else "?")
        self.all_orchs = all_orchs or ({symbol: orchestrator} if orchestrator else {})
        self.ceo       = ceo
        self.console   = Console()
        self._bus      = event_bus
        self._running  = False
        self._frame    = 0
        self._pnl_history: deque[float] = deque(maxlen=40)

        # ربط event_cb لكل orchestrator
        for sym, orch in self.all_orchs.items():
            if orch is None:
                continue
            _orig_cb = getattr(orch, "event_cb", None)
            def _patched(evt, data, _sym=sym, _orig=_orig_cb):
                self._translate_event(evt, data, _sym)
                if callable(_orig):
                    _orig(evt, data)
            orch.event_cb = _patched

    # ── API ──────────────────────────────────────────────────────────────────

    def run(self, block: bool = True):
        if block:
            self._loop()
        else:
            threading.Thread(target=self._loop, daemon=True, name="gader-dash").start()

    def push(self, sender: str, recipient: str, msg: str,
             level: str = "info", symbol: str = ""):
        self._bus.push(sender, recipient, msg, level, symbol)

    # ── شخصيات متحركة ────────────────────────────────────────────────────────

    def _sprite(self, name: str, color: str = "green", busy: bool = True) -> Text:
        frames = _SPRITES.get(name, _SPRITES["ceo"])
        fi     = (self._frame % len(frames)) if busy else 0
        lines  = frames[fi]
        t      = Text(justify="center")
        for i, line in enumerate(lines):
            if i > 0:
                t.append("\n")
            t.append(line, style=color)
        return t

    def _sprite_row(self, name: str, color: str, label: str, busy: bool = True) -> Text:
        sp = self._sprite(name, color, busy)
        sp.append(f"\n[dim]{label}[/dim]", style="")
        return sp

    # ── ترجمة أحداث الأوركيسترتور إلى رسائل بين الوكلاء ─────────────────────

    def _translate_event(self, evt: str, data: dict, symbol: str = ""):
        b = self._bus
        if evt == "trade_open":
            side = data.get("action", "?")
            sl   = data.get("sl", 0)
            tp   = data.get("tp", 0)
            rr   = data.get("rr", "?")
            tid  = data.get("trade_id", "")
            b.push("► الدخول", "★ المتداول",
                   f"[{symbol}] ► {side} SL={sl:.2f} TP={tp:.2f} R:R={rr} [{tid}]",
                   "trade", symbol)
            b.push("▲ CRO", "★ المتداول",
                   f"[{symbol}] ✓ Δ={abs(data.get('price',0)-sl):.3f}/{abs(tp-data.get('price',0)):.3f}",
                   "risk", symbol)

        elif evt == "trade_closed":
            won = data.get("won")
            pnl = float(data.get("pnl_points", 0))
            tid = data.get("trade_id", "")
            why = data.get("reason", "")
            if symbol == self.symbol or not symbol:
                self._pnl_history.append(pnl)
            icon = "▲ ربح" if won else "▼ خسارة"
            b.push("◎ المراقب", "◆ التعلم",
                   f"[{symbol}] {icon} {pnl:+.4f} [{why}] {tid}",
                   "trade" if won else "warn", symbol)
            b.push("◆ التعلم", "▣ المدير",
                   f"[{symbol}] {'▲ ربح' if won else '▼ خسارة'} — أحدّث العتبات",
                   "info", symbol)

        elif evt == "sl_update":
            reason = data.get("reason", "")
            sl_new = data.get("sl", 0)
            mult   = data.get("trail_mult")
            mult_s = f" [{mult:.2f}×ATR]" if mult else ""
            b.push("◎ المراقب", "★ المتداول",
                   f"[{symbol}] ⚙ SL→{sl_new:.5f} [{reason}]{mult_s}",
                   "info", symbol)

        elif "drawdown" in evt or "cooldown" in evt:
            b.push("■ الحارس", "▣ المدير",
                   f"[{symbol}] ■ توقف إجباري", "warn", symbol)

    # ── حلقة العرض ───────────────────────────────────────────────────────────

    def _loop(self):
        self._running = True
        with Live(
            self._render(),
            refresh_per_second=1 / self.REFRESH,
            console=self.console,
            screen=True,
        ) as live:
            try:
                while self._running:
                    self._frame += 1
                    live.update(self._render())
                    time.sleep(self.REFRESH)
            except KeyboardInterrupt:
                self._running = False

    # ── غرفة القيادة — كل الوكلاء في صف واحد ────────────────────────────────

    def _agents_command_center(self) -> Panel:
        """صف يُظهر جميع الوكلاء بشخصياتهم وحالتهم دفعة واحدة."""
        st  = self._orch_status()
        pos = self._all_open_positions()

        # ── تحديد حالة كل وكيل ──────────────────────────────────────────────
        smc_b    = int(st.get("smc_buy",  0))
        smc_s    = int(st.get("smc_sell", 0))
        ssl      = bool(st.get("ssl_active"))
        bsl      = bool(st.get("bsl_active"))
        bos_u    = bool(st.get("bos_up"))
        bos_d    = bool(st.get("bos_down"))
        prob     = float(st.get("prob", 0.5))
        n_open   = int(st.get("open_count", 0))
        last_act = str(st.get("action", "HOLD"))
        lrn      = st.get("learning", {})
        n_trades = int(lrn.get("trades", 0))
        wr       = float(lrn.get("win_rate", 0))
        conf_d   = st.get("confidence", {})
        streak   = int(conf_d.get("streak", 0))
        extra    = int(conf_d.get("extra_positions", 0))

        guard_d  = {}
        wick_bd  = 0
        wick_al  = 0
        if self.orch:
            try:    guard_d = self.orch.guard.status()
            except: pass
            if hasattr(self.orch, "wick"):
                wick_bd = getattr(self.orch.wick, "_blocked_total", 0)
                wick_al = getattr(self.orch.wick, "_allowed_total", 0)

        paused   = bool(guard_d.get("pause_bars_left", 0))
        cl       = int(guard_d.get("consec_losses", 0))

        # ── كل وكيل: sprite_key, color, status_text, metric, busy, alarm ───
        agents = [
            {   # 1 — المحلل الفني
                "name":   "المحلل",
                "sk":     "ana",
                "busy":   bool(bos_u or bos_d or smc_b or smc_s),
                "alarm":  False,
                "color":  "cyan",
                "stat":   f"SMC {smc_b}▲{smc_s}▼",
                "metric": f"AI={prob:.2f}",
            },
            {   # 2 — السيولة
                "name":   "السيولة",
                "sk":     "wck",   # استخدم sprite الذيول للسيولة
                "busy":   bool(ssl or bsl),
                "alarm":  False,
                "color":  "blue",
                "stat":   ("SSL" if ssl else "") + ("+" if ssl and bsl else "") + ("BSL" if bsl else "") or "هادئ",
                "metric": f"BOS {'↑' if bos_u else '─'}{'↓' if bos_d else '─'}",
            },
            {   # 3 — وكيل الدخول
                "name":   "الدخول",
                "sk":     "mon",
                "busy":   last_act != "HOLD",
                "alarm":  False,
                "color":  "green" if "BUY" in last_act else ("red" if "SELL" in last_act else "dim"),
                "stat":   last_act if last_act != "HOLD" else "ينتظر",
                "metric": f"p={prob:.2f}",
            },
            {   # 4 — مدير المخاطر
                "name":   "CRO",
                "sk":     "risk",
                "busy":   n_open > 0,
                "alarm":  cl >= 2,
                "color":  "red" if cl >= 2 else "yellow",
                "stat":   f"SL×{getattr(getattr(self.orch, 'risk', None), 'atr_sl_mult', 1.5):.1f}" if self.orch else "─",
                "metric": f"RR≥{getattr(getattr(self.orch, 'risk', None), 'min_rr', 1.2):.1f}" if self.orch else "─",
            },
            {   # 5 — المراقب
                "name":   "المراقب",
                "sk":     "mon",
                "busy":   n_open > 0,
                "alarm":  False,
                "color":  "yellow",
                "stat":   f"{n_open} مفتوحة" if n_open else "لا صفقات",
                "metric": f"pos={'▣'*n_open or '○'}",
            },
            {   # 6 — التعلم
                "name":   "التعلم",
                "sk":     "lrn",
                "busy":   n_trades > 0,
                "alarm":  wr < 0.35 and n_trades >= 8,
                "color":  "green" if wr > 0.55 else ("yellow" if wr > 0.40 else "red"),
                "stat":   f"WR={wr:.0%}" if n_trades else "لا بيانات",
                "metric": f"n={n_trades}",
            },
            {   # 7 — حارس الخسائر
                "name":   "الحارس",
                "sk":     "drw",
                "busy":   True,
                "alarm":  paused or cl >= 3,
                "color":  "red" if (paused or cl >= 2) else "green",
                "stat":   "PAUSED" if paused else "ACTIVE",
                "metric": f"loss={'■'*cl+'□'*max(0,3-cl)}",
            },
            {   # 8 — فلتر الذيول
                "name":   "الذيول",
                "sk":     "wck",
                "busy":   wick_bd > 0 or wick_al > 0,
                "alarm":  False,
                "color":  "cyan",
                "stat":   f"✓{wick_al} ✗{wick_bd}",
                "metric": f"فلتر نشط" if (wick_bd + wick_al) > 0 else "ينتظر",
            },
            {   # 9 — محرك الثقة
                "name":   "الثقة",
                "sk":     "ceo",
                "busy":   True,
                "alarm":  streak <= -3,
                "color":  "green" if streak > 0 else ("red" if streak < -2 else "yellow"),
                "stat":   f"{'▲' if streak>0 else '▼' if streak<0 else '─'}{streak:+d}",
                "metric": f"extra=+{extra}" if extra else f"conf={conf_d.get('confidence',1.0):.2f}",
            },
            {   # 10 — CEO / Ollama
                **self._ceo_card(),
            },
        ]

        # ── بناء الجدول ─────────────────────────────────────────────────────
        t = Table(box=None, show_header=False, show_edge=False,
                  pad_edge=False, expand=True)
        for _ in agents:
            t.add_column("", justify="center", ratio=1)

        cells = []
        for ag in agents:
            sk    = ag["sk"]
            busy  = ag["busy"] or ag["alarm"]
            alarm = ag["alarm"]
            color = "red" if alarm else ag["color"]

            # إطار الشخصية (3 أسطر)
            frames = _SPRITES.get(sk, _SPRITES["ceo"])
            fi     = (self._frame % len(frames)) if busy else 0
            sp     = frames[fi]

            # نبض التنبيه: يتبدّل بين ● و■ كل إطار
            blink  = "■" if alarm and (self._frame % 2 == 0) else ("●" if busy else "○")
            bc     = "red" if alarm else ("green" if busy else "dim")

            card = Text(justify="center")
            card.append(sp[0] + "\n",             style=color)
            card.append(sp[1] + "\n",             style=color)
            card.append(sp[2] + "\n",             style="dim " + color)
            card.append(ag["name"][:7] + "\n",    style="bold " + color)
            card.append(blink + " ",              style=bc)
            card.append(ag["stat"][:11] + "\n",   style=color)
            card.append(ag["metric"][:13],        style="dim")
            cells.append(card)

        t.add_row(*cells)

        return Panel(
            t,
            title="[bold bright_green]▣ غرفة القيادة — جميع الوكلاء + CEO يعملون[/bold bright_green]",
            box=box.HEAVY,
            border_style="bright_green",
            padding=(0, 1),
        )

    def _ceo_card(self) -> dict:
        """بطاقة CEO/Ollama للـ command center."""
        if self.ceo is None:
            return {
                "name":   "CEO",
                "sk":     "ceo",
                "busy":   False,
                "alarm":  False,
                "color":  "dim",
                "stat":   "غير نشط",
                "metric": "Ollama غير مضبوط",
            }
        try:
            st    = self.ceo.status()
            avail = st.get("available", False)
            mood  = st.get("mood", "calm")
            cycle = st.get("cycle", 0)
            thought = st.get("thoughts", "…")[:13]
            alarm  = mood == "urgent"
            color  = "red" if alarm else ("bright_green" if avail else "yellow")
            mood_icon = "🔴" if alarm else ("🟢" if avail else "🟡")
            return {
                "name":   "CEO/AI",
                "sk":     "ceo",
                "busy":   avail,
                "alarm":  alarm,
                "color":  color,
                "stat":   f"{mood_icon} {mood[:8]}",
                "metric": f"c{cycle} {thought}",
            }
        except Exception:
            return {
                "name":   "CEO/AI",
                "sk":     "ceo",
                "busy":   False,
                "alarm":  False,
                "color":  "yellow",
                "stat":   "يتصل…",
                "metric": "Ollama",
            }

    def _all_open_positions(self) -> list:
        result = []
        for sym, orch in self.all_orchs.items():
            if orch is None:
                continue
            try:
                for tid, pos in orch.monitor.open_positions().items():
                    result.append((sym, tid, pos))
            except Exception:
                pass
        return result

    # ── تخطيط الشاشة ─────────────────────────────────────────────────────────

    def _render(self) -> Layout:
        lo = Layout()
        lo.split_column(
            Layout(self._header(),               name="hdr",    size=4),
            Layout(self._agents_command_center(), name="agents", size=9),
            Layout(name="main",                  ratio=1),
            Layout(self._comms(),                name="comms",  size=10),
            Layout(self._footer(),               name="ftr",    size=1),
        )
        lo["main"].split_row(
            Layout(name="col_left",   ratio=3),
            Layout(name="col_center", ratio=4),
            Layout(name="col_right",  ratio=3),
        )
        lo["col_left"].split_column(
            Layout(self._ceo_office(),  name="ceo",  ratio=3),
            Layout(self._risk_office(), name="risk", ratio=2),
        )
        lo["col_center"].split_column(
            Layout(self._trading_floor(),  name="floor", ratio=3),
            Layout(self._analyst_office(), name="ana",   ratio=2),
        )
        lo["col_right"].split_column(
            Layout(self._learning_office(), name="lrn", ratio=2),
            Layout(self._guard_office(),    name="grd", ratio=2),
            Layout(self._symbols_panel(),   name="sym", ratio=1),
        )
        return lo

    # ── مكتب المدير ──────────────────────────────────────────────────────────

    def _ceo_office(self) -> Panel:
        st  = self._orch_status()
        acc = self._account()
        t   = Table(box=box.MINIMAL, show_header=False, expand=True)
        t.add_column("k", style="dim", width=13)
        t.add_column("v", style="bold")

        bal  = acc.get("balance", "?")
        eq   = acc.get("equity",  "?")
        free = acc.get("margin_free", "?")
        conn = "[green]● LIVE[/green]" if acc.get("connected") else "[red]○ OFF[/red]"
        demo = " [yellow][DEMO][/yellow]" if acc.get("demo_detected") else ""

        try:
            bal_f    = float(bal)
            eq_f     = float(eq)
            eq_bar   = _pbar(eq_f, bal_f, width=12)
            eq_color = "green" if eq_f >= bal_f else ("yellow" if eq_f >= bal_f * 0.95 else "red")
        except (ValueError, TypeError):
            eq_bar   = "░" * 12
            eq_color = "white"

        t.add_row("رصيد",    f"[bold green]$ {bal}[/bold green]")
        t.add_row("حقوق",    f"[{eq_color}]{eq_bar}[/{eq_color}] ${eq}")
        t.add_row("هامش حر", f"$ {free}")
        t.add_row("اتصال",   f"{conn}{demo}")
        t.add_row("", "")

        bars   = st.get("bars_processed", 0)
        opened = st.get("trades_opened",  0)
        open_n = st.get("open_count",     0)
        t.add_row("Bars",   f"[dim]{bars}[/dim]")
        t.add_row("فُتحت",  f"[cyan]{opened}[/cyan]")
        pos_icons = ("▣ " * open_n).strip() if open_n else "○"
        t.add_row("مفتوحة", f"[yellow]{pos_icons}[/yellow]")

        lrn = st.get("learning", {})
        if lrn.get("trades"):
            wr     = float(lrn.get("win_rate", 0))
            pf     = float(lrn.get("profit_factor", 0))
            wc     = "green" if wr > 0.55 else ("yellow" if wr > 0.45 else "red")
            pc     = "green" if pf > 1.2  else ("yellow" if pf > 0.9  else "red")
            wr_bar = _pbar(wr, 1.0, width=10)
            t.add_row("", "")
            t.add_row("Win%", f"[{wc}]{wr_bar}[/{wc}] {wr:.0%}")
            t.add_row("PF",   f"[{pc}]{pf:.2f}[/{pc}]")

        if self._pnl_history:
            t.add_row("", "")
            t.add_row("PnL ▸", f"[cyan]{_sparkline(list(self._pnl_history))}[/cyan]")

        conf = st.get("confidence", {})
        if conf:
            streak = int(conf.get("streak", 0))
            sc     = "green" if streak > 0 else ("red" if streak < 0 else "dim")
            arr    = "▲" if streak > 0 else ("▼" if streak < 0 else "─")
            t.add_row("Streak", f"[{sc}]{arr} {streak:+d}[/{sc}]")
            ex = int(conf.get("extra_positions", 0))
            if ex:
                t.add_row("Extra",  f"[cyan]+{ex}[/cyan]")

        is_busy = bool(open_n or st.get("trades_opened", 0))
        ico, title, style = _CEO
        return Panel(
            Group(self._sprite_row("ceo", "bright_green", "المدير", busy=is_busy), t),
            title=f"[{style}]{ico} {title} — {self.symbol}[/{style}]",
            box=box.HEAVY, border_style="green", padding=(0, 1),
        )

    # ── مكتب المخاطر ─────────────────────────────────────────────────────────

    def _risk_office(self) -> Panel:
        t = Table(box=box.MINIMAL, show_header=False, expand=True)
        t.add_column("k", style="dim", width=12)
        t.add_column("v", style="bold")

        active = False
        if self.orch:
            sl_m = getattr(self.orch.risk, "atr_sl_mult", 1.5)
            rr   = getattr(self.orch.risk, "min_rr",      1.2)
            buf  = getattr(self.orch.risk, "sl_buffer",   0.1)
            bt   = getattr(self.orch.entry, "buy_prob_threshold",  0.60)
            st_  = getattr(self.orch.entry, "sell_prob_threshold", 0.40)
            ms   = getattr(self.orch.entry, "min_smc_score",       2)
            t.add_row("SL dist",  f"{sl_m:.2f}×ATR")
            t.add_row("min R:R",  f"{rr:.2f}")
            t.add_row("SL buf",   f"{buf:.2f}×ATR")
            t.add_row("", "")
            t.add_row("BUY thr",  f"[green]{bt:.2f}[/green]")
            t.add_row("SELL thr", f"[red]{st_:.2f}[/red]")
            t.add_row("SMC min",  f"≥ {ms}")
            active = True
        else:
            t.add_row("حالة", "[dim]غير مربوط[/dim]")

        ico, title, style = _CRO
        return Panel(
            Group(self._sprite_row("risk", "red", "CRO", busy=active), t),
            title=f"[{style}]{ico} {title}[/{style}]",
            box=box.HEAVY, border_style="red", padding=(0, 1),
        )

    # ── طابق التداول ─────────────────────────────────────────────────────────

    def _trading_floor(self) -> Panel:
        # تجميع كل الصفقات المفتوحة من جميع الرموز
        all_positions: list[tuple[str, str, dict]] = []
        for sym, orch in self.all_orchs.items():
            if orch is None:
                continue
            try:
                for tid, pos in orch.monitor.open_positions().items():
                    all_positions.append((sym, tid, pos))
            except Exception:
                pass

        t = Table(box=box.SIMPLE_HEAVY, show_header=True, expand=True,
                  header_style="bold green on dark_green")
        t.add_column("رمز",  width=8)
        t.add_column("▲/▼",  width=6)
        t.add_column("دخول", width=10)
        t.add_column("SL",   width=10)
        t.add_column("مرحلة",width=12)
        t.add_column("PnL",  width=9)

        for sym, tid, pos in all_positions:
            side  = pos.get("side", "?")
            entry = float(pos.get("entry", 0))
            sl    = float(pos.get("sl",    0))
            tp    = float(pos.get("tp",    0))
            be    = pos.get("be_applied", False)
            max_p = float(pos.get("max_profit", 0))

            sc       = "green" if side == "BUY" else "red"
            pix_side = "▲ BUY" if side == "BUY" else "▼ SEL"
            pnl_pts  = 0.0
            try:
                orch = self.all_orchs.get(sym)
                if orch and self.gw:
                    tick    = self.gw.symbol_snapshot(sym)
                    bid     = float(tick.get("bid", entry)) if tick else entry
                    pnl_pts = (bid - entry) if side == "BUY" else (entry - bid)
            except Exception:
                pass

            if pos.get("sl_update_cooldown", 0) > 0:
                stage = "[dim]─ wait[/dim]"
            elif max_p > 0:
                ratio = max_p / max(float(pos.get("atr", 1e-9)), 1e-9) if pos.get("atr") else 0
                if ratio >= 5.5:   stage = "[red]■■■ LOCK[/red]"
                elif ratio >= 3.5: stage = "[magenta]▓▓ ultra[/magenta]"
                elif ratio >= 2.0: stage = "[yellow]▒▒ tight[/yellow]"
                elif be:           stage = "[green]░ BE ✓[/green]"
                else:              stage = "[cyan]░ trail[/cyan]"
            elif be:
                stage = "[green]░ BE ✓[/green]"
            else:
                stage = "[dim]○ open[/dim]"

            pc  = "green" if pnl_pts >= 0 else "red"
            arr = "▲" if pnl_pts >= 0 else "▼"
            t.add_row(
                f"[dim]{sym}[/dim]",
                f"[{sc}]{pix_side}[/{sc}]",
                f"{entry:.4f}",
                f"{sl:.4f}",
                stage,
                f"[{pc}]{arr}{abs(pnl_pts):.3f}[/{pc}]",
            )

        if not all_positions:
            t.add_row("─", "─", "─", "─", "[dim]○ لا صفقات[/dim]", "─")

        busy = bool(all_positions)
        ico, title, style = _MON
        return Panel(
            Group(self._sprite_row("mon", "yellow", "المراقب", busy=busy), t),
            title=f"[{style}]{ico} {title} — طابق التداول[/{style}]",
            box=box.HEAVY, border_style="yellow", padding=(0, 1),
        )

    # ── مكتب المحلل ──────────────────────────────────────────────────────────

    def _analyst_office(self) -> Panel:
        t = Table(box=box.MINIMAL, show_header=False, expand=True)
        t.add_column("k", style="dim", width=13)
        t.add_column("v", style="bold")

        tick   = self._current_tick()
        active = False
        if tick:
            spread = tick.get("spread", "?")
            t.add_row("Bid",    f"[white bold]{tick.get('bid','?')}[/white bold]")
            t.add_row("Ask",    f"{tick.get('ask','?')}")
            sp_c = "red" if float(spread or 0) > 30 else "green"
            t.add_row("Spread", f"[{sp_c}]{spread}[/{sp_c}] pts")
            active = True

        st = self._orch_status()
        t.add_row("", "")

        def _flag(val: bool) -> str:
            return "[green]▣[/green]" if val else "[dim]□[/dim]"

        t.add_row("SSL",  _flag(st.get("ssl_active")))
        t.add_row("BSL",  _flag(st.get("bsl_active")))
        t.add_row("BOS↑", _flag(st.get("bos_up")))
        t.add_row("BOS↓", _flag(st.get("bos_down")))

        if self.orch:
            prob  = st.get("prob", 0.0)
            pc    = "green" if prob > 0.60 else ("red" if prob < 0.40 else "yellow")
            pb    = _pbar(prob, 1.0, width=8)
            t.add_row("AI",    f"[{pc}]{pb}[/{pc}] {prob:.3f}")
            smc_b = st.get("smc_buy",  0)
            smc_s = st.get("smc_sell", 0)
            t.add_row("SMC▲", f"[green]{'◆' * min(smc_b, 5)}[/green] {smc_b}")
            t.add_row("SMC▼", f"[red]{'◆' * min(smc_s, 5)}[/red] {smc_s}")
            active = active or bool(smc_b or smc_s)

        ico, title, style = _ANA
        return Panel(
            Group(self._sprite_row("ana", "cyan", "المحلل", busy=active), t),
            title=f"[{style}]{ico} {title}  ◉ {_LIQ[1]}[/{style}]",
            box=box.HEAVY, border_style="cyan", padding=(0, 1),
        )

    # ── مكتب التعلم ──────────────────────────────────────────────────────────

    def _learning_office(self) -> Panel:
        t = Table(box=box.MINIMAL, show_header=False, expand=True)
        t.add_column("k", style="dim", width=12)
        t.add_column("v", style="bold")

        active = False
        if self.orch:
            lrn = self.orch.learning.summary("smc", self.symbol, lookback=30)
            wr  = float(lrn.get("win_rate", 0))
            pf  = float(lrn.get("profit_factor", 0))
            avg = float(lrn.get("avg_r", 0))
            n   = int(lrn.get("trades", 0))
            wc  = "green" if wr > 0.55 else ("yellow" if wr > 0.45 else "red")
            pc  = "green" if pf > 1.2  else ("yellow" if pf > 0.9  else "red")
            t.add_row("صفقات", f"{n}/30")
            t.add_row("Win%",  f"[{wc}]{_pbar(wr, 1.0, width=8)}[/{wc}] {wr:.0%}")
            t.add_row("PF",    f"[{pc}]{pf:.2f}[/{pc}]")
            arr = "▲" if avg >= 0 else "▼"
            t.add_row("avgR",  f"{arr}{abs(avg):.3f}")
            thr = lrn.get("thresholds", {})
            t.add_row("", "")
            t.add_row("SL×",  f"{thr.get('atr_sl_mult', 1.5):.2f}")
            t.add_row("R:R",  f"{thr.get('min_rr', 1.2):.2f}")
            t.add_row("BUY",  f"{thr.get('buy_threshold', 0.60):.2f}")
            active = n > 0
        else:
            t.add_row("حالة", "[dim]غير مربوط[/dim]")

        ico, title, style = _LRN
        return Panel(
            Group(self._sprite_row("lrn", "magenta", "التعلم", busy=active), t),
            title=f"[{style}]{ico} {title}[/{style}]",
            box=box.HEAVY, border_style="magenta", padding=(0, 1),
        )

    # ── مكتب حارس الخسائر ────────────────────────────────────────────────────

    def _guard_office(self) -> Panel:
        t = Table(box=box.MINIMAL, show_header=False, expand=True)
        t.add_column("k", style="dim", width=12)
        t.add_column("v", style="bold")

        alarmed = False
        if self.orch:
            gs  = self.orch.guard.status()
            cl  = gs.get("consec_losses",   0)
            pb  = gs.get("pause_bars_left", 0)
            fl  = gs.get("force_min_lot",   False)
            bt  = gs.get("boost_thresh",    False)
            sts = "[red]■ PAUSED[/red]" if pb > 0 else "[green]▣ ACTIVE[/green]"
            t.add_row("حالة",  sts)
            t.add_row("خسائر", "[red]" + "■" * cl + "□" * max(0, 3 - cl) + "[/red]")
            t.add_row("توقف",  f"[red]{pb}[/red]" if pb else "[dim]0[/dim]")
            t.add_row("Lot",   "[red]MIN▼[/red]" if fl else "[dim]norm[/dim]")
            t.add_row("THR+",  "[yellow]▲[/yellow]" if bt else "[dim]─[/dim]")
            t.add_row("", "")
            cf  = self.orch.confidence.status()
            sk  = int(cf.get("streak", 0))
            ex  = int(cf.get("extra_positions", 0))
            sc  = "green" if sk > 0 else ("red" if sk < 0 else "dim")
            arr = "▲" if sk > 0 else ("▼" if sk < 0 else "─")
            t.add_row("Streak", f"[{sc}]{arr}{sk:+d}[/{sc}]")
            if ex:
                t.add_row("Extra",  f"[cyan]+{ex}[/cyan]")
            alarmed = pb > 0 or cl >= 2
        else:
            t.add_row("حالة", "[dim]غير مربوط[/dim]")

        ico, title, style = _DRW
        color  = "red" if alarmed else "yellow"
        return Panel(
            Group(self._sprite_row("drw", color, "الحارس", busy=True), t),
            title=f"[{style}]{ico} {title}[/{style}]",
            box=box.HEAVY, border_style="red", padding=(0, 1),
        )

    # ── لوحة ملخص جميع الرموز ────────────────────────────────────────────────

    def _symbols_panel(self) -> Panel:
        t = Table(box=box.MINIMAL, show_header=False, expand=True)
        t.add_column("sym", style="dim", width=9)
        t.add_column("s",   width=3)
        t.add_column("wr",  width=6)

        for sym, orch in list(self.all_orchs.items())[:8]:
            if orch is None:
                continue
            try:
                n_open = orch.monitor.count()
                lrn    = orch.learning.summary("smc", sym, lookback=20)
                n_t    = int(lrn.get("trades", 0))
                wr     = float(lrn.get("win_rate", 0))
                wc     = "green" if wr > 0.55 else ("yellow" if wr > 0.45 else "red")
                pos    = f"[yellow]▣[/yellow]" if n_open else "[dim]○[/dim]"
                wr_s   = f"[{wc}]{wr:.0%}[/{wc}]" if n_t > 0 else "[dim]─[/dim]"
                t.add_row(sym[:9], pos, wr_s)
            except Exception:
                pass

        return Panel(
            t,
            title="[dim cyan]◈ رموز نشطة[/dim cyan]",
            box=box.HEAVY, border_style="dim cyan", padding=(0, 0),
        )

    # ── قناة الاتصالات ────────────────────────────────────────────────────────

    def _comms(self) -> Panel:
        msgs = self._bus.recent(8)
        t = Table(box=box.SIMPLE, show_header=True, expand=True,
                  header_style="bold dim green")
        t.add_column("▸ وقت", width=9)
        t.add_column("من",    width=16)
        t.add_column("إلى",   width=16)
        t.add_column("الرسالة", ratio=1)

        _LEVEL_COLORS = {
            "trade": "green",
            "risk":  "red",
            "warn":  "yellow",
            "info":  "dim white",
        }

        for m in msgs:
            col    = _LEVEL_COLORS.get(m.get("level", "info"), "white")
            prefix = "▲" if m.get("level") == "trade" else ("■" if m.get("level") in ("risk", "warn") else "►")
            t.add_row(
                f"[dim]{m['time']}[/dim]",
                f"[{col}]{m['sender'][:14]}[/{col}]",
                f"[dim]{m['recipient'][:14]}[/dim]",
                f"[{col}]{prefix} {m['msg'][:88]}[/{col}]",
            )

        if not msgs:
            t.add_row("─", "─", "─", "[dim]○ في انتظار الأحداث...[/dim]")

        return Panel(
            t,
            title="[bold green]◈ قناة الاتصالات — رسائل الوكلاء[/bold green]",
            box=box.HEAVY, border_style="dim green", padding=(0, 1),
        )

    # ── رأس الصفحة والتذييل ──────────────────────────────────────────────────

    def _header(self) -> Panel:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d  %H:%M:%S  UTC")
        acc = self._account()
        bal = acc.get("balance", "?")
        eq  = acc.get("equity",  "?")
        srv = acc.get("server",  "?")
        lg  = acc.get("login",   "?")

        pulse = ["◆", "◇", "◆", "◇"][self._frame % 4]
        n_sym = len(self.all_orchs)
        n_pos = sum(
            o.monitor.count() for o in self.all_orchs.values() if o
        )

        txt = Text(justify="center")
        txt.append("▄▀▀ ▄▀█ █▀▄ █▀▀ █▀█  ", style="bold bright_green")
        txt.append(f"{pulse} ", style="bright_green")
        txt.append("قادر  GADER", style="bold white")
        txt.append(f"  {pulse}  ", style="bright_green")
        txt.append(f"{self.symbol}", style="bold yellow")
        txt.append(f"  رموز={n_sym} مفتوحة={n_pos}", style="dim cyan")
        txt.append(f"  │  ${bal} / ${eq}", style="green")
        txt.append(f"  │  {srv} #{lg}", style="dim green")
        txt.append(f"  │  {now}", style="dim white")

        return Panel(txt, box=box.HEAVY, border_style="bright_green", padding=(0, 1))

    def _footer(self) -> Text:
        t = Text(justify="center")
        t.append("Ctrl+C للخروج  ◆  ", style="dim green")
        t.append("GADER AI — Paper/Demo فقط  ◆  ", style="dim bold green")
        t.append("لا تداول حقيقي", style="dim red")
        return t

    # ── جلب البيانات ─────────────────────────────────────────────────────────

    def _orch_status(self) -> dict:
        if not self.orch:
            return {}
        try:
            s = self.orch.status()
            s["open_count"] = len(s.get("open_positions", {}))
            return s
        except Exception:
            return {}

    def _account(self) -> dict:
        if not self.gw:
            return {}
        try:
            return self.gw.account_snapshot()
        except Exception:
            return {}

    def _current_tick(self) -> dict | None:
        if not self.gw:
            return None
        try:
            return self.gw.symbol_snapshot(self.symbol)
        except Exception:
            return None
