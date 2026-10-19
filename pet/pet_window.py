"""桌寵本體：一個透明、置頂、不搶焦點的小視窗，整個視窗在螢幕上移動。

透明的像素在 Windows 上會讓滑鼠直接穿過去，只有點到狗（或影子、名牌）才算互動。

座標說明
    (gx, gy)  狗「站的地面點」= 影子中心，螢幕座標
    lift      離地高度（像素），0 = 站在地上

v0.2 互動（全部用現有 84 格圖，沒有新動畫）
    A 摸牠    滑鼠停在狗身上輕輕晃 0.5 秒 = 摸頭；雙擊或選單「翻肚」= 揉肚子；
              單擊 = 戳一下（轉頭 / 嚇一跳 / 打噴嚏 / 開心）；
              拎起來亂晃 → 落地頭暈；用力甩出去 → 拋物線飛出、落地滑行
    B 跟滑鼠  發呆時會看著游標；偶爾跑來聞游標；偶爾叼走滑鼠（甩開就鬆口）；
              游標快速掃過會嚇一跳
    C 自己玩  Zoomies 暴衝、追尾巴、聞地板
    D 心情    心情 / 親密度（見 mood.py），滑鼠停在狗身上會顯示名牌

v0.3
    待辦清單  點螢幕右邊的紅標籤：狗跑過去咬住標籤、倒退 4 下把清單拖出來；再點一次 = 用鼻子推回去
              （搬清單時 busy：點狗只會冒愛心，不會打斷）。每天 wake_time 自動拉一次。
    番茄鐘    狗坐在番茄左邊安靜陪你；時間到番茄搖、狗跳、叮一聲，自動休息，休息完再叮一聲後停止。
    對話泡泡  頭上冒的字改成圓角泡泡（bubble.py，獨立視窗，靠近螢幕邊會往內移）。
"""
from __future__ import annotations

import math
import random
import time
from collections import deque

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter,
                           QPainterPath, QPen, QRegion)
from PySide6.QtWidgets import QApplication, QWidget

from .bubble import Bubble
from .dog_model import ANIMS, DIR_ANGLE, DIRS8, ELEVATION_DEG, FRONT_ANGLE, GROUND_Y, angle_to_dir
from .mood import Mood
from .pomodoro import Pomodoro, fmt_mmss
from .settings import Settings
from .sprites import SpriteLibrary

ACTIVITY = {
    "calm":   {"idle": (5.0, 12.0), "walk_p": 0.35, "speed": 55.0, "play": 0.6},
    "normal": {"idle": (2.5, 6.0),  "walk_p": 0.60, "speed": 80.0, "play": 1.0},
    "hyper":  {"idle": (0.8, 2.5),  "walk_p": 0.85, "speed": 115.0, "play": 1.6},
}
PRANK_MEAN_SEC = {"rare": 1800.0, "sometimes": 600.0}   # 叼滑鼠平均多久一次；menu_only = 只在選單觸發

DRAG_THRESHOLD = 6          # 滑鼠移動超過幾 px 算「拖曳」而不是「點一下」
GRAVITY = 2600.0            # 重力（px/s²，以 160px 狗為準，下面的速度也一樣）
THROW_SPEED = 1100.0        # 放開時游標速度超過這個 = 丟出去
SLIDE_FRICTION = 1600.0     # 落地滑行的摩擦
SWIPE_SPEED = 2800.0        # 游標掃過狗的速度超過這個 = 嚇到
SHAKE_REVERSALS = 4         # 拎著時 1.2 秒內來回甩幾次算「亂晃」
PET_HOVER_SEC = 0.5         # 游標停在狗身上多久算摸頭
TICK_MS = 33                # 平常約 30 fps
FAST_TICK_MS = 16           # 拎著、飛行、暴衝時約 60 fps
FAST_STATES = {"held", "drop", "fly", "slide", "hop", "zoomies", "chase", "prank_go", "prank_carry"}
HANDS_OFF = {"held", "drop", "fly", "slide", "hop", "prank_go", "prank_carry"}   # 這些狀態不算摸頭
LOOKING = {"idle", "sit", "happy", "dizzy", "nose"}                              # 這些狀態會看著游標

# 嘴巴相對地面點的位置（sprite 邊長比例），依 Evan 的正式圖量的；換圖後可以微調
MOUTH = {
    "right": (0.41, -0.26), "down_right": (0.28, -0.15), "down": (0.02, -0.08),
    "up_right": (0.28, -0.49), "up": (0.0, -0.55),
}
for _d, _src in (("left", "right"), ("down_left", "down_right"), ("up_left", "up_right")):
    MOUTH[_d] = (-MOUTH[_src][0], MOUTH[_src][1])

# ---- v0.3 搬清單：量 Evan 的 run/right 圖（面向右），從腳底點往前、往上，單位 = sprite 邊長 S
BITE = (0.37, 0.22)         # 咬標籤的點
NOSE = 0.40                 # 鼻子往前多少（推清單）
TUG_FPS = 7.0               # 拉 / 推時 run 動畫的速度
BITE_SEC = 0.65             # 咬住標籤、冒 Grr! 多久
PULL_SEC = 2.2              # 拉出來總共多久
PULL_YANKS = 4              # 分幾下猛扯
NUDGE_SEC = 0.3             # 鼻子貼上紙邊後停多久
PUSH_SEC = 1.8              # 推回去多久
BACK_SEC = 0.45             # 搬完往後退多久
PULL_BACK = 0.30            # 拉完往後退多遠（× S）
PUSH_BACK = 0.38            # 推完往後退多遠（× S）
LIST_STATES = {"wake", "list_go", "list_bite", "list_tug", "list_back", "list_nudge", "list_push"}
FAST_STATES |= LIST_STATES | {"pomo_go"}
HANDS_OFF |= LIST_STATES


def _ease_io(k: float) -> float:
    return 2 * k * k if k < 0.5 else 1 - (-2 * k + 2) ** 2 / 2


def _heart_path(x: float, y: float, s: float) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(x, y + s * 0.3)
    path.cubicTo(x, y, x - s * 0.5, y, x - s * 0.5, y + s * 0.3)
    path.cubicTo(x - s * 0.5, y + s * 0.6, x, y + s * 0.8, x, y + s)
    path.cubicTo(x, y + s * 0.8, x + s * 0.5, y + s * 0.6, x + s * 0.5, y + s * 0.3)
    path.cubicTo(x + s * 0.5, y, x, y, x, y + s * 0.3)
    return path


def _star_path(x: float, y: float, r: float) -> QPainterPath:
    path = QPainterPath()
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pt = QPointF(x + math.cos(a) * rr, y + math.sin(a) * rr)
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    return path


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """點 P 到線段 AB 的距離。"""
    vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


