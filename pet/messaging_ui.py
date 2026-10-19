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
    """四個入口（右鍵選單直接開對的那一頁）：
        link    📱 Link my phone        你自己的手機（不用先有朋友）
        test    🧪 Test with my phone   手機假裝成朋友，訊息會跑到自己的狗頭上
        invite  💌 Invite a friend      給朋友的碼
        join    🔑 I have a code        輸入朋友給的碼（朋友那邊用）
        settings ⚙ Pairing              改名、解除配對
    還沒有房間時，link / test / invite 會先問名字。
    """

    TITLES = {"link": "📱 Link my phone", "test": "🧪 Test with my phone", "invite": "💌 Invite a friend",
              "join": "🔑 Join a friend's dog", "settings": "⚙ Pairing"}

    def __init__(self, cloud: CloudClient, on_change=lambda: None, parent=None):
        super().__init__(parent, FLAGS)
        self.cloud = cloud
        self.on_change = on_change
        self.setWindowTitle("Pair")
        self.setStyleSheet(STYLE)
        self.setFont(hand_font(19))
        self.setMinimumWidth(440)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(22, 14, 22, 16)
        self.lay.setSpacing(10)
        self.mode = "link"
        self.code = ""
        self.code_exp = 0.0
        self.status: QLabel | None = None
        self.count_lab: QLabel | None = None
        self.waiting = False
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
        self.waiting = False
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

    def open_mode(self, mode: str) -> None:
        """右鍵選單呼叫：開到指定那一頁。"""
        self.mode = mode
        self._clear()
        self.lay.addWidget(_label(self.TITLES[mode], 28))
        if mode == "join":
            self._view_join()
        elif mode == "settings":
            self._view_settings()
        elif not self.cloud.paired:
            self._view_name_first()
        else:
            self._request_code()

    show_home = open_mode   # 相容舊的呼叫

    # ---- 第一次：先問名字
    def _view_name_first(self) -> None:
        intro = {
            "link": "Connect your phone so you can send messages from it.",
            "test": "Your phone pretends to be a friend. Messages you send from it pop up on your own dog.",
            "invite": "Make a code for your friend. They type it into their dog or their phone.",
        }[self.mode]
        self.lay.addWidget(_label(intro, 16, "hint", True))
        self.lay.addWidget(_label("First, what's your name?", 18))
        self.name = QLineEdit(self.cloud.my_name)
        self.name.setMaxLength(20)
        self.name.setPlaceholderText("e.g. Evan")
        self.name.returnPressed.connect(self._request_code)
        self.go_btn = _button("Get a code", self._request_code)
        self.lay.addWidget(self._row(self.name, self.go_btn))
        self._add_status()

    def _request_code(self) -> None:
        name = self.name.text().strip() if self.name is not None and self.mode != "settings" else ""
        if not self.cloud.paired and not name:
            self._status("Type your name first", True)
            return
        if hasattr(self, "go_btn"):
            self.go_btn.setEnabled(False)
        if self.status is None:
            self._add_status()
        self._status("Working...")
        fn = {"link": self.cloud.link_phone, "test": self.cloud.test_phone, "invite": self.cloud.create_pair}[self.mode]
        self.cloud.call(fn, name, callback=self._got_code)

    def _got_code(self, value, err) -> None:
        self.on_change()
        if err:
            if hasattr(self, "go_btn"):
                self.go_btn.setEnabled(True)
            self._status(err, True)
            return
        self._view_code(value["code"])

    # ---- 顯示碼
    def _view_code(self, code: str) -> None:
        mode = self.mode
        self._clear()
        self.code = code
        self.code_exp = _now() + CODE_LIFE_SEC
        self.lay.addWidget(_label(self.TITLES[mode], 28))
        link = f'<a href="{PWA_URL}" style="color:#E2553B">{PWA_URL.replace("https://", "")}</a>'
        if mode == "link":
            steps = [f"On your phone, open {link}", "Type this code and your name, then tap <b>Join</b>",
                     "Done! Messages you send from your phone go to your friend's dog"]
        elif mode == "test":
            steps = [f"On your phone, open {link}", "Type this code and any name (like <b>Phone</b>), then tap <b>Join</b>",
                     "Send a message from your phone and watch your dog!",
                     "When you're done: phone <b>⋯</b> → <b>Unpair</b>, then use 💌 Invite a friend"]
        else:
            steps = ["Send this code to your friend",
                     f"They right-click their dog → 🔑 <b>I have a code</b>, or open {link} on their phone",
                     "When they join, you can start sending messages"]
        big = _label(fmt_code(code), 52, "code")
        big.setAlignment(Qt.AlignCenter)
        big.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lay.addWidget(big)
        self.count_lab = _label("", 15, "hint")
        self.count_lab.setAlignment(Qt.AlignCenter)
        self.lay.addWidget(self.count_lab)
        self._steps(steps)
        self._add_status("Waiting for your phone..." if mode != "invite" else "Waiting for your friend...")
        self.lay.addWidget(self._row("stretch", _button("Close", self.accept, "light")))
        self.waiting = True
        self._before = None                          # 第一次輪詢的結果 = 基準
        self.cloud.call(self.cloud.who_joined, callback=self._who)
        self._tick()

    # ---- 朋友那邊：輸入碼
    def _view_join(self) -> None:
        self.lay.addWidget(_label("Type the code your friend gave you.", 16, "hint", True))
        if self.cloud.paired:
            who = self.cloud.partner_name if self.cloud.has_partner else "your phone"
            warn = _label(f"Joining a new code leaves your current pair with {who}.", 15, "error", True)
            self.lay.addWidget(warn)
        self.code_in = QLineEdit()
        self.code_in.setMaxLength(6)
        self.code_in.setPlaceholderText("123456")
        self.code_in.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,6}"), self.code_in))
        f = hand_font(30)
        self.code_in.setFont(f)
        self.code_in.setAlignment(Qt.AlignCenter)
        self.lay.addWidget(self.code_in)
        self.lay.addWidget(_label("Your name", 18))
        self.name = QLineEdit(self.cloud.my_name)
        self.name.setMaxLength(20)
        self.name.setPlaceholderText("e.g. Amy")
        self.name.returnPressed.connect(self._join)
        self.join_btn = _button("Join", self._join)
        self.lay.addWidget(self._row(self.name, self.join_btn))
        self._add_status()

    def _join(self) -> None:
        code = self.code_in.text().strip()
        name = self.name.text().strip()
        if len(code) != 6:
            self._status("The code has 6 numbers", True)
            return
        if not name:
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
        self.lay.addWidget(_label("🎉 Paired!", 28))
        who = value.get("partner") or "your friend"
        self.lay.addWidget(_label(f"You can now send messages with {who}. Right-click your dog → "
                                  f"💌 Messages.", 17, wrap=True))
        self.lay.addWidget(self._row("stretch", _button("Close", self.accept)))

    # ---- 設定：改名、解除配對
    def _view_settings(self) -> None:
        c = self.cloud
        if not c.paired:
            state = "Not paired yet."
        elif c.has_partner:
            state = f"Paired with {c.partner_name}" + (" (test phone)" if c.test_mode else "")
        else:
            state = "No friend yet. Use 💌 Invite a friend."
        self.lay.addWidget(_label(state, 17, "hint", True))
        if c.paired:
            self.lay.addWidget(_label("Your name", 18))
            self.name = QLineEdit(c.my_name)
            self.name.setMaxLength(20)
            self.lay.addWidget(self._row(self.name, _button("Save", self._save_name, "light")))
            self.lay.addWidget(self._row(_button("Unpair", self._unpair, "danger"), "stretch",
                                         _button("Close", self.accept, "light")))
        else:
            self.lay.addWidget(self._row("stretch", _button("Close", self.accept, "light")))
        self._add_status()

    def _save_name(self) -> None:
        self._status("Saving...")
        self.cloud.call(self.cloud.set_my_name, self.name.text(), callback=self._saved)

    def _saved(self, value, err) -> None:
        self.on_change()
        self._status(err or "Saved!", bool(err))

    def _unpair(self) -> None:
        who = self.cloud.partner_name if self.cloud.has_partner else "your phone"
        ans = QMessageBox.question(self, "Unpair", f"Stop sending messages with {who}? "
                                   "Your phone and your friend will need a new code.")
        if ans != QMessageBox.Yes:
            return
        self._status("Working...")
        self.cloud.call(self.cloud.unpair, callback=self._unpaired)

    def _unpaired(self, value, err) -> None:
        self.on_change()
        self.open_mode("settings")
        self._status("Unpaired.")

    # ---------------------------------------------------------------- 每秒
    def _tick(self) -> None:
        if self.count_lab is not None and self.code:
            left = int(self.code_exp - _now())
            self.count_lab.setText(f"Code works for {left // 60}:{left % 60:02d}" if left > 0 else
                                   "This code expired. Close this and get a new one.")
        if self.waiting and self.isVisible():
            self._polls += 1
            if self._polls % 3 == 0:                 # 每 3 秒看一次有沒有人加入
                self.cloud.call(self.cloud.who_joined, callback=self._who)

    def _who(self, value, err) -> None:
        """有人用這組碼加入了嗎：自己的手機 → my_phones 變多；朋友 / 測試手機 → 對方名字出現或改變。"""
        if err or not value or not self.waiting:
            return
        if self._before is None:
            self._before = value
            return
        if self.mode == "link" and value["my_phones"] > self._before["my_phones"]:
            self.waiting = False
            self.on_change()
            self._status("🎉 Your phone is linked!")
        elif self.mode in ("invite", "test") and value["partner"] and value["partner"] != self._before["partner"]:
            self.waiting = False
            self.on_change()
            extra = " Send a message from your phone and watch your dog!" if self.mode == "test" else ""
            self._status(f"🎉 {value['partner']} joined!{extra}")


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
