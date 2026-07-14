"""terminal_widget.py — embedded interactive terminal panel for R Native.

A real shell living *inside* the desktop app — no separate console window.
Backed by a persistent QProcess running PowerShell, so working directory and
environment persist between commands (just like a normal terminal).

Used as a docked side-panel ("شاشة تيرنمال جانبي") in app.py:

    from r_native.terminal_widget import EmbeddedTerminal
    term = EmbeddedTerminal(cwd=PROJECT_ROOT)
    dock = QDockWidget("TERMINAL", self)
    dock.setWidget(term)
    self.addDockWidget(Qt.RightDockWidgetArea, dock)

Features
  • Live stdout/stderr streaming (merged channels, no blocking)
  • Persistent session — cd / $env survive across commands
  • Command history (↑/↓), Ctrl+L clear, Ctrl+C interrupt
  • Quick-command chips for common R Native ops
  • ANSI-free monospace output styled to match the app theme
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
                               QLineEdit, QPushButton, QLabel, QComboBox, QFrame)
from PySide6.QtCore import Qt, QProcess, Signal
from PySide6.QtGui import QFont, QTextCursor, QKeyEvent

# ─── Local theme constants (avoid circular import with app.py) ───
_BG_0   = "#070710"
_BG_1   = "#13131a"
_BG_2   = "#1a1a23"
_BORDER = "#26262f"
_TEXT   = "#d4d4dc"
_MUTED  = "#9494a0"
_GOLD   = "#f5a524"
_GREEN  = "#22c55e"
_RED    = "#ef4444"
_CYAN   = "#06b6d4"


class _CommandLine(QLineEdit):
    """Input line with ↑/↓ history recall and Ctrl+L / Ctrl+C hooks."""
    clear_requested  = Signal()
    interrupt_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: list[str] = []
        self._hist_idx = 0

    def remember(self, cmd: str) -> None:
        if cmd and (not self._history or self._history[-1] != cmd):
            self._history.append(cmd)
        self._hist_idx = len(self._history)

    def keyPressEvent(self, ev: QKeyEvent) -> None:
        if ev.key() == Qt.Key_Up:
            if self._history:
                self._hist_idx = max(0, self._hist_idx - 1)
                self.setText(self._history[self._hist_idx])
            return
        if ev.key() == Qt.Key_Down:
            if self._history:
                self._hist_idx = min(len(self._history), self._hist_idx + 1)
                self.setText(self._history[self._hist_idx]
                             if self._hist_idx < len(self._history) else "")
            return
        if ev.key() == Qt.Key_L and ev.modifiers() & Qt.ControlModifier:
            self.clear_requested.emit()
            return
        if ev.key() == Qt.Key_C and ev.modifiers() & Qt.ControlModifier and not self.selectedText():
            self.interrupt_requested.emit()
            return
        super().keyPressEvent(ev)


class EmbeddedTerminal(QWidget):
    """Self-contained interactive terminal panel backed by a live PowerShell."""

    def __init__(self, cwd: str | Path | None = None, parent=None):
        super().__init__(parent)
        self._cwd = str(cwd) if cwd else os.getcwd()
        self._proc: QProcess | None = None
        self._build_ui()
        self._start_shell()

    # ── UI ──
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Header row: title + cwd + controls
        head = QHBoxLayout(); head.setSpacing(6)
        title = QLabel("▌ TERMINAL")
        title.setStyleSheet(
            f"color: {_GOLD}; font-weight: 800; font-size: 11px; letter-spacing: 1.5px;")
        head.addWidget(title)
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        head.addWidget(self._status_dot)
        head.addStretch()

        clear_btn = QPushButton("CLEAR")
        clear_btn.setFixedHeight(22)
        clear_btn.clicked.connect(self.clear_output)
        head.addWidget(clear_btn)
        restart_btn = QPushButton("⟳ RESTART")
        restart_btn.setFixedHeight(22)
        restart_btn.clicked.connect(self._restart_shell)
        head.addWidget(restart_btn)
        for b in (clear_btn, restart_btn):
            b.setStyleSheet(
                f"QPushButton {{ background: {_BG_2}; color: {_MUTED};"
                f" border: 1px solid {_BORDER}; border-radius: 5px;"
                f" padding: 2px 10px; font-size: 9px; font-weight: 700; }}"
                f"QPushButton:hover {{ color: {_GOLD}; border-color: {_GOLD}; }}")
        root.addLayout(head)

        # Output console
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(5000)   # ring buffer — never unbounded
        self.output.setStyleSheet(
            f"QPlainTextEdit {{ background: {_BG_0}; color: {_TEXT};"
            f" border: 1px solid {_BORDER}; border-radius: 8px; padding: 8px;"
            f" font-family: 'JetBrains Mono','Cascadia Code','Consolas',monospace;"
            f" font-size: 11px; line-height: 1.45; }}")
        root.addWidget(self.output, 1)

        # Quick-command chips
        chips = QHBoxLayout(); chips.setSpacing(4)
        chip_lbl = QLabel("QUICK")
        chip_lbl.setStyleSheet(f"color: {_MUTED}; font-size: 8px; letter-spacing: 1px;")
        chips.addWidget(chip_lbl)
        self._quick = QComboBox()
        self._quick.addItem("— select a command —", "")
        for label, cmd in self._quick_commands():
            self._quick.addItem(label, cmd)
        self._quick.setStyleSheet(
            f"QComboBox {{ background: {_BG_2}; color: {_TEXT};"
            f" border: 1px solid {_BORDER}; border-radius: 6px;"
            f" padding: 3px 8px; font-size: 10px; }}")
        self._quick.activated.connect(self._on_quick_selected)
        chips.addWidget(self._quick, 1)
        root.addLayout(chips)

        # Input row
        inp = QHBoxLayout(); inp.setSpacing(4)
        self._prompt = QLabel("❯")
        self._prompt.setStyleSheet(
            f"color: {_GREEN}; font-weight: 900; font-size: 14px;"
            f" font-family: Consolas;")
        inp.addWidget(self._prompt)
        self.cmd = _CommandLine()
        self.cmd.setPlaceholderText("type a command and press Enter  ·  ↑↓ history  ·  Ctrl+L clear  ·  Ctrl+C stop")
        self.cmd.setStyleSheet(
            f"QLineEdit {{ background: {_BG_1}; color: {_TEXT};"
            f" border: 1px solid {_BORDER}; border-radius: 8px;"
            f" padding: 7px 10px; font-family: 'Consolas',monospace; font-size: 12px; }}"
            f"QLineEdit:focus {{ border-color: {_GOLD}; }}")
        self.cmd.returnPressed.connect(self._run_current)
        self.cmd.clear_requested.connect(self.clear_output)
        self.cmd.interrupt_requested.connect(self._interrupt)
        inp.addWidget(self.cmd, 1)
        send = QPushButton("RUN")
        send.setStyleSheet(
            f"QPushButton {{ background: {_GOLD}; color: {_BG_0};"
            f" border: none; border-radius: 8px; padding: 7px 16px;"
            f" font-weight: 800; font-size: 11px; }}"
            f"QPushButton:hover {{ background: #f7b341; }}")
        send.clicked.connect(self._run_current)
        inp.addWidget(send)
        root.addLayout(inp)

    def _quick_commands(self) -> list[tuple[str, str]]:
        """Handy R Native operations exposed as one-click chips."""
        py = sys.executable.replace("python.exe", "pythonw.exe")
        return [
            ("📂 list project files",         "Get-ChildItem"),
            ("🧠 brain health (port 5055)",   "(Invoke-WebRequest http://127.0.0.1:5055/api/account -UseBasicParsing).Content"),
            ("🧬 son status (multi)",         "Get-Content data\\son_status_multi.json -ErrorAction SilentlyContinue | Select-Object -First 1"),
            ("⚙ running python processes",    "Get-Process python,pythonw -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,@{N='MB';E={[int]($_.WS/1MB)}}"),
            ("🔒 circuit breaker state",      "Get-Content r_native_v2\\data\\circuit_breaker_state.json -ErrorAction SilentlyContinue"),
            ("📊 git status",                 "git status -s"),
            ("📜 last 30 log lines",          "Get-Content (Get-ChildItem r_native_v2\\data\\logs\\*.log | Sort-Object LastWriteTime | Select-Object -Last 1).FullName -Tail 30 -ErrorAction SilentlyContinue"),
        ]

    # ── shell process ──
    def _start_shell(self) -> None:
        self._proc = QProcess(self)
        self._proc.setWorkingDirectory(self._cwd)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.started.connect(self._on_started)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        # Interactive PowerShell reading commands from stdin (no profile = fast start)
        if sys.platform == "win32":
            self._proc.setProgram("powershell.exe")
            # No -Command/-File → PowerShell reads commands from stdin (REPL).
            self._proc.setArguments(["-NoLogo", "-NoProfile"])
        else:
            self._proc.setProgram("/bin/bash")
            self._proc.setArguments(["-i"])
        self._append(f"  R Native terminal · {self._cwd}\n", _MUTED)
        self._proc.start()

    def _restart_shell(self) -> None:
        if self._proc:
            try:
                self._proc.kill(); self._proc.waitForFinished(1500)
            except Exception:
                pass
        self.clear_output()
        self._start_shell()

    def _on_started(self) -> None:
        self._status_dot.setStyleSheet(f"color: {_GREEN}; font-size: 12px;")
        self._status_dot.setToolTip("shell running")

    def _on_finished(self, *_a) -> None:
        self._status_dot.setStyleSheet(f"color: {_RED}; font-size: 12px;")
        self._status_dot.setToolTip("shell exited — press ⟳ RESTART")
        self._append("\n  [shell exited]\n", _RED)

    def _on_error(self, *_a) -> None:
        self._status_dot.setStyleSheet(f"color: {_RED}; font-size: 12px;")

    def _on_output(self) -> None:
        if not self._proc:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        if data:
            self._append(data, _TEXT)

    # ── command execution ──
    def _run_current(self) -> None:
        cmd = self.cmd.text().strip()
        if not cmd:
            return
        self.run_command(cmd)
        self.cmd.remember(cmd)
        self.cmd.clear()

    def run_command(self, cmd: str) -> None:
        """Echo + send a command to the live shell (public API)."""
        if not self._proc or self._proc.state() != QProcess.Running:
            self._append("  [shell not running — press ⟳ RESTART]\n", _RED)
            return
        self._append(f"\n❯ {cmd}\n", _CYAN)
        self._proc.write((cmd + "\n").encode("utf-8"))

    def _interrupt(self) -> None:
        # PowerShell over stdin can't receive a true Ctrl+C; restart is the
        # reliable interrupt for a runaway command.
        self._append("\n  ^C — restarting shell to interrupt\n", _GOLD)
        self._restart_shell()

    def _on_quick_selected(self, idx: int) -> None:
        cmd = self._quick.itemData(idx)
        if cmd:
            self.cmd.setText(cmd)
            self.cmd.setFocus()
        self._quick.setCurrentIndex(0)

    # ── output helpers ──
    def _append(self, text: str, color: str = _TEXT) -> None:
        cur = self.output.textCursor()
        cur.movePosition(QTextCursor.End)
        self.output.setTextCursor(cur)
        if color and color != _TEXT:
            # color a whole chunk via inline HTML (cheap; no ANSI parsing)
            safe = (text.replace("&", "&amp;").replace("<", "&lt;")
                        .replace(">", "&gt;").replace("\n", "<br>"))
            self.output.appendHtml(f"<span style='color:{color}'>{safe}</span>")
        else:
            self.output.insertPlainText(text)
        sb = self.output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear_output(self) -> None:
        self.output.clear()

    # ── lifecycle ──
    def shutdown(self) -> None:
        if self._proc:
            try:
                self._proc.kill(); self._proc.waitForFinished(1000)
            except Exception:
                pass
