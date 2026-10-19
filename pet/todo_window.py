"""待辦清單視窗：螢幕右邊的筆記本紙 + 左邊的紅色標籤（狗咬的地方）。

視窗本身固定在「清單完全拉出來」的位置（不會跨到隔壁螢幕），紙在視窗裡面左右滑：
    slide = 0      完全打開
    slide = W      收起來，只剩紅標籤露在螢幕右邊緣
透明的地方滑鼠會穿透，所以收起來時只有標籤點得到。

打字用另一個小視窗（InputStrip）蓋在「Add a task...」那一列：清單本身不搶焦點，
只有點輸入框的時候才會讓你打字。

所有文字都坐在藍色橫線上：每一列高 lh，標題列 2 行高；直接用 baseline 畫字，所以不用補 EvanHand 的 0.24em。
"""
from __future__ import annotations

import time
from datetime import date

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from .paper import (INK, MARGIN, MUTED, PAPER, RULE, SHADOW, TOMATO, WEEKDAYS, hand_font,
                    left_round_rect)
from .todo import MAX_TEXT, TodoStore

SLIDE_SEC = 0.35          # 番茄鐘進行中，清單自己滑出來 / 收回去（狗不搬）


def _ease(k: float) -> float:
    return 2 * k * k if k < 0.5 else 1 - (-2 * k + 2) ** 2 / 2


class InputStrip(QWidget):
    """「Add a task...」輸入框。獨立視窗：點它才會拿到鍵盤焦點。"""
    submitted = Signal()
    focusChanged = Signal(bool)

    def __init__(self, font):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.Window, PAPER)
        self.setPalette(pal)
        self.edit = QLineEdit(self)
        self.edit.setFont(font)
        self.edit.setMaxLength(MAX_TEXT)
        self.edit.setPlaceholderText("Add a task...")
        self.edit.setFrame(False)
        self.edit.setStyleSheet("QLineEdit { background: #FFFDF6; color: #1E1B16; border: none; padding: 0 2px; }")
        epal = self.edit.palette()
        epal.setColor(QPalette.PlaceholderText, MUTED)
        self.edit.setPalette(epal)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit)
        self.edit.returnPressed.connect(self.submitted)
        self.edit.installEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if t == QEvent.FocusIn:
            self.focusChanged.emit(True)
        elif t == QEvent.FocusOut:
            self.focusChanged.emit(False)
        elif t == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.edit.clearFocus()
            return True
        return False

    def mousePressEvent(self, e) -> None:
        self.activateWindow()
        self.edit.setFocus()


