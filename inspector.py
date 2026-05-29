from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
                                QLabel, QTabWidget, QTableWidget, QTableWidgetItem,
                                QHeaderView, QScrollArea, QSizePolicy, QPushButton,
                                QMessageBox)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QUrl
from PySide6.QtGui import (QColor, QFont, QPainter, QPen, QBrush, QLinearGradient,
                            QPainterPath, QDesktopServices)


GOLD = "#fbbf24"
VIOLET = "#f5a524"   # was purple #8b5cf6 — unified to gold to match main UI
GREEN = "#10b981"
RED = "#ef4444"
TEXT = "#f1f5f9"
MUTED = "#94a3b8"
BG_0 = "#0a0a0f"     # was purple #060418 — unified with main UI
BG_1 = "#13131a"     # was purple #0d0824
BG_2 = "#1a1a23"     # was purple #14092e
BG_3 = "#222230"     # was purple #1c1142
BORDER = "#2d2d3a"   # was purple-blue #2d1b69 — unified with main UI palette


STATS_KPIS: list[tuple[str, str, str]] = [
    ("NET PROFIT", "net_profit", "money"),
    ("DRAWDOWN", "drawdown", "money_neg"),
    ("TOTAL TRADES", "total_trades", "int"),
    ("WIN RATE", "win_rate", "pct"),
    ("IS RETURN", "is_return", "pct"),
    ("IS TRADES", "is_trades", "int"),
    ("OOS RETURN", "oos_return", "pct"),
    ("OOS TRADES", "oos_trades", "int"),
    ("PROFIT FACTOR", "profit_factor", "ratio"),
    ("SHARPE RATIO", "sharpe", "ratio"),
    ("LINEARITY", "linearity", "ratio"),
    ("PERSISTENCE", "persistence", "ratio"),
    ("RECOVERY FACTOR", "recovery_factor", "ratio"),
    ("AVG HOLD TIME", "avg_hold_time", "text"),
    ("AVG PROFIT", "avg_profit", "money"),
    ("AVG LOSS", "avg_loss", "money_neg"),
    ("BIGGEST WIN", "biggest_win", "money"),
    ("BIGGEST LOSS", "biggest_loss", "money_neg"),
    ("MAX WIN STREAK", "max_win_streak", "int"),
    ("MAX LOSS STREAK", "max_loss_streak", "int"),
    ("AVG WIN STREAK", "avg_win_streak", "ratio"),
    ("AVG LOSS STREAK", "avg_loss_streak", "ratio"),
    ("LONG TRADES", "long_trades", "int"),
    ("SHORT TRADES", "short_trades", "int"),
]


SCORE_ROWS: list[tuple[str, str, str]] = [
    ("Min Trades", "min_trades", "total_trades"),
    ("Max Drawdown", "max_dd", "drawdown"),
    ("Min Profit Factor", "min_pf", "profit_factor"),
    ("Min Return", "min_ret", "net_profit"),
    ("Min Linearity", "min_linearity", "linearity"),
    ("Min Win Rate", "min_win_rate", "win_rate"),
    ("Min Sharpe", "min_sharpe", "sharpe"),
    ("Min Persistence", "min_persistence", "persistence"),
]


CLASS_ROWS: list[tuple[str, str, str]] = [
    ("ARCHETYPE", "archetype", "Strategy family (Reversion, Trend, Breakout, etc.)"),
    ("MECHANISM", "mechanism", "Primary signal logic"),
    ("BIAS", "bias", "Long / Short / Neutral preference"),
    ("FILTERS", "filters", "Active entry filters"),
    ("MANAGEMENT", "management", "Position-management policy"),
    ("SESSION", "session", "Active trading session window"),
    ("MARKET", "market", "Target market regime"),
]


def _fmt(value: Any, kind: str) -> tuple[str, str]:
    if value is None:
        return ("—", TEXT)
    try:
        v = float(value)
    except (TypeError, ValueError):
        return (str(value), TEXT)
    if kind == "money":
        col = GREEN if v >= 0 else RED
        return (f"${v:,.2f}", col)
    if kind == "money_neg":
        col = RED if v != 0 else TEXT
        return (f"${v:,.2f}", col)
    if kind == "pct":
        col = GREEN if v >= 0 else RED
        return (f"{v:,.2f}%", col)
    if kind == "int":
        return (f"{int(v):,}", TEXT)
    if kind == "ratio":
        return (f"{v:,.2f}", TEXT)
    return (str(value), TEXT)


