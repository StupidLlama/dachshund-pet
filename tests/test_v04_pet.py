"""v0.4 狗收到訊息的狀態機測試（假 PySide6）：「!」→ 跑到中間 → 汪 → 泡泡 → 點掉、排隊、番茄鐘、搬清單時等待。
    python tests/test_v04_pet.py
"""
import sys, tempfile, time as _time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fakeqt"))
PROJ = HERE.parent
sys.path.insert(0, str(PROJ))

clock = [1000.0]
_time.monotonic = lambda: clock[0]

from PySide6.QtCore import QPoint, QRect
from unittest.mock import MagicMock
from collections import deque


class Pix:
    def __init__(self, key): self.k = key
    def cacheKey(self): return self.k
    def mask(self):
        m = MagicMock(); m.isNull.return_value = True; return m
    def rect(self): return QRect(0, 0, 160, 160)
    def toImage(self):
        img = MagicMock(); c = MagicMock(); c.alpha.return_value = 255
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


from pet.settings import Settings
from pet import pet_window as PW
from pet.pet_window import PetWindow
from pet.todo import TodoStore
from pet.todo_window import TodoWindow
from pet.pomodoro import TomatoWindow
from pet.bubble import wrap_text

tmp = Path(tempfile.mkdtemp())
settings = Settings(tmp / "settings.json")
pet = PetWindow(Sprites(), settings)
tw = TodoWindow(TodoStore(tmp / "todo.json"), 160)
pet.attach_todo(tw)
ding, bark = MagicMock(), MagicMock()
pet.attach_pomodoro(TomatoWindow(PROJ / "assets", 160), ding)
pet.attach_messages(bark)
seen, notes = [], []
pet.seen_fn = lambda m: seen.append(m["id"])
pet.notify_fn = lambda title, text: notes.append((title, text))
S = 160


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


def msg(i, text="Hi Evan!", name="Amy"):
    return {"id": f"m{i}", "from": "b", "name": name, "text": text, "ts": 1000 + i, "via": "phone", "mine": False}


def ok(s): print("ok -", s)


# ---------------------------------------------------------------- 換行
w = lambda t: 10.0 * len(t)
assert wrap_text("hello there my friend", w, 120) == ["hello there", "my friend"]
assert wrap_text("今天要不要一起吃晚餐", w, 50) == ["今天要不要", "一起吃晚餐"]
assert wrap_text("Hi 你好嗎 ok", w, 40) == ["Hi 你", "好嗎", "ok"], wrap_text("Hi 你好嗎 ok", w, 40)
assert all(len(x) * 10 <= 60 for x in wrap_text("x" * 25, w, 60))
assert wrap_text("", w, 60) == [""]
ok("wrap_text (English words, Chinese chars, long words)")

# ---------------------------------------------------------------- 1. 一則訊息：! → 跑 → 汪 → 泡泡
pet.gx, pet.gy = 200.0, 300.0
pet._set_state("idle", 50)
pet.on_message(msg(1))
step()
assert pet.state == "hop" and pet.msg_seq and pet.alert_until == float("inf")
order = []
def watch():
    if not order or order[-1] != pet.state:
        order.append(pet.state)
    return pet.msg_cur is not None
run_until(watch)
print("  states:", order)
assert order[:3] == ["hop", "msg_go", "hop"], order
assert bark.play.call_count == 1
c = QPoint(960, 520)
assert abs(pet.gx - c.x()) < 4 and abs(pet.gy - c.y()) < 4, (pet.gx, pet.gy)
assert pet.state == "msg_wait" and pet.anim == "sit" and pet.alert_until == 0
assert pet.msg_bubble.active and pet.msg_bubble.name == "Amy" and pet.msg_bubble.lines == ["Hi Evan!"]
ok("alert -> run to the middle -> bark -> bubble")

# 泡泡一直在（沒有時間限制），狗不會走掉
for _ in range(300):
    step(0.1)
assert pet.msg_bubble.active and pet.state == "msg_wait"
# say() 不會蓋過訊息泡泡
pet.say("Zoom!"); assert not pet.bubble.active
ok("bubble stays until clicked; other bubbles held back")

