"""pixel_widget.py — PySide6 mascot widget for R Native (H.20).

Renders the 16x16 sprites declared in :mod:`r_native.pixel_sprites` using
plain ``QPainter`` rectangles — no external image files, no shaders, no
network. The widget is designed to slot next to the existing
``DNAHelix`` and ``EquityCurve`` in the Inspector tab, sharing the same
gold/violet R-Factory palette as ``app.py``.

Public API
==========

* :class:`PixelMascot`         - the QWidget (drop into any layout)
* :class:`PixelMascot.react`   - call with engine state to swap mascot
* :class:`PixelMascot.set_pnl` - convenience helper using live P/L numbers

Wiring example (inside ``RNativeMain``)
======================================

>>> from r_native.pixel_widget import PixelMascot
>>> self.mascot = PixelMascot(parent=self)
>>> inspector_layout.addWidget(self.mascot)
>>> # later when worker emits a new P/L tick
>>> self.mascot.set_pnl(pnl=open_pl, net_worth=equity, hodl=False)

The widget animates at the FPS supplied to the constructor (default 4)
which is intentionally choppy to keep the retro arcade feel.
"""
from __future__ import annotations

import math
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal, QRect, QSize
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPaintEvent,
                           QPen, QPixmap)
from PySide6.QtWidgets import QSizePolicy, QWidget

from r_native.pixel_sprites import (PALETTE, SPRITE_PRESETS, frame_pixels,
                                    get_preset, preset_for_state,
                                    state_from_pnl)


# Palette tokens borrowed verbatim from app.py so the mascot blends in.
BG_0     = QColor("#0a0a0f")
BG_1     = QColor("#13131a")
BG_2     = QColor("#1a1a23")
GOLD     = QColor("#f5a524")
GOLD_DIM = QColor("#c47e15")
VIOLET   = QColor("#a78bfa")
GREEN    = QColor("#22c55e")
RED      = QColor("#ef4444")
CYAN     = QColor("#06b6d4")
TEXT     = QColor("#ededf0")
MUTED    = QColor("#9494a0")
DIM      = QColor("#5a5a70")
BORDER   = QColor("#26262f")


# ─────────────────────────────────────────────────────────────────────────────


