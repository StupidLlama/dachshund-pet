"""把 Evan 畫好的 v0.5 sprite sheet 切開，放進 assets/（版面見 sheet_layout.py）。

用法（在專案資料夾執行）：
    py tools/slice_sheet.py 我的圖.png             # 切到 assets/
    py tools/slice_sheet.py 我的圖.png --out 測試   # 切到別的資料夾先看看

    動作格  → assets/<動作>/frame_01.png ...（320×320，位置不動）
    道具格  → assets/items/<名字>.png、assets/items/poop_<稀有度>.png（裁掉四周透明的部分）
空的格子會跳過（還沒畫的動作，程式會照舊用原本的動作湊）。
圖要是「模板圖層關掉、背景透明、畫布大小沒改」；不小心匯出成白底的話，會自動把格子外圍的白色去掉。
切完建議再跑一次 py tools/defringe.py 去白邊。
只需要 Pillow。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from sheet_layout import CELL, COLS, ROWS, cells  # noqa: E402

EMPTY_ALPHA = 12        # 整格的 alpha 都低於這個 = 空格


def _key_white(cell: Image.Image) -> Image.Image:
    """白底的圖：從四個角把連在一起的白色變透明。"""
    cell = cell.convert("RGBA")
    w, h = cell.size
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        r, g, b, a = cell.getpixel(xy)
        if a > 0 and min(r, g, b) >= 235:
            ImageDraw.floodfill(cell, xy, (255, 255, 255, 0), thresh=40)
    return cell


def slice_sheet(path: Path, out: Path) -> dict:
    img = Image.open(path).convert("RGBA")
    cw, ch = img.width / COLS, img.height / len(ROWS)
    if abs(cw - ch) > 1:
        raise SystemExit(f"畫布比例不對：{img.width}x{img.height}，應該是 {COLS}:{len(ROWS)}（例如 {COLS * CELL}x{len(ROWS) * CELL}）")
    opaque = img.getchannel("A").getextrema()[0] >= 250          # 沒有透明的地方 = 白底
    if opaque:
        print("注意：這張圖沒有透明背景，會自動把白底去掉（下次匯出記得選透明背景）")
    done: dict[str, int] = {}
    skipped: list[str] = []
    for r, c, item in cells():
        if item is None:
            continue
        box = (round(c * cw), round(r * ch), round((c + 1) * cw), round((r + 1) * ch))
        cell = img.crop(box)
        if opaque:
            cell = _key_white(cell)
        if cell.getchannel("A").getextrema()[1] < EMPTY_ALPHA:
            skipped.append(f"{item[1]}" + (f"#{item[2] + 1}" if item[0] == "anim" else ""))
            continue
        if item[0] == "anim":
            _, name, i = item
            if cell.size != (CELL, CELL):
                cell = cell.resize((CELL, CELL), Image.LANCZOS)
            dest = out / name / f"frame_{i + 1:02d}.png"
            done[name] = done.get(name, 0) + 1
        else:
            kind, name = item
            bbox = cell.getchannel("A").point(lambda v: 255 if v >= EMPTY_ALPHA else 0).getbbox()
            cell = cell.crop((max(0, bbox[0] - 2), max(0, bbox[1] - 2),
                              min(cell.width, bbox[2] + 2), min(cell.height, bbox[3] + 2)))
            dest = out / "items" / (f"poop_{name}.png" if kind == "poop" else f"{name}.png")
            done[f"{kind}:{name}"] = 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        cell.save(dest)
    # 同一個動作，前面有畫、中間缺格：提醒一下（程式是照檔名順序播的）
    for name in {k for k in done if ":" not in k}:
        frames = sorted(p.name for p in (out / name).glob("frame_*.png"))
        want = [f"frame_{i + 1:02d}.png" for i in range(len(frames))]
        if frames != want:
            print(f"注意：{name} 的格子不連續：{frames}")
    return {"done": done, "skipped": skipped}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--out", default=str(ROOT / "assets"))
    args = ap.parse_args()
    res = slice_sheet(Path(args.sheet), Path(args.out))
    for k, n in sorted(res["done"].items()):
        print(f"  {k}: {n}")
    if res["skipped"]:
        print("空的格子（跳過）:", ", ".join(res["skipped"]))
    print(f"done -> {args.out}")


if __name__ == "__main__":
    main()
