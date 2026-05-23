from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
                                QLabel, QTabWidget, QTableWidget, QTableWidgetItem,
                                QHeaderView, QScrollArea)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont


GOLD = "#fbbf24"
VIOLET = "#8b5cf6"
GREEN = "#10b981"
RED = "#ef4444"
TEXT = "#f1f5f9"
MUTED = "#94a3b8"
BG_0 = "#060418"
BG_1 = "#0d0824"
BG_2 = "#14092e"
BG_3 = "#1c1142"
BORDER = "#2d1b69"


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
            " letter-spacing: 1px; font-size: 10px; }}"
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


class InspectorPanel(QFrame):
    class_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        self.setStyleSheet(
            f"QFrame[role='card'] {{ background: {BG_1}; border: 1px solid {BORDER};"
            " border-radius: 6px; }}"
            f"QTabWidget::pane {{ border: 1px solid {BORDER}; background: {BG_1}; }}"
            f"QTabBar::tab {{ background: {BG_2}; color: {MUTED}; padding: 6px 14px;"
            " font-weight: 700; letter-spacing: 1px; font-size: 10px;"
            f" border: 1px solid {BORDER}; }}"
            f"QTabBar::tab:selected {{ background: {BG_3}; color: {GOLD}; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 12, 10, 12)
        outer.setSpacing(8)

        title = QLabel("INSPECTOR")
        title.setStyleSheet(
            f"color: {GOLD}; font-weight: 900; letter-spacing: 2px; font-size: 13px;"
        )
        outer.addWidget(title)

        self.stats_tab = StatsTab()
        self.score_tab = ScoreTab()
        self.class_tab = ClassTab()
        self.trades_tab = TradesTab()

        self.class_tab.row_clicked.connect(self._on_class_clicked)

        self.top_tabs = QTabWidget()
        self.top_tabs.addTab(self.stats_tab, "STATS")
        self.top_tabs.addTab(self.score_tab, "SCORE")
        self.top_tabs.addTab(self.class_tab, "CLASS")

        self.sub_tabs = QTabWidget()
        self.sub_tabs.addTab(self.top_tabs, "STRATEGY")
        self.sub_tabs.addTab(self.trades_tab, "TRADES")

        outer.addWidget(self.sub_tabs, 1)

    def _on_class_clicked(self, key: str, value: str) -> None:
        self.class_clicked.emit(f"{key}:{value}")

    def update_view(
        self,
        *,
        strategy: dict[str, Any],
        trades: list[dict[str, Any]],
        purge_req: dict[str, Any],
        classification: dict[str, Any],
    ) -> None:
        self.stats_tab.set_stats(strategy or {})
        self.score_tab.set_score(purge_req or {}, strategy or {})
        self.class_tab.set_class(classification or {})
        self.trades_tab.set_trades(trades or [])
