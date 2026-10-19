"""待辦清單資料（不依賴 Qt）。存在 %APPDATA%\\DachshundPet\\todo.json：

    {"date": "2026-10-19", "items": [{"id": "...", "text": "Calculus homework", "done": false, "ts": 0, "by": "pet"}, ...]}

換日時（載入時，或程式開著跨過半夜時）把打勾的項目刪掉、date 改成今天。

v0.4.2 手機同步：每一項有 id（新增時產生），本機改了就呼叫 on_change(動作, 資料) 讓 app 傳上 Firebase：
    ("put", item)        新增 / 打勾
    ("remove", id)       刪除
    ("rollover", (打勾的 id 們, 新日期))
手機改了 → app 呼叫 apply_remote(items, date) 整份換掉（不會再觸發 on_change）。
"""
from __future__ import annotations

import json
import random
import string
import time
from datetime import date
from pathlib import Path

MAX_TEXT = 40


def new_id() -> str:
    """跟 Firebase push id 一樣先放時間，排序就是新增順序。"""
    stamp = f"{int(time.time() * 1000):013d}"
    return "t" + stamp + "".join(random.choice(string.ascii_letters) for _ in range(6))


def _clean(text: str) -> str:
    return " ".join(str(text).split())[:MAX_TEXT]


class TodoStore:
    def __init__(self, path: Path, today_fn=date.today):
        self.path = Path(path)
        self.today_fn = today_fn
        self.date = self._today()
        self.items: list[dict] = []
        self.on_change = lambda op, data: None
        self.load()

    def _today(self) -> str:
        return self.today_fn().isoformat()

    # ------------------------------------------------------------------ 讀寫
    @staticmethod
    def _norm(it: dict, i: int = 0) -> dict:
        return {"id": str(it.get("id") or new_id() + str(i)), "text": _clean(it.get("text", "")),
                "done": bool(it.get("done", False)), "ts": int(it.get("ts") or time.time() * 1000) + 0,
                "by": it.get("by") if it.get("by") in ("pet", "phone") else "pet"}

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        items = data.get("items", [])
        self.items = [self._norm(it, i) for i, it in enumerate(items)
                      if isinstance(it, dict) and str(it.get("text", "")).strip()]
        self.date = str(data.get("date") or self._today())
        if any("id" not in it for it in items if isinstance(it, dict)):
            self.save()                              # 舊格式（沒有 id）→ 補上
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
        done_ids = [it["id"] for it in self.items if it["done"]]
        self.items = [it for it in self.items if not it["done"]]
        self.date = today
        self.save()
        self.on_change("rollover", (done_ids, today))
        return True

    # ------------------------------------------------------------------ 操作（本機）
    def add(self, text: str, by: str = "pet") -> bool:
        text = _clean(text)
        if not text:
            return False
        it = {"id": new_id(), "text": text, "done": False, "ts": int(time.time() * 1000), "by": by}
        self.items.append(it)
        self.save()
        self.on_change("put", dict(it))
        return True

    def toggle(self, i: int) -> bool:
        """切換第 i 項，回傳新的狀態（True = 打勾）。"""
        it = self.items[i]
        it["done"] = not it["done"]
        self.save()
        self.on_change("put", dict(it))
        return it["done"]

    def remove(self, i: int) -> None:
        if 0 <= i < len(self.items):
            it = self.items.pop(i)
            self.save()
            self.on_change("remove", it["id"])

    @property
    def all_done(self) -> bool:
        return bool(self.items) and all(it["done"] for it in self.items)

    # ------------------------------------------------------------------ 手機同步
    def apply_remote(self, items: dict, date_str: str = "") -> list[dict]:
        """Firebase 上的清單（{id: {text, done, ts, by}}）整份換掉本機的。回傳新出現、手機加的項目。"""
        before = {it["id"] for it in self.items}
        new = []
        for k, v in (items or {}).items():
            if isinstance(v, dict) and str(v.get("text", "")).strip():
                new.append(self._norm({**v, "id": k}))
        new.sort(key=lambda it: (it["ts"], it["id"]))
        self.items = new
        if date_str:
            self.date = date_str
        self.save()
        return [it for it in new if it["id"] not in before and it["by"] == "phone"]
