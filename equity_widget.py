"""equity_widget.py - Pure-Qt equity curve widget (no charting library needed).

Draws a balance-over-time line with:
  - Color-segmented points (green for wins, red for losses)
  - Min/max horizontal grid lines
  - Optional shaded drawdown areas
"""
from __future__ import annotations
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPainterPath
from PySide6.QtCore import Qt, QPoint, QRect


GOLD  = QColor(251, 191, 36)
GREEN = QColor(16, 185, 129)
RED   = QColor(239, 68, 68)
VIOLET= QColor(139, 92, 246)
BG    = QColor(13, 8, 36)
MUTED = QColor(148, 163, 184)
BORDER= QColor(45, 27, 105)


class EquityCurve(QWidget):
    """data: list of (timestamp_str, balance, optional_profit) tuples — chronological."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: list[tuple] = []
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, data: list[tuple]):
        self.data = data or []
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad_left, pad_right, pad_top, pad_bot = 50, 12, 12, 24

        # background
        p.fillRect(self.rect(), BG)

        if not self.data:
            p.setPen(MUTED)
            p.drawText(self.rect(), Qt.AlignCenter, "no equity data yet — make a trade")
            return

        balances = [b for (_, b, *_) in self.data]
        lo, hi = min(balances), max(balances)
        if hi - lo < 0.01: hi = lo + 1   # avoid div0
        rng = hi - lo
        # padding the y-range a bit
        lo -= rng * 0.05; hi += rng * 0.05
        rng = hi - lo

        chart_w = w - pad_left - pad_right
        chart_h = h - pad_top - pad_bot

        def to_xy(i, bal):
            x = pad_left + (i / max(1, len(self.data) - 1)) * chart_w
            y = pad_top + (1 - (bal - lo) / rng) * chart_h
            return QPoint(int(x), int(y))

        # ─── Grid + Y-axis labels ───
        p.setPen(QPen(BORDER, 1, Qt.DotLine))
        p.setFont(QFont("Consolas", 8))
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = pad_top + frac * chart_h
            bal_at = hi - frac * rng
            p.drawLine(pad_left, int(y), w - pad_right, int(y))
            p.setPen(MUTED)
            p.drawText(QRect(0, int(y) - 8, pad_left - 4, 16),
                        Qt.AlignRight | Qt.AlignVCenter, f"${bal_at:,.2f}")
            p.setPen(QPen(BORDER, 1, Qt.DotLine))

        # ─── Filled area under curve ───
        path = QPainterPath()
        first = to_xy(0, balances[0])
        path.moveTo(pad_left, h - pad_bot)
        path.lineTo(first)
        for i in range(1, len(self.data)):
            path.lineTo(to_xy(i, balances[i]))
        path.lineTo(w - pad_right, h - pad_bot)
        path.closeSubpath()
        gradient_fill = QColor(GOLD); gradient_fill.setAlpha(40)
        p.fillPath(path, QBrush(gradient_fill))

        # ─── Line ───
        p.setPen(QPen(GOLD, 2))
        for i in range(1, len(self.data)):
            p1 = to_xy(i - 1, balances[i - 1])
            p2 = to_xy(i, balances[i])
            p.drawLine(p1, p2)

        # ─── Points colored by profit ───
        for i, (ts, bal, *rest) in enumerate(self.data):
            profit = rest[0] if rest else 0
            pt = to_xy(i, bal)
            col = GREEN if profit > 0 else RED if profit < 0 else GOLD
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(pt, 3, 3)

        # ─── Title / current ───
        p.setPen(GOLD)
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        last_bal = balances[-1]
        delta = last_bal - balances[0]
        delta_pct = (delta / balances[0] * 100) if balances[0] else 0
        title = f"Equity: ${last_bal:,.2f}   Δ {'+' if delta>=0 else ''}${delta:.2f}  ({delta_pct:+.1f}%)"
        p.drawText(pad_left, 14, title)

        # ─── X-axis labels (first / mid / last) ───
        p.setPen(MUTED)
        p.setFont(QFont("Consolas", 7))
        if len(self.data) >= 2:
            for idx, frac in [(0, 0), (len(self.data)//2, 0.5), (len(self.data)-1, 1)]:
                x = pad_left + frac * chart_w
                ts = str(self.data[idx][0])[-8:]    # last 8 chars (HH:MM:SS)
                p.drawText(int(x) - 25, h - 4, ts)
