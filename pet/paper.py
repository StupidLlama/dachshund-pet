"""清單、泡泡、番茄牌子、Settings 共用的「筆記本紙」顏色和小工具。"""
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QPainterPath
from PySide6.QtWidgets import QApplication

PAPER = QColor("#FFFDF6")     # 米白紙
RULE = QColor("#BFD6F2")      # 藍色橫線
MARGIN = QColor("#EBA2A2")    # 左邊紅色邊線
INK = QColor("#1E1B16")       # 深色外框、字
MUTED = QColor("#6E675C")     # 灰字（打勾後、日期）
TOMATO = QColor("#E2553B")    # 紅標籤、紅勾
LEAF = QColor("#5A9A3C")      # 休息時間的綠字
SHADOW = QColor(0, 0, 0, 64)  # 紙的陰影（rgba 0,0,0,.25）

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]   # 不靠系統語系，永遠是英文


def hand_font(px: float, bold: bool = False) -> QFont:
    """EvanHand（程式啟動時已經設成整個 app 的字型，含中文 / emoji fallback）。"""
    f = QFont(QApplication.font())
    f.setPixelSize(max(8, int(round(px))))
    f.setBold(bold)
    return f


def msg_font(px: float) -> QFont:
    """訊息用的字：英數字用 EvanHand，中文用標楷體（手寫感，Windows 繁中內建），再不行用正黑體、emoji。"""
    f = hand_font(px)
    fams = list(f.families()) if hasattr(f, "families") else []
    first = fams[0] if fams else f.family()
    cjk = ["DFKai-SB", "標楷體", "KaiTi", "BiauKai"]
    rest = [x for x in fams[1:] if x not in cjk]
    f.setFamilies([first] + cjk + rest + ["Microsoft JhengHei UI", "Segoe UI Emoji"])
    return f


def left_round_rect(r: QRectF, radius: float) -> QPainterPath:
    """只有左上、左下是圓角的長方形（清單和紅標籤：右邊貼著螢幕邊）。"""
    rad = min(radius, r.height() / 2, r.width() / 2)
    p = QPainterPath()
    p.moveTo(r.right(), r.top())
    p.lineTo(r.left() + rad, r.top())
    p.arcTo(QRectF(r.left(), r.top(), rad * 2, rad * 2), 90, 90)
    p.lineTo(r.left(), r.bottom() - rad)
    p.arcTo(QRectF(r.left(), r.bottom() - rad * 2, rad * 2, rad * 2), 180, 90)
    p.lineTo(r.right(), r.bottom())
    p.closeSubpath()
    return p
