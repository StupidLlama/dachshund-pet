"""去掉狗圖外框外面的白邊（從白底切圖時殘留的白／灰色半透明像素）。

用法：
    py tools/defringe.py                 # 處理 assets/ 底下所有動作的 frame_*.png
    py tools/defringe.py --check         # 只統計，不改檔

做法：只看「透明區旁邊 3px 以內」的像素，如果它是白色或灰色（不是黃色身體、粉紅舌頭），
就改成外框的深色、保留原本的透明度 → 白點消失，邊緣還是平滑的。
第一次執行會先把原圖整份備份到 assets_original/（已經有備份就不再覆蓋）。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
BACKUP = ROOT / "assets_original"
OUTLINE = (24, 18, 12)      # 外框的深色
BAND = 3                    # 透明區往內幾 px 算「邊緣」


def defringe(im: Image.Image) -> tuple[Image.Image, int]:
    im = im.convert("RGBA")
    a = np.array(im).astype(np.int16)
    alpha = a[:, :, 3]
    clear = Image.fromarray(((alpha < 8) * 255).astype(np.uint8))
    near = np.array(clear.filter(ImageFilter.MaxFilter(2 * BAND + 1))) > 0
    rgb = a[:, :, :3]
    lo, hi = rgb.min(axis=2), rgb.max(axis=2)
    whitish = (lo > 110) & (hi - lo < 45)          # 白、灰；黃色和粉紅的彩度高，不會被選到
    fix = near & whitish & (alpha >= 8)
    a[fix, 0], a[fix, 1], a[fix, 2] = OUTLINE
    return Image.fromarray(a.astype(np.uint8), "RGBA"), int(fix.sum())


def frames():
    return sorted(p for p in ASSETS.rglob("frame_*.png") if "fonts" not in p.parts)


def main() -> None:
    check = "--check" in sys.argv
    if not check and not BACKUP.exists():
        shutil.copytree(ASSETS, BACKUP)
        print(f"備份原圖 → {BACKUP}")
    total = 0
    for p in frames():
        out, n = defringe(Image.open(p))
        total += n
        if not check and n:
            out.save(p)
    print(f"{len(frames())} 張圖，修正 {total} 個白邊像素" + ("（只檢查，沒改檔）" if check else ""))


if __name__ == "__main__":
    main()
