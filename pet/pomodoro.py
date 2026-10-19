"""番茄鐘：計時邏輯（Pomodoro，不依賴 Qt）、廚房番茄計時器視窗（TomatoWindow）、「叮」音效。

番茄是從上面往下看的：tomato.png（番茄本體）＋ leaf.png（葉子蒂頭 = 指針，最長那片朝上），
兩張 512×512、同一個中心點。開始時葉子轉一整圈（360°），隨剩餘時間轉回 0°。
不畫刻度、不畫扇形（Evan 要求）。
"""
from __future__ import annotations

import math
import struct
import sys
import time
import wave
from pathlib import Path

WOBBLE_DEG = 9.0          # 時間到：番茄左右搖晃 ±9°
WOBBLE_HALF = 0.14        # 搖一邊 0.14 秒
WOBBLE_TIMES = 8          # 來回 8 次（半程）


# ====================================================================== 計時
class Pomodoro:
    """phase：None（沒在跑）/ "focus" / "break"。"""

    def __init__(self):
        self.phase: str | None = None
        self.t0 = 0.0
        self.total = 0.0
        self.break_sec = 0.0

    @property
    def active(self) -> bool:
        return self.phase is not None

    def start(self, focus_sec: float, break_sec: float, now: float) -> None:
        self.phase = "focus"
        self.t0 = now
        self.total = max(1.0, float(focus_sec))
        self.break_sec = max(1.0, float(break_sec))

    def stop(self) -> None:
        self.phase = None

    def remaining(self, now: float) -> float:
        return max(0.0, self.total - (now - self.t0)) if self.phase else 0.0

    def fraction(self, now: float) -> float:
        """剩下多少（1 → 0）。葉子角度 = 360 × fraction。"""
        return self.remaining(now) / self.total if self.phase else 0.0

    def update(self, now: float) -> str | None:
        """時間到時回傳 "focus_done"（自動開始休息）或 "break_done"（停止）。"""
        if self.phase and now - self.t0 >= self.total:
            if self.phase == "focus":
                self.phase = "break"
                self.t0 = now
                self.total = self.break_sec
                return "focus_done"
            self.phase = None
            return "break_done"
        return None


def fmt_mmss(sec: float) -> str:
    sec = int(math.ceil(sec - 1e-6))
    return f"{sec // 60:02d}:{sec % 60:02d}"


# ====================================================================== 叮
def make_ding_wav(path: Path, sr: int = 44100) -> Path:
    """合成一個短的「叮」（像廚房計時器的小鈴）：幾個泛音 + 指數衰減。"""
    f0, dur = 1568.0, 1.3                         # G6
    partials = [(1.0, 1.0, 3.2), (2.76, 0.45, 5.0), (5.40, 0.22, 8.0), (0.5, 0.18, 2.5)]
    n = int(sr * dur)
    frames = bytearray()
    for i in range(n):
        t = i / sr
        attack = min(1.0, t / 0.004)
        v = sum(a * math.exp(-d * t) * math.sin(2 * math.pi * f0 * m * t) for m, a, d in partials)
        s = int(max(-1.0, min(1.0, 0.42 * attack * v / 1.85)) * 32767)
        frames += struct.pack("<h", s)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))
    return path


