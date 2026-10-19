"""右鍵「Settings...」：拉出清單的時間（24 小時制）、番茄鐘的專心 / 休息時間。米白紙風格、EvanHand。"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QSpinBox, QVBoxLayout, QWidget)

from .paper import hand_font
from .settings import Settings

STYLE = """
QDialog { background: #FFFDF6; }
QLabel { color: #1E1B16; }
QLabel#hint { color: #6E675C; }
QComboBox, QSpinBox {
    color: #1E1B16; background: #FFFFFF; border: 2px solid #1E1B16; border-radius: 8px; padding: 1px 6px;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView { background: #FFFDF6; color: #1E1B16; selection-background-color: #E2553B; }
QPushButton {
    color: #FFFDF6; background: #1E1B16; border: none; border-radius: 8px; padding: 3px 16px;
}
QPushButton:hover { background: #3A352D; }
"""


def parse_hhmm(text: str, default=(8, 0)) -> tuple[int, int]:
    try:
        h, m = (int(x) for x in str(text).split(":"))
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except (ValueError, TypeError):
        pass
    return default


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setStyleSheet(STYLE)
        self.setFont(hand_font(19))

        title = QLabel("Settings")
        title.setFont(hand_font(26))

        h, m = parse_hhmm(settings.get("wake_time"))
        self.hour = QComboBox()
        self.hour.addItems([f"{i:02d}" for i in range(24)])
        self.hour.setCurrentIndex(h)
        self.minute = QComboBox()
        self.minute.addItems([f"{i:02d}" for i in range(0, 60, 5)])
        self.minute.setCurrentIndex(m // 5)
        wake = QWidget()
        row = QHBoxLayout(wake)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self.hour)
        row.addWidget(QLabel(":"))
        row.addWidget(self.minute)

        self.focus = QSpinBox()
        self.focus.setRange(1, 120)
        self.focus.setValue(int(settings.get("focus_min")))
        self.focus.setSuffix(" min")
        self.brk = QSpinBox()
        self.brk.setRange(1, 60)
        self.brk.setValue(int(settings.get("break_min")))
        self.brk.setSuffix(" min")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(10)
        form.addRow("Pull out my list at", wake)
        form.addRow("Work time", self.focus)
        form.addRow("Break time", self.brk)

        hint = QLabel("The new work and break time start with the next timer.")
        hint.setObjectName("hint")
        hint.setFont(hand_font(15))
        hint.setWordWrap(True)

        buttons = QDialogButtonBox()
        buttons.addButton("Save", QDialogButtonBox.AcceptRole)
        buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 14)
        lay.setSpacing(10)
        lay.addWidget(title)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(buttons)

    def wake_text(self) -> str:
        return f"{self.hour.currentIndex():02d}:{self.minute.currentIndex() * 5:02d}"

    def accept(self) -> None:
        old = self.settings.get("wake_time")
        new = self.wake_text()
        self.settings.data["focus_min"] = self.focus.value()
        self.settings.data["break_min"] = self.brk.value()
        self.settings.data["wake_time"] = new
        if new != old:
            # 改成今天還沒到的時間 → 今天到了還會再拉一次
            h, m = parse_hhmm(new)
            now = datetime.now()
            if (now.hour, now.minute) < (h, m):
                self.settings.data["last_pull_date"] = ""
        self.settings.save()
        super().accept()