# 點狗 = 已讀
pet._on_click()
assert seen == ["m1"] and pet.msg_cur is None and not pet.msg_bubble.active and pet.state == "idle"
ok("click the dog -> seen")

# ---------------------------------------------------------------- 2. 好幾則：一則一則
pet._set_state("idle", 50)
pet.on_message(msg(2, "one")); pet.on_message(msg(3, "two")); pet.on_message(msg(3, "two"))   # 重複的不算
assert len(pet.msg_queue) == 2
run_until(lambda: pet.msg_cur is not None)
assert pet.msg_bubble.lines == ["one"] and pet.msg_bubble.more == 1
pet.on_message(msg(4, "three"))
assert pet.msg_bubble.more == 2
pet.msg_bubble.clicked.emit()                    # 點泡泡
assert seen[-1] == "m2" and pet.state == "hop"
run_until(lambda: pet.msg_cur is not None, 3)
assert pet.msg_bubble.lines == ["two"] and bark.play.call_count == 2   # 第二則不用再跑、不再汪
pet.dismiss_message()
run_until(lambda: pet.msg_cur is not None, 3)
pet.dismiss_message()
assert seen == ["m1", "m2", "m3", "m4"] and pet.msg_cur is None
ok("queue: one after another, '+N more', no repeat run")

# ---------------------------------------------------------------- 3. 跑過去的路上點狗 → 直接冒
pet.gx, pet.gy = 100.0, 100.0
pet._set_state("idle", 50)
pet.on_message(msg(5))
run_until(lambda: pet.state == "msg_go")
pet._on_click()
assert pet.msg_cur and pet.state == "msg_wait"
pet.dismiss_message()
ok("click while running -> shows right away")

# ---------------------------------------------------------------- 4. 跑過去的路上被拎走 → 落地的地方冒
pet.gx, pet.gy = 100.0, 100.0
pet._set_state("idle", 50)
pet.on_message(msg(6))
run_until(lambda: pet.state == "msg_go")
pet._set_state("held"); step(); pet.lift_v = 0; pet._set_state("drop", anim="held")
run_until(lambda: pet.msg_cur is not None, 5)
assert pet.state == "msg_wait"
pet.dismiss_message()
ok("picked up on the way -> shows where it lands")

# ---------------------------------------------------------------- 5. 搬清單時先等
pet.gx, pet.gy = 600.0, 500.0
pet._set_state("idle", 50)
pet.toggle_list()
assert pet.busy
pet.on_message(msg(7))
run_until(lambda: not pet.busy, 20)
assert pet.msg_cur is None or pet.msg_cur["id"] == "m7"
run_until(lambda: pet.msg_cur is not None, 10)
pet.dismiss_message()
ok("waits until the list is moved")

# ---------------------------------------------------------------- 6. 睡覺中收到 → 醒來跑過去
pet._set_state("sleep", 300)
pet.on_message(msg(8))
step()
assert pet.state == "hop"
run_until(lambda: pet.msg_cur is not None, 10)
pet.dismiss_message()
ok("wakes up for a message")

# ---------------------------------------------------------------- 7. 番茄鐘：專心中只有「!」+ 通知；休息時原地冒
settings.data["focus_min"] = 1; settings.data["break_min"] = 1
pet.gx, pet.gy = 800.0, 600.0
pet._set_state("idle", 50)
pet.start_pomodoro()
run_until(lambda: pet.state == "pomo_sit")
bark_n = bark.play.call_count
pet.on_message(msg(9, "focus?"))
step()
assert notes[-1] == ("Message from Amy", "focus?") and pet.state == "pomo_sit" and pet.msg_cur is None
assert pet.alert_until == clock[0] - 0.016 + PW.ALERT_FOCUS_SEC or pet.alert_until > clock[0]
step(PW.ALERT_FOCUS_SEC + 0.1)
assert pet.alert_until < clock[0]                 # 「!」幾秒後消失
pet.on_message(msg(10, "again"))
step()
assert len(notes) == 2 and "(+1 more)" in notes[-1][1]
for _ in range(30):
    step(0.1)
