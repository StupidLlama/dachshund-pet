"""心情與親密度（純 Python，不依賴 Qt，方便測試）。

mood       心情 0~100：摸頭、揉肚子會變好；被亂甩、太久沒理會變差
affection  親密度 0~100：只會慢慢累積（摸越多越黏你），被亂甩會掉一點

心情會影響行為機率（見 pet_window._choose_next）：
    心情好 → 比較常亂跑、暴衝、追尾巴、跑來找你
    心情差 → 比較常坐著、睡覺
"""
from __future__ import annotations

NEGLECT_AFTER = 300.0        # 多久沒互動開始算「被冷落」（秒）
NEGLECT_RATE = 1.0 / 60.0    # 被冷落時，每秒掉多少心情（= 每分鐘 1 點）
NEGLECT_FLOOR = 30.0         # 冷落最多只會掉到這裡
SAVE_EVERY = 60.0            # 每隔幾秒存一次檔（避免一直寫硬碟）


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


class Mood:
    def __init__(self, mood: float = 70.0, affection: float = 30.0):
        self.mood = _clamp(float(mood))
        self.affection = _clamp(float(affection))
        self._since_save = 0.0
        self.dirty = False
        self.enabled = True          # 關掉心情系統時，change() 什麼都不做

    # ---------------------------------------------------------------- 變化
    def change(self, d_mood: float = 0.0, d_affection: float = 0.0) -> None:
        if not self.enabled:
            return
        self.mood = _clamp(self.mood + d_mood)
        self.affection = _clamp(self.affection + d_affection)
        self.dirty = True

    def tick(self, dt: float, idle_for: float) -> bool:
        """每一幀呼叫。回傳 True 代表該存檔了。"""
        if idle_for > NEGLECT_AFTER and self.mood > NEGLECT_FLOOR:
            self.mood = max(NEGLECT_FLOOR, self.mood - NEGLECT_RATE * dt)
            self.dirty = True
        self._since_save += dt
        if self.dirty and self._since_save >= SAVE_EVERY:
            self._since_save = 0.0
            self.dirty = False
            return True
        return False

    # ---------------------------------------------------------------- 顯示
    @property
    def level(self) -> float:
        """0~1，給行為機率用。"""
        return self.mood / 100.0

    def emoji(self) -> str:
        m = self.mood
        if m >= 80:
            return "😄"
        if m >= 60:
            return "😊"
        if m >= 40:
            return "😐"
        if m >= 20:
            return "😟"
        return "😢"

    def label(self, name: str) -> str:
        return f"{name} {self.emoji()} Mood {round(self.mood)}"

    def detail(self) -> str:
        return f"♥ Love {round(self.affection)}"
