"""臘腸狗桌寵 — 啟動點。  py main.py"""
import os
import sys
import traceback
from pathlib import Path


def _log_dir() -> Path:
    base = os.environ.get("APPDATA")
    d = (Path(base) if base else Path.home() / ".config") / "DachshundPet"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log_crash(exc_type, exc, tb) -> None:
    """用 pythonw 啟動時看不到終端機，所以錯誤寫進 error.log。"""
    try:
        with open(_log_dir() / "error.log", "a", encoding="utf-8") as f:
            traceback.print_exception(exc_type, exc, tb, file=f)
    except OSError:
        pass
    sys.__excepthook__(exc_type, exc, tb)


def main() -> None:
    sys.excepthook = _log_crash
    try:
        from PySide6.QtWidgets import QApplication   # 放在這裡，裝不起來時也會記進 error.log
    except Exception:
        _log_crash(*sys.exc_info())
        raise SystemExit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("DachshundPet")
    app.setQuitOnLastWindowClosed(False)   # 關掉取名視窗時程式不要跟著結束

    from pet.convenience import ping_running_instance
    if ping_running_instance():            # 已經開著了 → 叫那隻過來就好
        return

    from pet.app import PetApp
    _pet_app = PetApp(app)                 # noqa: F841  （要留著參考，不然會被回收）
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        _log_crash(*sys.exc_info())
        raise
