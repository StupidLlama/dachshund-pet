"""v0.5：地上的東西 — 大便（有稀有度）、掃把、零食碗。規則（稀有度、計時）在 poop_rules.py。

    大便    狗每 30~60 分鐘（隨機）大一次，吃了零食會更快。大便是一個小視窗留在桌面上，最多 10 坨；
            滿了狗就先憋著。之後的版本要做收集，所以每一坨「大過 / 掃掉」都有記在 settings.json 的 poop_log。
    掃把    右鍵選單拿出來，跟著游標走；掃把碰到的大便都會被掃掉（一次可以掃很多）。
            全部掃完、或 20 秒沒掃到東西會自己收起來。
    零食碗  右鍵選單拿出來，放在狗前面的地上；狗跑去吃，吃完碗會消失。

圖片（Evan 畫的，沒有就用程式畫的草圖頂替）：
    assets/items/poop_common.png、poop_uncommon.png、poop_rare.png、poop_epic.png、poop_legendary.png
    assets/items/broom.png（刷頭在圖的下面中間）、bowl.png（空碗）、
    assets/items/treat_01.png、treat_02.png ...（零食，隨機挑一張放在碗上）
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from .poop_rules import (POOP_MAX, RARITY_COLOR, RARITY_GLOW, RARITY_KEYS, RARITY_LABEL, TREATS,  # noqa: F401
                         Buffs, PoopClock, roll_rarity)

POOP_SIZE = 0.30 * 0.6      # 大便大小（× 狗的 sprite 邊長 S；沒有圖時用）
POOP_SCALE = 0.6            # Evan 畫的大便縮小成畫的時候的幾倍（Evan：大便縮小）
BOWL_SCALE = 0.6            # 碗、零食也縮小（Evan：碗和零食小一點）
BROOM_SIZE = 0.75
BOWL_SIZE = 0.42 * 0.6
SWEEP_RADIUS = 0.24         # 掃把頭離大便多近算掃到（× S）
SWEEP_SEC = 0.35            # 被掃掉的動畫多久
BROOM_IDLE_SEC = 20.0       # 掃把多久沒掃到東西就自己收起來
BROOM_DONE_SEC = 1.2        # 全部掃完後多久收起來
BOWL_GONE_SEC = 1.5         # 吃完後碗多久消失

INK = QColor(43, 33, 24)
GLOW_SIZE = 0.62            # 光暈半徑 × 東西的大小（Evan：光暈小一點）
GLOW_ALPHA = {"common": 70, "uncommon": 110, "rare": 120, "epic": 135, "legendary": 150}


def paint_glow(p: QPainter, cx: float, cy: float, radius: float, rarity: str, t: float = 0.0) -> None:
    """依稀有度畫一圈柔柔的光（中間亮、外面透明）。Legendary 會一明一暗。"""
    a = GLOW_ALPHA.get(rarity, 90)
    if rarity == "legendary":
        a = int(a * (0.75 + 0.25 * math.sin(t * 3.0)))
        radius *= 1.0 + 0.06 * math.sin(t * 3.0)
    c = QColor(RARITY_GLOW.get(rarity, "#A0A0A0"))
    g = QRadialGradient(QPointF(cx, cy), radius)
    c.setAlpha(a)
    g.setColorAt(0.0, c)
    c.setAlpha(int(a * 0.55))
    g.setColorAt(0.55, c)
    c.setAlpha(0)
    g.setColorAt(1.0, c)
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(cx, cy), radius, radius)


def paint_sparkles(p: QPainter, cx: float, cy: float, rx: float, ry: float, n: int, t: float, size: float) -> None:
    """繞著東西轉的小亮點（Epic、Legendary）。"""
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 235))
    for i in range(n):
        a = t * 2.0 + i * 2 * math.pi / n
        r = size * (0.6 + 0.4 * math.sin(t * 5 + i))
        p.drawEllipse(QPointF(cx + math.cos(a) * rx, cy + math.sin(a) * ry), r, r)


DRAWN_CELL = 320            # Evan 在模板上畫的格子大小：道具跟狗用同一個比例（格子邊長 = 狗的 S）


def _load(path: Path, S: int, scale: float = 1.0):
    """讀 Evan 畫的道具圖，照「畫的時候跟狗的比例」縮放（320 px 格子 = 狗的 S）；沒有檔案回傳 None（改用草圖）。"""
    px = QPixmap(str(path))
    if px.isNull():
        return None
    k = S / DRAWN_CELL * scale
    return px.scaled(max(1, round(px.width() * k)), max(1, round(px.height() * k)),
                     Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def _fit(px, default: float, S: int) -> int:
    """視窗大小：有圖就照圖的大小，沒圖用預設值（× S）。"""
    return max(px.width(), px.height()) if px is not None else int(default * S)


class _Item(QWidget):
    """地上的小東西：透明、置頂、不搶焦點、滑鼠穿透的小視窗。place(cx, ground_y) = 底部中間貼在地面點。"""

    def __init__(self, size: int):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoDropShadowWindowHint
            | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.size_px = int(size)
        self.pad = int(size * 0.25)                    # 四周留一點空間給特效
        self.resize(self.size_px + 2 * self.pad, self.size_px + 2 * self.pad)
        self.cx = self.cy = 0.0

    def place(self, cx: float, ground_y: float) -> None:
        self.cx, self.cy = float(cx), float(ground_y)
        self.move(int(round(cx - self.width() / 2)), int(round(ground_y - self.pad - self.size_px * 0.92)))

    def _painter(self) -> QPainter:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        return p

    def _draw_centered(self, p: QPainter, px, dy: float = 0.0) -> None:
        """把圖畫在視窗中間、底部對齊。"""
        x = (self.width() - px.width()) / 2
        y = self.pad + self.size_px - px.height() + dy
        p.drawPixmap(QPointF(x, y), px)


class PoopWindow(_Item):
    def __init__(self, assets_dir: Path, S: int, rarity: str):
        rarity = rarity if rarity in RARITY_KEYS else RARITY_KEYS[0]
        px = _load(Path(assets_dir) / "items" / f"poop_{rarity}.png", S, POOP_SCALE)
        super().__init__(_fit(px, POOP_SIZE, S))
        self.rarity = rarity
        self.px = px
        self.swept_t = -1.0                             # >= 0：正在被掃掉
        self.sweep_dir = 1.0
        self.age = 0.0

    @property
    def gone(self) -> bool:
        return self.swept_t >= SWEEP_SEC

    def sweep(self, direction: float) -> None:
        if self.swept_t < 0:
            self.swept_t = 0.0
            self.sweep_dir = 1.0 if direction >= 0 else -1.0

    def tick(self, dt: float) -> None:
        self.age += dt
        if self.swept_t >= 0:
            self.swept_t += dt
            self.update()
        elif self.rarity == "legendary" or self.rarity == "epic" or (self.rarity != "common" and self.px is None):
            self.update()                               # 會閃的光、亮晶晶

    def paintEvent(self, e) -> None:
        p = self._painter()
        if self.swept_t >= 0:                           # 被掃掉：往旁邊滑 + 變淡
            k = min(1.0, self.swept_t / SWEEP_SEC)
            p.setOpacity(1.0 - k)
            p.translate(self.sweep_dir * self.pad * 0.9 * k, 0)
        w, h = (self.px.width(), self.px.height()) if self.px is not None else (self.size_px * 0.84, self.size_px * 0.8)
        cx, cy = self.width() / 2, self.pad + self.size_px - h / 2
        paint_glow(p, cx, cy, max(w, h) * GLOW_SIZE, self.rarity, self.age)
        if self.px is not None:
            self._draw_centered(p, self.px)
            if self.rarity in ("epic", "legendary"):
                paint_sparkles(p, cx, cy, w * 0.55, h * 0.5, 3 if self.rarity == "epic" else 5, self.age,
                               max(1.5, max(w, h) * 0.045))
        else:
            self._sketch(p)
        p.end()

    def _sketch(self, p: QPainter) -> None:
        """還沒有圖：三層的便便，顏色跟著稀有度；稀有的旁邊有亮晶晶。"""
        s = self.size_px
        cx = self.width() / 2
        base = self.pad + s * 0.95
        p.setPen(QPen(INK, max(1.5, s * 0.045)))
        p.setBrush(QColor(RARITY_COLOR[self.rarity]))
        for w, h, up in ((0.42, 0.17, 0.17), (0.30, 0.15, 0.42), (0.17, 0.13, 0.64)):
            p.drawEllipse(QPointF(cx, base - s * up), s * w, s * h)
        n = RARITY_KEYS.index(self.rarity)
        if n:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 230))
            for i in range(n):
                a = self.age * 2.0 + i * 2 * math.pi / n
                r = s * 0.05 * (0.6 + 0.4 * math.sin(self.age * 5 + i))
                p.drawEllipse(QPointF(cx + math.cos(a) * s * 0.42, base - s * 0.45 + math.sin(a) * s * 0.3), r, r)


class BroomWindow(_Item):
    """跟著游標走的掃把。游標握在掃把中間（GRIP_AT 高度的掃把柄上），掃把繞著握的地方轉；刷頭負責掃。"""

    GRIP_AT = 0.45              # 握的位置：圖高度的幾成（Evan：握掃把中間）
    HEAD_FROM = 0.75            # 刷頭：圖下面這幾成的中心
    SWING = 0.04                # 左右移動多快 → 歪幾度
    SWING_MAX = 35.0

    def __init__(self, assets_dir: Path, S: int):
        px = _load(Path(assets_dir) / "items" / "broom.png", S)
        if px is not None:
            iw, ih = px.width(), px.height()
        else:
            iw = ih = int(BROOM_SIZE * S)
        self.px = px
        self.iw, self.ih = iw, ih
        self.grip = self._find_grip(px, iw, ih)
        self.head = self._find_head(px, iw, ih)
        gx, gy = self.grip
        reach = max(math.hypot(cx - gx, cy - gy) for cx, cy in ((0, 0), (iw, 0), (0, ih), (iw, ih)))
        super().__init__(1)
        side = int(2 * reach + 6)                       # 夠大，轉到哪個角度都不會被切到
        self.resize(side, side)
        self.angle = 0.0
        self.drawn_angle = None
        self.pos_xy = None

    def _find_grip(self, px, iw: int, ih: int) -> tuple[float, float]:
        """握的點：GRIP_AT 那一列不透明的地方的中間（就是掃把柄）。"""
        y = int(ih * self.GRIP_AT)
        if px is not None:
            try:
                img = px.toImage()
                xs = [x for x in range(iw) if img.pixelColor(x, y).alpha() > 128]
                if xs:
                    return (sum(xs) / len(xs), float(y))
            except Exception:
                pass
        return (iw * 0.59, ih * self.GRIP_AT)            # 草圖的柄

    def _find_head(self, px, iw: int, ih: int) -> tuple[float, float]:
        """刷頭的中心：圖下面 HEAD_FROM 以下不透明的地方的平均位置。"""
        if px is not None:
            try:
                img = px.toImage()
                sx = sy = n = 0
                for y in range(int(ih * self.HEAD_FROM), ih, 2):
                    for x in range(0, iw, 2):
                        if img.pixelColor(x, y).alpha() > 128:
                            sx += x
                            sy += y
                            n += 1
                if n:
                    return (sx / n, sy / n)
            except Exception:
                pass
        return (iw * 0.5, ih * 0.88)

    def head_at(self, x: float, y: float) -> tuple[float, float]:
        """游標在 (x, y) 時，刷頭在螢幕上的位置（跟著掃把轉）。"""
        dx, dy = self.head[0] - self.grip[0], self.head[1] - self.grip[1]
        a = math.radians(self.angle)
        return (x + dx * math.cos(a) - dy * math.sin(a), y + dx * math.sin(a) + dy * math.cos(a))

    def follow(self, x: float, y: float, vx: float, dt: float) -> None:
        """握的點貼著游標；往右拖刷頭會落在後面（往左歪），反之亦然。只有真的動了才移動 / 重畫。"""
        want = max(-self.SWING_MAX, min(self.SWING_MAX, vx * self.SWING))
        self.angle += (want - self.angle) * min(1.0, dt * 10)
        xy = (int(round(x - self.width() / 2)), int(round(y - self.height() / 2)))
        if xy != self.pos_xy:
            self.pos_xy = xy
            self.move(*xy)
        if self.drawn_angle is None or abs(self.angle - self.drawn_angle) > 0.5:
            self.drawn_angle = self.angle
            self.update()

    def paintEvent(self, e) -> None:
        p = self._painter()
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(self.angle)
        p.translate(-self.grip[0], -self.grip[1])
        if self.px is not None:
            p.drawPixmap(QPointF(0, 0), self.px)
        else:                                           # 草圖：木柄 + 稻草刷頭
            s = self.iw
            p.setPen(QPen(QColor("#A8702E"), max(3.0, s * 0.06), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(s * 0.5, s * 0.8), QPointF(s * 0.68, s * 0.1))
            p.setPen(QPen(INK, max(1.5, s * 0.02)))
            p.setBrush(QColor("#E8C766"))
            p.drawRoundedRect(QRectF(s * 0.3, s * 0.74, s * 0.4, s * 0.26), s * 0.04, s * 0.04)
        p.end()


class BowlWindow(_Item):
    def __init__(self, assets_dir: Path, S: int):
        folder = Path(assets_dir) / "items"
        px = _load(folder / "bowl.png", S, BOWL_SCALE)
        super().__init__(_fit(px, BOWL_SIZE, S))
        self.px = px
        self.treats = {}                                # 檔名（treat_01 …）→ 圖
        for key in TREATS:
            t = _load(folder / f"{key}.png", S, BOWL_SCALE)
            if t is not None:
                self.treats[key] = t
        self.treat = None
        self.treat_key = None
        self.rarity = "common"
        self.full = False
        self.age = 0.0

    def fill(self, treat_key: str | None = None, rarity: str | None = None) -> tuple[str, str]:
        """放零食：哪一種隨機、稀有度隨機抽（Evan 選 B）。回傳 (零食, 稀有度)。"""
        keys = list(self.treats) or list(TREATS)
        self.treat_key = treat_key if treat_key in TREATS else random.choice(keys)
        self.treat = self.treats.get(self.treat_key)
        self.rarity = rarity if rarity in RARITY_KEYS else roll_rarity()
        self.full = True
        self.update()
        return self.treat_key, self.rarity

    def tick(self, dt: float) -> None:
        self.age += dt
        if self.full and self.isVisible() and self.rarity in ("epic", "legendary"):
            self.update()

    def empty(self) -> None:
        self.full = False
        self.update()

    def paintEvent(self, e) -> None:
        p = self._painter()
        s = self.size_px
        cx, by = self.width() / 2, self.pad + s
        if self.px is not None:
            self._draw_centered(p, self.px)
        else:                                           # 草圖：紅色的碗
            p.setPen(QPen(INK, max(1.5, s * 0.035)))
            p.setBrush(QColor("#D9534F"))
            p.drawRoundedRect(QRectF(cx - s * 0.42, by - s * 0.34, s * 0.84, s * 0.34), s * 0.1, s * 0.1)
            p.setBrush(QColor("#7A2E2B"))
            p.drawEllipse(QPointF(cx, by - s * 0.34), s * 0.4, s * 0.09)
        if self.full:
            top = by - (self.px.height() if self.px is not None else s * 0.36)
            tw, th = (self.treat.width(), self.treat.height()) if self.treat is not None else (s * 0.5, s * 0.2)
            ty = top - th * 0.6 + th / 2                 # 零食中心
            paint_glow(p, cx, ty, max(tw, th) * GLOW_SIZE, self.rarity, self.age)
            if self.rarity in ("epic", "legendary"):
                paint_sparkles(p, cx, ty, tw * 0.55, th * 0.6, 3 if self.rarity == "epic" else 5, self.age,
                               max(1.5, max(tw, th) * 0.04))
            if self.treat is not None:                  # 零食放在碗口上
                p.drawPixmap(QPointF(cx - tw / 2, top - th * 0.6), self.treat)
            else:
                p.setPen(QPen(INK, max(1.0, s * 0.025)))
                p.setBrush(QColor("#C68642"))
                for dx, dy in ((-0.16, 0.0), (0.0, -0.05), (0.16, 0.0)):
                    p.drawEllipse(QPointF(cx + s * dx, top - s * (0.04 - dy)), s * 0.09, s * 0.07)
        p.end()


# ====================================================================== 管理
class Yard:
    """桌面上的大便、掃把、零食碗。PetWindow 每一幀呼叫 tick()。"""

    def __init__(self, assets_dir: Path, S: int, settings):
        self.assets = Path(assets_dir)
        self.S = S
        self.settings = settings
        self.clock = PoopClock(settings.data.get("poop_in"))
        self.buffs = Buffs(settings.data.get("buffs"))   # 吃零食得到的效果
        self.poops: list[PoopWindow] = []
        self.broom = BroomWindow(self.assets, S)
        self.broom_on = False
        self.broom_idle = 0.0
        self.bowl = BowlWindow(self.assets, S)
        self.bowl_hide_in = 0.0
        self._last_cursor: tuple[float, float] | None = None
        self.stack_fn = lambda: None                    # 視窗出現時叫 PetWindow 重新排疊放順序
        for item in settings.data.get("poops") or []:   # 上次留在桌面上的
            try:
                x, y, rarity = float(item[0]), float(item[1]), str(item[2])
            except (TypeError, ValueError, IndexError):
                continue
            if len(self.poops) < POOP_MAX:
                self._spawn(x, y, rarity)

    # ---- 大便
    @property
    def live_poops(self) -> list:
        return [w for w in self.poops if w.swept_t < 0]

    @property
    def full(self) -> bool:
        return len(self.live_poops) >= POOP_MAX

    def _spawn(self, x: float, y: float, rarity: str) -> PoopWindow:
        w = PoopWindow(self.assets, self.S, rarity)
        w.place(x, y)
        w.show()
        self.poops.append(w)
        return w

    def add_poop(self, x: float, y: float, rarity: str | None = None) -> str | None:
        """狗大完了。回傳稀有度；桌面上已經滿了回傳 None。"""
        if self.full:
            return None
        rarity = rarity or roll_rarity(luck=self.buffs.value("luck"))
        self._spawn(x, y, rarity)
        self._log("made", rarity)
        self.save()
        self.stack_fn()
        return rarity

    def _log(self, what: str, rarity: str) -> None:
        log = self.settings.data.get("poop_log")
        log = dict(log) if isinstance(log, dict) else {}
        part = dict(log.get(what) or {})
        part[rarity] = int(part.get(rarity, 0)) + 1
        log[what] = part
        self.settings.data["poop_log"] = log

    def save(self) -> None:
        self.settings.data["poops"] = [[round(w.cx), round(w.cy), w.rarity] for w in self.live_poops]
        self.settings.data["poop_in"] = round(self.clock.remaining, 1)
        self.settings.data["buffs"] = self.buffs.to_json()
        try:
            self.settings.save()
        except OSError:
            pass

    # ---- 掃把
    def set_broom(self, on: bool) -> None:
        self.broom_on = on
        self.broom_idle = 0.0
        self._last_cursor = None
        if on:
            self.broom.show()
            self.stack_fn()
        else:
            self.broom.hide()

    def toggle_broom(self) -> bool:
        self.set_broom(not self.broom_on)
        return self.broom_on

    # ---- 零食碗
    def show_bowl(self, x: float, ground_y: float, treat_key: str | None = None,
                  rarity: str | None = None) -> tuple[str, str]:
        """放碗。回傳 (零食, 稀有度)。"""
        self.bowl.place(x, ground_y)
        got = self.bowl.fill(treat_key, rarity)
        self.bowl_hide_in = 0.0
        self.bowl.show()
        self.stack_fn()
        return got

    @property
    def bowl_full(self) -> bool:
        return self.bowl.isVisible() and self.bowl.full

    def bowl_eaten(self) -> tuple[str, str]:
        """吃完了：倒數減半 + 得到這個零食的效果。回傳 (效果, 稀有度)。"""
        self.bowl.empty()
        self.bowl_hide_in = BOWL_GONE_SEC
        self.clock.fed()
        kind = TREATS.get(self.bowl.treat_key, ("", "poop"))[1]
        self.buffs.add(kind, self.bowl.rarity)
        return kind, self.bowl.rarity

    # ---- 每一幀
    def tick(self, dt: float, cx: float, cy: float) -> list[str]:
        """回傳這一幀被掃掉的大便稀有度。"""
        self.clock.tick(dt, self.buffs.value("poop"))
        had = bool(self.buffs.active)
        self.buffs.tick(dt)
        if had and not self.buffs.active:
            self.save()                                 # 效果結束了
        self.bowl.tick(dt)
        for w in self.poops:
            w.tick(dt)
        if any(w.gone for w in self.poops):
            for w in self.poops:
                if w.gone:
                    w.hide()
            self.poops = [w for w in self.poops if not w.gone]
        if self.bowl_hide_in > 0:
            self.bowl_hide_in -= dt
            if self.bowl_hide_in <= 0:
                self.bowl.hide()
        return []

    def broom_step(self, dt: float, cx: float, cy: float) -> list[str]:
        """掃把：PetWindow 用自己的快速計時器（約 120 次/秒）呼叫，跟著游標不會卡。回傳這次掃掉的稀有度。"""
        swept: list[str] = []
        if self.broom_on:
            px, _py = self._last_cursor or (cx, cy)
            self._last_cursor = (cx, cy)
            vx = (cx - px) / max(dt, 1e-3)
            self.broom.follow(cx, cy, vx, dt)
            hx, hy = self.broom.head_at(cx, cy)         # 掃的是刷頭，不是游標（游標握在掃把中間）
            reach = SWEEP_RADIUS * self.S
            for w in self.live_poops:
                if math.hypot(w.cx - hx, (w.cy - w.size_px * 0.4) - hy) <= reach:
                    w.sweep(vx if abs(vx) > 1 else (w.cx - hx))
                    self._log("swept", w.rarity)
                    swept.append(w.rarity)
            self.broom_idle = 0.0 if swept else self.broom_idle + dt
            limit = BROOM_IDLE_SEC if self.live_poops else BROOM_DONE_SEC
            if self.broom_idle >= limit:
                self.set_broom(False)
        if swept:
            self.save()
        return swept

    def raise_floor(self) -> None:
        """地上的東西（在狗下面）。"""
        for w in self.poops:
            if w.isVisible():
                w.raise_()
        if self.bowl.isVisible():
            self.bowl.raise_()

    def raise_top(self) -> None:
        """掃把在最上面。"""
        if self.broom.isVisible():
            self.broom.raise_()
