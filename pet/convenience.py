"""讓桌寵用起來更方便（Windows）：

- 單一實例：已經開著時再啟動一次，不會多一隻狗，而是叫原本那隻過來
- 全域快捷鍵 Ctrl + Alt + D：在任何地方都能叫狗過來
- 開機自動啟動：寫進 HKCU\\...\\Run（不需要系統管理員權限）
- 建立桌面捷徑：雙擊就開，不會跳出黑色終端機
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

IS_WINDOWS = sys.platform == "win32"
SERVER_NAME = "DachshundPet-single-instance"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "DachshundPet"
PROJECT_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- 單一實例
def ping_running_instance() -> bool:
    """如果已經有一隻狗在跑，叫牠過來並回傳 True。"""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(b"come")
    sock.flush()
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


class InstanceServer(QObject):
    summoned = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        QLocalServer.removeServer(SERVER_NAME)       # 清掉上次當掉留下的殘骸
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_conn)
        self.server.listen(SERVER_NAME)

    def _on_conn(self) -> None:
        conn = self.server.nextPendingConnection()
        if conn:
            conn.readyRead.connect(conn.readAll)
            conn.disconnected.connect(conn.deleteLater)
        self.summoned.emit()


# ---------------------------------------------------------------- 全域快捷鍵
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
WM_HOTKEY = 0x0312
HOTKEY_ID = 0xD0C5
HOTKEY_LABEL = "Ctrl + Alt + D"


class HotkeyFilter(QAbstractNativeEventFilter):
    """註冊 Ctrl+Alt+D。被其他程式佔用時 ok = False，其他功能照常。"""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.ok = False
        if IS_WINDOWS:
            try:
                self.ok = bool(ctypes.windll.user32.RegisterHotKey(
                    None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("D")))
            except OSError:
                self.ok = False

    def nativeEventFilter(self, event_type, message):
        if self.ok and bytes(event_type) == b"windows_generic_MSG":
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.callback()
                return True, 0
        return False, 0

    def unregister(self) -> None:
        if self.ok:
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            self.ok = False


# ---------------------------------------------------------------- 啟動指令
def launch_target() -> tuple[str, str]:
    """回傳 (執行檔, 參數)。用 pythonw.exe 啟動就不會有黑色終端機視窗。"""
    if getattr(sys, "frozen", False):                # 之後打包成 exe 的情況
        return sys.executable, ""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else exe), f'"{PROJECT_DIR / "main.py"}"'


def launch_command() -> str:
    exe, args = launch_target()
    return f'"{exe}" {args}'.strip()


# ---------------------------------------------------------------- 開機自動啟動
def autostart_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- 桌面捷徑
def create_desktop_shortcut(name: str, icon_path: Path | None) -> Path | None:
    """用 PowerShell 的 WScript.Shell 建 .lnk，回傳捷徑路徑；失敗回傳 None。"""
    if not IS_WINDOWS:
        return None
    exe, args = launch_target()

    def ps(s: str) -> str:                            # PowerShell 單引號字串跳脫
        return "'" + str(s).replace("'", "''") + "'"

    safe = "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "Dachshund"
    script = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        f"$p=Join-Path $d ({ps(safe)}+'.lnk');"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($p);"
        f"$s.TargetPath={ps(exe)};"
        f"$s.Arguments={ps(args)};"
        f"$s.WorkingDirectory={ps(PROJECT_DIR)};"
        + (f"$s.IconLocation={ps(icon_path)};" if icon_path else "")
        + "$s.Save();Write-Output $p"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        path = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
        return Path(path) if out.returncode == 0 and path else None
    except (OSError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------- 搬家後自動修路徑
def repair_launch_paths(icon_path: Path | None = None) -> None:
    """專案資料夾搬家或改名後，桌面捷徑和開機啟動會指向不存在的舊路徑。
    每次啟動時檢查：開機啟動的指令不一樣就重寫；桌面上指向別的 dachshund-pet\\main.py
    的捷徑，改成指向現在這份。在背景跑 PowerShell，不會卡住狗。"""
    if not IS_WINDOWS:
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            current, _ = winreg.QueryValueEx(k, RUN_VALUE)
        if current != launch_command():
            set_autostart(True)
    except OSError:
        pass                                          # 沒開開機啟動就不用修

    exe, args = launch_target()

    def ps(s: str) -> str:
        return "'" + str(s).replace("'", "''") + "'"

    script = (
        "$sh=New-Object -ComObject WScript.Shell;"
        "$dirs=@([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('CommonDesktopDirectory'));"
        "foreach($d in $dirs){ if(-not $d){continue};"
        " Get-ChildItem -LiteralPath $d -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {"
        "  $s=$sh.CreateShortcut($_.FullName);"
        "  if(($s.Arguments -like '*dachshund-pet*main.py*' -or $s.WorkingDirectory -like '*dachshund-pet*')"
        f"     -and $s.WorkingDirectory -ne {ps(PROJECT_DIR)}){{"
        f"   $s.TargetPath={ps(exe)}; $s.Arguments={ps(args)}; $s.WorkingDirectory={ps(PROJECT_DIR)};"
        + (f"   $s.IconLocation={ps(icon_path)};" if icon_path else "")
        + "   try{$s.Save()}catch{} } } }"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        pass
