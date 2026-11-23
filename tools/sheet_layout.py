"""v0.5 新動畫的 sprite sheet 版面：make_template.py（出描圖模板）和 slice_sheet.py（切圖）共用。

整張圖 = COLS × len(ROWS) 格，每格 CELL × CELL。Evan 在模板上面開新圖層畫，匯出時把模板圖層關掉、
背景透明、畫布大小不要改，slice_sheet.py 就能照這個版面切好放進 assets/。
"""
from __future__ import annotations

CELL = 320
COLS = 8

# 代號（跟 Evan 討論時用的 A~L）
LETTER = {"tug": "A", "push": "B", "bark": "C", "carry": "D", "startle": "E", "study": "F",
          "snore": "G", "eat": "H", "poop": "I", "dizzy": "J", "spin": "K", "sniff": "L"}


def _anim(name: str, n: int) -> list:
    return [("anim", name, i) for i in range(n)]


# 每一格：("anim", 動作, 第幾格) / ("item", 檔名) / ("poop", 稀有度) / None（空格）
ROWS = [
    _anim("tug", 4) + _anim("push", 4),
    _anim("bark", 4) + _anim("study", 4),
    _anim("snore", 4) + _anim("dizzy", 4),
    _anim("sniff", 4) + _anim("startle", 3) + [None],
    _anim("carry", 6) + [("item", "treat_01"), ("item", "treat_02")],
    _anim("eat", 6) + [("item", "treat_03"), ("item", "bowl")],
    _anim("poop", 6) + [("item", "broom"), None],
    _anim("spin", 8),
    [("poop", "common"), ("poop", "uncommon"), ("poop", "rare"), ("poop", "epic"), ("poop", "legendary"),
     None, None, None],
]

WIDTH = COLS * CELL
HEIGHT = len(ROWS) * CELL

# 動作格子裡的記號：(u, v, 說明)，單位 = 格子邊長。位置要對準，程式是照這些點算的（見 pet_window.py）
GROUND_V = 0.64                                  # 腳底的高度（跟其他動作一樣）
MARKS = {
    "tug": (0.87, 0.42, "bite here"),           # BITE = (0.37, 0.22)：咬住清單標籤的點
    "push": (0.90, 0.39, "nose here"),          # NOSE = 0.40：鼻子頂著紙邊
    "carry": (0.91, 0.38, "mouth"),             # MOUTH["right"]：游標會接在這裡
    "eat": (0.87, 0.64, "bowl center"),         # EAT_REACH = 0.37：碗放在這裡
    "poop": (0.20, 0.64, "poop lands"),         # POOP_BEHIND = 0.30
}


def cells():
    """逐格回傳 (列, 欄, 內容)。"""
    for r, row in enumerate(ROWS):
        assert len(row) == COLS, (r, len(row))
        for c, item in enumerate(row):
            yield r, c, item
