"""v0.4.2 桌寵端的配對視窗（PairDialog）和訊息視窗（MessagesWindow）。米白紙風格、EvanHand。

網路的事都交給 CloudClient.call() 在背景做，結果由 app.py 的 _pump() 在主執行緒呼叫這裡的 callback。
"""
from __future__ import annotations

import html
import time
from datetime import datetime

from PySide6.QtCore import QRegularExpression, Qt, QTimer
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QTextBrowser, QVBoxLayout, QWidget)

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
QListWidget { background: #FFFDF6; border: 2px solid #1E1B16; border-radius: 10px; padding: 4px; color: #1E1B16; }
QListWidget::item { padding: 6px 6px; border-bottom: 1px solid #BFD6F2; }
QListWidget::item:selected { background: #F7E6B8; color: #1E1B16; }
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


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()
            item.widget().deleteLater()


def _now() -> float:
    return time.time()


def _link() -> str:
    return f'<a href="{PWA_URL}" style="color:#E2553B">{PWA_URL.replace("https://", "")}</a>'


# ====================================================================== 配對
class PairDialog(QDialog):
    """右鍵「📱 Phone & friends」的每一項都開到對的那一頁：
        link      📱 Link my phone      你的手機加入你的「家」（不用先有朋友）
        invite    💌 Invite a friend    給朋友的碼（朋友在他的狗或手機輸入）
        join      🔑 I have a code      輸入朋友給的碼（一直都能用，會多一個聊天室）
        test      🧪 Test chat          自己跟自己聊：手機傳的訊息會跑到自己的狗頭上
        settings  ⚙ Settings           名字、連了幾支手機、聊天室（離開）、全部重來
    還沒有「家」時，link / invite / test 會先問名字。
    """

    TITLES = {"link": "📱 Link my phone", "invite": "💌 Invite a friend", "join": "🔑 I have a code",
              "test": "🧪 Test chat", "settings": "⚙ Phone & friends"}

    def __init__(self, cloud: CloudClient, on_change=lambda: None, parent=None):
        super().__init__(parent, FLAGS)
        self.cloud = cloud
        self.on_change = on_change
        self.setWindowTitle("Phone & friends")
        self.setStyleSheet(STYLE)
        self.setFont(hand_font(19))
        self.setMinimumWidth(460)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(22, 14, 22, 16)
        self.lay.setSpacing(10)
        self.mode = "link"
        self.code = ""
        self.code_exp = 0.0
        self.status: QLabel | None = None
        self.count_lab: QLabel | None = None
        self.waiting = ""                    # "phone" / "friend" / ""：正在等誰加入
        self.wait_room = ""
        self.phones_before = 0
        self.name = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._polls = 0

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
        self.waiting = ""
        self.code = ""

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

    def _steps(self, lines: list[str]) -> None:
        """編號步驟（真的是先後順序）。"""
        text = "<br>".join(f"<b>{i}.</b> {t}" for i, t in enumerate(lines, 1))
        lab = _label(text, 17, wrap=True)
        lab.setTextFormat(Qt.RichText)
        lab.setOpenExternalLinks(True)
        self.lay.addWidget(lab)

    def _add_status(self, text: str = "") -> None:
        self.status = _label(text, 15, "status", True)
        self.lay.addWidget(self.status)

    def _close_row(self) -> None:
        self.lay.addWidget(self._row("stretch", _button("Close", self.accept, "light")))

    def open_mode(self, mode: str) -> None:
        """右鍵選單呼叫：開到指定那一頁。"""
        self.mode = mode
        self._clear()
        self.lay.addWidget(_label(self.TITLES[mode], 28))
        if mode == "join":
            self._view_join()
        elif mode == "settings":
            self._view_settings()
        elif not self.cloud.linked:
            self._view_name_first()
        else:
            self._go()

    show_home = open_mode   # 相容舊的呼叫

    # ---- 第一次：先問名字
    def _view_name_first(self) -> None:
        intro = {
            "link": "Connect your phone. Then you can chat with friends and edit your to-do list from it.",
            "invite": "Make a code for your friend. They type it into their dog or their phone.",
            "test": "Your phone pretends to be a friend. Messages you send from it pop up on your own dog.",
        }[self.mode]
        self.lay.addWidget(_label(intro, 16, "hint", True))
        self.lay.addWidget(_label("First, what's your name?", 18))
        self.name = QLineEdit(self.cloud.my_name)
        self.name.setMaxLength(20)
        self.name.setPlaceholderText("e.g. Evan")
        self.name.returnPressed.connect(self._go)
        self.go_btn = _button("Next", self._go)
        self.lay.addWidget(self._row(self.name, self.go_btn))
        self._add_status()

    def _go(self) -> None:
        name = self.name.text().strip() if (self.name is not None and not self.cloud.linked) else ""
        if not self.cloud.linked and not name:
            self._status("Type your name first", True)
            return
        if hasattr(self, "go_btn"):
            self.go_btn.setEnabled(False)
        if self.status is None:
            self._add_status()
        self._status("Working...")
        if self.mode == "link":
            self.cloud.call(self.cloud.link_code, name, callback=self._got_link)
        elif self.mode == "invite":
            self.cloud.call(self.cloud.invite_code, name, callback=self._got_invite)
        else:
            self.cloud.call(self.cloud.test_chat, name, callback=self._got_test)

    def _failed(self, err: str) -> None:
        if hasattr(self, "go_btn"):
            self.go_btn.setEnabled(True)
        self._status(err, True)

    def _big_code(self, code: str) -> None:
        self.code = code
        self.code_exp = _now() + CODE_LIFE_SEC
        big = _label(fmt_code(code), 52, "code")
        big.setAlignment(Qt.AlignCenter)
        big.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lay.addWidget(big)
        self.count_lab = _label("", 15, "hint")
        self.count_lab.setAlignment(Qt.AlignCenter)
        self.lay.addWidget(self.count_lab)

    def _got_link(self, value, err) -> None:
        self.on_change()
        if err:
            return self._failed(err)
        self._clear()
        self.lay.addWidget(_label(self.TITLES["link"], 28))
        self._big_code(value["code"])
        self._steps([f"On your phone, open {_link()}", "Type this code and tap <b>Join</b>",
                     "Your phone shows all your chats and your to-do list"])
        self._add_status("Waiting for your phone...")
        self._close_row()
        self.waiting, self.phones_before = "phone", self.cloud.phones()
        self._tick()

    def _got_invite(self, value, err) -> None:
        self.on_change()
        if err:
            return self._failed(err)
        self._clear()
        self.lay.addWidget(_label(self.TITLES["invite"], 28))
        self._big_code(value["code"])
        self._steps(["Send this code to your friend",
                     f"They right-click their dog → 🔑 <b>I have a code</b>, or open {_link()} on their phone",
                     "When they join, a new chat shows up"])
        self._add_status("Waiting for your friend...")
        self._close_row()
        self.waiting, self.wait_room = "friend", value.get("room", "")
        self._tick()

    def _got_test(self, value, err) -> None:
        self.on_change()
        if err:
            return self._failed(err)
        if self.cloud.phones() == 0:                 # 手機還沒連：順便給連手機的碼
            self.cloud.call(self.cloud.link_code, "", callback=self._got_test_link)
            return
        self._clear()
        self.lay.addWidget(_label(self.TITLES["test"], 28))
        self._steps(["On your phone, open the chat called <b>Test phone</b>",
                     "Send a message and watch your dog!"])
        self._add_status()
        self._status("Ready! Your test chat is on your phone.")
        self._close_row()

    def _got_test_link(self, value, err) -> None:
        if err:
            return self._failed(err)
        self._clear()
        self.lay.addWidget(_label(self.TITLES["test"], 28))
        self.lay.addWidget(_label("First link your phone:", 17))
        self._big_code(value["code"])
        self._steps([f"On your phone, open {_link()}", "Type this code and tap <b>Join</b>",
                     "Open the chat called <b>Test phone</b>", "Send a message and watch your dog!"])
        self._add_status("Waiting for your phone...")
        self._close_row()
        self.waiting, self.phones_before = "phone", 0
        self._tick()

    # ---- 輸入朋友的碼（一直都能用）
    def _view_join(self) -> None:
        self.lay.addWidget(_label("Type the code your friend gave you. You'll get a new chat with them.",
                                  16, "hint", True))
        self.code_in = QLineEdit()
        self.code_in.setMaxLength(6)
        self.code_in.setPlaceholderText("123456")
        self.code_in.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,6}"), self.code_in))
        self.code_in.setFont(hand_font(30))
        self.code_in.setAlignment(Qt.AlignCenter)
        self.lay.addWidget(self.code_in)
        if not self.cloud.linked:
            self.lay.addWidget(_label("Your name", 18))
        self.name = QLineEdit(self.cloud.my_name)
        self.name.setMaxLength(20)
        self.name.setPlaceholderText("e.g. Amy")
        self.name.returnPressed.connect(self._join)
        self.join_btn = _button("Join", self._join)
        if self.cloud.linked:
            self.name.hide()
            self.lay.addWidget(self._row("stretch", self.join_btn))
        else:
            self.lay.addWidget(self._row(self.name, self.join_btn))
        self.code_in.returnPressed.connect(self._join)
        self._add_status()

    def _join(self) -> None:
        code = self.code_in.text().strip()
        name = self.name.text().strip()
        if len(code) != 6:
            self._status("The code has 6 numbers", True)
            return
        if not self.cloud.linked and not name:
            self._status("Type your name too", True)
            return
        self.join_btn.setEnabled(False)
        self._status("Working...")
        self.cloud.call(self.cloud.join, code, name, callback=self._joined)

    def _joined(self, value, err) -> None:
        self.on_change()
        if err:
            self.join_btn.setEnabled(True)
            self._status(err, True)
            return
        self._clear()
        self.lay.addWidget(_label("🎉 New chat!", 28))
        who = value.get("partner") or "your friend"
        self.lay.addWidget(_label(f"You can now send messages with {who}. Right-click your dog → "
                                  f"💌 Messages.", 17, wrap=True))
        self.lay.addWidget(self._row("stretch", _button("Close", self.accept)))

    # ---- 設定：名字、手機、聊天室、全部重來
    def _view_settings(self) -> None:
        c = self.cloud
        if not c.linked:
            self.lay.addWidget(_label("Nothing linked yet. Start with 📱 Link my phone or 💌 Invite a friend.",
                                      16, "hint", True))
            self._close_row()
            return
        self.lay.addWidget(_label("Your name", 18))
        self.name = QLineEdit(c.my_name)
        self.name.setMaxLength(20)
        self.lay.addWidget(self._row(self.name, _button("Save", self._save_name, "light")))
        phones = c.phones()
        self.lay.addWidget(_label(f"📱 Phones linked: {phones}", 18))
        if phones:
            self.lay.addWidget(self._row(_button("Unlink my phones", self._unlink, "light"), "stretch"))
        rooms = c.rooms()
        self.lay.addWidget(_label("💌 Chats" if rooms else "💌 No chats yet", 18))
        for r in rooms:
            label = _label(r["partner"] + (" (test)" if r["test"] else ""), 17)
            self.lay.addWidget(self._row(label, "stretch",
                                         _button("Leave", lambda _=False, rid=r["id"]: self._leave(rid), "danger")))
        self.lay.addWidget(self._row(_button("Start over", self._start_over, "danger"), "stretch",
                                     _button("Close", self.accept, "light")))
        self._add_status()

    def _save_name(self) -> None:
        self._status("Saving...")
        self.cloud.call(self.cloud.set_my_name, self.name.text(), callback=self._saved)

    def _saved(self, value, err) -> None:
        self.on_change()
        self._status(err or "Saved!", bool(err))

    def _unlink(self) -> None:
        ans = QMessageBox.question(self, "Unlink phones", "Unlink all your phones? They'll need a new code.")
        if ans == QMessageBox.Yes:
            self.cloud.call(self.cloud.unlink_phones, callback=lambda v, e: self._after(e, "Phones unlinked."))

    def _leave(self, rid: str) -> None:
        who = self.cloud.partner_of(rid)
        ans = QMessageBox.question(self, "Leave chat", f"Leave the chat with {who}? Your phone leaves it too.")
        if ans == QMessageBox.Yes:
            self.cloud.call(self.cloud.leave_room, rid, callback=lambda v, e: self._after(e, f"Left the chat with {who}."))

    def _start_over(self) -> None:
        ans = QMessageBox.question(self, "Start over", "Leave all chats and unlink everything?")
        if ans == QMessageBox.Yes:
            self.cloud.call(self.cloud.reset, callback=lambda v, e: self._after(e, "Done. Everything is unlinked."))

    def _after(self, err, text: str) -> None:
        self.on_change()
        self.open_mode("settings")
        self._status(err or text, bool(err))

    # ---------------------------------------------------------------- 每秒
    def _tick(self) -> None:
        if self.count_lab is not None and self.code:
            left = int(self.code_exp - _now())
            self.count_lab.setText(f"Code works for {left // 60}:{left % 60:02d}" if left > 0 else
                                   "This code expired. Close this and get a new one.")
        if not self.waiting or not self.isVisible():
            return
        if self.waiting == "phone":                  # 家串流會即時更新手機數，不用打網路
            if self.cloud.phones() > self.phones_before:
                self.waiting = ""
                self.on_change()
                self._status("🎉 Your phone is linked!" + (" Open the Test phone chat on it." if self.mode == "test" else ""))
            return
        self._polls += 1
        if self._polls % 3 == 0:                     # 朋友：每 3 秒看一次名字出現了沒
            self.cloud.call(self.cloud.refresh_names, callback=self._names)

    def _names(self, value, err) -> None:
        if err or self.waiting != "friend":
            return
        for r in self.cloud.rooms():
            if r["id"] == self.wait_room:
                self.waiting = ""
                self.on_change()
                self._status(f"🎉 {r['partner']} joined! Right-click your dog → 💌 Messages.")


# ====================================================================== 訊息視窗
class MessagesWindow(QDialog):
    """左邊：所有聊天室（朋友）；右邊：最近 20 則 + 回覆。"""

    def __init__(self, cloud: CloudClient, parent=None):
        super().__init__(parent, FLAGS)
        self.cloud = cloud
        self.setWindowTitle("Messages")
        self.setStyleSheet(STYLE)
        self.setFont(hand_font(19))
        self.resize(640, 520)
        self.room = ""
        self.items: list[dict] = []
        self.unread: dict[str, int] = {}
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(12)
        # 左：聊天室列表
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        ll.addWidget(_label("💌 Chats", 22))
        self.list = QListWidget()
        self.list.setFont(hand_font(19))
        self.list.setFixedWidth(180)
        self.list.currentRowChanged.connect(self._picked)
        ll.addWidget(self.list, 1)
        outer.addWidget(left)
        # 右：聊天
        right = QWidget()
        lay = QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.title = _label("", 26)
        self.sub = _label("", 15, "hint", True)
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
        outer.addWidget(right, 1)
        self.refresh_rooms()

    # ---------------------------------------------------------------- 聊天室列表
    def refresh_rooms(self, online: bool | None = None) -> None:
        rooms = self.cloud.rooms()
        self._rooms = rooms
        self.list.blockSignals(True)
        self.list.clear()
        current = 0
        for i, rm in enumerate(rooms):
            n = self.unread.get(rm["id"], 0)
            text = rm["partner"] + (" (test)" if rm["test"] else "") + (f"  ● {n}" if n else "")
            self.list.addItem(QListWidgetItem(text))
            if rm["id"] == self.room:
                current = i
        if rooms:
            self.list.setCurrentRow(current)         # 只是重畫列表：不要重新載入訊息
        self.list.blockSignals(False)
        if rooms:
            if self.room not in {r["id"] for r in rooms}:
                self._picked(current)
        else:
            self.room = ""
            self.title.setText("No chats yet")
            self.sub.setText("Right-click your dog → 📱 Phone & friends → 💌 Invite a friend")
            self.view.setHtml("")
        self.send_btn.setEnabled(bool(rooms))
        if online is not None:
            self.status.setText("" if online else "Offline - messages will send when you're back online")

    refresh_title = refresh_rooms               # 舊名字

    def _picked(self, row: int) -> None:
        rooms = getattr(self, "_rooms", [])
        if not (0 <= row < len(rooms)):
            return
        rm = rooms[row]
        self.room = rm["id"]
        self.unread.pop(self.room, None)
        self.title.setText(f"{rm['partner']}" + (" (test)" if rm["test"] else ""))
        self.sub.setText("Messages from your phone in this chat pop up on your dog." if rm["test"] else "")
        self.load()

    def show_window(self, room: str = "", focus_reply: bool = False) -> None:
        if room:
            self.room = room
        self.refresh_rooms()
        self.show()
        self.raise_()
        self.activateWindow()
        if focus_reply:
            self.edit.setFocus()

    # ---------------------------------------------------------------- 訊息
    def load(self) -> None:
        if not self.room:
            return
        self.status.setText("Loading...")
        rid = self.room
        self.cloud.call(self.cloud.history, rid, callback=lambda v, e: self._loaded(rid, v, e))

    def _loaded(self, rid: str, value, err) -> None:
        if rid != self.room:
            return
        if err:
            self.status.setText(err)
            return
        self.status.setText("" if value else "No messages yet. Say hi!")
        self.items = list(value or [])
        self._render()

    def add(self, msg: dict) -> None:
        """串流收到的新訊息（視窗開著時）。別的聊天室的 → 列表上加紅點。"""
        if msg.get("room") and msg["room"] != self.room:
            self.unread[msg["room"]] = self.unread.get(msg["room"], 0) + 1
            self.refresh_rooms()
            return
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
        if not text or not self.room:
            return
        self.send_btn.setEnabled(False)
        self.status.setText("Sending...")
        self.cloud.call(self.cloud.send, self.room, text, callback=self._sent)

    def _sent(self, value, err) -> None:
        self.send_btn.setEnabled(True)
        if err:
            self.status.setText(err)
            return
        self.status.setText("Sent!")
        self.edit.clear()
        self.add({"room": value.get("room", self.room), "id": value.get("id", ""), "mine": True, "name": "Me",
                  "text": value["text"], "ts": int(_now() * 1000)})
