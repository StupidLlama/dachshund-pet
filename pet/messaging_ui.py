"""v0.4 桌寵端的配對視窗（PairDialog）和訊息視窗（MessagesWindow）。米白紙風格、EvanHand。

網路的事都交給 CloudClient.call() 在背景做，結果由 app.py 的 _pump() 在主執行緒呼叫這裡的 callback。
"""
from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtCore import QRegularExpression, Qt, QTimer
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

from .cloud import CODE_LIFE_SEC, MAX_TEXT, PWA_URL, CloudClient
from .paper import hand_font, msg_font

STYLE = """
QDialog { background: #FFFDF6; }
QLabel { color: #1E1B16; }
QLabel#hint, QLabel#status { color: #6E675C; }
QLabel#error { color: #C0392B; }
QLabel#code { color: #E2553B; }
QLineEdit {
    color: #1E1B16; background: #FFFFFF; border: 2px solid #1E1B16; border-radius: 8px; padding: 2px 8px;
}
QTextBrowser { background: #FFFFFF; border: 2px solid #1E1B16; border-radius: 10px; padding: 4px; color: #1E1B16; }
QPushButton {
    color: #FFFDF6; background: #1E1B16; border: none; border-radius: 8px; padding: 4px 16px;
}
QPushButton:hover { background: #3A352D; }
QPushButton:disabled { background: #A8A196; }
QPushButton#light { color: #1E1B16; background: #FFFDF6; border: 2px solid #1E1B16; }
QPushButton#light:hover { background: #F3EEDF; }
QPushButton#danger { color: #C0392B; background: #FFFDF6; border: 2px solid #C0392B; }
"""

FLAGS = Qt.Dialog | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint


def fmt_code(code: str) -> str:
    return f"{code[:3]} {code[3:]}" if len(code) == 6 else code


def fmt_time(ts_ms: int, now: datetime | None = None) -> str:
    """24 小時制；今天只顯示時間，其他天加月/日。"""
    if not ts_ms:
        return ""
    t = datetime.fromtimestamp(ts_ms / 1000)
    now = now or datetime.now()
    return t.strftime("%H:%M") if t.date() == now.date() else t.strftime("%m/%d %H:%M")


def _label(text: str, px: float, name: str | None = None, wrap: bool = False):
    lab = QLabel(text)
    lab.setFont(hand_font(px))
    if name:
        lab.setObjectName(name)
    if wrap:
        lab.setWordWrap(True)
    return lab


def _button(text: str, fn, kind: str | None = None):
    b = QPushButton(text)
    b.setFont(hand_font(18))
    if kind:
        b.setObjectName(kind)
    b.clicked.connect(fn)
    return b