class Ding:
    """播 assets/sounds/ding.wav（沒有就合成一個）。Windows 用內建的 winsound（最穩），其他系統用 QSoundEffect。
    v0.4：也拿來播汪汪（sounds.Bark = 同一個類別換檔名和合成器）。"""
    FILE = "ding.wav"

    @staticmethod
    def make(path: Path) -> Path:
        return make_ding_wav(path)

    def __init__(self, assets_dir: Path, fallback_dir: Path):
        self.path = Path(assets_dir) / "sounds" / self.FILE
        if not self.path.is_file():
            try:
                self.make(self.path)
            except OSError:                      # assets 唯讀（打包後）→ 存到 %APPDATA%
                self.path = self.make(Path(fallback_dir) / self.FILE)
        self._effect = None

    def play(self) -> None:
        try:
            if sys.platform == "win32":
                import winsound
                winsound.PlaySound(str(self.path), winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            if self._effect is None:
                from PySide6.QtCore import QUrl
                from PySide6.QtMultimedia import QSoundEffect
                self._effect = QSoundEffect()
                self._effect.setSource(QUrl.fromLocalFile(str(self.path)))
                self._effect.setVolume(0.8)
            self._effect.play()
        except Exception:
            pass                                  # 沒聲音也不要讓狗當掉


# ====================================================================== 番茄視窗
def _tomato_window_class():
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QFontMetricsF, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import QWidget

    from .paper import INK, LEAF, PAPER, hand_font

    class TomatoWindow(QWidget):
        """狗右邊地上的番茄計時器 + 上面的 MM:SS 小牌子。滑鼠穿透。"""

        def __init__(self, assets_dir: Path, S: int):
            super().__init__(
                None,
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoDropShadowWindowHint
                | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput,
            )
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.k = S / 160
            self.T = int(round(0.62 * S))                    # 番茄大小
            folder = Path(assets_dir) / "pomodoro"
            self.body = self._load(folder / "tomato.png")
            self.leaf = self._load(folder / "leaf.png")
            self.frac = 1.0
            self.text = "00:00"
            self.is_break = False
            self.wobble_t = -1.0                             # >= 0：正在搖
            self.f_big = hand_font(24 * self.k)
            self.f_tiny = hand_font(24 * self.k * 0.55)
            fm = QFontMetricsF(self.f_big)
            self.label_h = fm.ascent() + fm.descent() + 4
            w = max(self.T * 1.5, fm.horizontalAdvance("00:00 ") + QFontMetricsF(self.f_tiny).horizontalAdvance("break") + 40)
            self.resize(int(w), int(self.label_h + 12 + self.T * 1.15))

        def _load(self, path: Path):
            px = QPixmap(str(path))
            if px.isNull():
                return None
            return px.scaled(self.T, self.T, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        def place(self, cx: float, ground_y: float) -> None:
            """番茄中心 x = cx，底部貼地（番茄頂 = 地面 - 0.95T）。"""
            bottom_pad = self.height() - (self.label_h + 12 + self.T)   # 番茄下面留的空間
            x = cx - self.width() / 2
            y = ground_y + 0.05 * self.T + bottom_pad - self.height()
            self.move(int(round(x)), int(round(y)))

        def set_progress(self, frac: float, remaining: str, is_break: bool) -> None:
            if (abs(frac - self.frac) > 0.0005) or remaining != self.text or is_break != self.is_break:
                self.frac, self.text, self.is_break = frac, remaining, is_break
                self.update()

        def ding(self) -> None:
            self.wobble_t = 0.0

        def tick(self, dt: float) -> None:
            if self.wobble_t >= 0:
                self.wobble_t += dt
                if self.wobble_t > WOBBLE_HALF * WOBBLE_TIMES:
                    self.wobble_t = -1.0
                self.update()

        def _wobble_angle(self) -> float:
            if self.wobble_t < 0:
                return 0.0
            half = int(self.wobble_t / WOBBLE_HALF)
            f = (self.wobble_t % WOBBLE_HALF) / WOBBLE_HALF
            a, b = (-WOBBLE_DEG, WOBBLE_DEG) if half % 2 == 0 else (WOBBLE_DEG, -WOBBLE_DEG)
            if half == 0:
                a = 0.0
            return a + (b - a) * f

        def paintEvent(self, e) -> None:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.setRenderHint(QPainter.TextAntialiasing)
            k = self.k
            cx = self.width() / 2
            top = self.label_h + 12
            T = self.T

            # 小牌子 MM:SS（休息時綠字 + break）
            fm = QFontMetricsF(self.f_big)
            fmt = QFontMetricsF(self.f_tiny)
            extra = (" ", "break") if self.is_break else ("", "")
            tw = fm.horizontalAdvance(self.text + extra[0]) + (fmt.horizontalAdvance(extra[1]) if self.is_break else 0)
            box = QRectF(cx - tw / 2 - 10 * k, 2, tw + 20 * k, self.label_h)
            p.setPen(QPen(INK, 2))
            p.setBrush(PAPER)
            p.drawRoundedRect(box, 12 * k, 12 * k)
            base = box.top() + 1 + fm.ascent()
            x = box.left() + 10 * k
            p.setFont(self.f_big)
            p.setPen(LEAF if self.is_break else INK)
            p.drawText(QPointF(x, base), self.text + extra[0])
            if self.is_break:
                p.setFont(self.f_tiny)
                p.drawText(QPointF(x + fm.horizontalAdvance(self.text + " "), base), "break")

            # 番茄（搖晃時繞著底部附近 50%, 90% 轉）＋ 葉子指針
            p.save()
            p.translate(cx, top + T * 0.9)
            p.rotate(self._wobble_angle())
            p.translate(-cx, -(top + T * 0.9))
            if self.body is not None:
                p.drawPixmap(QPointF(cx - self.body.width() / 2, top + (T - self.body.height()) / 2), self.body)
            else:
                p.setPen(QPen(INK, 2))
                p.setBrush(QColor_tomato())
                p.drawEllipse(QPointF(cx, top + T / 2), T * 0.45, T * 0.42)
            if self.leaf is not None:
                p.translate(cx, top + T / 2)
                p.rotate(360.0 * self.frac)
                p.drawPixmap(QPointF(-self.leaf.width() / 2, -self.leaf.height() / 2), self.leaf)
            p.restore()
            p.end()

    def QColor_tomato():
        from .paper import TOMATO
        return TOMATO

    return TomatoWindow


def TomatoWindow(assets_dir: Path, S: int):
    """建立番茄視窗（Qt 只在這裡才載入，所以上面的計時邏輯不用 PySide6 也能測）。"""
    return _tomato_window_class()(assets_dir, S)
