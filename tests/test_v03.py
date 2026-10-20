"""v0.3 狀態機測試：用假的 PySide6 跑搬清單、打勾、起床、番茄鐘、泡泡、換日。
畫面不會真的出現，只檢查座標和狀態。  python tests/test_v03.py
（不要在裝了真 PySide6 的環境用 pytest 跑，這個檔會換掉 time.monotonic。）
"""
import sys, math, json, tempfile, time as _time
from pathlib import Path
from datetime import date, timedelta
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fakeqt"))     # 假的 PySide6（雲端裝不到真的）
PROJ = HERE.parent
sys.path.insert(0, str(PROJ))

# ---- fake clock
clock = [1000.0]
_time.monotonic = lambda: clock[0]

from PySide6.QtCore import QPoint, QPointF, QRect
from PySide6.QtGui import QCursor
from unittest.mock import MagicMock

class Pix:
    def __init__(self, key): self.k = key
    def cacheKey(self): return self.k
    def mask(self):
        m = MagicMock(); m.isNull.return_value = True; return m
    def rect(self): return QRect(0, 0, 160, 160)
    def toImage(self):
        img = MagicMock()
        c = MagicMock(); c.alpha.return_value = 255
        img.pixelColor.return_value = c
        return img

class Sprites:
    size = 160
    def __init__(self):
        self.frames = {("run", "right"): [Pix(i) for i in range(6)]}
    def frame(self, name, d, t, flip=False): return Pix(hash((name, d)) % 1000)
    def frame_at(self, name, d, i, flip=False): return Pix(5000 + i)
    def shadow(self, *a): return None
    def held_grab(self, t, flip=False): return (0.5, 0.2)

tmp = Path(tempfile.mkdtemp())
from pet.settings import Settings
from pet import pet_window as PW
from pet.pet_window import PetWindow, BITE, NOSE
from pet.todo import TodoStore
from pet.todo_window import TodoWindow
from pet.pomodoro import TomatoWindow, Ding

settings = Settings(tmp / "settings.json")
pet = PetWindow(Sprites(), settings)
store = TodoStore(tmp / "todo.json")
store.add("Calculus ch.3 homework"); store.add("Push SE homework repo"); store.add("Football practice 6pm")
tw = TodoWindow(store, 160)
ding = MagicMock()
pet.attach_pomodoro(TomatoWindow(PROJ / "assets", 160), ding)
pet.attach_todo(tw)

def step(sec=0.016):
    clock[0] += sec
    pet._tick()
    if tw._anim.isActive(): tw._anim_step()

def run_until(cond, limit=30.0, dt=0.016):
    t = 0.0
    while not cond():
        step(dt); t += dt
        assert t < limit, f"timeout, state={pet.state}"
    return t

S = 160
sr = tw.screen_right
print("screen right", sr, "floor", tw.floor, "list window", tw.geometry().x(), tw.geometry().y(), tw.width(), tw.height())
assert tw.isVisible() and not tw.is_open and tw.slide == tw.W

# ---------------------------------------------------------- 1. 拉出來
pet.gx, pet.gy = 600.0, 500.0
pet._set_state("idle", 50)
pet.toggle_list()
assert pet.state == "list_go" and pet.busy
seen = []
mouth_err = 0.0
yank_slides = []
def watch():
    global mouth_err
    seen.append(pet.state)
    if pet.state == "list_tug":
        mouth = pet.gx + BITE[0] * S
        tab_center = tw.sr - tw.W + tw.slide - tw.T / 2
        if tw.slide > 0:
            mouth_err = max(mouth_err, abs(mouth - tab_center))
        yank_slides.append(tw.slide)
        assert pet.facing_left is False
    return not pet.busy
