"""載入 sprite 圖片；找不到正式圖時，用 dog_model 自動畫草圖頂替。

正式圖放法（詳見 README）：
    assets/walk/right/frame_01.png ...   分方向動作只要畫 5 個方向
    assets/idle/frame_01.png ...         不分方向的動作
左邊的方向（left / up_left / down_left）程式會自動鏡像。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QTransform

from .dog_model import ANIMS, DRAWN_DIRS, HELD_GRAB, MIRROR_OF, OUTLINE, PALETTE, build
from .shadow import ALPHA_ON, GRID, mirror, shadow_from_masks

BASE_SIZE = 160
LYING = {"belly", "sleep"}   # 躺在地上的動作，影子貼身體
HELD_FIRST_SEC = 0.25      # 剛被拎起來時，第 1 格停多久


def _mirror(px: QPixmap) -> QPixmap:
    return px.transformed(QTransform().scale(-1, 1), Qt.SmoothTransformation)


def _mask(px: QPixmap) -> list[list[bool]]:
    img = px.toImage().scaled(GRID, GRID, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return [[img.pixelColor(x, y).alpha() > ALPHA_ON for x in range(GRID)] for y in range(GRID)]


def render_sketch(anim: str, direction: str, phase: float, size: int) -> QPixmap:
    """把 dog_model 的繪圖指令畫成 QPixmap。"""
    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    w = OUTLINE * size
    for op in build(anim, direction, phase):
        if op.kind == "discs":
            if op.outline:
                p.setBrush(QColor(PALETTE[op.outline]))
                for u, v, r in op.data:
                    p.drawEllipse(QPointF(u * size, v * size), r * size + w, r * size + w)
            p.setBrush(QColor(PALETTE[op.fill]))
            for u, v, r in op.data:
                p.drawEllipse(QPointF(u * size, v * size), r * size, r * size)
        elif op.kind == "line":
            (u0, v0), (u1, v1) = op.data
            p.setPen(QPen(QColor(PALETTE[op.fill]), max(1.0, op.width * size), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(u0 * size, v0 * size), QPointF(u1 * size, v1 * size))
            p.setPen(Qt.NoPen)
        elif op.kind == "text":
            (u, v), = op.data
            font = QFont()
            font.setPixelSize(max(6, int(op.width * size)))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(PALETTE[op.fill]))
            p.drawText(QPointF(u * size, v * size), op.text)
            p.setPen(Qt.NoPen)
    p.end()
    return px


class SpriteLibrary:
    def __init__(self, assets_dir: Path, size: int):
        self.size = size
        self.frames: dict[tuple[str, str], list[QPixmap]] = {}
        self.sketched: list[str] = []          # 哪些動作還在用草圖
        self.shadows: dict[tuple[str, str], tuple | None] = {}   # 從圖片算出來的影子
        manual = self._load_shadows(assets_dir / "shadows.json")   # Evan 用 Shadow Picker 調的（有就優先用）
        for name, (n, _fps, directional) in ANIMS.items():
            if directional:
                for d in DRAWN_DIRS:
                    self.frames[(name, d)] = self._load_or_sketch(assets_dir / name / d, name, d, n)
                    self.shadows[(name, d)] = manual.get(f"{name}/{d}") or self._shadow(self.frames[(name, d)])
                for d, src in MIRROR_OF.items():
                    self.frames[(name, d)] = [_mirror(px) for px in self.frames[(name, src)]]
                    self.shadows[(name, d)] = mirror(self.shadows[(name, src)])
            else:
                frames = self._load_or_sketch(assets_dir / name, name, "down", n)
                self.frames[(name, "front")] = frames
                self.frames[(name, "front_flip")] = [_mirror(px) for px in frames]
                self.shadows[(name, "front")] = manual.get(name) or self._shadow(frames, lying=name in LYING)
                self.shadows[(name, "front_flip")] = mirror(self.shadows[(name, "front")])
        # 拎起來時游標抓的位置：有正式圖才讀 grab.json，草圖用預設值
        if "held" in self.sketched:
            self.held_grabs = [HELD_GRAB]
        else:
            self.held_grabs = self._load_grabs(assets_dir / "held" / "grab.json")

    @staticmethod
    def _load_shadows(path: Path) -> dict[str, tuple]:
        """assets/shadows.json：{"idle": [cx, cy, a, b, angle], "walk/right": [...], ...}（sprite 邊長比例、角度）。
        Shadow Picker 工具調出來的；沒有寫到的動作照舊自動算，往左的方向自動鏡像。"""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {k: tuple(float(v) for v in vals) for k, vals in data.items()
                    if isinstance(vals, list) and len(vals) == 5}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    @staticmethod
    def _load_grabs(path: Path) -> list[tuple[float, float]]:
        """assets/held/grab.json：每一格「脖子」的位置 [[x, y], ...]（圖片寬高的比例）。"""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            grabs = [(float(x), float(y)) for x, y in data]
            if grabs:
                return grabs
        except (OSError, ValueError, TypeError):
            pass
        return [HELD_GRAB]

    def _held_index(self, t: float) -> int:
        return 0 if t < HELD_FIRST_SEC else -1

    def held_grab(self, t: float, flip: bool = False) -> tuple[float, float]:
        """被拎著時，游標要抓住的位置（跟著目前顯示的那一格）。"""
        n = len(self.frames[("held", "front")])
        i = self._held_index(t) % n
        x, y = self.held_grabs[min(i, len(self.held_grabs) - 1)]
        return (1.0 - x if flip else x), y

    @staticmethod
    def _shadow(frames: list[QPixmap], lying: bool = False):
        return shadow_from_masks([_mask(px) for px in frames], lying=lying)

    def shadow(self, name: str, direction: str, flip: bool = False):
        """(cx, cy, a, b, angle)，單位是 sprite 邊長比例；沒有就回傳 None。"""
        if ANIMS[name][2]:
            return self.shadows.get((name, direction))
        return self.shadows.get((name, "front_flip" if flip else "front"))

    def _load_or_sketch(self, folder: Path, name: str, direction: str, n: int) -> list[QPixmap]:
        if folder.is_dir():
            loaded = []
            for f in sorted(folder.glob("*.png")):
                px = QPixmap(str(f))
                if not px.isNull():
                    loaded.append(self._fit(px))
            if loaded:
                return loaded
        self.sketched.append(f"{name}/{direction}" if ANIMS[name][2] else name)
        return [render_sketch(name, direction, i / n, self.size) for i in range(n)]

    def _fit(self, px: QPixmap) -> QPixmap:
        """縮到 size×size，置中放在透明正方形上（圖不是正方形也不會跑位）。"""
        scaled = px.scaled(self.size, self.size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if scaled.width() == self.size and scaled.height() == self.size:
            return scaled
        canvas = QPixmap(self.size, self.size)
        canvas.fill(Qt.transparent)
        p = QPainter(canvas)
        p.drawPixmap((self.size - scaled.width()) // 2, self.size - scaled.height(), scaled)
        p.end()
        return canvas

    def _key(self, name: str, direction: str, flip: bool) -> tuple[str, str]:
        if ANIMS[name][2]:
            return (name, direction)
        return (name, "front_flip" if flip else "front")

    def frame_at(self, name: str, direction: str, index: int, flip: bool = False) -> QPixmap:
        """固定拿第 index 格（嚇一跳用 held 第 1 格、滑行用 belly 第 1 格）。"""
        frames = self.frames[self._key(name, direction, flip)]
        return frames[index % len(frames)]

    def frame(self, name: str, direction: str, t: float, flip: bool = False) -> QPixmap:
        n, fps, directional = ANIMS[name]
        if directional:
            key = (name, direction)
        else:
            key = (name, "front_flip" if flip else "front")
        frames = self.frames[key]
        if name == "held":
            # 拎起來：先停在第 1 格一下下，之後一直停在最後一格（不循環）
            return frames[self._held_index(t)]
        return frames[int(t * fps) % len(frames)]
