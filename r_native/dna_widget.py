from __future__ import annotations
import math
import sys
from PySide6.QtWidgets import QWidget, QSizePolicy, QApplication
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPainterPath, QShowEvent, QHideEvent, QPaintEvent
from PySide6.QtCore import Qt, QPointF, QTimer

RED = QColor("#ef4444")
GOLD = QColor("#fbbf24")
MUTED = QColor("#94a3b8")
BG = QColor("#060418")
VIOLET = QColor("#8b5cf6")


def _blend(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        int(a.red() * (1 - t) + b.red() * t),
        int(a.green() * (1 - t) + b.green() * t),
        int(a.blue() * (1 - t) + b.blue() * t),
    )


class DNAHelix(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        self.genes: list[str] = []
        self.rotation: float = 0.0

        self._turns: int = 4
        self._samples: int = 160
        self._rung_spacing_px: int = 25
        self._strand2_color: QColor = _blend(RED, VIOLET, 0.35)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_genes(self, genes: list[str]) -> None:
        self.genes = list(genes)
        self.update()

    def _tick(self) -> None:
        self.rotation = (self.rotation + (5.0 * 0.033)) % 360.0
        self.update()

    def showEvent(self, event: QShowEvent) -> None:
        if not self._timer.isActive():
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        if self._timer.isActive():
            self._timer.stop()
        super().hideEvent(event)

    def _strand_point(self, t: float, phase: float, w: float, h: float, amp: float, cx: float) -> QPointF:
        y = t * h
        angle = (t * self._turns * 2.0 * math.pi) + phase + math.radians(self.rotation)
        x = cx + math.sin(angle) * amp
        return QPointF(x, y)

    def _build_strand_path(self, phase: float, w: float, h: float, amp: float, cx: float) -> QPainterPath:
        path = QPainterPath()
        for i in range(self._samples + 1):
            t = i / self._samples
            p = self._strand_point(t, phase, w, h, amp, cx)
            if i == 0:
                path.moveTo(p)
            else:
                path.lineTo(p)
        return path

    def _pick_annotations(self, max_n: int) -> list[tuple[str, float]]:
        if not self.genes:
            return []
        picks: list[tuple[str, float]] = []
        seen: set[str] = set()
        for g in self.genes:
            if g in seen:
                continue
            seen.add(g)
            h = abs(hash(g))
            t = 0.1 + (h % 1000) / 1000.0 * 0.8
            picks.append((g, t))
            if len(picks) >= max_n:
                break
        picks.sort(key=lambda x: x[1])
        return picks

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        w = float(self.width())
        h = float(self.height())
        p.fillRect(self.rect(), BG)

        margin_top = 16.0
        margin_bot = 16.0
        usable_h = max(40.0, h - margin_top - margin_bot)
        cx = w * 0.45
        amp = w * 0.35 * 0.5

        p.save()
        p.translate(0, margin_top)

        path1 = self._build_strand_path(0.0, w, usable_h, amp, cx)
        path2 = self._build_strand_path(math.pi, w, usable_h, amp, cx)

        n_rungs = max(2, int(usable_h / self._rung_spacing_px))
        rung_pen = QPen(MUTED, 1.0)
        rung_pen.setCapStyle(Qt.RoundCap)
        p.setPen(rung_pen)
        for i in range(n_rungs + 1):
            t = i / n_rungs
            a = self._strand_point(t, 0.0, w, usable_h, amp, cx)
            b = self._strand_point(t, math.pi, w, usable_h, amp, cx)
            depth = (math.sin((t * self._turns * 2.0 * math.pi) + math.radians(self.rotation)) + 1.0) * 0.5
            col = QColor(MUTED)
            col.setAlphaF(0.25 + 0.55 * depth)
            rp = QPen(col, 1.0)
            p.setPen(rp)
            p.drawLine(a, b)

        pen1 = QPen(RED, 2.0)
        pen1.setCapStyle(Qt.RoundCap)
        pen1.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen1)
        p.drawPath(path1)

        pen2 = QPen(self._strand2_color, 2.0)
        pen2.setCapStyle(Qt.RoundCap)
        pen2.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen2)
        p.drawPath(path2)

        node_brush_r = QBrush(RED)
        node_brush_v = QBrush(self._strand2_color)
        p.setPen(Qt.NoPen)
        for i in range(0, self._samples + 1, max(1, self._samples // (self._turns * 4))):
            t = i / self._samples
            a = self._strand_point(t, 0.0, w, usable_h, amp, cx)
            b = self._strand_point(t, math.pi, w, usable_h, amp, cx)
            p.setBrush(node_brush_r)
            p.drawEllipse(a, 2.0, 2.0)
            p.setBrush(node_brush_v)
            p.drawEllipse(b, 2.0, 2.0)

        annotations = self._pick_annotations(4)
        if annotations:
            font = QFont("Consolas", 9)
            p.setFont(font)
            label_x = w - 6.0
            for gene, t in annotations:
                anchor = self._strand_point(t, 0.0, w, usable_h, amp, cx)
                label_y = t * usable_h
                fm = p.fontMetrics()
                text_w = fm.horizontalAdvance(gene)
                text_h = fm.height()
                tx = label_x - text_w
                ty = label_y + fm.ascent() / 2.0 - 2.0

                connector_pen = QPen(GOLD, 0.8)
                connector_pen.setStyle(Qt.SolidLine)
                p.setPen(connector_pen)
                p.drawLine(anchor, QPointF(tx - 4.0, label_y))

                p.setPen(QPen(GOLD, 1.0))
                p.drawText(QPointF(tx, ty), gene)

                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(GOLD))
                p.drawEllipse(anchor, 2.5, 2.5)

        p.restore()

        axis_pen = QPen(MUTED, 1.0)
        axis_pen.setStyle(Qt.DotLine)
        p.setPen(axis_pen)
        p.drawLine(QPointF(cx, margin_top), QPointF(cx, h - margin_bot))

        p.setFont(QFont("Consolas", 8))
        p.setPen(QPen(MUTED, 1.0))
        p.drawText(QPointF(6.0, h - 4.0), "DNA")

        p.end()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = DNAHelix()
    w.set_genes(['SL_LOCK', 'WILLIAMS', 'CONSEC', 'use_sig_macd', 'use_bias_ema'])
    w.resize(800, 600)
    w.show()
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        sys.exit(0)
