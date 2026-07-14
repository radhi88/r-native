"""
dashboard.py — FRIDAY Corporate Operations Center
مركز عمليات FRIDAY — كل وكيل في مكتبه الخاص يعمل ويرسل تعليمات.

تشغيل:
    python scripts/run_dashboard.py
    # أو من داخل الكود:
    dash = FridayDashboard(orchestrator=orch, gateway=gw)
    dash.run()
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING

try:
    from rich.console import Console
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

# ── ألوان ومسميات الوكلاء ────────────────────────────────────────────────────
_CEO   = ("🏢", "المدير التنفيذي",         "bold cyan")
_CRO   = ("🛡️ ", "مدير المخاطر CRO",       "bold red")
_ANA   = ("📊", "المحلل الفني",            "bold blue")
_LIQ   = ("💧", "أخصائي السيولة",          "blue")
_ENT   = ("🎯", "استراتيجي الدخول",        "bold green")
_MON   = ("👁️ ", "مراقب التداول",           "bold yellow")
_DRW   = ("🚨", "حارس الخسائر",            "bold red")
_CON   = ("📈", "محلل الأداء",             "magenta")
_LRN   = ("🧠", "مدير التعلم",             "bold magenta")
_WCK   = ("🕯️ ", "فلتر الذيول",             "cyan")
_HUM   = ("🤝", "محلل سلوك المتداول",      "yellow")
_TRD   = ("💼", "المتداول",                "bold white")


class _EventBus:
    """حافلة أحداث داخلية تتيح للوكلاء 'إرسال رسائل' لبعضهم."""

    def __init__(self, maxlen: int = 60):
        self._q: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, sender: str, recipient: str, msg: str, level: str = "info"):
        with self._lock:
            self._q.appendleft({
                "time":      datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "sender":    sender,
                "recipient": recipient,
                "msg":       msg,
                "level":     level,
            })

    def recent(self, n: int = 20) -> list[dict]:
        with self._lock:
            return list(self._q)[:n]


# الحافلة المشتركة بين الداشبورد وأي كود خارجي
event_bus = _EventBus()


class FridayDashboard:
    """
    شاشة مركز عمليات FRIDAY — كل وكيل في مكتبه الخاص.

    الاستخدام:
        dash = FridayDashboard(orchestrator=orch, gateway=gw)
        dash.run()                # blocking — Ctrl+C للخروج
        dash.run(block=False)     # thread خلفي
    """

    REFRESH = 2.0   # ثواني بين كل تحديث

    def __init__(
        self,
        orchestrator: "FridayOrchestrator | None" = None,
        gateway:      "MT5Gateway | None"          = None,
        symbol:       str                          = "XAUUSDm",
    ):
        if not _RICH_OK:
            raise ImportError("pip install rich")

        self.orch    = orchestrator
        self.gw      = gateway
        self.symbol  = symbol or (orchestrator.symbol if orchestrator else "?")
        self.console = Console()
        self._bus    = event_bus
        self._running = False

        # اعترض أحداث الأوركيسترتور وأدخلها في الحافلة
        if orchestrator:
            _orig_cb = getattr(orchestrator, "event_cb", None)
            def _patched(evt, data, **kw):
                self._translate_event(evt, data)
                if callable(_orig_cb):
                    _orig_cb(evt, data)
            orchestrator.event_cb = _patched

    # ── API ──────────────────────────────────────────────────────────────────────

    def run(self, block: bool = True):
        if block:
            self._loop()
        else:
            threading.Thread(target=self._loop, daemon=True, name="friday-dash").start()

    def push(self, sender: str, recipient: str, msg: str, level: str = "info"):
        self._bus.push(sender, recipient, msg, level)

    # ── ترجمة أحداث الأوركيسترتور إلى رسائل بين الوكلاء ────────────────────────

    def _translate_event(self, evt: str, data: dict):
        b = self._bus
        if evt == "trade_open":
            side = data.get("action", "?")
            sl   = data.get("sl", 0)
            tp   = data.get("tp", 0)
            rr   = data.get("rr", "?")
            tid  = data.get("trade_id", "")
            b.push("استراتيجي الدخول", "المتداول",
                   f"► أدخل {side} | SL={sl:.2f}  TP={tp:.2f}  R:R={rr}  [{tid}]", "trade")
            b.push("مدير المخاطر CRO", "المتداول",
                   f"✓ SL/TP مُعتمَد: خسارة={abs(data.get('price',0)-sl):.3f}  ربح={abs(tp-data.get('price',0)):.3f}", "risk")

        elif evt == "trade_closed":
            won  = data.get("won")
            pnl  = float(data.get("pnl_points", 0))
            tid  = data.get("trade_id", "")
            why  = data.get("reason", "")
            icon = "💰 ربح" if won else "💸 خسارة"
            b.push("مراقب التداول", "مدير التعلم",
                   f"{icon} {pnl:+.4f} pts  [{why}]  {tid}", "trade" if won else "warn")
            b.push("مدير التعلم", "المدير التنفيذي",
                   f"سجّلت صفقة جديدة {'✓ ربح' if won else '✗ خسارة'} — أحدّث العتبات", "info")

        elif evt == "sl_update":
            reason = data.get("reason", "")
            sl_new = data.get("sl", 0)
            mult   = data.get("trail_mult")
            mult_s = f" [{mult:.2f}×ATR]" if mult else ""
            b.push("مراقب التداول", "المتداول",
                   f"⚙ حرّكت SL → {sl_new:.5f}  [{reason}]{mult_s}", "info")

        elif "drawdown" in evt or "cooldown" in evt:
            b.push("حارس الخسائر", "المدير التنفيذي",
                   f"🚨 توقف إجباري — {data}", "warn")

    # ── حلقة العرض ───────────────────────────────────────────────────────────────

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
                    live.update(self._render())
                    time.sleep(self.REFRESH)
            except KeyboardInterrupt:
                self._running = False

    # ── بناء التخطيط الكامل ──────────────────────────────────────────────────────

    def _render(self) -> Layout:
        lo = Layout()

        # صف العنوان
        lo.split_column(
            Layout(self._header(),  name="hdr",  size=3),
            Layout(name="main",     ratio=1),
            Layout(self._comms(),   name="comms", size=13),
            Layout(self._footer(),  name="ftr",  size=1),
        )

        # الصف الرئيسي: مكاتب الوكلاء
        lo["main"].split_row(
            Layout(name="col_left",   ratio=3),
            Layout(name="col_center", ratio=4),
            Layout(name="col_right",  ratio=3),
        )

        lo["col_left"].split_column(
            Layout(self._ceo_office(),      name="ceo",  ratio=3),
            Layout(self._risk_office(),     name="risk", ratio=2),
        )

        lo["col_center"].split_column(
            Layout(self._trading_floor(),   name="floor", ratio=3),
            Layout(self._analyst_office(),  name="ana",   ratio=2),
        )

        lo["col_right"].split_column(
            Layout(self._learning_office(), name="lrn",  ratio=2),
            Layout(self._guard_office(),    name="grd",  ratio=2),
            Layout(self._wick_office(),     name="wck",  ratio=1),
        )

        return lo

    # ── مكتب المدير التنفيذي ─────────────────────────────────────────────────────

    def _ceo_office(self) -> Panel:
        st  = self._orch_status()
        acc = self._account()
        t   = Table(box=box.SIMPLE, show_header=False, expand=True)
        t.add_column("k", style="dim", width=18)
        t.add_column("v", style="bold")

        bal  = acc.get("balance", "?")
        eq   = acc.get("equity",  "?")
        free = acc.get("margin_free", "?")
        conn = "[green]متصل ✓[/green]" if acc.get("connected") else "[red]منقطع ✗[/red]"
        demo = " [yellow][DEMO][/yellow]" if acc.get("demo_detected") else ""

        t.add_row("رصيد", f"[bold green]${bal}[/bold green]")
        t.add_row("حقوق", f"${eq}")
        t.add_row("هامش حر", f"${free}")
        t.add_row("اتصال", f"{conn}{demo}")
        t.add_row("", "")

        bars   = st.get("bars_processed", 0)
        opened = st.get("trades_opened",  0)
        open_n = st.get("open_count",     0)
        t.add_row("Bars محلّلة",  str(bars))
        t.add_row("صفقات فُتحت", str(opened))
        t.add_row("مفتوحة الآن", f"[yellow]{open_n}[/yellow]")

        lrn = st.get("learning", {})
        if lrn.get("trades"):
            wr = float(lrn.get("win_rate", 0))
            pf = float(lrn.get("profit_factor", 0))
            wc = "green" if wr > 0.55 else ("yellow" if wr > 0.45 else "red")
            pc = "green" if pf > 1.2  else ("yellow" if pf > 0.9  else "red")
            t.add_row("", "")
            t.add_row("Win Rate",  f"[{wc}]{wr:.0%}[/{wc}]")
            t.add_row("Profit F",  f"[{pc}]{pf:.2f}[/{pc}]")
            t.add_row("صفقات",     str(lrn.get("trades", 0)))
            thr = lrn.get("thresholds", {})
            if thr:
                t.add_row("SL mult",  f"{thr.get('atr_sl_mult',1.5):.2f}×ATR")
                t.add_row("min R:R",  f"{thr.get('min_rr',1.2):.2f}")

        conf = st.get("confidence", {})
        if conf:
            streak = conf.get("streak", 0)
            sc = "green" if streak > 0 else ("red" if streak < 0 else "dim")
            t.add_row("", "")
            t.add_row("Streak",   f"[{sc}]{streak:+d}[/{sc}]")
            t.add_row("Extra Pos",str(conf.get("extra_positions", 0)))

        ico, title, style = _CEO
        return Panel(t, title=f"[{style}]{ico}  {title} — {self.symbol}[/{style}]",
                     border_style="cyan", padding=(0, 1))

    # ── مكتب المخاطر ─────────────────────────────────────────────────────────────

    def _risk_office(self) -> Panel:
        t = Table(box=box.SIMPLE, show_header=False, expand=True)
        t.add_column("k", style="dim", width=18)
        t.add_column("v", style="bold")

        if self.orch:
            sl_m = getattr(self.orch.risk, "atr_sl_mult", 1.5)
            rr   = getattr(self.orch.risk, "min_rr",      1.2)
            buf  = getattr(self.orch.risk, "sl_buffer",   0.1)
            t.add_row("SL distance", f"{sl_m:.2f}×ATR")
            t.add_row("min R:R",     f"{rr:.2f}")
            t.add_row("SL buffer",   f"{buf:.2f}×ATR")
            t.add_row("", "")
            # Entry thresholds
            bt = getattr(self.orch.entry, "buy_prob_threshold",  0.60)
            st_ = getattr(self.orch.entry, "sell_prob_threshold", 0.40)
            ms  = getattr(self.orch.entry, "min_smc_score",       2)
            t.add_row("BuyThresh",  f"{bt:.2f}")
            t.add_row("SellThresh", f"{st_:.2f}")
            t.add_row("SMC score",  f"≥ {ms}")
        else:
            t.add_row("حالة", "غير مربوط")

        ico, title, style = _CRO
        return Panel(t, title=f"[{style}]{ico} {title}[/{style}]",
                     border_style="red", padding=(0, 1))

    # ── طابق التداول ─────────────────────────────────────────────────────────────

    def _trading_floor(self) -> Panel:
        positions = self._open_positions()
        t = Table(box=box.SIMPLE_HEAVY, show_header=True, expand=True,
                  header_style="bold white")
        t.add_column("ID",    width=7)
        t.add_column("اتجاه", width=6)
        t.add_column("دخول",  width=10)
        t.add_column("SL",    width=10)
        t.add_column("TP",    width=10)
        t.add_column("مرحلة", width=14)
        t.add_column("PnL Pts", width=9)

        acc   = self._account()
        tick  = self._current_tick()

        for tid, pos in positions.items():
            side  = pos.get("side", "?")
            entry = float(pos.get("entry", 0))
            sl    = float(pos.get("sl",    0))
            tp    = float(pos.get("tp",    0))
            be    = pos.get("be_applied", False)
            max_p = float(pos.get("max_profit", 0))

            sc = "green" if side == "BUY" else "red"
            pnl_pts = 0.0
            if tick:
                bid = float(tick.get("bid", entry))
                pnl_pts = (bid - entry) if side == "BUY" else (entry - bid)

            if pos.get("sl_update_cooldown", 0) > 0:
                stage = "[dim]cooldown[/dim]"
            elif max_p > 0:
                ratio = max_p / max(float(pos.get("atr", 1e-9)), 1e-9) if pos.get("atr") else 0
                if ratio >= 5.5:   stage = "[red]🔒 lock[/red]"
                elif ratio >= 3.5: stage = "[magenta]ultra[/magenta]"
                elif ratio >= 2.0: stage = "[yellow]tight[/yellow]"
                elif be:           stage = "[green]BE ✓[/green]"
                else:              stage = "[cyan]trail[/cyan]"
            elif be:
                stage = "[green]BE ✓[/green]"
            else:
                stage = "[dim]open[/dim]"

            pc = "green" if pnl_pts >= 0 else "red"
            t.add_row(
                tid,
                f"[{sc}]{side}[/{sc}]",
                f"{entry:.4f}",
                f"{sl:.4f}",
                f"{tp:.4f}",
                stage,
                f"[{pc}]{pnl_pts:+.3f}[/{pc}]",
            )

        if not positions:
            t.add_row("—", "—", "—", "—", "—", "[dim]لا صفقات[/dim]", "—")

        ico, title, style = _MON
        return Panel(t, title=f"[{style}]{ico} {title} — طابق التداول[/{style}]",
                     border_style="yellow", padding=(0, 1))

    # ── مكتب المحلل الفني ────────────────────────────────────────────────────────

    def _analyst_office(self) -> Panel:
        t = Table(box=box.SIMPLE, show_header=False, expand=True)
        t.add_column("k", style="dim", width=16)
        t.add_column("v", style="bold")

        tick = self._current_tick()
        if tick:
            t.add_row("سعر Bid",  f"[white]{tick.get('bid','?')}[/white]")
            t.add_row("سعر Ask",  f"{tick.get('ask','?')}")
            t.add_row("Spread",   f"{tick.get('spread','?')} pts")

        st = self._orch_status()
        t.add_row("", "")
        t.add_row("SSL نشط", "[green]✓[/green]" if st.get("ssl_active") else "·")
        t.add_row("BSL نشط", "[green]✓[/green]" if st.get("bsl_active") else "·")
        t.add_row("BOS↑",    "[green]✓[/green]" if st.get("bos_up")    else "·")
        t.add_row("BOS↓",    "[green]✓[/green]" if st.get("bos_down")  else "·")
        if self.orch:
            prob = st.get("prob", 0.0)
            pc   = "green" if prob > 0.60 else ("red" if prob < 0.40 else "yellow")
            t.add_row("احتمال AI",  f"[{pc}]{prob:.3f}[/{pc}]")
            t.add_row("SMC Buy",   str(st.get("smc_buy", 0)))
            t.add_row("SMC Sell",  str(st.get("smc_sell", 0)))

        ico, title, style = _ANA
        return Panel(t, title=f"[{style}]{ico} {title}  |  {_LIQ[1]}[/{style}]",
                     border_style="blue", padding=(0, 1))

    # ── مكتب التعلم ──────────────────────────────────────────────────────────────

    def _learning_office(self) -> Panel:
        t = Table(box=box.SIMPLE, show_header=False, expand=True)
        t.add_column("k", style="dim", width=14)
        t.add_column("v", style="bold")

        if self.orch:
            lrn = self.orch.learning.summary("smc", self.symbol, lookback=30)
            wr  = float(lrn.get("win_rate", 0))
            pf  = float(lrn.get("profit_factor", 0))
            avg = float(lrn.get("avg_r", 0))
            n   = int(lrn.get("trades", 0))
            wc  = "green" if wr > 0.55 else ("yellow" if wr > 0.45 else "red")
            pc  = "green" if pf > 1.2  else ("yellow" if pf > 0.9  else "red")
            t.add_row("صفقات",    f"{n} (آخر 30)")
            t.add_row("Win Rate", f"[{wc}]{wr:.0%}[/{wc}]")
            t.add_row("PF",       f"[{pc}]{pf:.2f}[/{pc}]")
            t.add_row("avg R",    f"{avg:+.3f}")
            thr = lrn.get("thresholds", {})
            t.add_row("", "")
            t.add_row("SL mult",  f"{thr.get('atr_sl_mult',1.5):.2f}×")
            t.add_row("min R:R",  f"{thr.get('min_rr',1.2):.2f}")
            t.add_row("BuyThr",   f"{thr.get('buy_threshold',0.60):.2f}")
        else:
            t.add_row("حالة", "غير مربوط")

        ico, title, style = _LRN
        return Panel(t, title=f"[{style}]{ico} {title}[/{style}]",
                     border_style="magenta", padding=(0, 1))

    # ── مكتب حارس الخسائر ────────────────────────────────────────────────────────

    def _guard_office(self) -> Panel:
        t = Table(box=box.SIMPLE, show_header=False, expand=True)
        t.add_column("k", style="dim", width=14)
        t.add_column("v", style="bold")

        if self.orch:
            gs   = self.orch.guard.status()
            cl   = gs.get("consec_losses",   0)
            pb   = gs.get("pause_bars_left", 0)
            fl   = gs.get("force_min_lot",   False)
            bt   = gs.get("boost_thresh",    False)
            sts  = "[red]⏸ PAUSED[/red]" if pb > 0 else "[green]● ACTIVE[/green]"
            t.add_row("حالة",      sts)
            t.add_row("خسائر",     f"[{'red' if cl>0 else 'green'}]{cl}[/]")
            t.add_row("توقف bars", f"[red]{pb}[/red]" if pb else "0")
            t.add_row("Force Lot", "[red]✓[/red]" if fl else "·")
            t.add_row("عتبات+",    "[yellow]✓[/yellow]" if bt else "·")
            t.add_row("", "")
            # Confidence
            cf  = self.orch.confidence.status()
            sk  = cf.get("streak", 0)
            ex  = cf.get("extra_positions", 0)
            sc  = "green" if sk > 0 else ("red" if sk < 0 else "dim")
            t.add_row("Streak",   f"[{sc}]{sk:+d}[/{sc}]")
            t.add_row("Extra Pos",str(ex))
        else:
            t.add_row("حالة", "غير مربوط")

        ico, title, style = _DRW
        return Panel(t, title=f"[{style}]{ico} {title}  |  {_CON[1]}[/{style}]",
                     border_style="red", padding=(0, 1))

    # ── مكتب فلتر الذيول ─────────────────────────────────────────────────────────

    def _wick_office(self) -> Panel:
        t = Table(box=box.SIMPLE, show_header=False, expand=True)
        t.add_column("k", style="dim", width=14)
        t.add_column("v", style="bold")

        if self.orch and hasattr(self.orch, "wick"):
            wk = self.orch.wick
            bd = getattr(wk, "_blocked_total",   0)
            al = getattr(wk, "_allowed_total",   0)
            t.add_row("محجوب",  str(bd))
            t.add_row("مسموح",  str(al))
        else:
            t.add_row("حالة", "يراقب...")

        ico, title, style = _WCK
        return Panel(t, title=f"[{style}]{ico} {title}[/{style}]",
                     border_style="cyan", padding=(0, 1))

    # ── غرفة الاتصالات بين الوكلاء ────────────────────────────────────────────────

    def _comms(self) -> Panel:
        msgs = self._bus.recent(10)
        t = Table(box=box.SIMPLE, show_header=True, expand=True,
                  header_style="bold dim")
        t.add_column("وقت",    width=9)
        t.add_column("من",     width=22)
        t.add_column("إلى",    width=22)
        t.add_column("الرسالة", ratio=1)

        _LEVEL_COLORS = {
            "trade": "green",
            "risk":  "red",
            "warn":  "yellow",
            "info":  "white",
        }

        for m in msgs:
            col = _LEVEL_COLORS.get(m.get("level", "info"), "white")
            t.add_row(
                m["time"],
                f"[{col}]{m['sender'][:20]}[/{col}]",
                f"[dim]{m['recipient'][:20]}[/dim]",
                f"[{col}]{m['msg'][:90]}[/{col}]",
            )

        if not msgs:
            t.add_row("—", "—", "—", "[dim]في انتظار الأحداث...[/dim]")

        return Panel(
            t,
            title="[bold white]📡 قناة الاتصالات — رسائل بين الوكلاء[/bold white]",
            border_style="dim white",
            padding=(0, 1),
        )

    # ── رأس الصفحة وتذييلها ──────────────────────────────────────────────────────

    def _header(self) -> Panel:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d  %H:%M:%S  UTC")
        acc = self._account()
        bal = acc.get("balance", "?")
        eq  = acc.get("equity",  "?")
        srv = acc.get("server",  "?")
        lg  = acc.get("login",   "?")
        txt = Text(justify="center")
        txt.append("⚡  FRIDAY OPERATIONS CENTER  ", style="bold white on dark_blue")
        txt.append(f"  {self.symbol}  ", style="bold yellow on dark_blue")
        txt.append(f"  ${bal} / ${eq}  |  {srv}  #{lg}  |  {now}  ",
                   style="green on dark_blue")
        return Panel(txt, style="bold blue", padding=(0, 1))

    def _footer(self) -> Text:
        t = Text(justify="center")
        t.append("Ctrl+C للخروج  │  ", style="dim")
        t.append("FRIDAY AI — Paper/Demo only  │  ", style="dim bold")
        t.append("لا تداول حقيقي", style="dim red")
        return t

    # ── جلب البيانات ─────────────────────────────────────────────────────────────

    def _orch_status(self) -> dict:
        if not self.orch:
            return {}
        try:
            s = self.orch.status()
            s["open_count"] = len(s.get("open_positions", {}))
            return s
        except Exception:
            return {}

    def _open_positions(self) -> dict:
        if not self.orch:
            return {}
        try:
            return self.orch.monitor.open_positions()
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