# 搬的時候點狗：不會打斷
ev = MagicMock(); ev.button.return_value = PW.Qt.LeftButton
run_until(lambda: pet.state == "list_bite")
print("bite at gx", round(pet.gx, 1), "mouth", round(pet.gx + BITE[0] * S, 1), "tab center", sr - tw.T / 2, "bubble", pet.bubble.text)
assert abs(pet.gy - tw.floor) < 1 and abs(pet.gx + BITE[0] * S - (sr - tw.T / 2)) < 1
pet.mousePressEvent(ev); assert pet.state == "list_bite" and pet.press_global is None
pet.start_zoomies(); assert pet.state == "list_bite"           # 選單指令也不會打斷
run_until(watch)
order = [s for i, s in enumerate(seen) if i == 0 or seen[i - 1] != s]
print("pull states:", order)
print("max |mouth - tab center| during tug:", round(mouth_err, 3))
assert mouth_err < 0.5
assert all(b <= a + 1e-6 for a, b in zip(yank_slides, yank_slides[1:])), "list should only move out"
assert tw.is_open and tw.slide == 0 and tw.ready
assert pet.state == "sit" and pet.bubble.text == "Here you go!"
x_after = pet.gx
print("dog after pull gx", round(pet.gx, 1), "= open tab x", sr - tw.W - tw.T / 2, "- 0.37S - 0.3S")
assert abs(pet.gx - (sr - tw.W - tw.T / 2 - BITE[0] * S - 0.3 * S)) < 0.5
assert tw.strip.isVisible(), "input strip shows when open"

# ---------------------------------------------------------- 2. 打勾、全部做完、刪除、新增
pet._set_state("idle", 50)
tw.toggled.emit(store.toggle(0), store.all_done)
assert pet.state == "hop" and pet.bubble.text in ("Nice!", "One down!", "Woof!")
run_until(lambda: pet.state not in ("hop",))
store.toggle(1); store.toggle(2)
pet._set_state("idle", 50)
tw.toggled.emit(True, store.all_done)
assert pet.bubble.text == "All done! Good job!", pet.bubble.text
run_until(lambda: pet.state == "idle" or pet.state == "walk" or pet.state == "sit", 10)
tw.strip.edit.setText("  Drink   water  "); tw.add_current()
assert store.items[-1]["text"] == "Drink water" and tw.strip.edit.text() == ""
h0 = tw.height(); tw.store.remove(3); tw.relayout(); assert tw.height() < h0
print("todo ops ok, paper height", tw.paper_h)

# hit test on the window
pos_row0 = QPointF(tw.L + 80, tw.line_y(3) - 8)
assert tw._hit(pos_row0) == ("toggle", 0), tw._hit(pos_row0)
pos_x = QPointF(tw.L + tw.W - 16, tw.line_y(3) - 8)
assert tw._hit(pos_x) == ("delete", 0)
b = tw._add_button(); assert tw._hit(QPointF(b.center().x(), b.center().y()))[0] == "add"
tr = tw.tab_rect()
print("tab rect", tr, "tab center y on screen", tw.y() + tr.center().y(), "= floor - 0.22S", tw.floor - 0.22 * S)
assert abs(tw.y() + tr.center().y() - (tw.floor - 0.22 * S)) < 1.5

# ---------------------------------------------------------- 3. 推回去
pet.gx, pet.gy = 900.0, 400.0
pet._set_state("idle", 50)
pet.toggle_list()
seen.clear(); nose_err = [0.0]
def watch2():
    seen.append(pet.state)
    if pet.state == "list_push":
        nose_err[0] = max(nose_err[0], abs(tw.sr - tw.W + tw.slide - (pet.gx + NOSE * S)) if tw.slide < tw.W else 0)
    return not pet.busy
run_until(watch2)
order = [s for i, s in enumerate(seen) if i == 0 or seen[i - 1] != s]
print("push states:", order, "max nose err", round(nose_err[0], 3))
assert not tw.is_open and tw.slide == tw.W and pet.bubble.text == "See you later!"
assert not tw.strip.isVisible()
assert abs(pet.gx - (sr - NOSE * S - 0.38 * S)) < 0.5

# ---------------------------------------------------------- 4. 早上：睡覺 → 醒來 → 拉出來
pet.gx, pet.gy = 500.0, 300.0
pet._set_state("sleep", 300)
assert pet.morning()
assert pet.state == "wake" and pet.bubble.text == "08:00! Good morning!"
run_until(lambda: not pet.busy)
assert tw.is_open and pet.bubble.text == "Your list for today!", pet.bubble.text
print("morning ok")
# 已經開著 → 只打招呼
assert pet.morning() and pet.bubble.text == "Your list for today!"
# 被拎著 → False（等一下再試）
pet._set_state("held"); assert pet.morning() is False
pet._set_state("idle", 50)