# ====================================================================== 配對
class PairDialog(QDialog):
    """沒配對：取名字 → 產生配對碼 / 輸入朋友的碼。已配對：連手機、再產生朋友的碼、改名、解除配對。"""

    def __init__(self, cloud: CloudClient, on_change=lambda: None, parent=None):
        super().__init__(parent, FLAGS)
        self.cloud = cloud
        self.on_change = on_change
        self.setWindowTitle("Pair")
        self.setStyleSheet(STYLE)
        self.setFont(hand_font(19))
        self.setMinimumWidth(420)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 14, 20, 16)
        self.lay.setSpacing(10)
        self.code = ""
        self.code_exp = 0.0
        self.status: QLabel | None = None
        self.count_lab: QLabel | None = None
        self.waiting = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._polls = 0
        self.show_home()

    # ---------------------------------------------------------------- 版面
    def _clear(self) -> None:
        while self.lay.count():
            item = self.lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
            elif item.layout() is not None:
                _clear_layout(item.layout())
        self.status = self.count_lab = None
        self.waiting = False

    def _status(self, text: str, error: bool = False) -> None:
        if self.status is not None:
            self.status.setObjectName("error" if error else "status")
            self.status.style().unpolish(self.status)      # 換了 objectName → 重新套用顏色
            self.status.style().polish(self.status)
            self.status.setText(text)

    def _row(self, *widgets) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for w in widgets:
            if w == "stretch":
                row.addStretch(1)
            else:
                row.addWidget(w)
        return box

    def show_home(self) -> None:
        self._clear()
        self.code = ""
        if self.cloud.paired:
            self._view_paired()
        else:
            self._view_new()

    def _view_new(self) -> None:
        self.lay.addWidget(_label("Pair with a friend", 28))
        self.lay.addWidget(_label("Send messages between your dog and your friend's dog or phone.", 15, "hint", True))
        self.lay.addWidget(_label("Your name", 18))
        self.name = QLineEdit(self.cloud.my_name)
        self.name.setMaxLength(20)
        self.name.setPlaceholderText("e.g. Evan")
        self.lay.addWidget(self.name)
        self.make_btn = _button("Make a code", self._make)
        self.lay.addWidget(self._row(self.make_btn, "stretch"))
        self.lay.addWidget(_label("Got a code from your friend?", 18))
        self.code_in = QLineEdit()
        self.code_in.setMaxLength(6)
        self.code_in.setPlaceholderText("123456")
        self.code_in.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,6}"), self.code_in))
        self.code_in.returnPressed.connect(self._join)
        self.join_btn = _button("Join", self._join, "light")
        self.lay.addWidget(self._row(self.code_in, self.join_btn))
        self.status = _label("", 15, "status", True)
        self.lay.addWidget(self.status)

    def _view_paired(self) -> None:
        partner = self.cloud.state["partner_name"]
        title = f"Paired with {partner}" if partner else "Paired! Waiting for your friend"
        self.lay.addWidget(_label(title, 26, wrap=True))
        self.lay.addWidget(_label("Your name", 18))
        self.name = QLineEdit(self.cloud.my_name)
        self.name.setMaxLength(20)
        self.lay.addWidget(self._row(self.name, _button("Save", self._save_name, "light")))
        self.lay.addWidget(self._row(_button("Link my phone", self._link_phone), "stretch"))
        self.lay.addWidget(self._row(_button("New code for my friend", self._friend_code, "light"), "stretch"))
        self.lay.addWidget(self._row(_button("Unpair", self._unpair, "danger"), "stretch",
                                     _button("Close", self.accept, "light")))
        self.status = _label("", 15, "status", True)
        self.lay.addWidget(self.status)
        if not partner:
            self.waiting = True

    def _view_code(self, code: str, for_phone: bool) -> None:
        self._clear()
        self.code = code
        self.code_exp = _now() + CODE_LIFE_SEC
        self.lay.addWidget(_label("Link your phone" if for_phone else "Your pair code", 26))
        big = _label(fmt_code(code), 48, "code")
        big.setAlignment(Qt.AlignCenter)
        big.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lay.addWidget(big)
        link = f'<a href="{PWA_URL}" style="color:#E2553B">{PWA_URL}</a>'
        if for_phone:
            text = f"On your phone, open<br>{link}<br>and type this code."
        else:
            text = ("Give this code to your friend.<br>They type it into their dog (right-click → Pair...)"
                    f"<br>or on their phone: {link}")
        info = _label(text, 16, wrap=True)
        info.setTextFormat(Qt.RichText)
        info.setOpenExternalLinks(True)
        self.lay.addWidget(info)
        self.count_lab = _label("", 15, "hint")
        self.lay.addWidget(self.count_lab)
        self.status = _label("" if for_phone else "Waiting for your friend...", 15, "status", True)
        self.lay.addWidget(self.status)
        self.lay.addWidget(self._row("stretch", _button("Done", self.show_home)))
        self.waiting = not for_phone and not self.cloud.state["partner_name"]
        self._tick()

    # ---------------------------------------------------------------- 動作
    def _busy(self, text: str = "Working...") -> None:
        self._status(text)

    def _make(self) -> None:
        name = self.name.text().strip()
        if not name:
            self._status("Type your name first", True)
            return
        self.make_btn.setEnabled(False)
        self._busy()
        self.cloud.call(self.cloud.create_pair, name, callback=self._made)

    def _made(self, value, err) -> None:
        self.on_change()
        if err:
            if hasattr(self, "make_btn"):
                self.make_btn.setEnabled(True)
            self._status(err, True)
            return
        self._view_code(value["code"], for_phone=False)

    def _join(self) -> None:
        code = self.code_in.text().strip()
        name = self.name.text().strip()
        if not name:
            self._status("Type your name first", True)
            return
        self.join_btn.setEnabled(False)
        self._busy()
        self.cloud.call(self.cloud.join, code, name, callback=self._joined)

    def _joined(self, value, err) -> None:
        self.on_change()
        if err:
            self.join_btn.setEnabled(True)
            self._status(err, True)
            return
        self.show_home()
        self._status(f"Paired with {value['partner']}! Say hi!" if value.get("partner") else "Paired!")

    def _link_phone(self) -> None:
        self._busy()
        self.cloud.call(self.cloud.make_link_code, callback=lambda v, e: self._got_code(v, e, True))

    def _friend_code(self) -> None:
        self._busy()
        self.cloud.call(self.cloud.friend_code, callback=lambda v, e: self._got_code(v, e, False))

    def _got_code(self, value, err, for_phone: bool) -> None:
        if err:
            self._status(err, True)
            return
        self._view_code(value["code"], for_phone)

    def _save_name(self) -> None:
        self._busy("Saving...")
        self.cloud.call(self.cloud.set_my_name, self.name.text(), callback=self._saved)

    def _saved(self, value, err) -> None:
        self.on_change()
        self._status(err or "Saved!", bool(err))

    def _unpair(self) -> None:
        partner = self.cloud.partner_name
        ans = QMessageBox.question(self, "Unpair", f"Stop sending messages with {partner}?")
        if ans != QMessageBox.Yes:
            return
        self._busy()
        self.cloud.call(self.cloud.unpair, callback=self._unpaired)

    def _unpaired(self, value, err) -> None:
        self.on_change()
        self.show_home()

    # ---------------------------------------------------------------- 每秒
    def _tick(self) -> None:
        if self.count_lab is not None and self.code:
            left = int(self.code_exp - _now())
            self.count_lab.setText(f"Expires in {left // 60}:{left % 60:02d}" if left > 0 else
                                   "This code expired. Press Done and make a new one.")
        if self.waiting and self.isVisible():
            self._polls += 1
            if self._polls % 3 == 0:                 # 每 3 秒看一次朋友加入了沒
                self.cloud.call(self.cloud.refresh_names, callback=self._names)

    def _names(self, value, err) -> None:
        if not err and value and value.get("partner") and self.waiting:
            self.waiting = False
            self.on_change()
            self._status(f"Paired with {value['partner']}!")


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()
            item.widget().deleteLater()