class _KpiCell(QFrame):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background: {BG_2}; border: 1px solid {BORDER}; border-radius: 4px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)
        self.label = QLabel(label)
        self.label.setStyleSheet(
            f"color: {VIOLET}; font-size: 9px; font-weight: 700; letter-spacing: 1.5px;"
        )
        self.value = QLabel("—")
        f = QFont("Consolas", 16)
        f.setBold(True)
        self.value.setFont(f)
        self.value.setStyleSheet(f"color: {TEXT};")
        lay.addWidget(self.label)
        lay.addWidget(self.value)

    def set_value(self, text: str, color: str) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"color: {color};")


class StatsTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"background: {BG_1}; border: none;")
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        self._cells: dict[str, _KpiCell] = {}
        for i, (label, key, _kind) in enumerate(STATS_KPIS):
            cell = _KpiCell(label)
            row = i // 2
            col = i % 2
            grid.addWidget(cell, row, col)
            self._cells[key] = cell
        scroll.setWidget(host)
        outer.addWidget(scroll)

    def set_stats(self, stats: dict[str, Any]) -> None:
        for _label, key, kind in STATS_KPIS:
            if key not in self._cells:
                continue
            text, color = _fmt(stats.get(key), kind)
            self._cells[key].set_value(text, color)


class ScoreTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        header = QFrame()
        header.setStyleSheet(f"background: {BG_3}; border: 1px solid {BORDER};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8, 4, 8, 4)
        for text, stretch in [("CRITERION", 3), ("REQUIRED", 2), ("ACTUAL", 2), ("STATUS", 1)]:
            lab = QLabel(text)
            lab.setStyleSheet(
                f"color: {VIOLET}; font-size: 10px; font-weight: 800; letter-spacing: 1.5px;"
            )
            hl.addWidget(lab, stretch)
        outer.addWidget(header)
        self._rows: dict[str, dict[str, QLabel]] = {}
        for label, req_key, _stat_key in SCORE_ROWS:
            row = QFrame()
            row.setStyleSheet(f"background: {BG_2}; border: 1px solid {BORDER};")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(8, 6, 8, 6)
            name = QLabel(label)
            name.setStyleSheet(f"color: {TEXT}; font-size: 12px; font-weight: 600;")
            rl.addWidget(name, 3)
            req = QLabel("—")
            req.setStyleSheet(f"color: {MUTED}; font-family: Consolas; font-size: 12px;")
            rl.addWidget(req, 2)
            act = QLabel("—")
            act.setStyleSheet(f"color: {TEXT}; font-family: Consolas; font-size: 12px; font-weight: 700;")
            rl.addWidget(act, 2)
            pill = QLabel("—")
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pill.setStyleSheet(
                f"background: {MUTED}; color: {BG_0}; font-size: 10px; font-weight: 800;"
                " border-radius: 6px; padding: 2px 6px;"
            )
            rl.addWidget(pill, 1)
            outer.addWidget(row)
            self._rows[req_key] = {"req": req, "act": act, "pill": pill}
        outer.addStretch()

    def set_score(self, purge_req: dict[str, Any], stats: dict[str, Any]) -> None:
        for label, req_key, stat_key in SCORE_ROWS:
            r = self._rows.get(req_key)
            if r is None:
                continue
            req_val = purge_req.get(req_key)
            act_val = stats.get(stat_key)
            r["req"].setText("—" if req_val is None else f"{req_val}")
            r["act"].setText("—" if act_val is None else f"{act_val}")
            passed = self._evaluate(req_key, req_val, act_val)
            if req_val is None or act_val is None:
                r["pill"].setText("—")
                r["pill"].setStyleSheet(
                    f"background: {MUTED}; color: {BG_0}; font-size: 10px; font-weight: 800;"
                    " border-radius: 6px; padding: 2px 6px;"
                )
            elif passed:
                r["pill"].setText("PASS")
                r["pill"].setStyleSheet(
                    f"background: {GREEN}; color: {BG_0}; font-size: 10px; font-weight: 800;"
                    " border-radius: 6px; padding: 2px 6px;"
                )
            else:
                r["pill"].setText("FAIL")
                r["pill"].setStyleSheet(
                    f"background: {RED}; color: {BG_0}; font-size: 10px; font-weight: 800;"
                    " border-radius: 6px; padding: 2px 6px;"
                )

    @staticmethod
    def _evaluate(req_key: str, req: Any, actual: Any) -> bool:
        try:
            r = float(req)
            a = float(actual)
        except (TypeError, ValueError):
            return False
        if req_key == "max_dd":
            return abs(a) <= abs(r)
        return a >= r


class _ClassRow(QFrame):
    clicked = Signal(str, str)

    def __init__(self, label: str, key: str, tip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._key = key
        self._value = ""
        self.setStyleSheet(f"background: {BG_2}; border: 1px solid {BORDER};")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        name = QLabel(label)
        name.setStyleSheet(
            f"color: {GOLD}; font-size: 11px; font-weight: 800; letter-spacing: 1.5px;"
        )
        lay.addWidget(name, 2)
        self.value = QLabel("—")
        self.value.setStyleSheet(f"color: {TEXT}; font-size: 12px; font-weight: 600;")
        lay.addWidget(self.value, 4)
        q = QLabel("?")
        q.setToolTip(tip)
        q.setStyleSheet(
            f"color: {MUTED}; font-size: 10px; font-weight: 700; border: 1px solid {BORDER};"
            " border-radius: 7px; padding: 0px 4px;"
        )
        q.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(q, 0)

    def set_value(self, value: str) -> None:
        self._value = value
        self.value.setText(value if value else "—")

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self._value:
            self.clicked.emit(self._key, self._value)
        super().mousePressEvent(event)


class ClassTab(QWidget):
    row_clicked = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        self._rows: dict[str, _ClassRow] = {}
        for label, key, tip in CLASS_ROWS:
            row = _ClassRow(label, key, tip)
            row.clicked.connect(self.row_clicked.emit)
            outer.addWidget(row)
            self._rows[key] = row
        outer.addStretch()

    def set_class(self, d: dict[str, Any]) -> None:
        for _label, key, _tip in CLASS_ROWS:
            row = self._rows.get(key)
            if row is None:
                continue
            val = d.get(key)
            if isinstance(val, (list, tuple)):
                val = ", ".join(str(x) for x in val)
            row.set_value("" if val is None else str(val))


class TradesTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["#", "Type", "Entry", "Exit", "P&L ($)", "Ret%"])
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setStyleSheet(
            f"QTableWidget {{ background: {BG_1}; alternate-background-color: {BG_2};"
            f" color: {TEXT}; gridline-color: {MUTED}; border: 1px solid {BORDER}; }}"
            f"QHeaderView::section {{ background: {BG_3}; color: {VIOLET};"
            f" border: 1px solid {BORDER}; padding: 4px; font-weight: 800;"
            " letter-spacing: 1px; font-size: 10px; }"
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        outer.addWidget(self.table)

    def set_trades(self, trades: list[dict[str, Any]]) -> None:
        self.table.setRowCount(0)
        for t in trades:
            r = self.table.rowCount()
            self.table.insertRow(r)
            idx = t.get("idx", r + 1)
            ttype = str(t.get("type", "")).upper()
            entry = str(t.get("entry_time", ""))
            exitt = str(t.get("exit_time", ""))
            profit = t.get("profit")
            ret = t.get("ret_pct")
            self.table.setItem(r, 0, self._mk(str(idx), TEXT, Qt.AlignmentFlag.AlignCenter))
            type_color = GREEN if ttype == "BUY" else RED if ttype == "SELL" else TEXT
            self.table.setItem(r, 1, self._mk(ttype, type_color, Qt.AlignmentFlag.AlignCenter, bold=True))
            self.table.setItem(r, 2, self._mk(entry, MUTED, Qt.AlignmentFlag.AlignLeft))
            self.table.setItem(r, 3, self._mk(exitt, MUTED, Qt.AlignmentFlag.AlignLeft))
            pnl_text, pnl_col = _fmt(profit, "money")
            self.table.setItem(r, 4, self._mk(pnl_text, pnl_col, Qt.AlignmentFlag.AlignRight, bold=True))
            ret_text, ret_col = _fmt(ret, "pct")
            self.table.setItem(r, 5, self._mk(ret_text, ret_col, Qt.AlignmentFlag.AlignRight, bold=True))

    @staticmethod
    def _mk(text: str, color: str, align: Qt.AlignmentFlag, bold: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setForeground(QColor(color))
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        if bold:
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        return item


class GenomeTab(QWidget):
    """Algory-style strategy detail dump: params + active genes + flags + exit breakdown."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(6)

        # Scrollable so 48 flags fit comfortably
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {BG_1}; }}")
        container = QWidget(); container.setStyleSheet(f"background: {BG_1};")
        v = QVBoxLayout(container); v.setContentsMargins(8, 6, 8, 6); v.setSpacing(8)

        # ── Section: Active Genes (highlighted card) ──
        v.addWidget(self._section_title("⚡ ACTIVE GENES"))
        self.active_box = QLabel("—")
        self.active_box.setWordWrap(True)
        self.active_box.setStyleSheet(
            f"background: {BG_2}; color: {GOLD}; padding: 8px 10px; border-radius: 4px;"
            f" border-left: 3px solid {GOLD}; font-family: Consolas; font-size: 11px;"
            " font-weight: 700; letter-spacing: 1px;")
        v.addWidget(self.active_box)

        # ── Section: Exit Breakdown ──
        v.addWidget(self._section_title("📊 EXIT BREAKDOWN"))
        self.exit_grid = QGridLayout(); self.exit_grid.setSpacing(4)
        self.exit_box = QWidget(); self.exit_box.setLayout(self.exit_grid)
        self.exit_box.setStyleSheet(f"background: {BG_2}; padding: 8px; border-radius: 4px;")
        v.addWidget(self.exit_box)

        # ── Section: Params grid ──
        v.addWidget(self._section_title("⚙ PARAMETERS"))
        self.params_grid = QGridLayout(); self.params_grid.setSpacing(2)
        self.params_box = QWidget(); self.params_box.setLayout(self.params_grid)
        self.params_box.setStyleSheet(
            f"QWidget {{ background: {BG_2}; padding: 6px; border-radius: 4px; }}"
            f"QLabel {{ font-family: Consolas; font-size: 11px; }}")
        v.addWidget(self.params_box)

        # ── Section: All gene flags (collapsible feel) ──
        v.addWidget(self._section_title("🧬 GENE FLAGS (48 total)"))
        self.flags_grid = QGridLayout(); self.flags_grid.setSpacing(2)
        self.flags_box = QWidget(); self.flags_box.setLayout(self.flags_grid)
        self.flags_box.setStyleSheet(f"background: {BG_2}; padding: 6px; border-radius: 4px;")
        v.addWidget(self.flags_box)

        v.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _section_title(self, txt: str) -> QLabel:
        lbl = QLabel(txt)
        lbl.setStyleSheet(
            f"color: {GOLD}; font-weight: 900; letter-spacing: 2px; font-size: 11px;"
            " padding: 4px 0;")
        return lbl

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w: w.setParent(None)

    def set_genome(self, params: dict, active_genes: list, flags: dict, exit_breakdown: dict):
        # Active genes — golden chips, comma-separated
        if active_genes:
            chips = " · ".join(g.replace("use_", "").upper() for g in active_genes)
            self.active_box.setText(f"{len(active_genes)} active:\n{chips}")
        else:
            self.active_box.setText("(no active genes in this entry)")

        # Exit breakdown
        self._clear_layout(self.exit_grid)
        total = sum(exit_breakdown.values()) if exit_breakdown else 0
        if total == 0:
            self.exit_grid.addWidget(QLabel("(no exit data)"), 0, 0)
        else:
            row = 0
            for reason, count in sorted(exit_breakdown.items(), key=lambda x: -x[1]):
                pct = count * 100 / total
                color = GREEN if reason in ("TP", "TRAIL", "BREAKEVEN") else \
                        RED   if reason in ("SL",) else GOLD
                lbl_name = QLabel(reason.ljust(10))
                lbl_name.setStyleSheet(
                    f"color: {color}; font-family: Consolas; font-weight: 700; font-size: 11px;")
                lbl_count = QLabel(f"{count} ({pct:.1f}%)")
                lbl_count.setStyleSheet(
                    f"color: {TEXT}; font-family: Consolas; font-size: 11px;")
                # Bar visualization
                bar = QWidget(); bar.setFixedHeight(8)
                bar.setStyleSheet(
                    f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                    f" stop:0 {color}, stop:{pct/100:.3f} {color},"
                    f" stop:{pct/100:.3f} {BG_3}, stop:1 {BG_3});"
                    " border-radius: 4px;")
                self.exit_grid.addWidget(lbl_name,  row, 0)
                self.exit_grid.addWidget(lbl_count, row, 1)
                self.exit_grid.addWidget(bar,       row, 2)
                self.exit_grid.setColumnStretch(2, 1)
                row += 1

        # Params — 2-column grid (label : value)
        self._clear_layout(self.params_grid)
        if not params:
            self.params_grid.addWidget(QLabel("(no params)"), 0, 0)
        else:
            row = 0
            col = 0
            for k, v in sorted(params.items()):
                lbl = QLabel(k.replace("_", " ") + ":")
                lbl.setStyleSheet(f"color: {MUTED}; font-family: Consolas; font-size: 10px;")
                val_str = f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
                val_lbl = QLabel(val_str)
                val_lbl.setStyleSheet(f"color: {TEXT}; font-family: Consolas; font-size: 11px; font-weight: 700;")
                self.params_grid.addWidget(lbl,     row, col * 2)
                self.params_grid.addWidget(val_lbl, row, col * 2 + 1)
                col += 1
                if col >= 2:
                    col = 0; row += 1

        # Gene flags — 4-column compact grid (check or dim X for each of the 48)
        self._clear_layout(self.flags_grid)
        if not flags:
            self.flags_grid.addWidget(QLabel("(no flag data)"), 0, 0)
        else:
            items = sorted(flags.items())
            cols = 3
            for i, (k, v) in enumerate(items):
                row = i // cols; col = i % cols
                icon = "●" if v else "○"
                color = GOLD if v else MUTED
                lbl = QLabel(f"{icon} {k.replace('use_', '')}")
                lbl.setStyleSheet(
                    f"color: {color}; font-family: Consolas; font-size: 10px;"
                    + (" font-weight: 700;" if v else ""))
                self.flags_grid.addWidget(lbl, row, col)


class EquityCurveWidget(QWidget):
    """Algory-style equity curve: white IS line + cyan OOS line + red drawdown shade.
    Renders via QPainter on a custom canvas — no external charting library."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(f"background: {BG_1}; border: 1px solid {BORDER}; border-radius: 4px;")
        self._eq_pts: list[dict] = []
        self._oos_split_idx: int = 0   # 0 means "no split" (show all white)
        self._tooltip_text = ""

    def set_curve(self, equity_pts: list[dict], oos_split_idx: int = 0):
        self._eq_pts = equity_pts or []
        self._oos_split_idx = max(0, min(oos_split_idx, len(self._eq_pts)))
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        W, H = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 50, 14, 14, 24
        plot_w = W - pad_l - pad_r
        plot_h = H - pad_t - pad_b

        # Background
        p.fillRect(self.rect(), QColor(BG_1))

        if len(self._eq_pts) < 2:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "(no equity curve — engine didn't save trade-level data)")
            return

        eqs = [pt["eq"] for pt in self._eq_pts]
        eq_min, eq_max = min(eqs), max(eqs)
        # Track running peak for drawdown shading
        peak = eqs[0]
        dds  = []
        for eq in eqs:
            peak = max(peak, eq)
            dds.append(eq - peak)   # negative or zero
        dd_min = min(dds) if dds else 0

        # Y-axis range: include both equity AND drawdown depth so DD shows below 0
        y_top = max(eq_max, 0)
        y_bot = min(eq_min, dd_min)   # whichever is lower
        y_span = (y_top - y_bot) or 1
        # Pad by 5% top/bot for visual breathing room
        y_top += y_span * 0.05; y_bot -= y_span * 0.05
        y_span = y_top - y_bot

        n = len(self._eq_pts)
        def X(i): return pad_l + (i / max(1, n - 1)) * plot_w
        def Y(v): return pad_t + (1 - (v - y_bot) / y_span) * plot_h

        # ── Horizontal grid (3 levels) ──
        p.setPen(QPen(QColor(BORDER), 1, Qt.PenStyle.SolidLine))
        for i in range(4):
            v  = y_bot + (y_span * (3 - i) / 3)
            yp = pad_t + ((plot_h * i) / 3)
            p.drawLine(pad_l, int(yp), W - pad_r, int(yp))
            p.setPen(QColor(MUTED))
            p.setFont(QFont("Consolas", 8))
            p.drawText(2, int(yp) + 4, f"${v:.1f}")
            p.setPen(QPen(QColor(BORDER), 1))
        # Zero line — emphasized
        zero_y = Y(0)
        p.setPen(QPen(QColor(MUTED), 1, Qt.PenStyle.DashLine))
        p.drawLine(pad_l, int(zero_y), W - pad_r, int(zero_y))

        # ── Drawdown — red filled area beneath equity, above zero line ──
        dd_path = QPainterPath()
        dd_path.moveTo(X(0), zero_y)
        for i, dd in enumerate(dds):
            # plot the drawdown depth in the bottom half
            dd_path.lineTo(X(i), Y(dd))
        dd_path.lineTo(X(n - 1), zero_y)
        dd_path.closeSubpath()
        dd_grad = QLinearGradient(0, pad_t, 0, pad_t + plot_h)
        dd_grad.setColorAt(0, QColor(239, 68, 68, 0))     # transparent at top
        dd_grad.setColorAt(1, QColor(239, 68, 68, 110))   # red bottom
        p.fillPath(dd_path, QBrush(dd_grad))

        # ── IS portion (white) ──
        split = self._oos_split_idx if 0 < self._oos_split_idx < n else n
        if split > 1:
            p.setPen(QPen(QColor("#f1f5f9"), 2))
            for i in range(1, split):
                p.drawLine(int(X(i - 1)), int(Y(eqs[i - 1])),
                           int(X(i)),     int(Y(eqs[i])))
        # ── OOS portion (cyan) ──
        if split < n - 1:
            p.setPen(QPen(QColor("#22d3ee"), 2))
            for i in range(max(1, split + 1), n):
                p.drawLine(int(X(i - 1)), int(Y(eqs[i - 1])),
                           int(X(i)),     int(Y(eqs[i])))

        # ── IS/OOS split marker ──
        if 0 < split < n:
            x_split = int(X(split))
            p.setPen(QPen(QColor("#ef4444"), 1, Qt.PenStyle.DashLine))
            p.drawLine(x_split, pad_t, x_split, pad_t + plot_h)
            p.setPen(QColor("#ef4444"))
            p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            p.drawText(x_split + 3, pad_t + 12, "OOS")

        # ── Final equity dot ──
        last_x, last_y = X(n - 1), Y(eqs[-1])
        p.setBrush(QColor(GOLD))
        p.setPen(QPen(QColor(GOLD), 1))
        p.drawEllipse(QPointF(last_x, last_y), 4, 4)

        # ── Footer: stats summary ──
        p.setPen(QColor(MUTED))
        p.setFont(QFont("Consolas", 9))
        net = eqs[-1] - eqs[0]
        max_dd = abs(min(dds)) if dds else 0
        net_color = GREEN if net >= 0 else RED
        p.setPen(QColor(net_color))
        p.drawText(pad_l, H - 8,
                   f"Net: {'+' if net >= 0 else ''}${net:.2f}   ·   Max DD: ${max_dd:.2f}   ·   Trades: {n - 1}")


class InspectorPanel(QFrame):
    class_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        self.setStyleSheet(
            f"QFrame[role='card'] {{ background: {BG_1}; border: 1px solid {BORDER};"
            " border-radius: 6px; }"
            f"QTabWidget::pane {{ border: 1px solid {BORDER}; background: {BG_1}; }}"
            f"QTabBar::tab {{ background: {BG_2}; color: {MUTED}; padding: 6px 14px;"
            " font-weight: 700; letter-spacing: 1px; font-size: 10px;"
            f" border: 1px solid {BORDER}; }}"
            f"QTabBar::tab:selected {{ background: {BG_3}; color: {GOLD}; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        title = QLabel("INSPECTOR")
        title.setStyleSheet(
            f"color: {GOLD}; font-weight: 800; letter-spacing: 2px; font-size: 10px;"
        )
        outer.addWidget(title)

        # ── Compact action bar: small pill + single ⚙ menu (decluttered) ──
        from PySide6.QtWidgets import QMenu, QToolButton
        from PySide6.QtCore import QSize
        self._current_genome_id: str | None = None
        self._current_symbol:    str | None = None
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        toolbar.setContentsMargins(0, 0, 0, 0)
        self.gid_pill = QLabel("—")
        self.gid_pill.setStyleSheet(
            f"color: {MUTED}; font-family: 'JetBrains Mono','Consolas',monospace;"
            f" font-size: 9px; padding: 2px 6px;"
            f" border: 1px solid {BORDER}; border-radius: 3px;")
        toolbar.addWidget(self.gid_pill)
        toolbar.addStretch(1)
        # Single chart button (most-used) + everything else in ⚙ menu
        _btn_css = (f"QPushButton {{ background: transparent; color: {MUTED}; "
                    f"border: 1px solid {BORDER}; border-radius: 3px; "
                    f"padding: 2px 8px; font-size: 10px; font-weight: 700; }}"
                    f"QPushButton:hover {{ color: {GOLD}; border-color: {GOLD}; }}"
                    f"QPushButton:disabled {{ color: {MUTED}; opacity: 0.5; }}")
        self.btn_chart = QPushButton("📊 CHART")
        self.btn_chart.setStyleSheet(_btn_css)
        self.btn_chart.clicked.connect(self._on_open_chart)
        self.btn_chart.setEnabled(False)
        toolbar.addWidget(self.btn_chart)

        self.btn_more = QToolButton()
        self.btn_more.setText("⋮")
        self.btn_more.setStyleSheet(
            f"QToolButton {{ background: transparent; color: {MUTED}; "
            f"border: 1px solid {BORDER}; border-radius: 3px; padding: 2px 8px;"
            f" font-size: 13px; font-weight: 900; }}"
            f"QToolButton:hover {{ color: {GOLD}; border-color: {GOLD}; }}"
            f"QToolButton::menu-indicator {{ image: none; }}")
        self.btn_more.setPopupMode(QToolButton.InstantPopup)
        more_menu = QMenu(self.btn_more)
        more_menu.setStyleSheet(
            f"QMenu {{ background: {BG_2}; color: {TEXT};"
            f" border: 1px solid {BORDER}; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 14px; font-size: 11px; }}"
            f"QMenu::item:selected {{ background: {BG_3}; color: {GOLD}; }}")
        self.act_complement = more_menu.addAction("🤝  Find complement for this genome")
        self.act_complement.triggered.connect(self._on_find_complement)
        self.act_complement.setEnabled(False)
        more_menu.addSeparator()
        more_menu.addAction("🧬  Run breed round").triggered.connect(self._on_breed_round)
        more_menu.addAction("⚖  Scan asymmetry").triggered.connect(self._on_scan_asymmetry)
        self.btn_more.setMenu(more_menu)
        toolbar.addWidget(self.btn_more)
        outer.addLayout(toolbar)

        self.stats_tab  = StatsTab()
        self.score_tab  = ScoreTab()
        self.class_tab  = ClassTab()
        self.genome_tab = GenomeTab()
        self.equity_tab = EquityCurveWidget()
        self.trades_tab = TradesTab()

        self.class_tab.row_clicked.connect(self._on_class_clicked)

        # H.10: Flattened — single tab row (Algory-style), no nested STRATEGY wrapper
        self.top_tabs = QTabWidget()
        self.top_tabs.addTab(self.stats_tab,  "STATS")
        self.top_tabs.addTab(self.score_tab,  "SCORE")
        self.top_tabs.addTab(self.class_tab,  "CLASS")
        self.top_tabs.addTab(self.genome_tab, "GENOME")
        self.top_tabs.addTab(self.equity_tab, "EQUITY")
        self.top_tabs.addTab(self.trades_tab, "TRADES")

        # sub_tabs kept as alias for backwards compat (some code may reference it)
        self.sub_tabs = self.top_tabs

        outer.addWidget(self.top_tabs, 1)

    def _on_class_clicked(self, key: str, value: str) -> None:
        self.class_clicked.emit(f"{key}:{value}")

    def update_view(
        self,
        *,
        strategy: dict[str, Any],
        trades: list[dict[str, Any]],
        purge_req: dict[str, Any],
        classification: dict[str, Any],
        params: dict[str, Any] | None = None,
        active_genes: list | None = None,
        flags: dict[str, Any] | None = None,
        exit_breakdown: dict[str, Any] | None = None,
        equity_curve: list[dict] | None = None,
        oos_split_idx: int = 0,
    ) -> None:
        self.stats_tab.set_stats(strategy or {})
        self.score_tab.set_score(purge_req or {}, strategy or {})
        self.class_tab.set_class(classification or {})
        self.trades_tab.set_trades(trades or [])
        self.genome_tab.set_genome(
            params         = params or {},
            active_genes   = active_genes or [],
            flags          = flags or {},
            exit_breakdown = exit_breakdown or {},
        )
        self.equity_tab.set_curve(equity_curve or [], oos_split_idx)
        # ── Refresh genome-aware action buttons ──
        gid = (strategy or {}).get("id") or (strategy or {}).get("genome_id")
        sym = (strategy or {}).get("symbol") or self._current_symbol
        self.set_genome_context(gid, sym)

    # ── Toolbar context + slots ──
    def set_genome_context(self, genome_id: str | None, symbol: str | None) -> None:
        self._current_genome_id = (genome_id or None)
        self._current_symbol    = (symbol or None)
        has = bool(self._current_genome_id)
        self.btn_chart.setEnabled(has)
        # complement action lives on the ⋮ menu (legacy btn_complement was removed)
        if hasattr(self, "act_complement"):
            self.act_complement.setEnabled(has)
        if has:
            self.gid_pill.setText(self._current_genome_id
                                  + (f" · {symbol}" if symbol else ""))
            self.gid_pill.setStyleSheet(
                f"color: {GOLD}; font-family: 'JetBrains Mono','Consolas',monospace;"
                f" font-size: 9px; padding: 2px 6px;"
                f" border: 1px solid {GOLD}; border-radius: 3px;")
        else:
            self.gid_pill.setText("—")
            self.gid_pill.setStyleSheet(
                f"color: {MUTED}; font-family: 'JetBrains Mono','Consolas',monospace;"
                f" font-size: 9px; padding: 2px 6px;"
                f" border: 1px solid {BORDER}; border-radius: 3px;")

    def _on_open_chart(self) -> None:
        if not self._current_genome_id: return
        url = QUrl(f"http://localhost:5055/r/genome/{self._current_genome_id}")
        QDesktopServices.openUrl(url)

    def _on_find_complement(self) -> None:
        if not self._current_genome_id: return
        gid = self._current_genome_id
        import subprocess, json as _j
        try:
            r = subprocess.run(
                ["python", "-m", "r_native.genome_asymmetry", "suggest", gid],
                capture_output=True, text=True, timeout=30,
                cwd=r"C:\Users\Radhi\MT5")
            try: data = _j.loads(r.stdout)
            except Exception: data = {"ok": False, "raw": r.stdout, "err": r.stderr}
            if data.get("ok"):
                p = data["primary"]; c = data["complement"]
                msg = (f"PRIMARY  {p['id']}  ({p['specialty']}  WR {p.get('wr')})\n"
                       f"COMPLEMENT  {c['id']}  ({c['specialty']}  WR {c.get('wr')})\n\n"
                       f"Suggested deployed_genomes:\n"
                       f"{_j.dumps(data['deployed_genomes_payload'], indent=2)}\n\n"
                       f"Apply by editing symbol_configs/<sym>.json.")
                QMessageBox.information(self, f"Complement for {gid}", msg)
            else:
                reason = data.get("reason") or data.get("classification", {}).get(
                    "reasons", ["?"])[0]
                QMessageBox.warning(self, f"Complement for {gid}",
                                    f"No complement found.\n\nReason: {reason}")
        except Exception as e:
            QMessageBox.critical(self, "Find Complement failed", str(e))

    def _on_breed_round(self) -> None:
        sym = self._current_symbol
        import subprocess, json as _j
        args = ["python", "-m", "r_native.genome_lineage", "--run-once",
                "--children-per-parent", "3", "--n-bars", "3000"]
        if sym: args.extend(["--symbols", sym])
        try:
            r = subprocess.run(args, capture_output=True, text=True,
                               timeout=300, cwd=r"C:\Users\Radhi\MT5")
            try: data = _j.loads(r.stdout)
            except Exception:
                QMessageBox.warning(self, "Breed Round — raw output",
                                    (r.stdout or r.stderr or "")[:1500])
                return
            lines = [f"Lineage Breeder — processed {data.get('symbols_processed')} symbol(s)",
                     f"Deployed: {data.get('deployed_count')}   "
                     f"HoF admitted: {data.get('hof_admitted')}",
                     ""]
            for res in data.get("results", []):
                lines.append(f"  {res.get('symbol')}: top_pf={res.get('top_child_pf')} "
                             f"top_wr={res.get('top_child_wr')} "
                             f"children={res.get('children_born')} "
                             f"survivors={res.get('survivors')} "
                             f"deployed={res.get('deployed')}")
            QMessageBox.information(self, "Breed Round complete",
                                    "\n".join(lines))
        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, "Breed Round",
                                "Timed out after 5 min — check console")
        except Exception as e:
            QMessageBox.critical(self, "Breed Round failed", str(e))

    def _on_scan_asymmetry(self) -> None:
        import subprocess, json as _j
        try:
            r = subprocess.run(
                ["python", "-m", "r_native.genome_asymmetry", "scan-all"],
                capture_output=True, text=True, timeout=60,
                cwd=r"C:\Users\Radhi\MT5")
            try: data = _j.loads(r.stdout)
            except Exception:
                QMessageBox.warning(self, "Scan output",
                                    (r.stdout or r.stderr or "")[:1500])
                return
            lines = [f"Scanned {data.get('scanned')} genomes",
                     f"Protected (kept as ensemble candidates): {data.get('protected')}",
                     f"Weak: {data.get('weak')}   Unknown (too few trades): {data.get('unknown')}",
                     "",
                     "By type:"]
            for t, n in (data.get("by_type") or {}).items():
                lines.append(f"  {t}: {n}")
            if data.get("protected_ids"):
                lines.append("")
                lines.append("Protected IDs: " + ", ".join(data["protected_ids"][:20]))
            QMessageBox.information(self, "Asymmetry scan", "\n".join(lines))
        except Exception as e:
            QMessageBox.critical(self, "Scan failed", str(e))
