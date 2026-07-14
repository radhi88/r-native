"""Market scanner table."""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from qader_app.services.scanner_service import ScannerService
from qader_app.storage.settings_store import SettingsStore


class ScannerView(QWidget):
    HEADERS = [
        "symbol",
        "timeframe",
        "fractal_result",
        "smc_result",
        "arbiter_result",
        "confidence",
        "risk_status",
        "spread",
        "atr",
        "final_action",
        "reason",
    ]

    def __init__(self, scanner: ScannerService | None = None, parent=None):
        super().__init__(parent)
        self.scanner = scanner or ScannerService()
        self.settings = SettingsStore()
        self.status = QLabel("Live market scanner: ready")
        self.scan_button = QPushButton("Scan now")
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.scan_button.clicked.connect(self.scan_now)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.scan_button)
        layout.addWidget(self.table)
        self.setStyleSheet("""
            QWidget { background:#050816; color:#dbeafe; font-family: Segoe UI, Arial; }
            QLabel { background:#0f172a; border:1px solid #1f2a44; border-radius:8px; padding:8px; color:#67e8f9; font-weight:800; }
            QPushButton { background:#102033; border:1px solid #245071; border-radius:6px; padding:8px; color:#e0f2fe; font-weight:700; }
            QPushButton:hover { background:#153a56; border-color:#38bdf8; }
            QTableWidget { background:#06111f; alternate-background-color:#0c1b2e; border:1px solid #1f2a44; gridline-color:#1f2a44; color:#dbeafe; }
            QHeaderView::section { background:#111827; color:#93c5fd; border:0; padding:6px; font-weight:800; }
        """)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.scan_now)
        self.timer.start(5000)

    def scan_now(self) -> list[dict]:
        settings = self.settings.load()
        rows = self.scanner.scan_symbols(
            settings.get("selected_symbols", ["XAUUSDm"]),
            settings.get("selected_timeframes", ["M1"]),
        )
        self.set_rows(rows)
        self.status.setText(f"Live market scanner: {len(rows)} rows")
        return rows

    def set_rows(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(self.HEADERS):
                item = QTableWidgetItem(str(row.get(key, "")))
                action = str(row.get("final_action", ""))
                risk = str(row.get("risk_status", ""))
                if action == "BUY":
                    item.setBackground(QColor("#064e3b"))
                elif action == "SELL":
                    item.setBackground(QColor("#7f1d1d"))
                elif "blocked" in risk:
                    item.setBackground(QColor("#713f12"))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
