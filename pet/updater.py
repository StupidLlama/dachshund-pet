"""自動更新：開狗時去 GitHub 看有沒有新版 → 問使用者要不要更新（顯示更新紀錄）→ 下載 zip → 關掉自己、換檔、重開。

只在打包好的 exe 才會檢查（用 py 跑原始碼的是開發者，用 git 更新）。
核心邏輯不依賴 Qt（可以測）；UpdateDialog 在檔案下面，用到時才 import Qt。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

from .version import __version__

REPO = "StupidLlama/dachshund-pet"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = "DachshundPet-windows.zip"
EXE_NAME = "DachshundPet.exe"
UA = {"User-Agent": "DachshundPet-updater", "Accept": "application/vnd.github+json"}


def parse_version(v: str) -> tuple[int, ...]:
    """'v0.4.10' → (0, 4, 10)；看不懂的回 ()。"""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", v or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def can_update() -> bool:
    """只有 Windows 上打包好的 exe 能自己換檔。"""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def app_dir() -> Path:
    return Path(sys.executable).resolve().parent


def fetch_latest(api: str = LATEST_API, timeout: float = 10.0) -> dict | None:
    """回傳 {tag, notes, url, size, page}；沒有 Release / 沒有 zip / 連不上 → None。"""
    req = urllib.request.Request(api, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rel = json.load(r)
    asset = next((a for a in rel.get("assets") or [] if a.get("name") == ASSET_NAME), None)
    if not asset:
        return None
    return {"tag": rel.get("tag_name", ""), "notes": (rel.get("body") or "").strip(),
            "url": asset["browser_download_url"], "size": int(asset.get("size") or 0),
            "page": rel.get("html_url", "")}


def check(skip: str = "", api: str = LATEST_API) -> dict | None:
    """有比現在新、而且不是使用者按過「Skip」的版本 → 回傳那個版本的資訊。"""
    info = fetch_latest(api)
    if info and is_newer(info["tag"]) and info["tag"] != skip:
        return info
    return None


def download(info: dict, progress=lambda done, total: None, workdir: Path | None = None) -> Path:
    """下載 zip、解壓縮，回傳新版資料夾（裡面有 DachshundPet.exe）。"""
    work = Path(workdir or tempfile.mkdtemp(prefix="DachshundPet-update-"))
    zpath = work / ASSET_NAME
    req = urllib.request.Request(info["url"], headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30) as r, open(zpath, "wb") as f:
        total = int(r.headers.get("Content-Length") or info.get("size") or 0)
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            progress(done, total)
    out = work / "new"
    with zipfile.ZipFile(zpath) as z:
        z.extractall(out)
    zpath.unlink(missing_ok=True)
    exe = next(out.rglob(EXE_NAME), None)
    if exe is None:
        shutil.rmtree(work, ignore_errors=True)
        raise RuntimeError("The download doesn't contain DachshundPet.exe")
    return exe.parent


def write_swap_script(new_dir: Path, target: Path, pid: int) -> Path:
    """等舊的狗關掉 → 新檔蓋過去 → 開新的狗 → 刪暫存。"""
    work = next((p.parent for p in [new_dir, *new_dir.parents] if p.name == "new"), new_dir.parent)
    bat = work / "update.bat"
    bat.write_text(
        "@echo off\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
        f'robocopy "{new_dir}" "{target}" /E /R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul\r\n'
        f'start "" "{target / EXE_NAME}"\r\n'
        f'(goto) 2>nul & rmdir /s /q "{work}"\r\n',
        encoding="mbcs" if os.name == "nt" else "utf-8")
    return bat


def run_swap(bat: Path) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True)


class Background:
    """在背景跑 fn，主執行緒用 poll() 拿結果（Qt 只能在主執行緒碰）。"""

    def __init__(self, fn, *args, **kw):
        self.result = self.error = None
        self.done = False
        self.progress = (0, 0)
        if "progress" in kw:
            kw["progress"] = lambda d, t: setattr(self, "progress", (d, t))
        threading.Thread(target=self._run, args=(fn, args, kw), daemon=True).start()

    def _run(self, fn, args, kw):
        try:
            self.result = fn(*args, **kw)
        except Exception as e:                       # 沒網路、GitHub 掛掉……都不影響狗
            self.error = e
        self.done = True


# ---------------------------------------------------------------- 視窗（Qt）
def make_dialog(info: dict, on_update, on_skip, on_later):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout

    from .messaging_ui import FLAGS, STYLE
    from .paper import hand_font

    class UpdateDialog(QDialog):
        def __init__(self):
            super().__init__(None, FLAGS)
            self.setWindowTitle("Update available")
            self.setStyleSheet(STYLE)
            self.setFont(hand_font(19))
            self.resize(480, 420)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(18, 14, 18, 16)
            lay.setSpacing(10)
            title = QLabel(f"A new version is here: {info['tag']}")
            title.setFont(hand_font(26))
            sub = QLabel(f"You have v{__version__}. What's new:")
            sub.setFont(hand_font(17))
            self.notes = QTextBrowser()
            self.notes.setOpenExternalLinks(True)
            self.notes.setMarkdown(info["notes"] or "Small fixes and improvements.")
            self.bar = QProgressBar()
            self.bar.setVisible(False)
            self.status = QLabel("")
            self.status.setFont(hand_font(16))
            row = QHBoxLayout()
            self.skip_btn = QPushButton("Skip this version")
            self.later_btn = QPushButton("Later")
            self.go_btn = QPushButton("Update now")
            for b in (self.skip_btn, self.later_btn, self.go_btn):
                b.setFont(hand_font(18))
                b.setAutoDefault(False)
            self.go_btn.setObjectName("primary")
            self.skip_btn.clicked.connect(lambda: (on_skip(), self.close()))
            self.later_btn.clicked.connect(lambda: (on_later(), self.close()))
            self.go_btn.clicked.connect(self._go)
            row.addWidget(self.skip_btn)
            row.addStretch(1)
            row.addWidget(self.later_btn)
            row.addWidget(self.go_btn)
            for w in (title, sub):
                lay.addWidget(w)
            lay.addWidget(self.notes, 1)
            lay.addWidget(self.bar)
            lay.addWidget(self.status)
            lay.addLayout(row)
            self.setAttribute(Qt.WA_DeleteOnClose)

        def _go(self):
            for b in (self.skip_btn, self.later_btn, self.go_btn):
                b.setEnabled(False)
            self.bar.setVisible(True)
            self.status.setText("Downloading...")
            on_update(self)

        def set_progress(self, done: int, total: int):
            if total:
                self.bar.setMaximum(total)
                self.bar.setValue(done)

        def failed(self, msg: str):
            self.status.setText(f"Couldn't update: {msg}")
            for b in (self.later_btn, self.go_btn):
                b.setEnabled(True)
            self.go_btn.setText("Try again")

    return UpdateDialog()
