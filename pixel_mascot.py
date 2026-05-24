"""pixel_mascot.py — Bull/Bear pixel mascot that reacts to live P/L.

Inspired by user's easy-peasy.ai pixel art trading game.
A PySide6 widget that shows a 32x32 pixel character whose emotion + animation
reflects the live trading state:

  P/L state         → Character + Mood
  ─────────────────────────────────────
  Profit > 5%       → 💎 Diamond Hands Bull (jumping, gold sparkle)
  Profit 1-5%       → 😎 Confident Bull
  Profit 0-1%       → 🤔 Watching Bull
  Loss   0-2%       → 😬 Worried Bear
  Loss   2-5%       → 😨 FOMO Bear (sweating)
  Loss   > 5%       → 💀 Capitulation Bear (head down)
  In trade          → ⚡ Active state (pulsing)
  No position       → 😴 Idle

Sprite assets go in: r_native/assets/pixel/
  - bull_idle.png    (32x32 or any size, will be scaled)
  - bull_confident.png
  - bull_diamond.png
  - bear_worried.png
  - bear_fomo.png
  - bear_capitulation.png
  - watcher.png      (neutral)
  - placeholder.png  (fallback if a sprite is missing)

When sprites are missing, falls back to emoji + colored shape.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizePolicy

ASSETS_DIR = Path(__file__).parent / "assets" / "pixel"

# Emotion → (label, color, fallback emoji, sprite filename)
EMOTIONS = {
    "DIAMOND":      ("DIAMOND HANDS", "#a78bfa", "💎", "bull_diamond.png"),
    "CONFIDENT":    ("CONFIDENT",     "#22c55e", "😎", "bull_confident.png"),
    "WATCHING":     ("WATCHING",      "#06b6d4", "🤔", "watcher.png"),
    "IDLE":         ("IDLE",          "#9494a0", "😴", "idle.png"),
    "WORRIED":      ("WORRIED",       "#f5a524", "😬", "bear_worried.png"),
    "FOMO":         ("FOMO",          "#f97316", "😨", "bear_fomo.png"),
    "CAPITULATION": ("CAPITULATION",  "#ef4444", "💀", "bear_capitulation.png"),
    "ACTIVE":       ("ACTIVE TRADE",  "#fbbf24", "⚡", "bull_active.png"),
}


def emotion_for_pl(today_pl: float, today_trades: int,
                   has_open_position: bool) -> str:
    """Map current P/L state → emotion key."""
    if has_open_position:        return "ACTIVE"
    if today_trades == 0:        return "IDLE"
    if today_pl > 5:             return "DIAMOND"
    if today_pl > 1:             return "CONFIDENT"
    if today_pl >= 0:            return "WATCHING"
    if today_pl > -2:            return "WORRIED"
    if today_pl > -5:            return "FOMO"
    return "CAPITULATION"


class PixelMascot(QWidget):
    """64x64 pixel character widget. Shows sprite if available, else emoji+color shape."""

    def __init__(self, size_px: int = 64, parent: QWidget | None = None):
        super().__init__(parent)
        self.size_px = size_px
        self.setFixedSize(QSize(size_px, size_px + 18))   # +18 for label
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._emotion = "IDLE"
        self._pulse_phase = 0
        # Pulse animation
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._on_pulse)
        self._pulse_timer.start(120)

    def set_emotion(self, emotion: str):
        if emotion not in EMOTIONS:
            emotion = "IDLE"
        if emotion != self._emotion:
            self._emotion = emotion
            self.update()

    def set_from_pl(self, today_pl: float, today_trades: int = 0,
                    has_open_position: bool = False):
        """Convenience: derive emotion from P/L state."""
        self.set_emotion(emotion_for_pl(today_pl, today_trades, has_open_position))

    def _on_pulse(self):
        # Only pulse active/extreme states
        if self._emotion in ("ACTIVE", "DIAMOND", "CAPITULATION"):
            self._pulse_phase = (self._pulse_phase + 1) % 20
            self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)   # pixel art = no AA
        label, color, emoji, sprite_name = EMOTIONS[self._emotion]

        # Try to load sprite
        sprite_path = ASSETS_DIR / sprite_name
        sprite_loaded = False
        if sprite_path.exists():
            pix = QPixmap(str(sprite_path))
            if not pix.isNull():
                # Scale with NO smoothing for pixel-art crispness
                pix = pix.scaled(self.size_px, self.size_px,
                                 Qt.KeepAspectRatio, Qt.FastTransformation)
                # Center
                x = (self.width()  - pix.width())  // 2
                y = (self.size_px  - pix.height()) // 2
                # Pulse glow for high-intensity emotions
                if self._emotion in ("ACTIVE", "DIAMOND", "CAPITULATION"):
                    glow = abs(self._pulse_phase - 10) / 10  # 0..1
                    p.setPen(QPen(QColor(color), 2))
                    p.setBrush(QBrush(QColor(color).lighter(150 + int(glow * 100))))
                    p.setOpacity(glow * 0.3)
                    p.drawRoundedRect(x - 2, y - 2,
                                       pix.width() + 4, pix.height() + 4,
                                       4, 4)
                    p.setOpacity(1)
                p.drawPixmap(x, y, pix)
                sprite_loaded = True

        # Fallback: colored circle + emoji
        if not sprite_loaded:
            # Background circle
            p.setPen(Qt.NoPen)
            base_color = QColor(color)
            if self._emotion in ("ACTIVE", "DIAMOND"):
                glow = abs(self._pulse_phase - 10) / 10
                base_color = base_color.lighter(100 + int(glow * 50))
            p.setBrush(QBrush(base_color))
            margin = 4
            p.drawEllipse(margin, margin,
                          self.size_px - 2 * margin, self.size_px - 2 * margin)
            # Emoji
            p.setPen(QColor("#ededf0"))
            f = QFont("Segoe UI Emoji", int(self.size_px * 0.45))
            p.setFont(f)
            p.drawText(self.rect().adjusted(0, 0, 0, -18),
                       Qt.AlignCenter, emoji)

        # Label underneath
        p.setPen(QColor(color))
        f = QFont("Inter", 7, QFont.Bold)
        p.setFont(f)
        p.drawText(0, self.size_px + 2, self.width(), 16,
                   Qt.AlignCenter, label)


class MascotBar(QWidget):
    """Horizontal bar with mascot + small status text. Drops into Hero card."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout
        h = QHBoxLayout(self); h.setContentsMargins(8, 4, 8, 4); h.setSpacing(8)
        self.mascot = PixelMascot(size_px=52)
        h.addWidget(self.mascot)
        # Mood + reason text
        col = QVBoxLayout(); col.setSpacing(0); col.setContentsMargins(0, 0, 0, 0)
        self.mood_label = QLabel("IDLE")
        self.mood_label.setStyleSheet("color:#9494a0; font-size:10px; font-weight:700; letter-spacing:2px;")
        self.reason_label = QLabel("waiting…")
        self.reason_label.setStyleSheet("color:#ededf0; font-size:11px; font-family:'JetBrains Mono','Consolas',monospace;")
        col.addWidget(self.mood_label)
        col.addWidget(self.reason_label)
        h.addLayout(col)
        h.addStretch()

    def update_from_state(self, today_pl: float, today_trades: int,
                          has_open_position: bool, reason: str = ""):
        emotion = emotion_for_pl(today_pl, today_trades, has_open_position)
        self.mascot.set_emotion(emotion)
        self.mood_label.setText(EMOTIONS[emotion][0])
        color = EMOTIONS[emotion][1]
        self.mood_label.setStyleSheet(
            f"color:{color}; font-size:10px; font-weight:700; letter-spacing:2px;")
        if reason:
            self.reason_label.setText(reason[:60])


# ── Standalone preview ───────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QMainWindow, QHBoxLayout, QPushButton
    app = QApplication(sys.argv)
    w = QMainWindow(); w.setStyleSheet("background:#0a0a0f;")
    central = QWidget(); w.setCentralWidget(central)
    h = QHBoxLayout(central); h.setSpacing(20); h.setContentsMargins(20, 20, 20, 20)
    # Show all emotions side-by-side
    for emo in EMOTIONS:
        m = PixelMascot(size_px=80)
        m.set_emotion(emo)
        h.addWidget(m)
    w.resize(900, 200)
    w.show()
    sys.exit(app.exec())
