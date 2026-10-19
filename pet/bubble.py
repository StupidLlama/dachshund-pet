"""狗頭上的對話泡泡：獨立的透明小視窗（滑鼠穿透），所以可以比狗寬，
靠近螢幕邊時整個往內移，尾巴還是指著狗。白底、深色外框 2px、圓角 14px、底下小三角、EvanHand。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .paper import INK, PAPER, SHADOW, hand_font

TAIL = 8          # 小三角高度（px，以 160px 狗為準）


class Bubble(QWidget):
    def __init__(self, k: float = 1.0):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoDropShadowWindowHint
            | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.k = k
        self.text = ""
        self.expire = 0.0
        self.tail_x = 0.0
        self.font_ = hand_font(18 * k)

    @property
    def active(self) -> bool:
        return bool(self.text)

    def show_text(self, text: str, life: float = 1.6) -> None:
        """life <= 0 = 一直顯示，直到 clear()。"""
        self.text = text
        self.expire = time.monotonic() + life if life > 0 else float("inf")
        fm = QFontMetricsF(self.font_)
        w = fm.horizontalAdvance(text) + 24 * self.k + 6
        h = fm.ascent() + fm.descent() + 10 * self.k + TAIL * self.k + 6
        self.resize(int(w + 0.5), int(h + 0.5))
        self.update()

    def clear(self) -> None:
        self.text = ""
        self.hide()

    def follow(self, tip_x: float, tip_y: float, area) -> None:
        """tip = 小三角尖端要指的螢幕座標；area = 這個螢幕的 availableGeometry()。"""
        if not self.text:
            return
        if time.monotonic() > self.expire:
            self.clear()
            return
        w, h = self.width(), self.height()
        x = tip_x - w / 2
        x = min(max(x, area.left() + 4), area.left() + area.width() - 4 - w)   # 不要超出螢幕
        y = max(float(area.top()) + 2, tip_y - h)
        tail = min(max(tip_x - x, 18 * self.k), w - 18 * self.k)
        if abs(tail - self.tail_x) > 0.5:
            self.tail_x = tail
            self.update()
        self.move(int(round(x)), int(round(y)))
        if not self.isVisible():
            self.show()
            self.raise_()

    def paintEvent(self, e) -> None:
        if not self.text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        k = self.k
        body = QRectF(3, 2, self.width() - 6, self.height() - 2 - TAIL * k - 4)
        path = QPainterPath()
        path.addRoundedRect(body, 14 * k, 14 * k)
        tx = self.tail_x
        tail = QPainterPath()
        tail.addPolygon(QPolygonF([QPointF(tx - 7 * k, body.bottom() - 2), QPointF(tx, body.bottom() + TAIL * k),
                                   QPointF(tx + 7 * k, body.bottom() - 2)]))
        tail.closeSubpath()
        shape = path.united(tail)
        p.fillPath(shape.translated(0, 2), SHADOW)
        p.fillPath(shape, PAPER)
        p.strokePath(shape, QPen(INK, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setFont(self.font_)
        p.setPen(INK)
        p.drawText(body.adjusted(0, 0, 0, -1 * k), Qt.AlignCenter, self.text)
        p.end()
