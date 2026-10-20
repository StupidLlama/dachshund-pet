"""設定檔與路徑。設定存在 %APPDATA%\\DachshundPet\\settings.json。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "DachshundPet"

DEFAULTS = {
    "pet_name": "",            # 第一次開啟時讓使用者取名
    "scale": 1.0,              # 狗的大小倍率
    "activity": "normal",      # calm / normal / hyper
    "sleep_after_sec": 180,    # 多久沒理牠就睡著
    "wake_time": "08:00",      # 每天幾點把待辦清單拉出來（v0.3，24 小時制）
    "last_pull_date": "",      # 今天已經自動拉過清單的日期（同一天只自動拉一次）
    "focus_min": 25,           # 番茄鐘：專心幾分鐘
    "break_min": 5,            # 番茄鐘：休息幾分鐘
    "mouse_prank": True,       # 叼走滑鼠惡作劇開關（v0.2）
    "prank_freq": "sometimes", # rare（約 30 分鐘一次）/ sometimes（約 10 分鐘）/ menu_only（只在選單觸發）
    "extras": {},              # Evan 沒勾的互動，預設關閉，右鍵「更多互動」可打開（見 EXTRAS）
    "mood": 70,                # 心情 0~100（v0.2）
    "affection": 30,           # 親密度 0~100（v0.2）
    "skip_version": "",        # 自動更新：使用者按「Skip this version」的版本
}


# Evan 在 v0.2 答題卡沒勾的互動：程式碼保留，預設關閉
EXTRAS = [
    ("dizzy", "Shake to make dizzy"),
    ("throw", "Throw"),
    ("look", "Watch my cursor"),
    ("swipe", "Startle on fast swipe"),
    ("spin", "Chase tail"),
    ("sniff", "Sniff the floor"),
    ("mood", "Mood system"),
]


def data_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    d = root / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def assets_dir() -> Path:
    """打包成 exe 時優先用 exe 旁邊的 assets/，方便直接換圖。"""
    if getattr(sys, "frozen", False):
        beside = Path(sys.executable).parent / "assets"
        if beside.is_dir():
            return beside
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def firebase_config_path() -> Path:
    """v0.4：firebase/config.json（Firebase 的公開設定）。打包成 exe 時優先用 exe 旁邊的。"""
    if getattr(sys, "frozen", False):
        beside = Path(sys.executable).parent / "firebase" / "config.json"
        if beside.is_file():
            return beside
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "firebase" / "config.json"
    return Path(__file__).resolve().parent.parent / "firebase" / "config.json"


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else data_dir() / "settings.json"
        self.data = dict(DEFAULTS)
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass  # 檔案壞了就用預設值

    def get(self, key: str):
        return self.data.get(key, DEFAULTS.get(key))

    def extra(self, key: str) -> bool:
        ex = self.data.get("extras")
        return bool(ex.get(key, False)) if isinstance(ex, dict) else False

    def set_extra(self, key: str, on: bool) -> None:
        ex = self.data.get("extras")
        ex = dict(ex) if isinstance(ex, dict) else {}
        ex[key] = bool(on)
        self.set("extras", ex)

    def migrate(self) -> None:
        """舊設定檔升級。v0.2.1：叼滑鼠改成約 10 分鐘一次（Evan 選的）。"""
        if int(self.data.get("settings_version", 1)) < 2:
            self.data["prank_freq"] = "sometimes"
            self.data["mouse_prank"] = True
            self.data["settings_version"] = 2
            self.save()

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
