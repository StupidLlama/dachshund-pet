"""待辦清單資料（不依賴 Qt）。存在 %APPDATA%\\DachshundPet\\todo.json：

    {"date": "2026-10-19", "items": [{"text": "Calculus homework", "done": false}, ...]}

換日時（載入時，或程式開著跨過半夜時）把打勾的項目刪掉、date 改成今天。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

MAX_TEXT = 40


class TodoStore:
    def __init__(self, path: Path, today_fn=date.today):
        self.path = Path(path)
        self.today_fn = today_fn
        self.date = self._today()
        self.items: list[dict] = []
        self.load()

    def _today(self) -> str:
        return self.today_fn().isoformat()

    # ------------------------------------------------------------------ 讀寫
    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        items = data.get("items", [])
        self.items = [{"text": str(it.get("text", ""))[:MAX_TEXT], "done": bool(it.get("done", False))}
                      for it in items if isinstance(it, dict) and str(it.get("text", "")).strip()]
        self.date = str(data.get("date") or self._today())
        self.rollover()

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"date": self.date, "items": self.items}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def rollover(self) -> bool:
        """換日：刪掉打勾的項目。有換日就回傳 True。"""
        today = self._today()
        if self.date == today:
            return False
        self.items = [it for it in self.items if not it["done"]]
        self.date = today
        self.save()
        return True

    # ------------------------------------------------------------------ 操作
    def add(self, text: str) -> bool:
        text = " ".join(text.split())[:MAX_TEXT]
        if not text:
            return False
        self.items.append({"text": text, "done": False})
        self.save()
        return True

    def toggle(self, i: int) -> bool:
        """切換第 i 項，回傳新的狀態（True = 打勾）。"""
        it = self.items[i]
        it["done"] = not it["done"]
        self.save()
        return it["done"]

    def remove(self, i: int) -> None:
        if 0 <= i < len(self.items):
            del self.items[i]
            self.save()

    @property
    def all_done(self) -> bool:
        return bool(self.items) and all(it["done"] for it in self.items)
