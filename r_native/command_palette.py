"""r_native/command_palette.py — ⌘K command palette (VS Code-style).

Born 2026-05-30: "نظام احترافي غير عادي". Ctrl+K anywhere in R Native opens a
fuzzy-searchable palette of every navigation target and action — switch tabs,
RUN/PAUSE/STOP the executor, open Settings/Vault/Terminal — without hunting
through the UI. Type (Arabic or English), Enter to execute, Esc to dismiss.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QLabel)
from PySide6.QtCore import Qt

GOLD, TEXT, MUTED = "#fbbf24", "#f1f5f9", "#94a3b8"
BG_1, BG_2, BORDER = "#13131a", "#1a1a23", "#2d2d3a"


class CommandPalette(QDialog):
    """Frameless fuzzy launcher. commands = [(label, callback), ...]."""

    def __init__(self, parent, commands: list[tuple[str, Callable]]):
        super().__init__(parent)
        self._commands = commands
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setModal(True)
        self.setFixedWidth(560)
        self.setStyleSheet(
            f"QDialog {{ background:{BG_1}; border:1px solid {GOLD};"
            f" border-radius:10px; }}")

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        self.input = QLineEdit()
        self.input.setPlaceholderText("⌘ اكتب أمر أو تبويب…  (Enter تنفيذ · Esc إغلاق)")
        self.input.setStyleSheet(
            f"QLineEdit {{ background:{BG_2}; color:{TEXT}; border:1px solid {BORDER};"
            f" border-radius:6px; padding:8px 12px; font-size:14px; }}")
        self.input.textChanged.connect(self._filter)
        v.addWidget(self.input)

        self.listw = QListWidget()
        self.listw.setStyleSheet(
            f"QListWidget {{ background:{BG_1}; color:{TEXT}; border:none;"
            f" font-size:13px; }}"
            f"QListWidget::item {{ padding:6px 10px; border-radius:6px; }}"
            f"QListWidget::item:selected {{ background:{BG_2}; color:{GOLD}; }}")
        self.listw.itemActivated.connect(self._run_item)
        v.addWidget(self.listw)

        hint = QLabel("↑↓ تنقّل · Enter تنفيذ · Esc إغلاق")
        hint.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)

        self._filter("")
        self.input.setFocus()

    # ── behaviour ────────────────────────────────────────────────────────────
    def _filter(self, text: str) -> None:
        text = (text or "").strip().lower()
        self.listw.clear()
        for label, cb in self._commands:
            if not text or all(w in label.lower() for w in text.split()):
                it = QListWidgetItem(label)
                it.setData(Qt.UserRole, cb)
                self.listw.addItem(it)
        if self.listw.count():
            self.listw.setCurrentRow(0)
        self.listw.setFixedHeight(min(10, max(1, self.listw.count())) * 34 + 8)

    def _run_item(self, item: QListWidgetItem) -> None:
        cb = item.data(Qt.UserRole)
        self.accept()
        if callable(cb):
            cb()

    def keyPressEvent(self, e):  # noqa: N802 — Qt override
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            it = self.listw.currentItem()
            if it:
                self._run_item(it)
            return
        if e.key() in (Qt.Key_Down, Qt.Key_Up):
            row = self.listw.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
            self.listw.setCurrentRow(max(0, min(self.listw.count() - 1, row)))
            return
        super().keyPressEvent(e)

    def showEvent(self, e):  # noqa: N802 — center over parent
        if self.parent():
            g = self.parent().geometry()
            self.move(g.center().x() - self.width() // 2, g.top() + 120)
        super().showEvent(e)


__all__ = ["CommandPalette"]
