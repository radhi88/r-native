"""Professional realtime Qader dashboard widgets."""
from __future__ import annotations

import json
import webbrowser
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QPointF, QRectF, QTimer, Qt, QUrl
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qader_app.paths import app_root, logs_dir


class _MetricCard(QFrame):
    def __init__(self, title: str, value: str = "-", accent: str = "#38bdf8"):
        super().__init__()
        self.title = QLabel(title)
        self.value = QLabel(value)
        self.title.setObjectName("cardTitle")
        self.value.setObjectName("cardValue")
        self._accent = accent
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        self.setStyleSheet(f"border-left:3px solid {self._accent};")

    def set_value(self, value: Any) -> None:
        self.value.setText(str(value))


class _LiveChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[dict[str, Any]] = []
        self.setMinimumHeight(260)

    def set_points(self, points: list[dict[str, Any]]) -> None:
        self._points = points[-180:]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(14, 12, -14, -14)
        painter.fillRect(self.rect(), QColor("#06111f"))
        if rect.width() <= 20 or rect.height() <= 20:
            return

        gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
        gradient.setColorAt(0, QColor(15, 27, 45, 240))
        gradient.setColorAt(1, QColor(2, 6, 23, 240))
        painter.fillRect(rect, gradient)
        painter.setPen(QPen(QColor("#1f2a44"), 1))
        painter.drawRoundedRect(QRectF(rect), 8, 8)

        plot = rect.adjusted(54, 20, -18, -36)
        painter.setPen(QPen(QColor("#17233a"), 1))
        for idx in range(5):
            y = plot.top() + idx * plot.height() / 4
            painter.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
        for idx in range(6):
            x = plot.left() + idx * plot.width() / 5
            painter.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

        points = [p for p in self._points if float(p.get("mid", 0.0) or 0.0) > 0]
        if len(points) < 2:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Waiting for live chart data")
            return

        prices = [float(p.get("mid", 0.0) or 0.0) for p in points]
        lo = min(prices)
        hi = max(prices)
        if hi - lo < 0.01:
            lo -= 0.01
            hi += 0.01

        def xy(index: int, value: float) -> QPointF:
            x = plot.left() + (index / max(1, len(points) - 1)) * plot.width()
            y = plot.bottom() - ((value - lo) / (hi - lo)) * plot.height()
            return QPointF(x, y)

        price_path = QPainterPath(xy(0, prices[0]))
        for idx, value in enumerate(prices[1:], start=1):
            price_path.lineTo(xy(idx, value))
        painter.setPen(QPen(QColor("#22d3ee"), 2.4))
        painter.drawPath(price_path)

        conf_path = QPainterPath()
        for idx, point in enumerate(points):
            conf = max(0.0, min(1.0, float(point.get("confidence", 0.0) or 0.0)))
            x = plot.left() + (idx / max(1, len(points) - 1)) * plot.width()
            y = plot.bottom() - conf * plot.height()
            if idx == 0:
                conf_path.moveTo(x, y)
            else:
                conf_path.lineTo(x, y)
        painter.setPen(QPen(QColor("#f59e0b"), 1.8, Qt.PenStyle.DashLine))
        painter.drawPath(conf_path)

        for idx, point in enumerate(points[-40:], start=max(0, len(points) - 40)):
            action = str(point.get("arbiter_result") or point.get("final_action") or "HOLD")
            if action not in {"BUY", "SELL"}:
                continue
            pos = xy(idx, float(point.get("mid", 0.0) or 0.0))
            color = QColor("#34d399") if action == "BUY" else QColor("#ef4444")
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#020617"), 1))
            painter.drawEllipse(pos, 4.5, 4.5)

        latest = points[-1]
        painter.setPen(QColor("#e2e8f0"))
        painter.drawText(rect.adjusted(12, 6, -12, -6), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, "Live XAUUSDm M1 price / confidence")
        painter.setPen(QColor("#94a3b8"))
        painter.drawText(rect.adjusted(12, 6, -12, -6), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight, f"mid {float(latest.get('mid', 0.0)):.3f} | conf {float(latest.get('confidence', 0.0)):.3f}")
        painter.drawText(int(rect.left() + 10), int(plot.top() + 12), f"{hi:.3f}")
        painter.drawText(int(rect.left() + 10), int(plot.bottom()), f"{lo:.3f}")
        painter.setPen(QColor("#22d3ee"))
        painter.drawText(int(plot.left()), int(rect.bottom() - 10), "price")
        painter.setPen(QColor("#f59e0b"))
        painter.drawText(int(plot.left() + 58), int(rect.bottom() - 10), "confidence")