assert len(notes) == 2 and pet.msg_cur is None and pet.state == "pomo_sit"
pet._on_click(); assert pet.bubble.text == "Shh... focusing"
spot = pet.pomo_spot
run_until(lambda: pet.pomo.phase == "break", 70, dt=0.05)
run_until(lambda: pet.msg_cur is not None, 5)
assert bark.play.call_count == bark_n + 1 and abs(pet.gx - spot[0]) < 1   # 原地，沒有跑走
assert pet.msg_bubble.lines == ["focus?"] and pet.msg_bubble.more == 1
pet.dismiss_message()
run_until(lambda: pet.msg_cur is not None, 3)
pet.dismiss_message()
run_until(lambda: pet.state == "pomo_sit", 5)
assert pet.pomo.active and abs(pet.gx - spot[0]) < 1
pet.stop_pomodoro()
pet.gx = 1900.0
ok("pomodoro: '!' + notification while focusing, bubble in place during break")

# 正走去番茄的路上 = 也算專心
pet._set_state("idle", 50)
pet.start_pomodoro()
assert pet.pomo_pending
pet.on_message(msg(11))
step()
assert pet.msg_cur is None and notes[-1][0] == "Message from Amy"
pet.stop_pomodoro()
run_until(lambda: pet.msg_cur is not None, 10)
pet.dismiss_message()
ok("stopping the pomodoro lets queued messages through")

# ---------------------------------------------------------------- 8. 解除配對：清掉
pet._set_state("idle", 50)
pet.on_message(msg(12)); pet.on_message(msg(13))
run_until(lambda: pet.msg_cur is not None)
pet.clear_messages()
assert not pet.msg_queue and pet.msg_cur is None and not pet.msg_bubble.active and pet.state == "idle"
ok("clear_messages")

# ---------------------------------------------------------------- 9. 畫圖跑一遍
pet.on_message(msg(14, "今天 lunch 要吃什麼？要不要一起去吃那家很好吃的拉麵 ramen"))
step()
pet.paintEvent(None)                      # 有「!」
run_until(lambda: pet.msg_cur is not None)
pet.msg_bubble.paintEvent(None)
assert len(pet.msg_bubble.lines) >= 2
ev = MagicMock(); ev.button.return_value = PW.Qt.RightButton
got = []
pet.msg_bubble.replyRequested.connect(lambda: got.append(1))
pet.msg_bubble.mousePressEvent(ev)
assert got == [1] and pet.msg_cur is not None    # 右鍵 = 回覆，不會關掉
ev.button.return_value = PW.Qt.LeftButton
pet.msg_bubble.mousePressEvent(ev)
assert pet.msg_cur is None
ok("paint + right-click reply / left-click close")

# ---------------------------------------------------------------- 10. 配對視窗、訊息視窗（假的 cloud，同步回呼）
from pet import messaging_ui as UI
from datetime import datetime


class FakeCloud:
    def __init__(self):
        self.paired = False
        self.state = {"partner_name": "", "my_name": ""}
        self.my_name = ""
        self.partner_name = "Your friend"
        self.calls = []
        self.fail = None
    def call(self, fn, *args, callback=None):
        self.calls.append((fn.__name__, args))
        if self.fail:
            callback(None, self.fail); return
        callback(fn(*args), None)
    def create_pair(self, name):
        self.paired = True; self.my_name = name; return {"code": "123456", "room": "r"}
    def join(self, code, name):
        self.paired = True; self.state["partner_name"] = "Evan"; self.partner_name = "Evan"; return {"partner": "Evan"}
    def make_link_code(self): return {"code": "654321"}
    def friend_code(self): return {"code": "111222"}
    def refresh_names(self): return {"me": self.my_name, "partner": "Amy"}
    def set_my_name(self, n): self.my_name = n
    def unpair(self): self.paired = False
    def history(self):
        return [{"id": "a", "mine": False, "name": "Amy", "text": "hi <b>", "ts": 1760000000000},
                {"id": "b", "mine": True, "name": "Me", "text": "yo", "ts": 1760000060000}]
    def send(self, t): return {"id": "z", "text": t}


