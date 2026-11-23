"""v0.5 大便的規則（不依賴 Qt）：稀有度、多久大一次、吃零食加速。視窗在 yard.py。"""
from __future__ import annotations

import random

# ---- 可調參數 ---------------------------------------------------------------
# (key, 顯示名稱, 機率權重, 草圖顏色)
RARITIES = [
    ("common", "Common", 60, "#8B5A2B"),
    ("uncommon", "Uncommon", 25, "#6E8B3D"),
    ("rare", "Rare", 10, "#3B82C4"),
    ("epic", "Epic", 4, "#8E44AD"),
    ("legendary", "Legendary", 1, "#E6B422"),
]
RARITY_KEYS = [r[0] for r in RARITIES]
RARITY_LABEL = {r[0]: r[1] for r in RARITIES}
RARITY_COLOR = {r[0]: r[3] for r in RARITIES}
# 發光顏色（Evan 選的：灰 / 綠 / 藍 / 紫 / 金）：大便、零食、吃了零食的狗都用這個
RARITY_GLOW = {"common": "#A0A0A0", "uncommon": "#3FBF5A", "rare": "#3B8BEA", "epic": "#A35BE0", "legendary": "#F2C230"}

POOP_MIN_SEC = 30 * 60.0    # 最快多久大一次
POOP_MAX_SEC = 60 * 60.0    # 最慢多久大一次
POOP_MAX = 10               # 桌面上最多幾坨（滿了就憋著）
FED_FACTOR = 0.5            # 吃一次零食：剩下的時間 × 這個
FED_MIN_SEC = 60.0          # 吃再多，至少還要等這麼久


def roll_rarity(rng=random, luck: float = 1.0) -> str:
    """照權重抽一個稀有度。luck > 1：Common 以外的權重 × luck（吃了雞腿的效果）。"""
    weights = [(key, w if key == "common" else w * luck) for key, _label, w, _c in RARITIES]
    x = rng.uniform(0, sum(w for _k, w in weights))
    for key, w in weights:
        x -= w
        if x <= 0:
            return key
    return RARITIES[0][0]


# ---- 零食和效果（v0.5，Evan 的答題卡：每種零食固定一種效果，稀有度越高越強、越久） -------------
# 零食圖片檔名 → (名字, 效果)
TREATS = {
    "treat_01": ("Bone", "run"),         # 骨頭：跑比較快
    "treat_02": ("Drumstick", "luck"),   # 雞腿：大便比較容易抽到稀有的
    "treat_03": ("Kibble", "poop"),      # 飼料：更快想大便
}
EFFECTS = {   # 效果 → (頭上圖示, 吃完說的話, 每個稀有度的強度 Common~Legendary)
    "run": ("\u26a1", "Zoom zoom!", (1.15, 1.3, 1.45, 1.65, 2.0)),    # 走路 / 跑步速度 ×
    "luck": ("\U0001F340", "Feeling lucky!", (1.5, 2.0, 3.0, 4.0, 6.0)),  # 稀有大便的權重 ×
    "poop": ("\U0001F4A9", "Uh oh...", (1.5, 2.0, 2.5, 3.0, 4.0)),    # 大便倒數走得快 ×
}
EFFECT_MIN = (5, 10, 15, 20, 30)      # 效果持續幾分鐘（Common ~ Legendary）


class Buffs:
    """吃零食得到的效果：{效果: [稀有度, 剩幾秒]}。跟大便倒數一樣只在狗開著時走，存進設定檔。"""

    def __init__(self, data=None):
        self.active: dict[str, list] = {}
        if isinstance(data, dict):
            for kind, v in data.items():
                try:
                    rarity, left = str(v[0]), float(v[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if kind in EFFECTS and rarity in RARITY_KEYS and 0 < left <= EFFECT_MIN[-1] * 60:
                    self.active[kind] = [rarity, left]

    def add(self, kind: str, rarity: str) -> None:
        """吃到新的：比較稀有就換掉；一樣稀有就重新計時；比較不稀有就不變。"""
        if kind not in EFFECTS or rarity not in RARITY_KEYS:
            return
        dur = EFFECT_MIN[RARITY_KEYS.index(rarity)] * 60.0
        old = self.active.get(kind)
        if old is None or RARITY_KEYS.index(rarity) > RARITY_KEYS.index(old[0]):
            self.active[kind] = [rarity, dur]
        elif rarity == old[0]:
            old[1] = max(old[1], dur)

    def tick(self, dt: float) -> None:
        for kind in list(self.active):
            self.active[kind][1] -= dt
            if self.active[kind][1] <= 0:
                del self.active[kind]

    def value(self, kind: str) -> float:
        """效果的強度（沒有這個效果 = 1.0）。"""
        v = self.active.get(kind)
        return EFFECTS[kind][2][RARITY_KEYS.index(v[0])] if v else 1.0

    def top(self) -> str | None:
        """現在最稀有的效果（狗身上發光用這個顏色）。"""
        if not self.active:
            return None
        return max((v[0] for v in self.active.values()), key=RARITY_KEYS.index)

    def to_json(self) -> dict:
        return {k: [v[0], round(v[1], 1)] for k, v in self.active.items()}


class PoopClock:
    """倒數計時：歸零 = 該大便了。只在狗開著的時候走；剩下的秒數會存進設定檔。"""

    def __init__(self, remaining=None, rng=random):
        self.rng = rng
        try:
            r = float(remaining)
        except (TypeError, ValueError):
            r = -1.0
        self.remaining = r if 0 <= r <= POOP_MAX_SEC else self._roll()

    def _roll(self) -> float:
        return self.rng.uniform(POOP_MIN_SEC, POOP_MAX_SEC)

    def tick(self, dt: float, speed: float = 1.0) -> None:
        """speed > 1：吃了飼料，倒數走得比較快。"""
        if self.remaining > 0:
            self.remaining = max(0.0, self.remaining - dt * speed)

    @property
    def due(self) -> bool:
        return self.remaining <= 0

    def reset(self) -> None:
        self.remaining = self._roll()

    def fed(self) -> None:
        """吃了零食：更快想大便（但至少還要等 FED_MIN_SEC）。"""
        if self.remaining > FED_MIN_SEC:
            self.remaining = max(FED_MIN_SEC, self.remaining * FED_FACTOR)
