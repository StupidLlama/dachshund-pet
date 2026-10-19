"""自訂字型：把 .ttf / .otf / .ttc 放進 assets/fonts/，程式會自動載入，
名字、心情、對話泡泡、右鍵選單的字都會用它。沒有字型檔就用系統字型。
"""
from __future__ import annotations

from pathlib import Path

FONT_EXTS = (".ttf", ".otf", ".ttc")


def find_font_files(assets_dir: Path) -> list[Path]:
    folder = Path(assets_dir) / "fonts"
    if not folder.is_dir():
        return []
    return sorted(f for f in folder.iterdir() if f.suffix.lower() in FONT_EXTS)


def load_custom_font(app, assets_dir: Path) -> str | None:
    """載入 assets/fonts/ 裡的第一個字型並設成整個程式的字型。回傳字型名稱或 None。"""
    from PySide6.QtGui import QFont, QFontDatabase

    for f in find_font_files(assets_dir):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(fid)
        if not families:
            continue
        font = QFont(app.font())
        # 手寫字型只有英數字：中文、emoji 等沒有的字自動改用系統字型
        fallback = [app.font().family(), "Microsoft JhengHei UI", "Microsoft JhengHei", "Segoe UI Emoji"]
        font.setFamilies([families[0]] + [f for f in fallback if f and f != families[0]])
        app.setFont(font)
        return families[0]
    return None