def _now() -> float:
    import time
    return time.time()


# ====================================================================== 訊息視窗
class MessagesWindow(QDialog):
    """最近 20 則（兩邊的都有）+ 回覆。"""

    def __init__(self, cloud: CloudClient, parent=None):
        super().__init__(parent, FLAGS)
        self.cloud = cloud
        self.setWindowTitle("Messages")
        self.setStyleSheet(STYLE)
        self.setFont(hand_font(19))
        self.resize(420, 520)
        self.items: list[dict] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(8)
        self.title = _label("", 26)
        self.sub = _label("", 15, "hint")
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        self.view = QTextBrowser()
        self.view.setFont(msg_font(19))
        self.view.setOpenExternalLinks(False)
        lay.addWidget(self.view, 1)
        self.edit = QLineEdit()
        self.edit.setFont(msg_font(19))
        self.edit.setMaxLength(MAX_TEXT)
        self.edit.setPlaceholderText("Write a message...")
        self.edit.returnPressed.connect(self.send)
        self.edit.textChanged.connect(self._count)
        self.counter = _label(f"0/{MAX_TEXT}", 14, "hint")
        self.send_btn = _button("Send", self.send)
        row = QWidget()
        r = QHBoxLayout(row)
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(8)
        r.addWidget(self.edit, 1)
        r.addWidget(self.counter)
        r.addWidget(self.send_btn)
        lay.addWidget(row)
        self.status = _label("", 15, "status", True)
        lay.addWidget(self.status)
        self.refresh_title()

    def refresh_title(self, online: bool | None = None) -> None:
        self.title.setText(f"Messages with {self.cloud.partner_name}")
        if online is not None:
            self.sub.setText("" if online else "Offline - messages will send when you're back online")

    def show_window(self, focus_reply: bool = False) -> None:
        self.refresh_title()
        self.show()
        self.raise_()
        self.activateWindow()
        if focus_reply:
            self.edit.setFocus()
        self.load()

    def load(self) -> None:
        self.status.setText("Loading...")
        self.cloud.call(self.cloud.history, callback=self._loaded)

    def _loaded(self, value, err) -> None:
        if err:
            self.status.setText(err)
            return
        self.status.setText("" if value else "No messages yet. Say hi!")
        self.items = list(value or [])
        self._render()

    def add(self, msg: dict) -> None:
        """串流收到的新訊息（視窗開著時）。"""
        if any(m["id"] == msg["id"] for m in self.items if m.get("id")):
            return
        self.items.append(msg)
        self.items = self.items[-40:]
        self.status.setText("")
        self._render()

    def _render(self) -> None:
        parts = []
        for m in self.items:
            mine = m.get("mine")
            who = "Me" if mine else html.escape(m.get("name", ""))
            color = "#1E1B16" if mine else "#E2553B"
            align = "right" if mine else "left"
            parts.append(
                f'<p align="{align}" style="margin:4px 2px 10px 2px;">'
                f'<span style="color:{color};">{who}</span> '
                f'<span style="color:#A8A196; font-size:13px;">{fmt_time(m.get("ts", 0))}</span><br>'
                f'{html.escape(m.get("text", ""))}</p>')
        self.view.setHtml("".join(parts))
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _count(self, text: str) -> None:
        self.counter.setText(f"{len(text)}/{MAX_TEXT}")

    def send(self) -> None:
        text = self.edit.text().strip()
        if not text:
            return
        self.send_btn.setEnabled(False)
        self.status.setText("Sending...")
        self.cloud.call(self.cloud.send, text, callback=self._sent)

    def _sent(self, value, err) -> None:
        self.send_btn.setEnabled(True)
        if err:
            self.status.setText(err)
            return
        self.status.setText("Sent!")
        self.edit.clear()
        self.add({"id": value.get("id", ""), "mine": True, "name": "Me", "text": value["text"],
                  "ts": int(_now() * 1000)})