# ---------------------------------------------------------- 5. 番茄鐘（1 分鐘 / 1 分鐘）
settings.data["focus_min"] = 1; settings.data["break_min"] = 1
pet.gx, pet.gy = 1880.0, 600.0            # 靠右邊：要往左挪才放得下番茄
pet.start_pomodoro()
assert pet.state == "pomo_go"
run_until(lambda: pet.state == "pomo_sit")
tom = pet.tomato_win
print("pomo spot", pet.pomo_spot, "tomato window", tom.x(), tom.y(), tom.width(), tom.height(), "bubble", pet.bubble.text)
assert pet.pomo.phase == "focus" and tom.isVisible() and pet.anim == "sit"
assert pet.gx + 0.62 * S + 0.31 * S <= 1920
# 專心中：點狗 = Shh；不會自己亂跑
pet._on_click(); assert pet.bubble.text == "Shh... focusing" and pet.state == "pomo_sit"
# 專心中：點標籤 → 清單自己滑（狗不動），番茄鐘繼續
assert tw.is_open
pet.toggle_list(); assert pet.state == "pomo_sit" and not tw.is_open
run_until(lambda: not tw._anim.isActive(), 2)
assert tw.slide == tw.W
# 打勾時安靜
st = pet.state; tw.toggled.emit(True, False); assert pet.state == st
# 拎走再放下 → 回到番茄旁邊
pet._set_state("happy", 0.5)
run_until(lambda: pet.state == "pomo_sit", 5)
print("focus remaining", round(pet.pomo.remaining(clock[0]), 1), "label", tom.text)
run_until(lambda: pet.pomo.phase == "break", 70, dt=0.05)
assert ding.play.call_count == 1 and pet.bubble.text == "Ding! Break time!" and tom.wobble_t >= 0
run_until(lambda: pet.state == "pomo_sit", 5)
assert pet.anim == "idle" and tom.is_break
run_until(lambda: not pet.pomo.active, 70, dt=0.05)
assert ding.play.call_count == 2 and pet.bubble.text == "Back to work?"
assert tom.isVisible()
run_until(lambda: not tom.isVisible(), 3)
run_until(lambda: pet.state not in ("hop", "happy"), 5)
print("pomodoro ok; after:", pet.state)
# 停止
pet.start_pomodoro(); run_until(lambda: pet.state == "pomo_sit", 10)
pet.stop_pomodoro(); assert not tom.isVisible() and pet.bubble.text == "OK, stopped." and pet.state == "idle"
# v0.4.3：番茄變大（0.8S）、離狗 0.85S，而且永遠不會被「打開的清單」蓋住（狗在哪都一樣、窄螢幕放左邊）
from pet.pomodoro import TOMATO_SCALE
from pet.pet_window import TOMATO_OFFSET
assert tom.T == round(TOMATO_SCALE * 160)
geo = pet._screen_here().availableGeometry()
list_left = geo.x() + geo.width() - tw.full_width()
def tomato_span():
    cx = tom.x() + tom.width() / 2
    return cx - tom.half_width(), cx + tom.half_width()
gr = pet._ground_rect(pet._screen_here())
for start_x in (gr.left(), (gr.left() + gr.right()) / 2, list_left - 40, gr.right()):
    for list_open in (False, True):
        if tw.is_open != list_open:
            tw.set_open(list_open) if hasattr(tw, "set_open") else None
        pet._set_state("idle", 1.0); pet.gx = start_x
        pet.start_pomodoro(); run_until(lambda: pet.state == "pomo_sit", 20)
        l, r = tomato_span()
        assert pet.pomo_side == 1 and r <= list_left - 0.1 * 160 + 0.5, (start_x, l, r, list_left)
        assert abs((tom.x() + tom.width() / 2) - pet.gx - TOMATO_OFFSET * 160) < 1.5
        pet.stop_pomodoro(quiet=True)