class TodoWindow(QWidget):
    tabClicked = Signal()
    toggled = Signal(bool, bool)       # (打勾了嗎, 全部做完了嗎)
    typingDone = Signal()              # 打完字（輸入框失去焦點）→ 狗要回到清單上面

    def __init__(self, store: TodoStore, S: int):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.store = store
        self.S = S
        k = self.k = S / 160
        self.W = round(300 * k)              # 紙的寬度
        self.T = max(10, round(16 * k))      # 紅標籤 寬
        self.TH = max(16, round(26 * k))     # 紅標籤 高
        self.lh = max(22, round(34 * k))     # 一行高（橫線間距）
        self.fp = max(12, round(19 * k))     # 字的大小
        self.PAD = 5                         # 陰影（往左下 4px）
        self.f_item = hand_font(self.fp)
        self.f_title = hand_font(self.fp * 1.35)
        self.f_small = hand_font(self.fp * 0.8)

        self.slide = float(self.W)
        self.open = False
        self.scroll = 0
        self.vis = 0
        self.hover = -1
        self.hover_x = False
        self.typing = False
        self.sr = 0.0
        self.floor = 0.0
        self.top_limit = 0.0
        self.paper_h = 0

        self.strip = InputStrip(self.f_item)
        self.strip.submitted.connect(self.add_current)
        self.strip.focusChanged.connect(self._on_focus)

        self._anim = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._anim_step)
        self._anim_from = self._anim_to = 0.0
        self._anim_t0 = 0.0

    # ================================================================== 位置
    def attach_screen(self, screen, floor: float) -> None:
        """清單放在這個螢幕的右邊，紙的底部貼齊 floor（狗走路的地面線）。"""
        geo = screen.availableGeometry()
        self.sr = float(geo.x() + geo.width())
        self.top_limit = float(geo.y())
        self.floor = float(floor)
        self.relayout()
        if not self.isVisible():
            self.show()

    def relayout(self) -> None:
        n = len(self.store.items)
        avail = self.floor - self.top_limit - 8
        max_rows = max(1, int(avail / self.lh - 3.5))
        self.vis = min(n, max_rows)
        self.scroll = max(0, min(self.scroll, n - self.vis))
        self.paper_h = int(round((3 + self.vis + 0.5) * self.lh))
        w = self.PAD + self.T + self.W
        h = 1 + self.paper_h + self.PAD
        self.setGeometry(int(self.sr - w), int(round(self.floor - self.paper_h - 1)), w, h)
        self._sync_strip()
        self.update()

    def refresh(self) -> None:
        """資料從外面改了（換日）。"""
        self.relayout()

    @property
    def screen_right(self) -> float:
        return self.sr

    @property
    def is_open(self) -> bool:
        return self.open

    @property
    def ready(self) -> bool:
        return self.open and self.slide == 0 and not self._anim.isActive()

    def set_left(self, x: float) -> None:
        """狗拉 / 推的時候：紙的左邊緣放在螢幕座標 x。"""
        self.slide = max(0.0, min(float(self.W), x - (self.sr - self.W)))
        self._sync_strip()
        self.update()

    def set_open(self, flag: bool) -> None:
        self._anim.stop()
        self.open = bool(flag)
        self.slide = 0.0 if self.open else float(self.W)
        self._sync_strip()
        self.update()

    def slide_to(self, flag: bool) -> None:
        """不用狗搬，自己滑（番茄鐘進行中用）。"""
        self._anim_from = self.slide
        self._anim_to = 0.0 if flag else float(self.W)
        self.open = bool(flag)
        self._anim_t0 = time.monotonic()
        self._sync_strip()
        self._anim.start()

    def _anim_step(self) -> None:
        k = min(1.0, (time.monotonic() - self._anim_t0) / SLIDE_SEC)
        self.slide = self._anim_from + (self._anim_to - self._anim_from) * _ease(k)
        if k >= 1:
            self._anim.stop()
            self.set_open(self.open)
        self.update()

    # ================================================================== 版面（視窗座標）
    @property
    def L(self) -> float:
        return self.PAD + self.T + self.slide

    def line_y(self, j: int) -> float:
        """第 j 條橫線（從紙的頂端數，第 2 條在標題下面）。"""
        return 1 + j * self.lh - 1

    def tab_rect(self) -> QRectF:
        cy = 1 + self.paper_h - 0.22 * self.S       # 剛好在狗嘴巴的高度
        return QRectF(self.L - self.T, cy - self.TH / 2, self.T + 4, self.TH)

    def _add_button(self) -> QRectF:
        fm = QFontMetricsF(self.f_small)
        bw = fm.horizontalAdvance("Add") + 20 * self.k
        bh = fm.ascent() + fm.descent() + 2
        y = self.line_y(3 + self.vis)
        return QRectF(self.L + self.W - 8 * self.k - bw, y - 4 - bh, bw, bh)

    def _input_rect(self) -> QRectF:
        y = self.line_y(3 + self.vis)
        x0 = self.L + 38 * self.k
        x1 = self._add_button().left() - 6 * self.k
        h = QFontMetricsF(self.f_item).height() + 2
        return QRectF(x0, y - 5 - h, x1 - x0, h)

    def _sync_strip(self) -> None:
        if self.ready and self.isVisible():
            r = self._input_rect()
            self.strip.setGeometry(self.x() + int(r.x()), self.y() + int(r.y()), int(r.width()), int(r.height()))
            if not self.strip.isVisible():
                self.strip.show()
                self.strip.raise_()
        elif self.strip.isVisible():
            if self.strip.edit.hasFocus():
                self.strip.edit.clearFocus()
            self.strip.hide()

    def moveEvent(self, e) -> None:
        self._sync_strip()

    def hideEvent(self, e) -> None:
        self.strip.hide()

    # ================================================================== 畫
    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        k, L, W, lh = self.k, self.L, self.W, self.lh
        top, H = 1.0, float(self.paper_h)
        rad = 10 * k

        # 陰影（往左下 4px）、紅標籤、紙
        p.fillPath(left_round_rect(QRectF(L - 4, top + 4, W + 40, H), rad), SHADOW)
        p.setPen(QPen(INK, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(TOMATO)
        p.drawPath(left_round_rect(self.tab_rect(), 6 * k))
        paper = left_round_rect(QRectF(L, top, W + 40, H), rad)   # 右邊延伸到視窗外 = 貼著螢幕邊、沒有框
        p.fillPath(paper, PAPER)
        p.save()
        p.setClipPath(paper)
        p.setPen(QPen(RULE, 2))
        for j in range(2, 4 + self.vis):
            y = self.line_y(j)
            p.drawLine(QPointF(L, y), QPointF(L + W + 40, y))
        p.setPen(QPen(MARGIN, 2))
        p.drawLine(QPointF(L + 28 * k, top), QPointF(L + 28 * k, top + H))
        p.restore()
        p.strokePath(paper, QPen(INK, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

        # 標題：Today ＋ 日期，baseline 貼第 2 條線
        base = self.line_y(2) - 3
        p.setFont(self.f_title)
        p.setPen(INK)
        p.drawText(QPointF(L + 38 * k, base), "Today")
        d = date.today()
        dtext = f"{WEEKDAYS[d.weekday()]} {d.month}/{d.day}"
        p.setFont(self.f_small)
        p.setPen(MUTED)
        fm_s = QFontMetricsF(self.f_small)
        p.drawText(QPointF(L + W - 10 * k - fm_s.horizontalAdvance(dtext), base), dtext)

        # 每一項
        fm = QFontMetricsF(self.f_item)
        b = 16 * k
        for i in range(self.vis):
            idx = self.scroll + i
            if idx >= len(self.store.items):
                break
            it = self.store.items[idx]
            y = self.line_y(3 + i)
            box = QRectF(L + 6 * k, y - 4 - b, b, b)
            p.setPen(QPen(INK, 2))
            p.setBrush(PAPER)
            p.drawRoundedRect(box, 3 * k, 3 * k)
            if it["done"]:                                    # 紅色勾
                tick = QPainterPath()
                tick.moveTo(box.left() + 0.22 * b, box.top() + 0.52 * b)
                tick.lineTo(box.left() + 0.44 * b, box.top() + 0.76 * b)
                tick.lineTo(box.left() + 0.84 * b, box.top() + 0.2 * b)
                p.strokePath(tick, QPen(TOMATO, 2.5 * k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            tx = L + 44 * k
            room = W - 44 * k - 30 * k
            text = fm.elidedText(it["text"], Qt.ElideRight, room)
            p.setFont(self.f_item)
            p.setPen(MUTED if it["done"] else INK)
            p.drawText(QPointF(tx, y - 3), text)
            if it["done"]:                                    # 刪除線
                sy = y - 3 - self.fp * 0.33
                p.setPen(QPen(MUTED, 2, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(tx - 2, sy), QPointF(tx + fm.horizontalAdvance(text) + 2, sy))
            if idx == self.hover:                             # 滑過出現 ×
                cx, cy, s = L + W - 16 * k, y - 3 - self.fp * 0.33, 5 * k
                p.setPen(QPen(TOMATO if self.hover_x else MUTED, 2, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
                p.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))

        # 最後一列：虛線輸入框（真的輸入框是 InputStrip，蓋在上面）＋ Add 按鈕
        y = self.line_y(3 + self.vis)
        btn = self._add_button()
        ul = self._input_rect()
        pen = QPen(INK, 2, Qt.SolidLine if self.typing else Qt.DashLine)
        if not self.typing:
            pen.setDashPattern([2.5, 2])
        p.setPen(pen)
        p.drawLine(QPointF(ul.left(), y - 3), QPointF(ul.right(), y - 3))
        if not self.ready:                                    # 滑動中輸入框藏起來，先畫提示字
            p.setFont(self.f_item)
            p.setPen(MUTED)
            p.drawText(QPointF(ul.left() + 2, y - 6), "Add a task...")
        p.setPen(Qt.NoPen)
        p.setBrush(INK)
        p.drawRoundedRect(btn, 8 * k, 8 * k)
        p.setFont(self.f_small)
        p.setPen(PAPER)
        p.drawText(btn, Qt.AlignCenter, "Add")

        # 項目太多：上下還有東西時，右邊畫小三角
        n = len(self.store.items)
        p.setPen(Qt.NoPen)
        p.setBrush(MUTED)
        s = 4 * k
        if self.scroll > 0:
            cx, cy = L + W - 16 * k, self.line_y(3) - lh + 6 * k
            p.drawPolygon(QPolygonF([QPointF(cx - s, cy + s), QPointF(cx + s, cy + s), QPointF(cx, cy)]))
        if self.scroll + self.vis < n:
            cx, cy = L + W - 16 * k, self.line_y(2 + self.vis) - 3 * k
            p.drawPolygon(QPolygonF([QPointF(cx - s, cy - s), QPointF(cx + s, cy - s), QPointF(cx, cy)]))
        p.end()

    # ================================================================== 滑鼠
    def _hit(self, pos) -> tuple[str, int]:
        x, y = pos.x() - self.L, pos.y()
        if not (0 <= x <= self.W):
            return "", -1
        if self._add_button().contains(pos):
            return "add", -1
        for i in range(self.vis):
            if self.line_y(2 + i) < y <= self.line_y(3 + i) + 1:
                idx = self.scroll + i
                if idx >= len(self.store.items):
                    return "", -1
                return ("delete" if x > self.W - 30 * self.k else "toggle"), idx
        return "", -1

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        if self.tab_rect().contains(pos):
            self.tabClicked.emit()
            return
        if not self.ready:
            return
        kind, idx = self._hit(pos)
        if kind == "toggle":
            checked = self.store.toggle(idx)
            self.update()
            self.toggled.emit(checked, self.store.all_done)
        elif kind == "delete":
            self.store.remove(idx)
            self.hover = -1
            self.relayout()
        elif kind == "add":
            if self.strip.edit.text().strip():
                self.add_current()
            else:
                self.strip.activateWindow()
                self.strip.edit.setFocus()

    def mouseMoveEvent(self, e) -> None:
        kind, idx = self._hit(e.position()) if self.ready else ("", -1)
        hover = idx if kind in ("toggle", "delete") else -1
        hx = kind == "delete"
        if (hover, hx) != (self.hover, self.hover_x):
            self.hover, self.hover_x = hover, hx
            self.update()
        over_tab = self.tab_rect().contains(e.position())
        self.setCursor(Qt.PointingHandCursor if (over_tab or kind) else Qt.ArrowCursor)

    def leaveEvent(self, e) -> None:
        if self.hover != -1:
            self.hover = -1
            self.update()

    def wheelEvent(self, e) -> None:
        n = len(self.store.items)
        if n <= self.vis:
            return
        step = -1 if e.angleDelta().y() > 0 else 1
        self.scroll = max(0, min(n - self.vis, self.scroll + step))
        self.update()

    # ================================================================== 新增
    def add_current(self) -> None:
        if self.store.add(self.strip.edit.text()):
            self.strip.edit.clear()
            self.relayout()
            self.scroll = max(0, len(self.store.items) - self.vis)   # 捲到最下面看得到新的那項
            self.update()

    def _on_focus(self, on: bool) -> None:
        self.typing = on
        self.update()
        if not on:
            self.typingDone.emit()
