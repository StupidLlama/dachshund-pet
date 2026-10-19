"""狗頭上的對話泡泡：獨立的透明小視窗（滑鼠穿透），所以可以比狗寬，
靠近螢幕邊時整個往內移，尾巴還是指著狗。白底、深色外框 2px、圓角 14px、底下小三角、EvanHand。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .paper import INK, MUTED, PAPER, SHADOW, TOMATO, hand_font, msg_font

TAIL = 8          # 小三角高度（px，以 160px 狗為準）


class Bubble(QWidget):
    def __init__(self, k: float = 1.0, clickable: bool = False):
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoDropShadowWindowHint
                 | Qt.WindowDoesNotAcceptFocus)
        if not clickable:
            flags |= Qt.WindowTransparentForInput
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        if not clickable:
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


# ====================================================================== v0.4 訊息泡泡
def wrap_text(text: str, width_of, max_w: float) -> list[str]:
    """把訊息切成好幾行：英文照單字斷，中文 / 日文一個字一個字斷。width_of(str) = 寬度。"""
    tokens: list[str] = []
    word = ""
    for ch in text:
        if ord(ch) >= 0x2E80:                    # CJK：每個字都可以斷行
            if word:
                tokens.append(word)
                word = ""
            tokens.append(ch)
        elif ch == " ":
            tokens.append(word + " ")
            word = ""
        else:
            word += ch
    if word:
        tokens.append(word)
    lines, cur = [], ""
    for tok in tokens:
        if cur and width_of((cur + tok).rstrip()) > max_w:
            lines.append(cur.rstrip())
            cur = tok.lstrip() if tok.strip() else ""
        else:
            cur += tok
        while width_of(cur.rstrip()) > max_w and len(cur) > 1:   # 一個超長的英文字：硬切
            cut = len(cur) - 1
            while cut > 1 and width_of(cur[:cut]) > max_w:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
    if cur.strip() or not lines:
        lines.append(cur.rstrip())
    return lines


class MsgBubble(Bubble):
    """朋友傳來的訊息：一直顯示到被點掉。第一行是名字（紅字小字），下面是訊息（會換行），
    右下角小字提示「還有幾則」。點泡泡 = 關掉（clicked）；右鍵 = 回覆（replyRequested）。"""
    clicked = Signal()
    replyRequested = Signal()

    MAX_W = 250          # 訊息最寬多少（以 160px 狗為準）

    def __init__(self, k: float = 1.0):
        super().__init__(k, clickable=True)
        self.name = ""
        self.lines: list[str] = []
        self.more = 0
        self.name_font = hand_font(15 * k)
        self.font_ = msg_font(19 * k)
        self.setCursor(Qt.PointingHandCursor)

    def show_msg(self, name: str, text: str, more: int = 0) -> None:
        self.name, self.more = name, more
        fm = QFontMetricsF(self.font_)
        fn = QFontMetricsF(self.name_font)
        k = self.k
        self.lines = wrap_text(text, fm.horizontalAdvance, self.MAX_W * k)
        head = f"{name}:" + (f"   +{more} more" if more else "")
        w = max([fm.horizontalAdvance(t) for t in self.lines] + [fn.horizontalAdvance(head)]) + 28 * k + 6
        lh = fm.ascent() + fm.descent()
        h = (fn.ascent() + fn.descent()) + lh * len(self.lines) + 16 * k + TAIL * k + 6
        self.text = text
        self.expire = float("inf")
        self.resize(int(w + 0.5), int(h + 0.5))
        self.update()

    def clear(self) -> None:
        self.lines = []
        super().clear()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.RightButton:
            self.replyRequested.emit()
        else:
            self.clicked.emit()

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
        fn, fm = QFontMetricsF(self.name_font), QFontMetricsF(self.font_)
        x = body.left() + 14 * k
        y = body.top() + 6 * k + fn.ascent()
        p.setFont(self.name_font)
        p.setPen(TOMATO)
        p.drawText(QPointF(x, y), f"{self.name}:")
        if self.more:
            p.setPen(MUTED)
            more = f"+{self.more} more"
            p.drawText(QPointF(body.right() - 14 * k - fn.horizontalAdvance(more), y), more)
        y += fn.descent() + fm.ascent()
        p.setFont(self.font_)
        p.setPen(INK)
        for line in self.lines:
            p.drawText(QPointF(x, y), line)
            y += fm.ascent() + fm.descent()
        p.end()
