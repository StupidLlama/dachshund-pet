"""匯出草圖：給你描正式圖用。

用法（在專案資料夾執行）：
    py tools/export_sketches.py            # 輸出到 sketches/
    py tools/export_sketches.py --size 320

會產生：
    sketches/<動作>/<方向>/frame_01.png ...   分方向的動作（walk、run）
    sketches/<動作>/frame_01.png ...          不分方向的動作
    sketches/contact_sheet.png                 全部縮圖一張看完
只需要 Pillow：py -m pip install pillow
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pet.dog_model import ANIMS, DRAWN_DIRS, OUTLINE, PALETTE, build  # noqa: E402

SUPER = 4  # 先放大 4 倍畫再縮小 = 反鋸齒


def render(anim: str, direction: str, phase: float, size: int) -> Image.Image:
    big = size * SUPER
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = OUTLINE * big
    for op in build(anim, direction, phase):
        if op.kind == "discs":
            if op.outline:
                for u, v, r in op.data:
                    R = r * big + w
                    d.ellipse((u * big - R, v * big - R, u * big + R, v * big + R), fill=PALETTE[op.outline])
            for u, v, r in op.data:
                R = r * big
                d.ellipse((u * big - R, v * big - R, u * big + R, v * big + R), fill=PALETTE[op.fill])
        elif op.kind == "line":
            (u0, v0), (u1, v1) = op.data
            d.line((u0 * big, v0 * big, u1 * big, v1 * big), fill=PALETTE[op.fill],
                   width=max(1, int(op.width * big)))
        elif op.kind == "text":
            (u, v), = op.data
            try:
                font = ImageFont.load_default(size=int(op.width * big))
            except TypeError:
                font = ImageFont.load_default()
            d.text((u * big, v * big), op.text, fill=PALETTE[op.fill], font=font, anchor="ls")
    return img.resize((size, size), Image.LANCZOS)


def jobs():
    for anim, (n, _fps, directional) in ANIMS.items():
        dirs = DRAWN_DIRS if directional else ["front"]
        for direction in dirs:
            yield anim, direction, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=320)
    ap.add_argument("--out", default=str(ROOT / "sketches"))
    args = ap.parse_args()
    out = Path(args.out)

    rows = []
    for anim, direction, n in jobs():
        folder = out / anim / direction if direction != "front" else out / anim
        folder.mkdir(parents=True, exist_ok=True)
        frames = []
        for i in range(n):
            img = render(anim, direction if direction != "front" else "down", i / n, args.size)
            img.save(folder / f"frame_{i + 1:02d}.png")
            frames.append(img)
        rows.append((f"{anim} / {direction}", frames))

    # 縮圖總表
    cell = 128
    label_w = 170
    max_n = max(len(f) for _, f in rows)
    sheet = Image.new("RGB", (label_w + cell * max_n, cell * len(rows)), "#F4F1EA")
    sd = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=18)
    except TypeError:
        font = ImageFont.load_default()
    for r, (label, frames) in enumerate(rows):
        y = r * cell
        if r % 2:
            sd.rectangle((0, y, sheet.width, y + cell), fill="#ECE7DC")
        sd.text((10, y + cell // 2), label, fill="#333", font=font, anchor="lm")
        for c, f in enumerate(frames):
            thumb = f.resize((cell, cell), Image.LANCZOS)
            sheet.paste(thumb, (label_w + c * cell, y), thumb)
    sheet.save(out / "contact_sheet.png")
    print(f"done → {out}")


if __name__ == "__main__":
    main()
