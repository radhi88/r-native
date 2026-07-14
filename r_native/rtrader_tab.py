"""r_native/rtrader_tab.py — 🖥 R TRADER gateway embedded INSIDE R Native.

Born 2026-05-30 from the user's mandate: "كل تبويب وكل شيء فيه دون استثناء
ودمجه معه http://127.0.0.1:8020/rt/brain بمميزاته كاملاً".

The :8020 unified gateway (r_trader/gateway.py) serves TWO live HTML pages —
the main cockpit `/` (which itself consumes every JSON API: engines control,
scoreboard, fleet, bus, meta-learner, senses, hand, coherence) and the company
brain galaxy `/rt/brain` (5 real layers: knowledge/fleet/council/trades/code).
Embedding those two pages live = the gateway's FULL feature set, in-app.

Professional touches:
  • section pills switch القمرة ⟷ مخ الشركة without leaving R Native
  • SELF-HEALING: if :8020 is down, one click (or first load) spawns
    r_trader/gateway.py detached and retries — no terminal needed
  • non-blocking health dot (QNetworkAccessManager ping every 5s, no UI stalls)
  • reload + open-in-external-browser per section
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout,
                               QLabel, QPushButton)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkProxy

GOLD, GREEN, RED = "#fbbf24", "#10b981", "#ef4444"
TEXT, MUTED = "#f1f5f9", "#94a3b8"
BG_1, BG_2, BORDER = "#13131a", "#1a1a23", "#2d2d3a"

BASE = "http://127.0.0.1:8020"
MT5_ROOT = Path(r"C:\Users\Radhi\MT5")
GATEWAY = MT5_ROOT / "r_trader" / "gateway.py"

SECTIONS = [   # (label, path) — the gateway's two live HTML faces
    ("🏠 القمرة الموحّدة", "/"),
    ("🧠 مخ الشركة", "/rt/brain"),
]


class RTraderTab(QWidget):
    """Embedded R Trader gateway with section pills + self-healing server."""

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ── header bar: sections · health · actions ──────────────────────────
        bar = QFrame()
        bar.setStyleSheet(f"QFrame {{ background:{BG_2}; border-bottom:1px solid {BORDER}; }}")
        bar.setMaximumHeight(38)
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(6)

        title = QLabel("🖥 R TRADER · :8020")
        title.setStyleSheet(f"color:{GOLD}; font-size:10px; font-weight:800; letter-spacing:2px;")
        h.addWidget(title)

        self._sec_btns: list[QPushButton] = []
        for i, (label, _path) in enumerate(SECTIONS):
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self.show_section(i))
            h.addWidget(b)
            self._sec_btns.append(b)

        self.health_lbl = QLabel("● …")
        self.health_lbl.setStyleSheet(f"color:{MUTED}; font-size:10px; font-weight:800;")
        h.addWidget(self.health_lbl)
        h.addStretch(1)

        self.start_btn = QPushButton("▶ تشغيل البوّابة")
        self.start_btn.clicked.connect(self._start_gateway)
        self.start_btn.setVisible(False)
        h.addWidget(self.start_btn)
        for txt, fn in [("⟳ Reload", self._reload),
                        ("🌐 Browser", self._open_external)]:
            b = QPushButton(txt)
            b.clicked.connect(fn)
            h.addWidget(b)

        for b in bar.findChildren(QPushButton):
            b.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{MUTED};"
                f" border:1px solid {BORDER}; border-radius:3px; padding:3px 10px;"
                f" font-size:10px; font-weight:700; }}"
                f"QPushButton:hover {{ color:{GOLD}; border-color:{GOLD}; }}"
                f"QPushButton:checked {{ color:#0b0b10; background:{GOLD};"
                f" border-color:{GOLD}; }}")
        v.addWidget(bar)

        # ── web view (or graceful fallback) ──────────────────────────────────
        self.view = None
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            self.view = QWebEngineView()
            self.view.setStyleSheet(f"background:{BG_1};")
            v.addWidget(self.view, 1)
        except Exception as e:
            msg = QLabel(f"QtWebEngine غير متوفر: {e}\n\nافتح بالمتصفح بدلاً منه:")
            msg.setAlignment(Qt.AlignCenter)
            msg.setStyleSheet(f"color:{TEXT}; padding:30px;")
            v.addWidget(msg, 1)
            btn = QPushButton("🌐 فتح R Trader بالمتصفح")
            btn.clicked.connect(self._open_external)
            v.addWidget(btn, alignment=Qt.AlignCenter)
            v.addStretch()

        self._current = 0
        self._nam = QNetworkAccessManager(self)
        # 127.0.0.1 must NEVER go through the system proxy (Cloudflare etc.) —
        # with a proxy the local ping fails and the dot lies "مطفأة" while the
        # gateway is actually alive.
        self._nam.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self._nam.finished.connect(self._on_ping_reply)
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._ping)
        self._health_timer.start(5000)
        self._was_up: bool | None = None
        QTimer.singleShot(200, self._ping)
        self.show_section(0)

    # ── sections ─────────────────────────────────────────────────────────────
    def show_section(self, idx: int) -> None:
        self._current = idx
        for i, b in enumerate(self._sec_btns):
            b.setChecked(i == idx)
        if self.view is not None:
            self.view.setUrl(QUrl(BASE + SECTIONS[idx][1]))

    def _reload(self) -> None:
        if self.view is not None:
            self.view.reload()

    def _open_external(self) -> None:
        QDesktopServices.openUrl(QUrl(BASE + SECTIONS[self._current][1]))

    # ── health ping (fully async — never blocks the Qt thread) ──────────────
    def _ping(self) -> None:
        if not self.isVisible():          # efficiency: idle while tab hidden
            return
        # /rt/token responds in ~2ms; /rt/health takes ~6s (deep engine probe)
        # and would always trip the 3s timeout → false "مطفأة".
        req = QNetworkRequest(QUrl(BASE + "/rt/token"))
        req.setTransferTimeout(3000)
        self._nam.get(req)

    def _on_ping_reply(self, reply) -> None:
        up = reply.error() == reply.NetworkError.NoError
        reply.deleteLater()
        self.health_lbl.setText("● حيّة" if up else "● مطفأة")
        self.health_lbl.setStyleSheet(
            f"color:{GREEN if up else RED}; font-size:10px; font-weight:800;")
        self.start_btn.setVisible(not up)
        if up and self._was_up is False and self.view is not None:
            self._reload()                # server came back → refresh the page
        self._was_up = up

    # ── self-healing: spawn the gateway detached ─────────────────────────────
    def _start_gateway(self) -> None:
        try:
            py = MT5_ROOT / ".venv" / "Scripts" / "python.exe"
            exe = str(py) if py.exists() else sys.executable
            flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
            log = open(MT5_ROOT / "r_native_v2" / "data" / "logs" / "rtrader_gateway.log",
                       "a", encoding="utf-8")
            subprocess.Popen([exe, str(GATEWAY)], cwd=str(MT5_ROOT),
                             stdout=log, stderr=subprocess.STDOUT,
                             creationflags=flags, close_fds=True)
            self.health_lbl.setText("● تُقلع…")
            self.health_lbl.setStyleSheet(f"color:{GOLD}; font-size:10px; font-weight:800;")
            QTimer.singleShot(4000, self._ping)
            QTimer.singleShot(5500, self._reload)
        except Exception as e:
            self.health_lbl.setText(f"● فشل الإقلاع: {e}")
            self.health_lbl.setStyleSheet(f"color:{RED}; font-size:10px;")


__all__ = ["RTraderTab"]
