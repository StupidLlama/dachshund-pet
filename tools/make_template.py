"""出 v0.5 新動畫的描圖模板（一張大圖，格子 + 淡淡的草圖 + 對位記號）。

用法（在專案資料夾執行）：
    py tools/make_template.py                 # 輸出 sketches/v05_template.png
    py tools/make_template.py --out 某個.png

怎麼畫：
    1. 把模板匯進繪圖 App 當最底下的圖層，在上面開新圖層畫。
    2. 每格 320×320。動作格：腳底中點在橫線（高 64%）和中間短直線的交點，不要畫影子。
       紅點是程式會對位的地方（咬的點、鼻子、嘴巴、碗），盡量對準。
    3. 匯出時關掉模板圖層、背景透明、畫布大小不要改（2560×2880），存成 PNG。
    4. py tools/slice_sheet.py 你的圖.png  → 自動切好放進 assets/。
只需要 Pillow。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from export_sketches import render  # noqa: E402
from sheet_layout import CELL, COLS, GROUND_V, HEIGHT, LETTER, MARKS, ROWS, WIDTH, cells  # noqa: E402

from pet.dog_model import ANIMS  # noqa: E402
from pet.poop_rules import RARITIES  # noqa: E402

GHOST = 0.40                      # 草圖的不透明度
LINE = (150, 190, 230, 255)       # 格線
GUIDE = (190, 205, 220, 255)      # 腳底線
TEXT = (90, 100, 115, 255)
RED = (226, 85, 59, 255)


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _ghost(img: Image.Image, k: float = GHOST) -> Image.Image:
    a = img.getchannel("A").point(lambda v: int(v * k))
    out = img.copy()
    out.putalpha(a)
    return out


def _item_sketch(kind: str, name: str) -> Image.Image:
    """道具格的參考草圖（很簡單，照自己的風格畫就好）。"""
    S = CELL * 2
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = (43, 33, 24, 255)
    cx, base = S // 2, int(S * 0.85)
    if kind == "poop":
        col = next(r[3] for r in RARITIES if r[0] == name)
        for w, h, up in ((0.30, 0.11, 0.11), (0.21, 0.10, 0.29), (0.12, 0.09, 0.45)):
            d.ellipse((cx - S * w, base - S * (up + h), cx + S * w, base - S * (up - h)), fill=col, outline=ink, width=6)
    elif name == "broom":
        d.line((cx, base - S * 0.18, cx + S * 0.14, base - S * 0.72), fill="#A8702E", width=22)
        d.rounded_rectangle((cx - S * 0.16, base - S * 0.20, cx + S * 0.16, base), radius=14, fill="#E8C766",
                            outline=ink, width=6)
    elif name == "bowl":
        d.rounded_rectangle((cx - S * 0.26, base - S * 0.20, cx + S * 0.26, base), radius=30, fill="#D9534F",
                            outline=ink, width=6)
        d.ellipse((cx - S * 0.25, base - S * 0.26, cx + S * 0.25, base - S * 0.14), fill="#7A2E2B", outline=ink, width=6)
    else:                                             # treat：骨頭餅乾
        y = base - S * 0.12
        d.rounded_rectangle((cx - S * 0.16, y - S * 0.04, cx + S * 0.16, y + S * 0.04), radius=16, fill="#C68642",
                            outline=ink, width=6)
        for sx in (-1, 1):
            for sy in (-1, 1):
                x0, y0 = cx + sx * S * 0.17, y + sy * S * 0.04
                d.ellipse((x0 - S * 0.045, y0 - S * 0.045, x0 + S * 0.045, y0 + S * 0.045), fill="#C68642",
                          outline=ink, width=6)
    return img.resize((CELL, CELL), Image.LANCZOS)


ITEM_NOTE = {
    "broom": "broom: brush head at bottom center",
    "bowl": "bowl: empty (treat goes on top)",
}


def build() -> Image.Image:
    sheet = Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, 255))
    d = ImageDraw.Draw(sheet)
    f_label, f_small = _font(22), _font(17)
    for r, c, item in cells():
        x, y = c * CELL, r * CELL
        if item is None:
            d.line((x + 20, y + 20, x + CELL - 20, y + CELL - 20), fill=GUIDE, width=2)
            continue
        if item[0] == "anim":
            _, name, i = item
            n = ANIMS[name][0]
            gy = y + int(CELL * GROUND_V)
            d.line((x + 12, gy, x + CELL - 12, gy), fill=GUIDE, width=2)                 # 腳底線
            d.line((x + CELL // 2, gy - 10, x + CELL // 2, gy + 10), fill=GUIDE, width=2)
            ghost = _ghost(render(name, "down", i / n, CELL))
            sheet.alpha_composite(ghost, (x, y))
            d.text((x + 10, y + 8), f"{LETTER[name]}{i + 1}  {name}", fill=TEXT, font=f_label)
            if name in MARKS:
                u, v, note = MARKS[name]
                mx, my = x + u * CELL, y + v * CELL
                d.ellipse((mx - 6, my - 6, mx + 6, my + 6), outline=RED, width=3)
                if i == 0:
                    if u < 0.5:
                        d.text((mx + 12, my + 6), note, fill=RED, font=f_small, anchor="la")
                    else:
                        d.text((mx - 4, my + 10), note, fill=RED, font=f_small, anchor="ra")
        else:
            kind, name = item
            sheet.alpha_composite(_ghost(_item_sketch(kind, name)), (x, y))
            label = f"poop: {name}" if kind == "poop" else ITEM_NOTE.get(name, name.replace("_0", " "))
            d.text((x + 10, y + 8), label, fill=TEXT, font=f_small if len(label) > 22 else f_label)
    for c in range(COLS + 1):                                                            # 格線
        d.line((min(c * CELL, WIDTH - 1), 0, min(c * CELL, WIDTH - 1), HEIGHT), fill=LINE, width=2)
    for r in range(len(ROWS) + 1):
        d.line((0, min(r * CELL, HEIGHT - 1), WIDTH, min(r * CELL, HEIGHT - 1)), fill=LINE, width=2)
    return sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "sketches" / "v05_template.png"))
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    build().save(out)
    print(f"done -> {out}  ({WIDTH}x{HEIGHT}, {CELL}px cells)")


if __name__ == "__main__":
    main()