class PetWindow(QWidget):
    menuRequested = Signal(QPoint)

    def __init__(self, sprites: SpriteLibrary, settings: Settings, name_fn=lambda: "Dachshund"):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.sprites = sprites
        self.settings = settings
        self.name_fn = name_fn
        self.mood = Mood(settings.get("mood"), settings.get("affection"))
        self.mood.enabled = settings.extra("mood")

        self.S = sprites.size
        self.k = self.S / 160                                # 速度、距離都跟著狗的大小縮放
        self.LIFT = int(self.S * 0.4)                       # 視窗上方留給「拎起來」、愛心、名牌的空間
        self.setFixedSize(self.S, self.S + self.LIFT)
        self.anchor = QPointF(self.S / 2, self.LIFT + self.S * GROUND_Y)

        # 狀態
        self.state = "idle"
        self.state_t = 0.0
        self.state_dur = 2.0
        self.anim = "idle"
        self.anim_t = 0.0
        self.anim_speed = 1.0
        self.frame_lock: int | None = None                  # 固定顯示某一格（嚇一跳、滑行用）
        self.direction = "down"
        self.facing_left = False
        self.target: tuple[float, float] | None = None
        self.lift = 0.0
        self.lift_v = 0.0
        self.extra = 0.0                                    # 飛太高時視窗往上挪的量
        self.stay = False

        # 特效
        self.hearts: list[list[float]] = []                 # [x, y, age]
        self.texts: list[list] = []                         # [文字, x, y, age, 壽命, 顏色]
        self.base_font = QFont(QApplication.font())

        # 滑鼠 / 互動
        self.press_global: QPointF | None = None
        self.last_interaction = time.monotonic()
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self._on_click)
        self._dbl = False
        self.samples: deque = deque(maxlen=16)              # 拎著時的游標軌跡 (t, x, y)
        self.shake_times: list[float] = []
        self._shake_sign = [0, 0]
        self.shaken = False
        self.pending_dizzy = False
        self.fly_vx = 0.0
        self.after_hop = None
        self.hovering = False
        self.hover_t = 0.0
        self.hover_move = 0.0
        self.last_pet = 0.0
        self.pet_combo = 0
        self.rub = 0.0
        self.last_rub = 0.0
        self.rub_rewarded = False
        self.wobble_until = 0.0
        self.look_next = 0.0
        self.startle_ready = 0.0
        self.zoom_targets: list[tuple[float, float]] = []
        self.spin_i = 0
        self.spin_steps = 0
        self.spin_dir = 1
        self._spin_start = 0
        self.sniff_left = 0
        self.prank_last_set: QPoint | None = None
        self._img_cache: dict = {}
        self._box_cache: dict = {}
        self._schedule_prank()

        # v0.3
        self.bubble = Bubble(self.k)                        # 頭上的對話泡泡
        self.todo_win = None                                # 待辦清單視窗（attach_todo）
        self.list_job: dict = {}                            # 正在搬清單的資料
        self.pomo = Pomodoro()
        self.pomo_pending: tuple[float, float] | None = None   # 走去番茄旁邊的路上（還沒開始計時）
        self.pomo_spot: tuple[float, float] = (0.0, 0.0)
        self.tomato_win = None
        self.ding_sound = None
        self.tomato_hide_at = 0.0

        center = QGuiApplication.primaryScreen().availableGeometry().center()
        self.gx, self.gy = float(center.x()), float(center.y())
        c = QCursor.pos()
        self._prev_cursor = (float(c.x()), float(c.y()))
        self._place()
        self.setCursor(Qt.OpenHandCursor)

        self._last = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_MS)

    # ================================================================== 工具
    @property
    def _act(self) -> dict:
        return ACTIVITY.get(self.settings.get("activity"), ACTIVITY["normal"])

    def _ground_rect(self, screen) -> QRectF:
        """這個螢幕上，地面點可以在的範圍（確保整隻狗都在螢幕內、不壓到工作列）。"""
        r = screen.availableGeometry()
        return QRectF(r.left() + self.anchor.x(), r.top() + self.anchor.y(),
                      max(1, r.width() - self.width()), max(1, r.height() - self.height()))

    def _screen_here(self):
        return QGuiApplication.screenAt(QPoint(int(self.gx), int(self.gy))) or QGuiApplication.primaryScreen()

    def _clamp_point(self, x: float, y: float) -> tuple[float, float]:
        rect = self._ground_rect(self._screen_here())
        return min(max(x, rect.left()), rect.right()), min(max(y, rect.top()), rect.bottom())

    def _clamp_ground(self) -> None:
        self.gx, self.gy = self._clamp_point(self.gx, self.gy)

    def _settle_airborne(self) -> None:
        """在空中（丟出去、放下、彈跳）時，讓落地點留在螢幕可用範圍內（不會掉到工作列或螢幕底下）。
        落地點往上移多少，離地高度就少多少，所以畫面上的狗不會突然跳位；只有低到連高度都不夠扣時才往上貼齊。"""
        rect = self._ground_rect(self._screen_here())
        self.gx = min(max(self.gx, rect.left()), rect.right())
        if self.gy > rect.bottom():
            d = self.gy - rect.bottom()
            self.gy = rect.bottom()
            self.lift = max(0.0, self.lift - d)
        elif self.gy < rect.top():
            d = rect.top() - self.gy
            self.gy = rect.top()
            self.lift += d

    def _place(self) -> None:
        self.extra = max(0.0, self.lift - self.LIFT * 0.9)
        self.move(int(round(self.gx - self.anchor.x())), int(round(self.gy - self.anchor.y() - self.extra)))

    def _sprite_y(self) -> float:
        """sprite 左上角在視窗裡的 y。"""
        return self.LIFT - self.lift + self.extra

    def _set_state(self, state: str, dur: float = 0.0, anim: str | None = None,
                   speed: float = 1.0, lock: int | None = None) -> None:
        if hasattr(self, "timer"):
            self.timer.setInterval(FAST_TICK_MS if state in FAST_STATES else TICK_MS)
        if self.state in ("prank_go", "prank_carry") and state not in ("prank_go", "prank_carry"):
            self.setCursor(Qt.OpenHandCursor)
        self.state = state
        self.state_t = 0.0
        self.state_dur = dur
        self.anim_speed = speed
        self.frame_lock = lock
        self._set_anim(anim or state)

    def _set_anim(self, anim: str) -> None:
        if anim != self.anim:
            self.anim_t = 0.0
        self.anim = anim

    def _touch(self) -> None:
        self.last_interaction = time.monotonic()

    def _cursor_here(self, c: QPoint) -> bool:
        """游標是不是跟狗在同一個螢幕。"""
        return QGuiApplication.screenAt(c) is self._screen_here()

    def _mouth_offset(self, d: str) -> tuple[float, float]:
        mx, my = MOUTH.get(d, (0.0, 0.0))
        return mx * self.S, my * self.S

    def _move_toward(self, tx: float, ty: float, speed: float, dt: float, wobble: bool = False) -> bool:
        """往 (tx, ty) 走一步，回傳是否到了。"""
        dx, dy = tx - self.gx, ty - self.gy
        dist = math.hypot(dx, dy)
        if dist < 3:
            self.gx, self.gy = tx, ty
            return True
        ux, uy = dx / dist, dy / dist
        if wobble:                                  # 頭暈：走路歪來歪去
            a = math.sin(self.state_t * 5.0) * 0.7
            ux, uy = ux * math.cos(a) - uy * math.sin(a), ux * math.sin(a) + uy * math.cos(a)
        step = min(dist, speed * self.k * dt)
        self.gx += ux * step
        self.gy += uy * step
        self._set_direction(angle_to_dir(dx, dy))
        return False

    def _set_direction(self, d: str) -> None:
        self.direction = d
        if "left" in d:
            self.facing_left = True
        elif "right" in d:
            self.facing_left = False

    def _current_pixmap(self):
        if self.frame_lock is not None:
            return self.sprites.frame_at(self.anim, self.direction, self.frame_lock, flip=self.facing_left)
        return self.sprites.frame(self.anim, self.direction, self.anim_t, flip=self.facing_left)

    def _image(self, px):
        key = px.cacheKey()
        img = self._img_cache.get(key)
        if img is None:
            img = self._img_cache[key] = px.toImage()
        return img

    def _box(self, px) -> QRectF:
        """這一格不透明部分的範圍（sprite 座標）。"""
        key = px.cacheKey()
        box = self._box_cache.get(key)
        if box is None:
            m = px.mask()
            r = QRegion(m).boundingRect() if not m.isNull() else px.rect()
            box = self._box_cache[key] = QRectF(r)
        return box

    def _hit(self, c: QPoint) -> bool:
        """游標是不是正指著狗的身體（不透明的像素）。"""
        x = c.x() - self.x()
        y = c.y() - self.y() - self._sprite_y()
        if not (0 <= x < self.S and 0 <= y < self.S):
            return False
        img = self._image(self._current_pixmap())
        return img.pixelColor(int(x), int(y)).alpha() > 40

    def say(self, text: str, color: str = "#5A3A1A", life: float = 1.4) -> None:
        """頭上冒對話泡泡（v0.3 起是圓角泡泡，color 不用了，留著是為了相容舊的呼叫）。"""
        self.bubble.show_text(text, max(0.9, life) + 0.2)
        self._place_bubble()

    def _place_bubble(self) -> None:
        if not self.bubble.active:
            return
        tip_x = self.gx + (-1 if self.facing_left else 1) * self.S * 0.08
        tip_y = self.y() + self._sprite_y() + self.S * 0.12
        self.bubble.follow(tip_x, tip_y, self._screen_here().availableGeometry())

    @property
    def busy(self) -> bool:
        """正在搬清單（含早上起床那一整段）：點狗不會打斷。"""
        return self.state in LIST_STATES

    def _free(self) -> bool:
        """選單指令用：搬清單時不接新指令，只搖尾巴冒愛心。"""
        if self.busy:
            self.add_hearts(1)
            return False
        return True

    def add_hearts(self, n: int = 3) -> None:
        box = self._box(self._current_pixmap())
        for i in range(n):
            self.hearts.append([
                box.center().x() + random.uniform(-0.15, 0.15) * self.S,
                self._sprite_y() + box.top() + random.uniform(-4, 8),
                -i * 0.18,
            ])

    def feat(self, key: str) -> bool:
        """額外互動開關（settings.EXTRAS），Evan 沒勾的預設關閉。"""
        return self.settings.extra(key)

    def extras_changed(self) -> None:
        self.mood.enabled = self.feat("mood")

    def save_mood(self) -> None:
        self.settings.data["mood"] = round(self.mood.mood, 1)
        self.settings.data["affection"] = round(self.mood.affection, 1)
        try:
            self.settings.save()
        except OSError:
            pass

    # ================================================================== 主迴圈
    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        self.anim_t += dt * self.anim_speed
        self.state_t += dt
        self._sense(dt, now)
        getattr(self, f"_update_{self.state}")(dt)
        self._update_fx(dt)
        self._tick_pomo(dt, now)
        if self.mood.enabled and self.mood.tick(dt, now - self.last_interaction):
            self.save_mood()
        self._place()
        self._place_bubble()
        self.update()

    def _sense(self, dt: float, now: float) -> None:
        """每一幀看一下游標：摸頭、揉肚子、被掃過、看著游標。"""
        c = QCursor.pos()
        cx, cy = float(c.x()), float(c.y())
        px, py = self._prev_cursor
        self._prev_cursor = (cx, cy)
        dx, dy = cx - px, cy - py
        moved = math.hypot(dx, dy)
        speed = moved / max(dt, 1e-3)

        self.hovering = self.state not in HANDS_OFF and self._hit(c)
        if self.hovering:
            if self.state == "belly":
                if moved > 1:
                    self.rub += moved
                    self.last_rub = now
                    self._touch()
            elif self.state != "sleep":
                self.hover_t += dt
                self.hover_move += moved
                if self.hover_t >= PET_HOVER_SEC and self.hover_move >= 12 * self.k:
                    self.pet()
                    self.hover_t = self.hover_move = 0.0
        else:
            self.hover_t = self.hover_move = 0.0

        # 被游標快速掃過 → 嚇一跳
        if (self.feat("swipe") and speed > SWIPE_SPEED * self.k and not self.hovering
                and now >= self.startle_ready
                and self.state in {"idle", "sit", "walk", "happy", "sniff", "nose"}):
            bx, by = self.gx, self.gy - self.S * 0.15
            if _seg_dist(bx, by, px, py, cx, cy) < self.S * 0.3:
                self.startle()

        # 發呆時看著游標
        if self.feat("look") and self.state in LOOKING and now >= self.look_next and self._cursor_here(c):
            self.look_next = now + 0.5
            if abs(cx - self.gx) > self.S * 0.2:
                self.facing_left = cx < self.gx

    # ------------------------------------------------------------------ 選下一件事
    def _enter_idle(self) -> None:
        self._set_state("idle", random.uniform(*self._act["idle"]))

    def _choose_next(self) -> None:
        if self.pomo.active or self.pomo_pending:            # 番茄鐘：回到番茄旁邊乖乖坐著
            self._go_pomo_spot()
            return
        now = time.monotonic()
        idle_for = now - self.last_interaction
        m = self.mood.level if self.mood.enabled else 0.7       # 心情系統關掉 = 固定普通心情
        sleep_after = float(self.settings.get("sleep_after_sec")) * (0.6 + 0.8 * m)   # 心情差比較愛睡
        if idle_for > sleep_after and random.random() < 0.5:
            self._set_state("sleep", random.uniform(90, 240))
            return
        if self.stay:
            self._enter_idle()
            return
        c = QCursor.pos()
        if self._prank_due(now) and self._cursor_here(c):
            self.start_prank()
            return

        play = self._act["play"]
        f = self.mood.affection / 100.0 if self.mood.enabled else 0.3
        options = [
            (self.start_walk, self._act["walk_p"] * (0.6 + 0.6 * m)),
            (lambda: self._set_state("sit", random.uniform(3, 8)), 0.15 * (1.6 - m)),
            (self.start_zoomies, 0.035 * play * m),
            (self.start_spin, 0.03 * play * m * self.feat("spin")),
            (self.start_sniff, 0.07 * self.feat("sniff")),
            (self._enter_idle, 0.2),
        ]
        if self._cursor_here(c):
            options.append((self.start_chase, 0.05 * play * (0.3 + f)))
        total = sum(w for _, w in options)
        r = random.uniform(0, total)
        for fn, w in options:
            r -= w
            if r <= 0:
                fn()
                return
        self._enter_idle()

    # ------------------------------------------------------------------ 各狀態
    def _update_idle(self, dt: float) -> None:
        if self.state_t >= self.state_dur:
            self._choose_next()

    _update_sit = _update_idle
    _update_happy = _update_idle
    _update_nose = _update_idle

    def _update_sleep(self, dt: float) -> None:
        if self.state_t >= self.state_dur:
            self._enter_idle()

    def _update_walk(self, dt: float) -> None:
        if self.target is None:
            self._enter_idle()
            return
        wobble = time.monotonic() < self.wobble_until
        if self._move_toward(*self.target, self._act["speed"] * (0.8 if wobble else 1.0), dt, wobble):
            self.target = None
            self._enter_idle()

    def _update_dizzy(self, dt: float) -> None:
        if self.state_t >= self.state_dur:
            self.wobble_until = time.monotonic() + 8.0
            self._enter_idle() if self.stay else self.start_walk()

    # ---- 拎起來、丟出去
    def _update_held(self, dt: float) -> None:
        target_lift = self.LIFT * 0.85
        self.lift += (target_lift - self.lift) * min(1.0, dt * 14)
        c = QCursor.pos()
        self._sample(c)
        self._follow(c)

    def _sample(self, c) -> None:
        """記錄游標軌跡，算「亂晃」次數。"""
        now = time.monotonic()
        if self.samples and now - self.samples[-1][0] < 0.008:
            return
        self.samples.append((now, float(c.x()), float(c.y())))
        if len(self.samples) >= 2:
            (t0, x0, y0), (t1, x1, y1) = self.samples[-2], self.samples[-1]
            dt = max(t1 - t0, 1e-3)
            fast = 500 * self.k
            for axis, v in ((0, (x1 - x0) / dt), (1, (y1 - y0) / dt)):
                if abs(v) < fast:
                    continue
                sign = 1 if v > 0 else -1
                if self._shake_sign[axis] and sign != self._shake_sign[axis]:   # 方向反轉 = 甩一下
                    self.shake_times.append(now)
                self._shake_sign[axis] = sign
        self.shake_times = [t for t in self.shake_times if now - t < 1.2]
        if not self.shaken and len(self.shake_times) >= SHAKE_REVERSALS:
            self.shaken = True
            self.say("Whoaaa!", "#C0392B", 1.0)

    def _release_velocity(self) -> tuple[float, float]:
        now = time.monotonic()
        recent = [s for s in self.samples if now - s[0] < 0.1]
        if len(recent) < 2 or now - recent[-1][0] > 0.06:     # 停住一下才放開 = 沒有速度
            return 0.0, 0.0
        (t0, x0, y0), (t1, x1, y1) = recent[0], recent[-1]
        dt = max(t1 - t0, 1e-3)
        return (x1 - x0) / dt, (y1 - y0) / dt

    def _follow(self, m) -> None:
        """讓狗的脖子貼在游標上。"""
        sprite_top = self.LIFT - self.lift
        gx, gy = self.sprites.held_grab(self.anim_t, self.facing_left)   # 這一格的脖子位置
        wx = m.x() - gx * self.S
        wy = m.y() - (sprite_top + gy * self.S)
        self.gx = wx + self.anchor.x()
        self.gy = wy + self.anchor.y()

    def _land(self) -> None:
        """落地後：頭暈或開心。"""
        if self.pending_dizzy:
            self.pending_dizzy = False
            self.dizzy()
        else:
            self._set_state("happy", 1.2)

    def _update_drop(self, dt: float) -> None:
        self._settle_airborne()
        self.lift_v += GRAVITY * self.k * dt
        self.lift -= self.lift_v * dt
        if self.lift <= 0:
            self.lift = 0.0
            if self.lift_v > 450 * self.k:                 # 落地彈一下
                self.lift_v = -self.lift_v * 0.3
            else:
                self.lift_v = 0.0
                self._land()

    def _update_fly(self, dt: float) -> None:
        self._settle_airborne()
        rect = self._ground_rect(self._screen_here())
        self.gx += self.fly_vx * dt
        if self.gx < rect.left() or self.gx > rect.right():   # 撞到螢幕邊彈回來
            self.gx = min(max(self.gx, rect.left()), rect.right())
            self.fly_vx = -self.fly_vx * 0.5
            self.facing_left = self.fly_vx < 0
        self.lift_v += GRAVITY * self.k * dt
        self.lift -= self.lift_v * dt
        ceiling = self.gy - self.anchor.y() + self.LIFT - (self._screen_here().availableGeometry().top())
        if self.lift > ceiling:                            # 撞到螢幕頂
            self.lift = max(0.0, ceiling)
            self.lift_v = max(self.lift_v, 0.0)
        if self.lift <= 0:
            self.lift = 0.0
            if self.lift_v > 450 * self.k:
                self.lift_v = -self.lift_v * 0.35
                self.fly_vx *= 0.7
            else:
                self.lift_v = 0.0
                self._set_state("slide", 3.0, anim="belly", lock=0)

    def _update_slide(self, dt: float) -> None:
        self._settle_airborne()
        rect = self._ground_rect(self._screen_here())
        v = abs(self.fly_vx) - SLIDE_FRICTION * self.k * dt
        self.fly_vx = math.copysign(max(0.0, v), self.fly_vx)
        self.gx = min(max(self.gx + self.fly_vx * dt, rect.left()), rect.right())
        if abs(self.fly_vx) < 20 or self.state_t > self.state_dur:
            if not self.pending_dizzy:
                self.mood.change(2)
                self.say("Again!", "#2E86C1")
            self._land()

    def _update_hop(self, dt: float) -> None:
        self.lift_v += GRAVITY * self.k * dt
        self.lift -= self.lift_v * dt
        if self.lift <= 0:
            self.lift, self.lift_v = 0.0, 0.0
            then, self.after_hop = self.after_hop, None
            (then or self._enter_idle)()

    # ---- 揉肚子
    def _update_belly(self, dt: float) -> None:
        now = time.monotonic()
        self.rub = max(0.0, self.rub - 250 * self.k * dt)
        self.anim_speed = 0.4 + min(2.2, self.rub / (220 * self.k))   # 越爽踢越快
        if not self.rub_rewarded and self.rub > 500 * self.k:
            self.rub_rewarded = True
            self.mood.change(8, 2)
            self.add_hearts(5)
            self.say("So good!", "#D35400")
        quiet = now - self.last_rub
        if (quiet > 5 and self.state_t > 4) or self.state_t > 30:
            self._set_state("happy", 1.4)

    # ---- 跟滑鼠玩
    def _update_chase(self, dt: float) -> None:
        c = QCursor.pos()
        if not self._cursor_here(c) or self.state_t > self.state_dur:
            self._enter_idle()
            return
        d = "right" if c.x() > self.gx else "left"
        mx, my = self._mouth_offset(d)
        tx, ty = self._clamp_point(c.x() - mx, c.y() - my)
        if self._move_toward(tx, ty, self._act["speed"] * 2.4, dt):
            self.facing_left = d == "left"
            self._set_state("nose", 1.8, anim="idle")
            self.mood.change(1)
            self.say("Sniff sniff")

    def _update_prank_go(self, dt: float) -> None:
        c = QCursor.pos()
        if not self._cursor_here(c) or self.state_t > self.state_dur:
            self._enter_idle()
            return
        d = "right" if c.x() > self.gx else "left"
        mx, my = self._mouth_offset(d)
        tx, ty = c.x() - mx, c.y() - my
        if self._move_toward(tx, ty, self._act["speed"] * 2.8, dt) or math.hypot(tx - self.gx, ty - self.gy) < 6:
            self._set_direction(d)
            ang = random.uniform(-0.6, 0.6) + (math.pi if d == "left" else 0.0)
            dist = random.uniform(200, 420) * self.k
            self.target = self._clamp_point(self.gx + math.cos(ang) * dist, self.gy + math.sin(ang) * dist)
            self.prank_last_set = None
            self._set_state("prank_carry", 5.0, anim="walk")
            self.setCursor(Qt.ArrowCursor)
            self.say("Hehe", "#8E44AD", 1.0)

    def _update_prank_carry(self, dt: float) -> None:
        c = QCursor.pos()
        if self.prank_last_set is not None and \
                (c - self.prank_last_set).manhattanLength() > 40 * self.k:   # 被用力甩開
            self._prank_release(yanked=True)
            return
        arrived = self.target is None or self._move_toward(*self.target, self._act["speed"] * 1.3, dt)
        mx, my = self._mouth_offset(self.direction)
        pos = QPoint(int(round(self.gx + mx)), int(round(self.gy + my)))
        QCursor.setPos(pos)
        self.prank_last_set = pos
        if arrived or self.state_t > self.state_dur:
            self._prank_release(yanked=False)

    def _prank_release(self, yanked: bool) -> None:
        self.target = None
        self.prank_last_set = None
        self.mood.change(3)
        self._schedule_prank()
        self._set_state("sit", 3.0)
        self.say("Woof!" if yanked else "Hehe!", "#8E44AD")

    # ---- 自己玩
    def _update_zoomies(self, dt: float) -> None:
        if not self.zoom_targets:
            self.mood.change(2)
            self._set_state("sit", 3.0)
            self.say("Huff... huff...")
            return
        if self._move_toward(*self.zoom_targets[0], self._act["speed"] * 3.2, dt):
            self.zoom_targets.pop(0)

    def _update_spin(self, dt: float) -> None:
        step = int(self.state_t / 0.085)
        if step >= self.spin_steps:
            if random.random() < 0.5:
                self.dizzy(2.0)
            else:
                self._set_state("happy", 1.2)
            return
        if step != self.spin_i:
            self.spin_i = step
            self.direction = DIRS8[(self._spin_start + self.spin_dir * step) % 8]
            self.facing_left = "left" in self.direction

    def _update_sniff(self, dt: float) -> None:
        if self.target is not None:
            if self._move_toward(*self.target, self._act["speed"] * 0.35, dt):
                self.target = None
                self.state_dur = self.state_t + random.uniform(0.8, 1.6)
                self._set_anim("idle")
                self.say("Sniff...", life=1.0)
        elif self.state_t >= self.state_dur:
            self.sniff_left -= 1
            if self.sniff_left <= 0:
                self._enter_idle()
                return
            ang = random.uniform(0, 2 * math.pi)
            dist = random.uniform(25, 60) * self.k
            self.target = self._clamp_point(self.gx + math.cos(ang) * dist, self.gy + math.sin(ang) * dist)
            self.anim_speed = 0.6
            self._set_anim("walk")

    # ---- 特效
    def _update_fx(self, dt: float) -> None:
        for h in self.hearts:
            h[2] += dt
            if h[2] > 0:
                h[1] -= 38 * dt * self.k
        self.hearts = [h for h in self.hearts if h[2] < 1.3]
        for t in self.texts:
            t[3] += dt
            t[2] -= 14 * dt * self.k
        self.texts = [t for t in self.texts if t[3] < t[4]]

    # ================================================================== 指令（選單也會呼叫）
    def start_walk(self) -> None:
        if not self._free():
            return
        if random.random() < 0.12 and len(QGuiApplication.screens()) > 1:
            rect = self._ground_rect(random.choice(QGuiApplication.screens()))
            tx = random.uniform(rect.left(), rect.right())
            ty = random.uniform(rect.top(), rect.bottom())
        else:
            ang = random.uniform(0, 2 * math.pi)
            dist = random.uniform(120, 480) * self.k
            tx, ty = self._clamp_point(self.gx + math.cos(ang) * dist, self.gy + math.sin(ang) * dist)
        self.target = (tx, ty)
        self._set_state("walk")

    def pet(self) -> None:
        """摸摸頭：開心 + 冒愛心，連續摸會越來越黏你。"""
        if not self._free():
            return
        self._touch()
        now = time.monotonic()
        self.pet_combo = self.pet_combo + 1 if now - self.last_pet < 2.5 else 1
        self.last_pet = now
        self.mood.change(4, 0.5 + 0.5 * min(self.pet_combo, 4))
        self._set_state("happy", 1.6)
        self.add_hearts(min(2 + self.pet_combo, 6))
        if self.pet_combo in (3, 6, 10):
            self.say(random.choice(["Love you!", "More pets!", "Hehe"]), "#C0392B", 1.6)

    def poke(self) -> None:
        """戳一下：隨機反應。"""
        self._touch()
        self.mood.change(1)
        r = random.random()
        if r < 0.3:                                      # 轉頭
            self.target = None
            self.facing_left = not self.facing_left
            self.look_next = time.monotonic() + 2.0
            self._set_state("idle", 1.5)
            self.say("?")
        elif r < 0.55:
            self.startle()
        elif r < 0.75:                                   # 打噴嚏
            self.target = None
            self.say("Achoo!", "#2E86C1")
            self.lift_v = -260 * self.k
            self.after_hop = lambda: self._set_state("idle", 1.0)
            self._set_state("hop", anim="idle", lock=0)
        else:
            self.pet()

    def startle(self) -> None:
        """嚇一跳：held 第 1 格跳起來。"""
        self._touch()
        self.target = None
        self.startle_ready = time.monotonic() + 3.0
        self.say("!", "#C0392B", 1.0)
        self.lift_v = -460 * self.k
        self.after_hop = lambda: self._set_state("sit", random.uniform(2, 4))
        self._set_state("hop", anim="held", lock=0)

    def dizzy(self, dur: float = 4.0) -> None:
        self.target = None
        self._set_state("dizzy", dur, anim="sit")

    def belly_up(self) -> None:
        """翻肚，等你揉。"""
        if not self._free():
            return
        self._touch()
        self.target = None
        self.rub = 0.0
        self.rub_rewarded = False
        self.last_rub = time.monotonic()
        self._set_state("belly", anim="belly", speed=0.4)

    def start_chase(self) -> None:
        if not self._free():
            return
        self.target = None
        self._set_state("chase", 6.0, anim="run")

    def start_prank(self) -> None:
        if not self._free():
            return
        self.target = None
        self._set_state("prank_go", 6.0, anim="run")

    def start_zoomies(self) -> None:
        if not self._free():
            return
        self.zoom_targets = []
        x, y = self.gx, self.gy
        for _ in range(random.randint(3, 5)):
            ang = random.uniform(0, 2 * math.pi)
            dist = random.uniform(150, 500) * self.k
            x, y = self._clamp_point(x + math.cos(ang) * dist, y + math.sin(ang) * dist)
            self.zoom_targets.append((x, y))
        self.target = None
        self._set_state("zoomies", anim="run", speed=1.3)
        self.say("Zoom!", "#D35400", 1.0)

    def start_spin(self) -> None:
        if not self._free():
            return
        self.target = None
        self.spin_steps = 8 * random.choice([2, 3])
        self.spin_dir = random.choice([1, -1])
        self.spin_i = -1
        self._spin_start = DIRS8.index(self.direction) if self.direction in DIRS8 else 0
        self._set_state("spin", anim="walk", speed=1.5)

    def start_sniff(self) -> None:
        if not self._free():
            return
        self.target = None
        self.sniff_left = random.randint(3, 5)
        self._set_state("sniff", random.uniform(0.6, 1.2), anim="idle")
        self.say("Sniff...", life=1.0)

    def sit(self) -> None:
        if not self._free():
            return
        self._touch()
        self.target = None
        self._set_state("sit", random.uniform(6, 12))

    def sleep(self) -> None:
        if not self._free():
            return
        self.target = None
        self._set_state("sleep", random.uniform(120, 300))

    def set_stay(self, stay: bool) -> None:
        self.stay = stay
        if stay and self.state in ("walk", "zoomies", "chase", "sniff", "spin"):
            self.target = None
            self._enter_idle()

    def come_here(self) -> None:
        """瞬間移到游標所在螢幕的中央（狗跑不見時用）。"""
        if not self._free():
            return
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        c = screen.availableGeometry().center()
        self.gx, self.gy = float(c.x()), float(c.y())
        self.lift = 0.0
        self.lift_v = 0.0
        self.pet()

    # ---- 叼滑鼠排程
    def _schedule_prank(self) -> None:
        mean = PRANK_MEAN_SEC.get(self.settings.get("prank_freq"))
        self.next_prank = time.monotonic() + random.expovariate(1.0 / mean) if mean else float("inf")

    def _prank_due(self, now: float) -> bool:
        if not self.settings.get("mouse_prank") or self.settings.get("prank_freq") not in PRANK_MEAN_SEC:
            return False
        return now >= self.next_prank

    def prank_settings_changed(self) -> None:
        self._schedule_prank()

    # ================================================================== v0.3 待辦清單（狗搬清單）
    def attach_todo(self, win) -> None:
        self.todo_win = win
        win.tabClicked.connect(self.toggle_list)
        win.toggled.connect(self.on_todo_toggled)
        win.typingDone.connect(self._raise_all)
        self._attach_list_screen(self._screen_here())

    def _attach_list_screen(self, screen) -> None:
        """清單放在這個螢幕的右邊，底部貼齊狗走路的地面線。"""
        self.todo_win.attach_screen(screen, self._ground_rect(screen).bottom())
        self._raise_all()

    def _raise_all(self) -> None:
        """疊放順序：清單 < 輸入框 < 狗（嘴和鼻子蓋住紙邊）< 番茄 < 泡泡。"""
        if self.todo_win is not None and self.todo_win.strip.isVisible():
            self.todo_win.strip.raise_()
        self.raise_()
        if self.tomato_win is not None and self.tomato_win.isVisible():
            self.tomato_win.raise_()
        if self.bubble.isVisible():
            self.bubble.raise_()

    def toggle_list(self) -> None:
        """點紅標籤：收著 → 拉出來；開著 → 推回去。"""
        if self.todo_win is None or self.busy:
            return
        self._touch()
        self._start_list("push" if self.todo_win.is_open else "pull")

    def morning(self) -> bool:
        """起床時間到。回傳 False = 現在不方便（被拎著、在空中），等一下再叫一次。"""
        if self.todo_win is None:
            return True
        if self.busy or self.state in ("held", "drop", "fly", "slide", "hop", "prank_go", "prank_carry"):
            return False
        if self.todo_win.is_open:                            # 已經開著了：打聲招呼就好
            self.say("Your list for today!", life=2.2)
            return True
        if self.state == "sleep" and not (self.pomo.active or self.pomo_pending):
            self.target = None
            self._set_state("wake", 1.5, anim="idle")
            self.say(f"{self.settings.get('wake_time')}! Good morning!", life=1.5)
        else:
            self._start_list("pull", morning=True)
        return True

    def _start_list(self, mode: str, morning: bool = False) -> None:
        tw = self.todo_win
        if mode == "pull":
            self._attach_list_screen(self._screen_here())   # 拉出來：清單放在狗所在的螢幕
        if self.pomo.active or self.pomo_pending:          # 番茄鐘進行中：狗不動，清單自己滑
            tw.slide_to(mode == "pull")
            return
        self.target = None
        self.zoom_targets = []
        self.lift = self.lift_v = 0.0
        sr, W, T, S = tw.screen_right, tw.W, tw.T, self.S
        if mode == "pull":
            tx = sr - T / 2 - BITE[0] * S                  # 嘴巴對準露在螢幕邊的標籤
        else:
            tx = sr - W - NOSE * S                         # 鼻子貼著清單左邊緣
        self.list_job = {"mode": mode, "morning": morning, "sr": sr, "W": W, "T": T}
        self.target = (tx, tw.floor)
        self._set_state("list_go", anim="run")
        self._raise_all()

    def _tug_frame(self, t: float, reverse: bool) -> int:
        n = len(self.sprites.frames[("run", "right")])
        i = int(t * TUG_FPS) % n
        return n - 1 - i if reverse else i

    @staticmethod
    def _yank(k: float) -> float:
        """分 4 下猛扯：每一下前 55% 快拉（ease-out cubic），後 45% 停頓。k: 0→1。"""
        step = min(PULL_YANKS - 1, int(k * PULL_YANKS))
        f = k * PULL_YANKS - step
        q = 1 - (1 - f / 0.55) ** 3 if f < 0.55 else 1.0
        return (step + q) / PULL_YANKS

    def _update_wake(self, dt: float) -> None:
        if self.state_t >= self.state_dur:
            self._start_list("pull", morning=True)

    def _update_list_go(self, dt: float) -> None:
        if self._move_toward(*self.target, max(self._act["speed"] * 2.6, 220.0), dt):
            self.target = None
            self._set_direction("right")
            if self.list_job["mode"] == "pull":
                self._set_state("list_bite", BITE_SEC, anim="run", lock=1)   # run 第 2 格：頭往前
                self.say("Grr!", life=0.7)
            else:
                self._set_state("list_nudge", NUDGE_SEC, anim="run", lock=1)

    def _update_list_bite(self, dt: float) -> None:
        if self.state_t >= self.state_dur:
            j = self.list_job
            j["x0"] = self.gx
            j["x1"] = j["sr"] - j["W"] - j["T"] / 2 - BITE[0] * self.S
            self._set_state("list_tug", PULL_SEC, anim="run", lock=self._tug_frame(0, True))

    def _update_list_tug(self, dt: float) -> None:
        """面向右、run 倒著播，往左一下一下拖；清單左邊緣 = 狗嘴 x + 標籤寬 / 2。"""
        j = self.list_job
        k = min(1.0, self.state_t / PULL_SEC)
        self.gx = j["x0"] + (j["x1"] - j["x0"]) * self._yank(k)
        self.frame_lock = self._tug_frame(self.state_t, True)
        self.todo_win.set_left(self.gx + BITE[0] * self.S + j["T"] / 2)
        if k >= 1:
            self.todo_win.set_open(True)
            self._start_back(PULL_BACK)

    def _update_list_nudge(self, dt: float) -> None:
        if self.state_t >= self.state_dur:
            j = self.list_job
            j["x0"] = self.gx
            j["x1"] = j["sr"] - NOSE * self.S
            self._set_state("list_push", PUSH_SEC, anim="run", lock=0)

    def _update_list_push(self, dt: float) -> None:
        """run 正著播慢慢往右，清單左邊緣 = 狗鼻子 x。"""
        j = self.list_job
        k = min(1.0, self.state_t / PUSH_SEC)
        self.gx = j["x0"] + (j["x1"] - j["x0"]) * _ease_io(k)
        self.frame_lock = self._tug_frame(self.state_t, False)
        self.todo_win.set_left(self.gx + NOSE * self.S)
        if k >= 1:
            self.todo_win.set_open(False)
            self._start_back(PUSH_BACK)

    def _start_back(self, dist: float) -> None:
        j = self.list_job
        j["b0"], j["b1"] = self.gx, self.gx - dist * self.S
        self._set_state("list_back", BACK_SEC, anim="run", lock=self._tug_frame(0, True))

    def _update_list_back(self, dt: float) -> None:
        """放開標籤（或離開螢幕邊），往後退一點，標籤才點得到。"""
        j = self.list_job
        k = min(1.0, self.state_t / BACK_SEC)
        self.gx = j["b0"] + (j["b1"] - j["b0"]) * _ease_io(k)
        self.frame_lock = self._tug_frame(self.state_t, True)
        if k >= 1:
            self._touch()
            if j["mode"] == "pull":
                self._set_state("sit", 2.3 if j["morning"] else 1.9)
                self.say("Your list for today!" if j["morning"] else "Here you go!",
                         life=2.2 if j["morning"] else 1.8)
            else:
                self._set_state("idle", 1.3)
                self.say("See you later!", life=1.3)
            self._raise_all()

    def on_todo_toggled(self, checked: bool, all_done: bool) -> None:
        """清單打勾：狗開心跳 + 愛心。搬清單、番茄鐘時保持安靜。"""
        if not checked or self.busy or self.pomo.active or self.pomo_pending or self.state in HANDS_OFF:
            return
        self._touch()
        self.target = None
        if all_done:
            self.add_hearts(6)
            self.say("All done! Good job!", life=2.2)
            self.lift_v = -440 * self.k
        else:
            self.add_hearts(3)
            self.say(random.choice(["Nice!", "One down!", "Woof!"]), life=1.2)
            self.lift_v = -320 * self.k
        self.after_hop = lambda: self._set_state("happy", 1.4)
        self._set_state("hop", anim="happy")

    # ================================================================== v0.3 番茄鐘
    def attach_pomodoro(self, tomato_win, ding) -> None:
        self.tomato_win = tomato_win
        self.ding_sound = ding

    def _focusing(self) -> bool:
        return self.pomo.phase == "focus" and self.state in ("pomo_sit", "pomo_go")

    def start_pomodoro(self) -> None:
        if self.tomato_win is None or self.pomo.active or self.pomo_pending:
            return
        if self.busy:                                       # 搬清單時不能開始
            self.say("One sec!", life=1.0)
            return
        self._touch()
        focus = float(self.settings.get("focus_min")) * 60
        brk = float(self.settings.get("break_min")) * 60
        self.pomo_pending = (focus, brk)
        rect = self._ground_rect(self._screen_here())
        x = min(max(self.gx, rect.left()), rect.right() - 0.45 * self.S)   # 右邊要放得下番茄
        y = min(max(self.gy, rect.top()), rect.bottom())
        self.pomo_spot = (x, y)
        self.target = None
        self.zoom_targets = []
        self.lift = self.lift_v = 0.0
        self._go_pomo_spot()

    def stop_pomodoro(self, quiet: bool = False) -> None:
        was = self.pomo.active or self.pomo_pending
        self.pomo.stop()
        self.pomo_pending = None
        self.tomato_hide_at = 0.0
        if self.tomato_win is not None:
            self.tomato_win.hide()
        if was and not quiet:
            if self.state in ("pomo_go", "pomo_sit"):
                self._set_state("idle", 1.0)
            self.say("OK, stopped.", life=1.0)

    def _go_pomo_spot(self) -> None:
        x, y = self.pomo_spot
        if math.hypot(x - self.gx, y - self.gy) < 4:
            self._arrive_pomo()
        else:
            self._set_state("pomo_go", anim="run")

    def _update_pomo_go(self, dt: float) -> None:
        if not (self.pomo.active or self.pomo_pending):
            self._enter_idle()
            return
        if self._move_toward(*self.pomo_spot, max(self._act["speed"] * 2.2, 180.0), dt):
            self._arrive_pomo()

    def _arrive_pomo(self) -> None:
        """坐在番茄左邊，面向右。第一次到 = 擺好番茄、開始計時。"""
        self.gx, self.gy = self.pomo_spot
        self._set_direction("right")
        if self.pomo_pending:
            focus, brk = self.pomo_pending
            self.pomo_pending = None
            self.pomo.start(focus, brk, time.monotonic())
            self.tomato_hide_at = 0.0
            x, y = self.pomo_spot
            self.tomato_win.set_progress(1.0, fmt_mmss(focus), False)
            self.tomato_win.place(x + 0.62 * self.S, y)
            self.tomato_win.show()
            self._raise_all()
            self.say("Wind it up!", life=1.0)
        self._set_state("pomo_sit", anim="sit" if self.pomo.phase == "focus" else "idle")

    def _update_pomo_sit(self, dt: float) -> None:
        if not self.pomo.active:
            self._enter_idle()
            return
        want = "sit" if self.pomo.phase == "focus" else "idle"   # 專心坐著，休息時站起來
        if self.anim != want:
            self._set_anim(want)

    def _tick_pomo(self, dt: float, now: float) -> None:
        if self.tomato_win is None:
            return
        if self.pomo.active:
            ev = self.pomo.update(now)
            if ev == "focus_done":
                self._pomo_ding("Ding! Break time!")
            elif ev == "break_done":
                self._pomo_ding("Back to work?", end=True)
        if self.tomato_win.isVisible():
            if self.pomo.active:
                self.tomato_win.set_progress(self.pomo.fraction(now), fmt_mmss(self.pomo.remaining(now)),
                                             self.pomo.phase == "break")
            self.tomato_win.tick(dt)
            if self.tomato_hide_at and now >= self.tomato_hide_at:
                self.tomato_hide_at = 0.0
                self.tomato_win.hide()

    def _pomo_ding(self, text: str, end: bool = False) -> None:
        """時間到：番茄搖 + 狗開心跳 + 愛心 + 叮。"""
        self.tomato_win.ding()
        if self.ding_sound is not None:
            self.ding_sound.play()
        if end:
            self.tomato_win.set_progress(0.0, "00:00", True)
            self.tomato_hide_at = time.monotonic() + 2.2
        if self.state not in HANDS_OFF:
            self.target = None
            self.lift_v = -380 * self.k
            self.after_hop = lambda: self._set_state("happy", 1.4)
            self._set_state("hop", anim="happy")
        self.add_hearts(4)
        self.say(text, life=2.2 if end else 1.6)

    # ================================================================== 滑鼠
    def mousePressEvent(self, e) -> None:
        self._touch()
        if self.state in ("prank_go", "prank_carry"):
            self._prank_release(yanked=True)
            return
        if self.busy and e.button() == Qt.LeftButton:     # 搬清單中：不打斷，只冒愛心
            self.add_hearts(2)
            return
        if e.button() == Qt.LeftButton:
            self.press_global = e.globalPosition()
        elif e.button() == Qt.RightButton:
            self.click_timer.stop()
            self.menuRequested.emit(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e) -> None:
        if self.state == "held":
            # 滑鼠一動就馬上移動視窗，不等下一次計時器，拖起來才不會延遲
            self._sample(e.globalPosition().toPoint())
            self._follow(e.globalPosition().toPoint())
            self._place()
            return
        if self.press_global is None:
            return
        if (e.globalPosition() - self.press_global).manhattanLength() > DRAG_THRESHOLD:
            self.click_timer.stop()
            self.target = None
            self.lift_v = 0.0
            self.samples.clear()
            self.shake_times.clear()
            self._shake_sign = [0, 0]
            self.shaken = False
            self._set_state("held")
            self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return
        if self.state == "held":
            self.setCursor(Qt.OpenHandCursor)
            vx, vy = self._release_velocity()
            self._settle_airborne()
            self.pending_dizzy = self.shaken and self.feat("dizzy")
            if self.shaken:
                self.mood.change(-10, -1)
            if self.feat("throw") and math.hypot(vx, vy) > THROW_SPEED * self.k:     # 丟出去
                lim = 2600 * self.k
                self.fly_vx = max(-lim, min(lim, vx))
                self.lift_v = max(-2200 * self.k, min(1500 * self.k, vy))
                self.facing_left = self.fly_vx < 0
                self._set_state("fly", anim="held")
            else:
                self.lift_v = 0.0
                self._set_state("drop", anim="held")
        elif self._dbl:
            self._dbl = False                    # 雙擊的第二次放開，不算戳
        elif self.press_global is not None:
            self.click_timer.start(QApplication.doubleClickInterval())   # 等一下看是不是雙擊
        self.press_global = None

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return
        self._dbl = True
        self.click_timer.stop()
        self.press_global = None
        if self.busy:
            return
        if self._focusing():
            self.say("Shh... focusing", life=0.9)
            return
        if self.state == "belly":
            self._set_state("happy", 1.2)        # 再雙擊一次 = 翻回來
        else:
            self.belly_up()

    def _on_click(self) -> None:
        if self.busy:
            return
        if self._focusing():
            self.say("Shh... focusing", life=0.9)
            return
        if self.state == "sleep":                # 叫醒
            self._touch()
            self._set_state("happy", 1.2)
            self.say("...?")
        elif self.state == "belly":
            self._touch()
            self.mood.change(1)
            self.add_hearts(1)
        elif self.state not in HANDS_OFF:
            self.poke()

    # ================================================================== 畫圖
    # 地上的影子：(身長的一半, 身寬的一半, 往前後偏移)，單位 = sprite 邊長
    SHADOW = {"walk": (0.36, 0.09, -0.05), "run": (0.38, 0.09, -0.05), "idle": (0.35, 0.09, -0.05),
              "happy": (0.35, 0.09, -0.05), "sit": (0.18, 0.10, -0.04), "sleep": (0.20, 0.18, 0.0),
              "belly": (0.38, 0.12, -0.02)}

    def _shadow_angle(self) -> float:
        """影子朝向（螢幕角度，0 = 右、90 = 下），跟狗面向的方向一樣。"""
        if ANIMS[self.anim][2]:
            return DIR_ANGLE[self.direction]
        a = FRONT_ANGLE[self.anim]
        return 180.0 - a if self.facing_left else a

    def _paint_shadow(self, p: QPainter) -> None:
        p.save()
        p.setPen(Qt.NoPen)
        p.translate(self.anchor.x(), self.anchor.y() + self.extra)
        if self.lift > 1 or self.state in ("held", "drop", "fly", "hop"):
            # 離地：小小圓圓的影子，越高越小越淡
            k = 1.0 - 0.6 * min(1.0, self.lift / max(1, self.LIFT * 2))
            p.setBrush(QColor(0, 0, 0, int(60 * k)))
            p.drawEllipse(QPointF(0, 0), self.S * 0.20 * k, self.S * 0.055 * k)
        elif (sh := self.sprites.shadow(self.anim, self.direction, self.facing_left)) is not None:
            # 站在地上：從圖片算出來的影子（換圖會自動跟著變）
            cx, cy, a, b, ang = sh
            p.translate(self.S * cx - self.anchor.x(), self.LIFT + self.S * cy - self.anchor.y())
            p.rotate(ang)
            p.setBrush(QColor(0, 0, 0, 55))
            p.drawEllipse(QPointF(0, 0), self.S * a, self.S * b)
        else:
            half_len, half_w, off = self.SHADOW.get(self.anim, (0.35, 0.09, -0.05))
            p.scale(1.0, math.sin(math.radians(ELEVATION_DEG)))
            p.rotate(self._shadow_angle())
            p.setBrush(QColor(0, 0, 0, 55))
            p.drawEllipse(QPointF(self.S * off, 0), self.S * half_len, self.S * half_w)
        p.restore()

    def _font(self, px: float, bold: bool = True) -> QFont:
        f = QFont(self.base_font)
        f.setPixelSize(max(8, int(px)))
        f.setBold(bold)
        return f

    def _outlined_text(self, p: QPainter, text: str, cx: float, y: float, font: QFont,
                       color: QColor) -> None:
        """白邊字，放在任何背景上都看得清楚。cx = 中心 x，y = 底線。"""
        fm = QFontMetrics(font)
        path = QPainterPath()
        path.addText(cx - fm.horizontalAdvance(text) / 2, y, font, text)
        p.strokePath(path, QPen(QColor(255, 255, 255, color.alpha()), max(2.0, font.pixelSize() / 5),
                                Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.fillPath(path, color)

    def _paint_label(self, p: QPainter, box: QRectF) -> None:
        """滑鼠停在狗身上：名牌（名字、心情、親密度）。"""
        f1, f2 = self._font(13 * self.k), self._font(10.5 * self.k, bold=False)
        fm1, fm2 = QFontMetrics(f1), QFontMetrics(f2)
        w_max = self.S - 6
        show_mood = self.mood.enabled
        title = self.mood.label(self.name_fn()) if show_mood else self.name_fn()
        l1 = fm1.elidedText(title, Qt.ElideMiddle, int(w_max - 12))
        l2 = self.mood.detail() if show_mood else ""
        w = min(w_max, max(fm1.horizontalAdvance(l1), fm2.horizontalAdvance(l2)) + 12)
        h = fm1.height() + (fm2.height() if show_mood else 0) + 6
        top = max(1.0, self._sprite_y() + box.top() - h - 4)
        r = QRectF((self.S - w) / 2, top, w, h)
        p.setPen(QPen(QColor(168, 112, 46, 200), 1.2))
        p.setBrush(QColor(255, 250, 240, 225))
        p.drawRoundedRect(r, 7, 7)
        p.setPen(QColor(90, 58, 26))
        p.setFont(f1)
        p.drawText(QRectF(r.left(), r.top() + 2, r.width(), fm1.height()), Qt.AlignCenter, l1)
        p.setPen(QColor(192, 57, 43))
        p.setFont(f2)
        p.drawText(QRectF(r.left(), r.top() + 3 + fm1.height(), r.width(), fm2.height()), Qt.AlignCenter, l2)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.TextAntialiasing)

        self._paint_shadow(p)

        px = self._current_pixmap()
        p.drawPixmap(QPointF(0, self._sprite_y()), px)
        box = self._box(px)

        # 頭暈：頭上轉圈圈的星星
        if self.state == "dizzy":
            cx, cy = box.center().x(), self._sprite_y() + box.top() + 2
            for i in range(3):
                a = self.state_t * 4.0 + i * 2 * math.pi / 3
                x = cx + math.cos(a) * self.S * 0.16
                y = cy + math.sin(a) * self.S * 0.05
                p.fillPath(_star_path(x, y, self.S * 0.045), QColor(245, 200, 40))
                p.strokePath(_star_path(x, y, self.S * 0.045), QPen(QColor(150, 110, 20), 1))

        for x, y, age in self.hearts:
            if age < 0:
                continue
            alpha = int(255 * max(0.0, 1.0 - age / 1.3))
            p.fillPath(_heart_path(x, y, self.S * 0.11), QColor(240, 80, 110, alpha))

        font = self._font(15 * self.k)
        for text, x, y, age, life, color in self.texts:
            c = QColor(color)
            c.setAlpha(int(255 * max(0.0, min(1.0, (life - age) / 0.4))))
            self._outlined_text(p, text, x, y, font, c)

        if self.hovering and self.state not in HANDS_OFF:
            self._paint_label(p, box)
        p.end()
