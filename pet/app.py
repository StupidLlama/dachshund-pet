"""組裝：設定、圖片、桌寵視窗、右鍵選單、系統匣圖示、取名；
v0.3：待辦清單、每天起床拉清單、番茄鐘、Settings 視窗。"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QObject, QPoint, QTimer
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QFont, QIcon, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox, QSystemTrayIcon

from . import convenience as conv
from .fonts import load_custom_font
from .pet_window import PetWindow
from .pomodoro import Ding, TomatoWindow
from .settings import EXTRAS, Settings, assets_dir, data_dir
from .settings_dialog import SettingsDialog, parse_hhmm
from .sprites import BASE_SIZE, SpriteLibrary
from .todo import TodoStore
from .todo_window import TodoWindow

WAKE_CHECK_MS = 20_000      # 多久檢查一次「到起床時間了沒」

ACTIVITY_LABELS = [("calm", "Calm"), ("normal", "Normal"), ("hyper", "Hyper")]
PRANK_LABELS = [("off", "Off"), ("rare", "Rarely (about every 30 min)"),
                ("sometimes", "Sometimes (about every 10 min)"), ("menu_only", "Only when I pick it")]


class PetApp(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.settings = Settings()
        self.settings.migrate()
        self.font_family = load_custom_font(app, assets_dir())   # assets/fonts/ 有字型就用
        size = int(BASE_SIZE * float(self.settings.get("scale")))
        self.sprites = SpriteLibrary(assets_dir(), size)
        if self.sprites.sketched:
            print("Still using sketches for:", ", ".join(self.sprites.sketched))

        self.pet = PetWindow(self.sprites, self.settings, name_fn=lambda: self.name)
        self.pet.menuRequested.connect(self.show_menu)
        # v0.3：待辦清單、番茄鐘
        self.todo = TodoStore(data_dir() / "todo.json")
        self.todo_win = TodoWindow(self.todo, self.sprites.size)
        self.pet.attach_pomodoro(TomatoWindow(assets_dir(), self.sprites.size), Ding(assets_dir(), data_dir()))
        self.tray = None
        self._build_tray()
        icon = self._icon_file()   # 每次啟動都更新圖示（桌面捷徑會用到）
        conv.repair_launch_paths(icon)   # 專案資料夾搬家後，自動修好捷徑和開機啟動的路徑
        self.pet.show()
        self.pet.attach_todo(self.todo_win)   # 清單收在螢幕右邊，只露出紅標籤

        # 每天起床：到時間（或開機時已經過了時間）且今天還沒拉過 → 狗把清單拉出來
        self.wake_timer = QTimer(self)
        self.wake_timer.timeout.connect(self._check_wake)
        self.wake_timer.start(WAKE_CHECK_MS)
        QTimer.singleShot(3000, self._check_wake)

        # 方便功能：再開一次 = 叫牠過來；全域快捷鍵
        self.instance = conv.InstanceServer(self)
        self.instance.summoned.connect(self.pet.come_here)
        self.hotkey = conv.HotkeyFilter(self.pet.come_here)
        app.installNativeEventFilter(self.hotkey)
        if not self.settings.get("tips_shown"):
            QTimer.singleShot(2500, self._show_tips)

        if not self.settings.get("pet_name"):
            QTimer.singleShot(800, self.ask_name)
        self._refresh_name()

    # ------------------------------------------------------------------ 名字
    @property
    def name(self) -> str:
        return self.settings.get("pet_name") or "Dachshund"

    def ask_name(self) -> None:
        text, ok = QInputDialog.getText(
            None, "Name your dachshund", "What's its name?", text=self.settings.get("pet_name"))
        if ok and text.strip():
            self.settings.set("pet_name", text.strip()[:20])
            self._refresh_name()
            self.pet.pet()

    def _refresh_name(self) -> None:
        # 狗身上不用 tooltip 了：滑鼠停在狗身上會顯示名牌（名字、心情、親密度）
        if self.tray:
            self.tray.setToolTip(self.name)

    # ------------------------------------------------------------------ 選單
    def _list_pomo_actions(self, menu: QMenu) -> None:
        """待辦清單、番茄鐘（狗身上和系統匣的選單都有）。"""
        busy = self.pet.busy
        a = menu.addAction("Put away my list" if self.todo_win.is_open else "Pull out my list", self.pet.toggle_list)
        a.setEnabled(not busy)
        pomo = menu.addMenu("Pomodoro")
        if self.pet.pomo.active or self.pet.pomo_pending:
            pomo.addAction("Stop", self.pet.stop_pomodoro)
        else:
            a = pomo.addAction(f"Start ({int(self.settings.get('focus_min'))} min)", self.pet.start_pomodoro)
            a.setEnabled(not busy)

    def _common_actions(self, menu: QMenu) -> None:
        stay = QAction("Stay", menu, checkable=True)
        stay.setChecked(self.pet.stay)
        stay.toggled.connect(self.pet.set_stay)
        menu.addAction(stay)

        act_menu = menu.addMenu("Energy level")
        group = QActionGroup(act_menu)
        for key, label in ACTIVITY_LABELS:
            a = QAction(label, act_menu, checkable=True)
            a.setChecked(self.settings.get("activity") == key)
            a.triggered.connect(lambda _=False, k=key: self.settings.set("activity", k))
            group.addAction(a)
            act_menu.addAction(a)

        prank_menu = menu.addMenu("Mouse-stealing prank")
        pgroup = QActionGroup(prank_menu)
        current = self.settings.get("prank_freq") if self.settings.get("mouse_prank") else "off"
        for key, label in PRANK_LABELS:
            a = QAction(label, prank_menu, checkable=True)
            a.setChecked(current == key)
            a.triggered.connect(lambda _=False, k=key: self._set_prank(k))
            pgroup.addAction(a)
            prank_menu.addAction(a)

        more = menu.addMenu("More interactions")
        for key, label in EXTRAS:
            a = QAction(label, more, checkable=True)
            a.setChecked(self.settings.extra(key))
            a.toggled.connect(lambda on, k=key: self._set_extra(k, on))
            more.addAction(a)

        menu.addAction("Settings...", self.open_settings)
        menu.addAction("Rename...", self.ask_name)
        if conv.IS_WINDOWS:
            menu.addSeparator()
            menu.addAction("Create desktop shortcut", self._make_shortcut)
            auto = QAction("Start with Windows", menu, checkable=True)
            auto.setChecked(conv.autostart_enabled())
            auto.toggled.connect(self._toggle_autostart)
            menu.addAction(auto)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)

    def _style_menu(self, menu: QMenu) -> None:
        """選單用 Evan 的手寫字型，稍微放大比較好讀（子選單會跟著繼承）。"""
        f = QFont(self.app.font())
        if self.font_family:
            size = f.pointSizeF() if f.pointSizeF() > 0 else 9.0
            f.setPointSizeF(size * 1.3)
        menu.setFont(f)

    def show_menu(self, pos: QPoint) -> None:
        menu = QMenu()
        self._style_menu(menu)
        mood = self.pet.mood
        text = f"🐶 {mood.label(self.name)}   {mood.detail()}" if mood.enabled else f"🐶 {self.name}"
        title = menu.addAction(text)
        title.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Pet", self.pet.pet)
        menu.addAction("Belly rub", self.pet.belly_up)
        menu.addAction("Sit", self.pet.sit)
        menu.addAction("Go for a walk", self.pet.start_walk)
        play = menu.addMenu("Play")
        play.addAction("Zoomies", self.pet.start_zoomies)
        if self.settings.extra("spin"):
            play.addAction("Chase tail", self.pet.start_spin)
        if self.settings.extra("sniff"):
            play.addAction("Sniff the floor", self.pet.start_sniff)
        play.addAction("Chase my cursor", self.pet.start_chase)
        play.addAction("Steal my mouse", self.pet.start_prank)
        menu.addAction("Sleep", self.pet.sleep)
        menu.addSeparator()
        self._list_pomo_actions(menu)
        menu.addSeparator()
        self._common_actions(menu)
        menu.exec(pos)

    # ------------------------------------------------------------------ 系統匣
    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QIcon(self._icon_pixmap())
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        self._style_menu(menu)
        menu.addAction("Come here", self.pet.come_here)
        menu.addSeparator()
        self._tray_menu = menu
        menu.aboutToShow.connect(self._rebuild_tray_menu)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.show()

    def _rebuild_tray_menu(self) -> None:
        m = self._tray_menu
        m.clear()
        label = f"Come here ({conv.HOTKEY_LABEL})" if self.hotkey.ok else "Come here"
        m.addAction(label, self.pet.come_here)
        m.addSeparator()
        self._list_pomo_actions(m)
        m.addSeparator()
        self._common_actions(m)

    # ------------------------------------------------------------------ 方便功能
    def _notify(self, text: str) -> None:
        if self.tray and self.tray.isVisible():
            self.tray.showMessage(self.name, text, self.tray.icon(), 4000)
        else:
            QMessageBox.information(None, self.name, text)

    def _show_tips(self) -> None:
        tip = f"Press {conv.HOTKEY_LABEL} to call me anytime!" if self.hotkey.ok else "Click my icon in the tray to call me!"
        self._notify(tip + "\nRight-click me to make a desktop shortcut or start me with Windows.")
        self.settings.set("tips_shown", True)

    def _toggle_autostart(self, on: bool) -> None:
        if conv.set_autostart(on):
            self._notify("I'll show up when your computer starts! 🐾" if on else "OK, I won't start with Windows.")
        else:
            self._notify("That didn't work :(")

    def _icon_pixmap(self, size: int = 256) -> QPixmap:
        """圖示：優先用 assets/icon.png，沒有就用 idle 第 1 格。裁掉透明邊，置中放進正方形。"""
        custom = assets_dir() / "icon.png"            # Evan 自己畫的圖示（有就優先用）
        if custom.is_file():
            pm = QPixmap(str(custom))
            if not pm.isNull():
                src = pm
            else:
                src = self.sprites.frame("idle", "down", 0.0)
        else:
            src = self.sprites.frame("idle", "down", 0.0)
        box = QRegion(src.mask()).boundingRect() if not src.mask().isNull() else src.rect()
        if box.isEmpty():
            box = src.rect()
        side = max(box.width(), box.height())
        out = QPixmap(side, side)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawPixmap((side - box.width()) // 2, (side - box.height()) // 2, src.copy(box))
        p.end()
        return out.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _icon_file(self):
        """寫出 icon.ico；桌面捷徑指向這個檔，所以換圖後捷徑圖示也會跟著換。"""
        path = data_dir() / "icon.ico"
        return path if self._icon_pixmap(256).save(str(path), "ICO") else None

    def _make_shortcut(self) -> None:
        lnk = conv.create_desktop_shortcut(self.name, self._icon_file())
        self._notify(f"Desktop shortcut created: {lnk.name}" if lnk else "Couldn't create the shortcut :(")

    def _tray_clicked(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.pet.come_here()

    def _set_prank(self, key: str) -> None:
        if key == "off":
            self.settings.set("mouse_prank", False)
        else:
            self.settings.data["mouse_prank"] = True
            self.settings.set("prank_freq", key)
        self.pet.prank_settings_changed()

    # ------------------------------------------------------------------ v0.3 起床、Settings
    def _check_wake(self) -> None:
        if self.todo.rollover():                 # 跨過半夜：打勾的項目清掉
            self.todo_win.refresh()
        self.todo_win.update()                   # 日期
        now = datetime.now()
        today = now.date().isoformat()
        if self.settings.get("last_pull_date") == today:
            return
        h, m = parse_hhmm(self.settings.get("wake_time"))
        if (now.hour, now.minute) < (h, m):
            return
        if self.pet.morning():                   # False = 狗正在被拎著之類的，下次再試
            self.settings.set("last_pull_date", today)

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings)
        if dlg.exec():
            self._check_wake()                   # 改成比現在早的時間、今天還沒拉過 → 馬上拉

    def _set_extra(self, key: str, on: bool) -> None:
        self.settings.set_extra(key, on)
        self.pet.extras_changed()

    def quit(self) -> None:
        self.pet.save_mood()
        self.todo.save()
        self.hotkey.unregister()
        if self.tray:
            self.tray.hide()
        self.app.quit()