# 窄螢幕（清單幾乎佔滿）：番茄放狗左邊，也不被清單蓋住
saved_W = tw.W
tw.W = int(geo.width() - tw.PAD - tw.T - 1.6 * 160)
list_left = geo.x() + geo.width() - tw.full_width()
pet._set_state("idle", 1.0); pet.gx = gr.right()
pet.start_pomodoro(); run_until(lambda: pet.state == "pomo_sit", 20)
l, r = tomato_span()
assert pet.pomo_side == -1 and r <= list_left and l >= geo.x() - 1 and pet.facing_left, (l, r, list_left)
pet.stop_pomodoro(quiet=True); tw.W = saved_W
pet._set_state("idle", 1.0)
print("v0.4.3 tomato placement ok")
# 搬清單時不能開始番茄鐘
pet.toggle_list(); assert pet.busy
pet.start_pomodoro(); assert not pet.pomo.active and pet.pomo_pending is None and pet.bubble.text == "One sec!"
run_until(lambda: not pet.busy)

# ---------------------------------------------------------- 6. 泡泡不超出螢幕
pet.gx = 1915.0; pet.say("Your list for today!", life=2); pet._place(); pet._place_bubble()
bb = pet.bubble
print("bubble x", bb.x(), "w", bb.width(), "tail", round(bb.tail_x, 1))
assert bb.x() + bb.width() <= 1920 - 4 + 1
pet.gx = 2.0; pet._place(); pet._place_bubble(); assert bb.x() >= 4
clock[0] += 5; pet._place_bubble(); assert not bb.active

# ---------------------------------------------------------- 7. 換日
d = [date(2026, 10, 19)]
s2 = TodoStore(tmp / "todo2.json", today_fn=lambda: d[0])
s2.add("a"); s2.add("b"); s2.toggle(0)
d[0] = date(2026, 10, 20)
assert s2.rollover() and [i["text"] for i in s2.items] == ["b"] and s2.date == "2026-10-20"
s3 = TodoStore(tmp / "todo2.json", today_fn=lambda: d[0]); assert [i["text"] for i in s3.items] == ["b"]
d[0] = date(2026, 10, 21)
s2.toggle(0); s4 = TodoStore(tmp / "todo2.json", today_fn=lambda: d[0]); assert s4.items == []
print("rollover ok")

# ---------------------------------------------------------- 8. 起床檢查（app._check_wake）
from pet.app import PetApp
from datetime import datetime
import pet.app as A
class FakeDT:
    now_v = datetime(2026, 10, 19, 7, 59)
    @classmethod
    def now(cls): return cls.now_v
A.datetime = FakeDT
calls = []
fake = MagicMock()
fake.settings = Settings(tmp / "s3.json")
fake.todo = TodoStore(tmp / "todo3.json")
fake.pet.morning = lambda: calls.append(1) or True
PetApp._check_wake(fake); assert calls == []
FakeDT.now_v = datetime(2026, 10, 19, 8, 0); PetApp._check_wake(fake); assert calls == [1]
PetApp._check_wake(fake); assert calls == [1]            # 同一天只拉一次
FakeDT.now_v = datetime(2026, 10, 20, 13, 5); PetApp._check_wake(fake); assert calls == [1, 1]   # 開機時已過時間
fake.pet.morning = lambda: False
FakeDT.now_v = datetime(2026, 10, 21, 9, 0); PetApp._check_wake(fake)
assert fake.settings.get("last_pull_date") == "2026-10-20"   # 不方便 → 不記錄，下次再試
print("wake check ok")

# ---------------------------------------------------------- 9. 畫圖程式跑一遍（假的 QPainter，只抓 Python 錯誤）
tw.set_open(True); tw.hover = 0; tw.hover_x = True; tw.paintEvent(None)
tw.set_left(tw.sr - 100); tw.paintEvent(None)
pet.bubble.show_text("Hi"); pet.bubble.paintEvent(None)
tom.set_progress(0.4, "10:00", True); tom.ding(); tom.tick(0.3); tom.paintEvent(None)
pet.paintEvent(None)
print("ALL TESTS PASSED")