class DashboardView(QWidget):
    def __init__(self, loop_service=None, parent=None):
        super().__init__(parent)
        self.loop_service = loop_service
        self._pulse = False
        self._state_path = app_root() / "dashboard" / "qader_live_state.json"
        self._loop_log_path = logs_dir() / "qader_realtime_loop.jsonl"
        self._audit_log_path = logs_dir() / "qader_audit.jsonl"
        self._journal_path = logs_dir() / "live_performance_journal.jsonl"

        self.status_label = QLabel("Qader realtime: standby")
        self.status_label.setObjectName("statusBanner")
        self.mt5_label = QLabel("MT5: not checked")
        self.mode_label = QLabel("Mode: observe_only")
        self.safety_label = QLabel("Safety: DEMO_ONLY")
        self.demo_badge = QLabel("DEMO ONLY")
        self.data_badge = QLabel("DATA: WAITING")
        self.autostart_badge = QLabel("AUTO-START: CHECKING")
        for badge in (self.demo_badge, self.data_badge, self.autostart_badge):
            badge.setObjectName("badge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.emergency_button = QPushButton("Emergency Stop")
        self.pause_button = QPushButton("Pause Loop")
        self.resume_button = QPushButton("Resume Loop")
        self.stop_entries_button = QPushButton("Stop New Entries")
        self.open_dashboard_button = QPushButton("Open HTML Dashboard")
        self.emergency_button.setObjectName("dangerButton")
        self.stop_entries_button.setObjectName("warnButton")

        self.cards = {
            "cycle": _MetricCard("Cycle Counter", "0", "#22d3ee"),
            "trades": _MetricCard("Trade Counter", "0", "#10b981"),
            "managed": _MetricCard("Managed Trades", "0", "#a78bfa"),
            "confidence": _MetricCard("Confidence", "0.000", "#f59e0b"),
            "heartbeat": _MetricCard("System Heartbeat", "-", "#ef4444"),
            "spread": _MetricCard("Spread", "-", "#38bdf8"),
        }

        self.risk_meter = QProgressBar()
        self.risk_meter.setRange(0, 100)
        self.risk_meter.setValue(0)
        self.risk_meter.setFormat("Risk meter: %p%")
        self.live_chart = _LiveChartWidget()

        self.account_text = QLabel("Login: -\nServer: -\nBalance: -\nEquity: -")
        self.account_text.setObjectName("panelText")

        self.scanner_table = self._table(["Cycle", "Symbol", "TF", "Bid", "Ask", "Spread", "Bars", "Action"])
        self.positions_table = self._table(["Ticket", "Symbol", "Side", "Volume", "Profit", "SL", "TP", "Status"])
        self.closed_table = self._table(["Time", "Symbol", "Action", "P/L", "Spread", "ATR", "Reason"])

        self.signal_cards = QLabel("Fractal: -\nSMC: -\nICT: -")
        self.signal_cards.setObjectName("panelText")
        self.arbiter_panel = QLabel("Decision: HOLD\nConfidence: 0.000\nReason: -")
        self.arbiter_panel.setObjectName("panelText")
        self.dna_panel = QLabel("Strategy DNA: collecting demo samples\nDNA application: guarded\nSource self-modification: disabled")
        self.dna_panel.setObjectName("panelText")
        self.logs_console = QPlainTextEdit()
        self.logs_console.setReadOnly(True)
        self.logs_console.setMaximumBlockCount(400)

        top = QHBoxLayout()
        top.addWidget(self.status_label, 4)
        top.addWidget(self.demo_badge, 1)
        top.addWidget(self.data_badge, 1)
        top.addWidget(self.autostart_badge, 1)

        buttons = QHBoxLayout()
        for button in (
            self.pause_button,
            self.resume_button,
            self.stop_entries_button,
            self.open_dashboard_button,
            self.emergency_button,
        ):
            buttons.addWidget(button)

        metrics = QGridLayout()
        for idx, card in enumerate(self.cards.values()):
            metrics.addWidget(card, idx // 3, idx % 3)

        left = QVBoxLayout()
        left.addLayout(metrics)
        left.addWidget(self._panel("Live Account", self.account_text))
        left.addWidget(self._panel("Risk Meter", self.risk_meter))
        left.addWidget(self._panel("Realtime Signal Cards", self.signal_cards))
        left.addWidget(self._panel("SignalArbiter Decision", self.arbiter_panel))
        left.addWidget(self._panel("Strategy DNA", self.dna_panel))

        right = QVBoxLayout()
        right.addWidget(self._panel("Realtime Price / Signal Chart", self.live_chart))
        right.addWidget(self._panel("Live Market Scanner", self.scanner_table))
        right.addWidget(self._panel("Position Management", self.positions_table))
        right.addWidget(self._panel("Closed Trades Journal", self.closed_table))
        right.addWidget(self._panel("Logs Console", self.logs_console))

        left_widget = QWidget()
        left_widget.setLayout(left)
        right_widget = QWidget()
        right_widget.setLayout(right)
        splitter = QSplitter()
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(buttons)
        layout.addWidget(splitter, 1)

        self.open_dashboard_button.clicked.connect(self.open_html_dashboard)
        self._apply_theme()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_live_state)
        self.timer.start(1000)

    def _panel(self, title: str, widget: QWidget) -> QGroupBox:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.addWidget(widget)
        return box

    def _table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return table

    def _apply_theme(self) -> None:
        self.setStyleSheet("""
            QWidget { background:#050816; color:#dbeafe; font-family: Segoe UI, Arial; font-size:12px; }
            QGroupBox {
                border:1px solid #1f2a44; border-radius:8px; margin-top:12px;
                padding:12px; background:#0b1222;
            }
            QGroupBox::title { subcontrol-origin: margin; left:12px; padding:0 6px; color:#67e8f9; font-weight:700; }
            QFrame { background:#0b1222; border:1px solid #1f2a44; border-radius:8px; }
            QLabel#statusBanner {
                background:#0f172a; border:1px solid #22d3ee; border-radius:8px;
                padding:10px; font-size:17px; font-weight:800; color:#e0f2fe;
            }
            QLabel#badge {
                background:#111827; border:1px solid #334155; border-radius:8px;
                padding:8px; font-weight:800; color:#a7f3d0;
            }
            QLabel#panelText { color:#bfdbfe; line-height:140%; }
            QLabel#cardTitle { color:#94a3b8; font-weight:700; text-transform:uppercase; }
            QLabel#cardValue { color:#f8fafc; font-size:24px; font-weight:900; }
            QPushButton {
                background:#102033; border:1px solid #245071; border-radius:6px;
                padding:8px 10px; color:#e0f2fe; font-weight:700;
            }
            QPushButton:hover { background:#153a56; border-color:#38bdf8; }
            QPushButton#dangerButton { background:#7f1d1d; border-color:#ef4444; color:#fff1f2; }
            QPushButton#warnButton { background:#713f12; border-color:#f59e0b; color:#fffbeb; }
            QTableWidget {
                background:#06111f; alternate-background-color:#0c1b2e;
                border:1px solid #1f2a44; gridline-color:#1f2a44; color:#dbeafe;
            }
            QHeaderView::section { background:#111827; color:#93c5fd; border:0; padding:6px; font-weight:800; }
            QPlainTextEdit { background:#020617; border:1px solid #1f2a44; border-radius:6px; color:#a7f3d0; }
            QProgressBar { border:1px solid #1f2a44; border-radius:6px; text-align:center; background:#020617; color:#e0f2fe; }
            QProgressBar::chunk { border-radius:5px; background:#22c55e; }
            QSplitter::handle { background:#1f2a44; }
        """)

    def set_loop_service(self, service) -> None:
        self.loop_service = service

    def set_status(self, mt5_status: str, mode: str, safety: str) -> None:
        self.mt5_label.setText(f"MT5: {mt5_status}")
        self.mode_label.setText(f"Mode: {mode}")
        self.safety_label.setText(f"Safety: {safety}")
        self.status_label.setText(f"Qader realtime: {mt5_status} | {mode} | {safety}")

    def refresh_live_state(self) -> None:
        state = self._read_state()
        latest = state.get("latest_record", {})
        loop = state.get("loop", {})
        self._pulse = not self._pulse
        pulse_color = "#22d3ee" if self._pulse else "#0ea5e9"
        self.status_label.setStyleSheet(f"border-color:{pulse_color};")
        self.cards["cycle"].set_value(loop.get("cycle_count", latest.get("cycle_number", 0)))
        self.cards["trades"].set_value(loop.get("demo_trades_opened", 0))
        self.cards["managed"].set_value(loop.get("demo_trades_managed", 0))
        self.cards["confidence"].set_value(f"{float(latest.get('confidence', 0) or 0):.3f}")
        self.cards["heartbeat"].set_value(state.get("timestamp", "-"))
        self.cards["spread"].set_value(latest.get("spread", "-"))

        action = str(latest.get("final_action", "HOLD"))
        bars = int(latest.get("bars_received", 0) or 0)
        self.data_badge.setText("DATA: OK" if bars > 0 else "DATA: WAITING")
        self.demo_badge.setText("DEMO ONLY")
        self.autostart_badge.setText("AUTO-START: " + ("RUNNING" if loop.get("thread_alive") else "READY"))
        self.risk_meter.setValue(self._risk_value(latest))
        self.signal_cards.setText(
            f"Fractal: {latest.get('fractal_result', '-')}\n"
            f"SMC: {latest.get('smc_result', '-')}\n"
            f"ICT: {latest.get('ict_result', '-')}"
        )
        self.arbiter_panel.setText(
            f"Decision: {action}\n"
            f"Confidence: {float(latest.get('confidence', 0) or 0):.3f}\n"
            f"Risk: {latest.get('risk_status', '-')}\n"
            f"Execution: {latest.get('execution_status', '-')}\n"
            f"Reason: {latest.get('reason', '-')}"
        )
        learning = state.get("learning_state", {}) if isinstance(state, dict) else {}
        application = learning.get("application", {}) if isinstance(learning, dict) else {}
        dna_status = "applied" if application.get("applied") else str(application.get("reason") or learning.get("strategy_dna_modification") or "guarded")
        self.dna_panel.setText(
            "Strategy DNA: live demo journal active\n"
            f"Samples: {loop.get('demo_trades_opened', 0)}\n"
            f"DNA application: {dna_status}\n"
            "Source self-modification: disabled"
        )
        self.live_chart.set_points(self._chart_points(state, latest))
        self._update_scanner(latest)
        self._update_positions(latest)
        self._update_closed_trades()
        self._update_logs()

    def _risk_value(self, latest: dict[str, Any]) -> int:
        risk = str(latest.get("risk_status", ""))
        if risk == "approved":
            return 28
        if "blocked" in risk:
            return 82
        if latest.get("final_action") in ("BUY", "SELL"):
            return 45
        return 12

    def _read_state(self) -> dict[str, Any]:
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        if self._loop_log_path.exists():
            try:
                line = self._loop_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-1]
                return {"timestamp": "-", "loop": self.loop_service.status() if self.loop_service else {}, "latest_record": json.loads(line)}
            except Exception:
                pass
        return {"timestamp": "-", "loop": self.loop_service.status() if self.loop_service else {}, "latest_record": {}}

    def _chart_points(self, state: dict[str, Any], latest: dict[str, Any]) -> list[dict[str, Any]]:
        history = state.get("chart_history")
        if isinstance(history, list) and history:
            return [p for p in history if isinstance(p, dict)]
        points = self._read_recent_chart_points(140)
        if points:
            return points
        if latest:
            bid = float(latest.get("bid", 0.0) or 0.0)
            ask = float(latest.get("ask", 0.0) or 0.0)
            if bid > 0 and ask > 0:
                return [{
                    "timestamp": latest.get("timestamp", ""),
                    "cycle_number": latest.get("cycle_number", 0),
                    "bid": bid,
                    "ask": ask,
                    "mid": (bid + ask) / 2.0,
                    "spread": latest.get("spread", 0),
                    "confidence": latest.get("confidence", 0),
                    "final_action": latest.get("final_action", "HOLD"),
                    "arbiter_result": latest.get("arbiter_result", "HOLD"),
                }]
        return []

    def _read_recent_chart_points(self, limit: int) -> list[dict[str, Any]]:
        if not self._loop_log_path.exists():
            return []
        points: list[dict[str, Any]] = []
        try:
            for line in self._loop_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit * 2:]:
                row = json.loads(line)
                if "bid" not in row or "ask" not in row:
                    continue
                bid = float(row.get("bid", 0.0) or 0.0)
                ask = float(row.get("ask", 0.0) or 0.0)
                if bid <= 0 or ask <= 0:
                    continue
                points.append({
                    "timestamp": row.get("timestamp", ""),
                    "cycle_number": row.get("cycle_number", 0),
                    "bid": bid,
                    "ask": ask,
                    "mid": (bid + ask) / 2.0,
                    "spread": row.get("spread", 0),
                    "confidence": row.get("confidence", 0),
                    "final_action": row.get("final_action", "HOLD"),
                    "arbiter_result": row.get("arbiter_result", "HOLD"),
                })
        except Exception:
            return []
        return points[-limit:]

    def _update_scanner(self, latest: dict[str, Any]) -> None:
        if not latest:
            return
        row = [
            latest.get("cycle_number", "-"),
            latest.get("symbol", "-"),
            latest.get("timeframe", "-"),
            latest.get("bid", "-"),
            latest.get("ask", "-"),
            latest.get("spread", "-"),
            latest.get("bars_received", "-"),
            latest.get("final_action", "-"),
        ]
        self._append_table_row(self.scanner_table, row, max_rows=30)

    def _update_positions(self, latest: dict[str, Any]) -> None:
        self.positions_table.setRowCount(1)
        row = [
            "-",
            latest.get("symbol", "-"),
            latest.get("final_action", "-"),
            "-",
            "-",
            latest.get("risk_status", "-"),
            latest.get("execution_status", "-"),
            f"open={latest.get('open_positions', 0)}",
        ]
        for col, value in enumerate(row):
            self.positions_table.setItem(0, col, QTableWidgetItem(str(value)))

    def _update_closed_trades(self) -> None:
        if not self._journal_path.exists():
            return
        try:
            rows = []
            for line in self._journal_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]:
                item = json.loads(line)
                if item.get("event") in {"demo_trade_entry", "opposite_signal_exit", "position_management_order_result"}:
                    rows.append([
                        item.get("timestamp", "-"),
                        item.get("symbol", "-"),
                        item.get("action", item.get("event", "-")),
                        item.get("profit", "-"),
                        item.get("spread", "-"),
                        item.get("atr", "-"),
                        item.get("reason", item.get("message", "-")),
                    ])
            self.closed_table.setRowCount(0)
            for row in rows[-12:]:
                self._append_table_row(self.closed_table, row, max_rows=12)
        except Exception:
            return

    def _update_logs(self) -> None:
        paths = [self._loop_log_path, self._audit_log_path]
        lines: list[str] = []
        for path in paths:
            if path.exists():
                lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines()[-8:])
        text = "\n".join(lines[-16:])
        if text and text != self.logs_console.toPlainText():
            self.logs_console.setPlainText(text)
            self.logs_console.verticalScrollBar().setValue(self.logs_console.verticalScrollBar().maximum())

    def _append_table_row(self, table: QTableWidget, values: list[Any], max_rows: int) -> None:
        while table.rowCount() >= max_rows:
            table.removeRow(0)
        row_idx = table.rowCount()
        table.insertRow(row_idx)
        for col, value in enumerate(values[: table.columnCount()]):
            table.setItem(row_idx, col, QTableWidgetItem(str(value)))

    def open_html_dashboard(self) -> None:
        path = app_root() / "dashboard" / "qader_live_dashboard.html"
        if path.exists():
            webbrowser.open(path.resolve().as_uri())


class WebDashboardView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        path = app_root() / "dashboard" / "qader_live_dashboard.html"
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
        except Exception:
            label = QLabel(f"PyQt6 WebEngine is not installed.\nOpen: {path}")
            label.setWordWrap(True)
            layout.addWidget(label)
            return

        view = QWebEngineView()
        if path.exists():
            view.load(QUrl.fromLocalFile(str(path.resolve())))
        layout.addWidget(view)