fc = FakeCloud()
changes = []
dlg = UI.PairDialog(fc, on_change=lambda: changes.append(1))
dlg.name.setText("")
dlg._make(); assert "name first" in str(dlg.status.setText.call_args)
dlg.name.setText("Evan"); dlg._make()
assert fc.calls[-1] == ("create_pair", ("Evan",)) and dlg.code == "123456" and dlg.waiting and changes
dlg._vis = True
for _ in range(3): dlg._tick()
assert dlg.waiting is False and "Paired with Amy" in str(dlg.status.setText.call_args)
dlg.show_home(); assert dlg.code == ""
dlg._link_phone(); assert dlg.code == "654321" and not dlg.waiting
dlg._friend_code(); assert dlg.code == "111222"
fc2 = FakeCloud(); dlg2 = UI.PairDialog(fc2)
dlg2.name.setText("Amy"); dlg2.code_in.setText("123456"); dlg2._join()
assert fc2.paired and "Paired with Evan" in str(dlg2.status.setText.call_args)
fc3 = FakeCloud(); fc3.fail = "That code doesn't work. Ask for a new one!"
dlg3 = UI.PairDialog(fc3); dlg3.name.setText("x"); dlg3.code_in.setText("999999"); dlg3._join()
assert "doesn't work" in str(dlg3.status.setText.call_args)
UI.QMessageBox.question.return_value = UI.QMessageBox.Yes
dlg._unpair(); assert not fc.paired
assert UI.fmt_code("123456") == "123 456"
now = datetime(2026, 10, 19, 22, 0)
ts_today = int(datetime(2026, 10, 19, 21, 3).timestamp() * 1000)
ts_old = int(datetime(2026, 10, 18, 9, 5).timestamp() * 1000)
assert UI.fmt_time(ts_today, now) == "21:03" and UI.fmt_time(ts_old, now) == "10/18 09:05"
ok("pair dialog flows (make code, friend joins, link phone, join, error, unpair)")

mw = UI.MessagesWindow(fc)
mw.show_window(focus_reply=True)
html_out = mw.view.setHtml.call_args[0][0]
assert "hi &lt;b&gt;" in html_out and 'align="right"' in html_out and "Amy" in html_out
mw.edit.setText("  see you  "); mw.send()
assert fc.calls[-1] == ("send", ("see you",)) and mw.items[-1]["text"] == "see you" and mw.edit.text() == ""
mw.add({"id": "c", "mine": False, "name": "Amy", "text": "new!", "ts": 1}); mw.add({"id": "c", "mine": False, "name": "Amy", "text": "new!", "ts": 1})
assert [m["id"] for m in mw.items].count("c") == 1
ok("messages window (history, escape, send, no duplicates)")

# ---------------------------------------------------------------- 11. app._pump / 選單
from pet.app import PetApp
fake = MagicMock()
fake.pet = pet
fake.msg_win = mw
fake.pair_dlg = None
mw._vis = True
events = [("message", msg(20, "from pump")), ("online", False), ("result", (lambda v, e: changes.append(("cb", v)), 5, None)),
          ("unpaired", None)]
fake.cloud.drain.return_value = events
pet._set_state("idle", 50)
PetApp._pump(fake)
assert pet.msg_queue == deque() or True
assert ("cb", 5) in changes and fake.cloud_online is False and mw.items[-1]["text"] == "from pump"
assert not pet.msg_queue                     # unpaired 清掉了
menu = MagicMock()
fake.cloud = FakeCloud(); fake.cloud.paired = False
PetApp._msg_actions(fake, menu); assert "Pair with a friend..." in str(menu.addAction.call_args_list)
fake.cloud.paired = True; fake.cloud.partner_name = "Amy"
menu = MagicMock(); PetApp._msg_actions(fake, menu)
assert "Messages with Amy..." in str(menu.addAction.call_args_list) and "Reply" not in str(menu.addAction.call_args_list)
fake.cloud = None; menu = MagicMock(); PetApp._msg_actions(fake, menu); assert not menu.addAction.called
ok("app pump + menus")

print("ALL PET MESSAGE TESTS PASSED")