class PixelMascot(QWidget):
    """Animated 16x16 retro mascot tied to the current trader state."""

    #: Emitted whenever ``react()`` changes the active preset.
    preset_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None,
                 *, fps: int = 4, scale: int = 8,
                 show_caption: bool = True) -> None:
        super().__init__(parent)
        self._scale = max(2, scale)        # pixel size of each "pixel"
        self._fps = max(1, fps)
        self._show_caption = show_caption

        self._preset_id: str = "bull-trader"
        self._state: str = "idle"
        self._frame_idx: int = 0
        self._frames: List[List[List[Optional[str]]]] = []

        self.setMinimumSize(QSize(96, 128 if show_caption else 96))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setStyleSheet("background: transparent;")

        # Animation timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(1000 / self._fps))

        # Initial render
        self._load_frames("bull-trader")

    # ---------------------------------------------------------------- public

    def react(self, state: str) -> None:
        """Change the visible mascot based on engine state (see STATE_TO_PRESET)."""
        if state == self._state:
            return
        self._state = state
        preset = preset_for_state(state)
        if preset["id"] != self._preset_id:
            self._load_frames(preset["id"])
            self.preset_changed.emit(preset["id"])

    def set_pnl(self, pnl: float, net_worth: float, *, hodl: bool = False,
                daily_cap: float = 10.0) -> None:
        """Convenience: pick the right state from live P/L + equity."""
        s = state_from_pnl(pnl, net_worth, daily_cap=daily_cap, hodl=hodl)
        self.react(s)

    def load_preset(self, preset_id: str) -> None:
        """Force a specific preset (used by the Pixel Lab tab)."""
        if preset_id != self._preset_id:
            self._load_frames(preset_id)
            self.preset_changed.emit(preset_id)

    def set_fps(self, fps: int) -> None:
        """Adjust animation speed at runtime."""
        self._fps = max(1, fps)
        self._timer.setInterval(int(1000 / self._fps))

    def export_png(self, path: str, *, scale: int = 32, frame: Optional[int] = None) -> None:
        """Save the current mascot to *path* at *scale* px per pixel."""
        idx = frame if frame is not None else self._frame_idx
        if not self._frames:
            return
        idx = max(0, min(idx, len(self._frames) - 1))
        grid = self._frames[idx]
        size = 16 * scale
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing, False)
        for y in range(16):
            for x in range(16):
                hex_col = grid[y][x]
                if hex_col is None:
                    continue
                painter.fillRect(x * scale, y * scale, scale, scale, QColor(hex_col))
        painter.end()
        pm.save(path, "PNG")

    @property
    def current_preset_id(self) -> str:
        return self._preset_id

    @property
    def current_state(self) -> str:
        return self._state

    # --------------------------------------------------------------- internal

    def _load_frames(self, preset_id: str) -> None:
        preset = get_preset(preset_id) or SPRITE_PRESETS[0]
        self._preset_id = preset["id"]
        self._frames = [
            frame_pixels(preset["id"], i) for i in range(len(preset["frames"]))
        ]
        self._frame_idx = 0
        self.update()

    def _tick(self) -> None:
        if not self._frames:
            return
        self._frame_idx = (self._frame_idx + 1) % len(self._frames)
        self.update()

    # ----------------------------------------------------------------- paint

    def paintEvent(self, ev: QPaintEvent) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        # Backdrop: rounded card matching app.py's QFrame[role="card"]
        rect = self.rect().adjusted(0, 0, -1, -1)
        bg_brush = QBrush(BG_1)
        p.setPen(QPen(BORDER, 1))
        p.setBrush(bg_brush)
        p.drawRoundedRect(rect, 12, 12)

        if not self._frames:
            p.end()
            return

        # Compute centered draw box: square scaled sprite at top, caption below.
        cap_h = 28 if self._show_caption else 0
        avail_w = self.width() - 16
        avail_h = self.height() - 16 - cap_h
        side = max(16, min(avail_w, avail_h))
        # Snap to multiples of 16 for crisp pixel rendering
        scale = max(2, side // 16)
        sprite_side = scale * 16
        ox = (self.width() - sprite_side) // 2
        oy = 8

        # Draw the pixel grid
        grid = self._frames[self._frame_idx]
        p.setPen(Qt.NoPen)
        for y in range(16):
            for x in range(16):
                hex_col = grid[y][x]
                if hex_col is None:
                    continue
                p.setBrush(QColor(hex_col))
                p.drawRect(ox + x * scale, oy + y * scale, scale, scale)

        # Optional caption: state + preset name
        if self._show_caption:
            preset = get_preset(self._preset_id) or SPRITE_PRESETS[0]

            # State pill (top-right of card)
            pill_text = self._state.upper()
            p.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
            fm = p.fontMetrics()
            pill_w = fm.horizontalAdvance(pill_text) + 16
            pill_h = 16
            pill_x = self.width() - pill_w - 10
            pill_y = 10
            pill_rect = QRect(pill_x, pill_y, pill_w, pill_h)
            pill_col = self._state_color()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(pill_col.red(), pill_col.green(), pill_col.blue(), 60))
            p.drawRoundedRect(pill_rect, 8, 8)
            p.setPen(QPen(pill_col, 1))
            p.drawText(pill_rect, Qt.AlignCenter, pill_text)

            # Caption (preset name)
            cap_y = oy + sprite_side + 6
            p.setPen(GOLD)
            p.setFont(QFont("Inter", 9, QFont.Bold))
            p.drawText(QRect(0, cap_y, self.width(), 14),
                       Qt.AlignHCenter, preset["name"])
            p.setPen(MUTED)
            p.setFont(QFont("Inter", 8))
            cap_sub = preset["category"].upper()
            p.drawText(QRect(0, cap_y + 14, self.width(), 12),
                       Qt.AlignHCenter, cap_sub)

        p.end()

    def _state_color(self) -> QColor:
        return {
            "idle":        MUTED,
            "scanning":    VIOLET,
            "profit":      GREEN,
            "big-profit":  GOLD,
            "loss":        RED,
            "panic":       RED,
            "liquidated":  RED,
            "hodl":        CYAN,
            "deploying":   GOLD,
            "campaign":    VIOLET,
            "range":       MUTED,
        }.get(self._state, MUTED)


# ─────────────────────────────────────────────────────────────────────────────
#  Standalone demo — run with:  python -m r_native.pixel_widget
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    import sys
    from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout,
                                   QPushButton, QVBoxLayout, QWidget)

    app = QApplication(sys.argv)
    app.setStyleSheet(f"""
        QWidget {{ background: #0a0a0f; color: #ededf0;
                   font-family: 'Inter'; }}
        QPushButton {{ background: transparent; border: 1px solid #26262f;
                       border-radius: 8px; padding: 6px 14px; }}
        QPushButton:hover {{ background: #1a1a23; }}
        QComboBox {{ background: #1a1a23; border: 1px solid #26262f;
                     border-radius: 8px; padding: 6px 10px; }}
    """)

    root = QWidget()
    root.setWindowTitle("R Native — Pixel Mascot Demo (H.20)")
    root.resize(360, 480)
    layout = QVBoxLayout(root)

    mascot = PixelMascot(scale=12)
    layout.addWidget(mascot)

    # State selector
    states = list({"idle", "scanning", "profit", "big-profit", "loss",
                   "panic", "liquidated", "hodl", "deploying",
                   "campaign", "range"})
    cb = QComboBox()
    cb.addItems(sorted(states))
    cb.setCurrentText("idle")
    cb.currentTextChanged.connect(mascot.react)
    layout.addWidget(cb)

    # Direct preset selector
    presets = [p["id"] for p in SPRITE_PRESETS]
    cb2 = QComboBox()
    cb2.addItems(presets)
    cb2.currentTextChanged.connect(mascot.load_preset)
    layout.addWidget(cb2)

    # Export demo
    btn = QPushButton("Export PNG (512x512)")
    btn.clicked.connect(lambda: mascot.export_png(
        "/tmp/rmascot_preview.png", scale=32))
    layout.addWidget(btn)

    root.show()
    sys.exit(app.exec())
