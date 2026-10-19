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


def msg(i, text="Hi Evan!", name="Amy", room="r1"):
    return {"room": room, "id": f"m{i}", "from": "b", "name": name, "text": text, "ts": 1000 + i, "via": "phone",
            "mine": False}


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
        self.linked = False
        self.my_name = ""
        self.old_pairing = False
        self._rooms = []                 # [{"id","partner","test"}]
        self._phones = 0
        self.calls = []
        self.fail = None
        self.home_data = {}
        self.sent = []
    paired = property(lambda self: self.linked)
    def rooms(self): return list(self._rooms)
    def phones(self): return self._phones
    def partner_of(self, rid): return next((r["partner"] for r in self._rooms if r["id"] == rid), "Friend")
    def call(self, fn, *args, callback=None):
        self.calls.append((fn.__name__, args))
        if self.fail:
            callback and callback(None, self.fail); return
        v = fn(*args)
        if callback:
            callback(v, None)
    def _home(self, name):
        if not self.linked:
            self.linked = True; self.my_name = name
    def link_code(self, name=""): self._home(name); return {"code": "111111"}
    def invite_code(self, name=""): self._home(name); return {"code": "333333", "room": "rNew"}
    def test_chat(self, name=""):
        self._home(name)
        if not any(r["test"] for r in self._rooms):
            self._rooms.append({"id": "rTest", "partner": "Test phone", "test": True})
        return {"room": "rTest"}
    def join(self, code, name=""):
        self._home(name); self._rooms.append({"id": "rJ", "partner": "Evan", "test": False})
        return {"room": "rJ", "partner": "Evan"}
    def refresh_names(self): return {"rooms": self.rooms()}
    def set_my_name(self, n): self.my_name = n
    def unlink_phones(self): n = self._phones; self._phones = 0; return n
    def leave_room(self, rid): self._rooms = [r for r in self._rooms if r["id"] != rid]
    def reset(self): self.linked = False; self._rooms = []; self._phones = 0
    def history(self, rid):
        return [{"room": rid, "id": "a", "mine": False, "name": "Amy", "text": "hi <b>", "ts": 1760000000000},
                {"room": rid, "id": "b", "mine": True, "name": "Me", "text": "yo", "ts": 1760000060000}]
    def send(self, rid, t): self.sent.append((rid, t)); return {"id": "z", "text": t, "room": rid}
    def mark_seen(self, rid, ts): self.calls.append(("mark_seen", (rid, ts)))
    def todo_put(self, it): pass
    def todo_remove(self, i): pass
    def todo_rollover(self, ids, d): pass
    def todo_upload(self, items, d): pass
    def settings_put(self, s): pass


def status_text(d):
    """假的 QLabel 全部是同一個 MagicMock → 看最近幾次 setText。"""
    return str(d.status.setText.call_args_list[-4:])


fc = FakeCloud()
changes = []
dlg = UI.PairDialog(fc, on_change=lambda: changes.append(1))
dlg._vis = True
# 📱 連手機：沒有家 → 先問名字
dlg.open_mode("link")
dlg.name.setText(""); dlg._go(); assert "name first" in status_text(dlg)
dlg.name.setText("Evan"); dlg._go()
assert fc.calls[-1] == ("link_code", ("Evan",)) and dlg.code == "111111" and dlg.waiting == "phone"
fc._phones = 1; dlg._tick()
assert "phone is linked" in status_text(dlg) and not dlg.waiting
# 有家了：直接給碼
dlg.open_mode("link"); assert fc.calls[-1] == ("link_code", ("",)) and dlg.code == "111111"
# 💌 邀請朋友
dlg.open_mode("invite"); assert dlg.code == "333333" and dlg.waiting == "friend" and dlg.wait_room == "rNew"
fc._rooms.append({"id": "rNew", "partner": "Amy", "test": False})
for _ in range(3): dlg._tick()
assert "Amy joined" in status_text(dlg) and not dlg.waiting
# 🧪 測試聊天：手機已連 → 直接告訴他去手機開 Test phone
dlg.open_mode("test"); assert any(r["test"] for r in fc.rooms()) and "Ready" in status_text(dlg)
# 手機沒連 → 先給連手機的碼
fc._phones = 0; dlg.open_mode("test"); assert dlg.code == "111111" and dlg.waiting == "phone"
fc._phones = 1; dlg._tick(); assert "Test phone chat" in status_text(dlg)
# 🔑 輸入碼：已經有家也能用（不用名字）
dlg.open_mode("join"); dlg.code_in.setText("12"); dlg._join(); assert "6 numbers" in status_text(dlg)
dlg.code_in.setText("123456"); dlg._join(); assert fc.calls[-1][0] == "join" and fc.calls[-1][1][0] == "123456"
assert any(r["id"] == "rJ" for r in fc.rooms())
fc2 = FakeCloud(); dlg2 = UI.PairDialog(fc2); dlg2.open_mode("join")
dlg2.code_in.setText("123456"); dlg2.name.setText(""); dlg2._join(); assert "name too" in status_text(dlg2)
fc3 = FakeCloud(); fc3.fail = "That code doesn't work. Ask for a new one!"
dlg3 = UI.PairDialog(fc3); dlg3.open_mode("join"); dlg3.name.setText("x"); dlg3.code_in.setText("999999"); dlg3._join()
assert "doesn't work" in status_text(dlg3)
# ⚙ 設定：改名、離開聊天室、移除手機、全部重來
UI.QMessageBox.question.return_value = UI.QMessageBox.Yes
dlg.open_mode("settings"); dlg.name.setText("Ev"); dlg._save_name(); assert fc.my_name == "Ev"
dlg._leave("rJ"); assert not any(r["id"] == "rJ" for r in fc.rooms())
dlg._unlink(); assert fc.phones() == 0
dlg._start_over(); assert not fc.linked and fc.rooms() == []
# 碼過期提示
dlg.open_mode("invite"); dlg.name.setText("Evan"); dlg._go(); dlg.code_exp = UI._now() - 1; dlg._tick()
assert "expired" in str(dlg.count_lab.setText.call_args)
assert UI.fmt_code("123456") == "123 456"
now = datetime(2026, 10, 19, 22, 0)
ts_today = int(datetime(2026, 10, 19, 21, 3).timestamp() * 1000)
ts_old = int(datetime(2026, 10, 18, 9, 5).timestamp() * 1000)
assert UI.fmt_time(ts_today, now) == "21:03" and UI.fmt_time(ts_old, now) == "10/18 09:05"
ok("phone & friends window: link phone, invite, test chat, join (any time), settings, expiry")

# 訊息視窗：左邊聊天室列表
fc._rooms = [{"id": "r1", "partner": "Amy", "test": False}, {"id": "r2", "partner": "Ben", "test": False}]
mw = UI.MessagesWindow(fc)
mw.show_window()
assert mw.room == "r1" and ("history", ("r1",)) in fc.calls
html_out = mw.view.setHtml.call_args[0][0]
assert "hi &lt;b&gt;" in html_out and 'align="right"' in html_out
mw.add({"room": "r2", "id": "x", "mine": False, "name": "Ben", "text": "yo", "ts": 1})
assert mw.unread == {"r2": 1} and mw.room == "r1"
mw._picked(1); assert mw.room == "r2" and "r2" not in mw.unread
mw.edit.setText("  see you  "); mw.send()
assert fc.sent[-1] == ("r2", "see you") and mw.items[-1]["text"] == "see you"
mw.add({"room": "r2", "id": "c", "mine": False, "name": "Ben", "text": "new!", "ts": 1})
mw.add({"room": "r2", "id": "c", "mine": False, "name": "Ben", "text": "new!", "ts": 1})
assert [m["id"] for m in mw.items].count("c") == 1
mw.show_window(room="r1", focus_reply=True); assert mw.room == "r1"
fc._rooms = []; mw.refresh_rooms(); assert mw.room == ""
ok("messages window: chat list, unread dots, switch chats, send, no duplicates")

# ---------------------------------------------------------------- 11. 待辦同步（TodoStore）
from pet.todo import TodoStore as TS
ops = []
ts_store = TS(tmp / "todo_sync.json")
ts_store.on_change = lambda op, d: ops.append(op)
ts_store.add("Calculus"); ts_store.toggle(0); ts_store.remove(0)
assert ops == ["put", "put", "remove"]
ts_store.add("Keep me")
keep_id = ts_store.items[0]["id"]
newp = ts_store.apply_remote({keep_id: {"text": "Keep me", "done": False, "ts": 1, "by": "pet"},
                              "p1": {"text": "From phone", "done": False, "ts": 5, "by": "phone"}}, "2026-10-19")
assert [it["text"] for it in ts_store.items] == ["Keep me", "From phone"] and [it["text"] for it in newp] == ["From phone"]
assert ts_store.apply_remote({"p1": {"text": "From phone", "done": True, "ts": 5, "by": "phone"}}) == []
assert ops == ["put", "put", "remove", "put"]                     # 套用手機的不會再觸發 on_change
old_file = tmp / "todo_old.json"
old_file.write_text('{"date": "%s", "items": [{"text": "old", "done": false}]}' % ts_store.date)
assert TS(old_file).items[0]["id"]                                  # 舊格式補上 id
ok("todo store: ids, on_change, apply_remote (new phone items found)")

# ---------------------------------------------------------------- 12. app._pump / 選單
from pet.app import PetApp
fake = MagicMock()
fake.pet = pet
fake.msg_win = mw
fake.pair_dlg = None
fake._todo_synced = False
fake.settings = settings
fake.todo = TS(tmp / "todo_app.json")
fake.todo.add("Local task")
for _m in ("_todo_from_cloud", "_settings_from_cloud", "_push_settings", "_todo_changed", "_cloud_changed"):
    setattr(fake, _m, (lambda name: lambda *a: getattr(PetApp, name)(fake, *a))(_m))
mw._vis = True
fake.cloud = FakeCloud(); fake.cloud.linked = True
fake.cloud._rooms = [{"id": "r1", "partner": "Amy", "test": False}]
mw.cloud = fake.cloud; mw.refresh_rooms()
bubbles = []
pet.todo_from_phone = lambda text: bubbles.append(text)
events = [("message", msg(20, "from pump")), ("online", False),
          ("result", (lambda v, e: changes.append(("cb", v)), 5, None)),
          ("todo", {"items": {}, "date": ""})]
fake.cloud.drain = lambda: list(events)
pet._set_state("idle", 50)
PetApp._pump(fake)
assert ("cb", 5) in changes and fake.cloud_online is False and mw.items[-1]["text"] == "from pump"
assert fake._todo_synced and any(n == "todo_upload" for n, a in fake.cloud.calls)   # 雲端空的 → 把電腦上的傳上去
assert any(n == "settings_put" for n, a in fake.cloud.calls)                         # 時間設定也傳上去
events[:] = [("todo", {"items": {"x1": {"text": "Buy milk", "done": False, "ts": 9, "by": "phone"}}, "date": fake.todo.date}),
             ("settings", {"wake_time": "07:45", "focus_min": 30, "break_min": 5})]
PetApp._pump(fake)
assert [it["text"] for it in fake.todo.items] == ["Buy milk"] and bubbles == ["Buy milk"]
assert settings.get("wake_time") == "07:45" and settings.get("focus_min") == 30
events[:] = [("reset", None)]
pet.on_message(msg(30)); PetApp._pump(fake)
assert not pet.msg_queue and not fake._todo_synced                 # reset 清掉

def labels(m):
    out = [str(c.args[0]) for c in m.addAction.call_args_list]
    sub = m.addMenu.return_value
    return out + [str(c.args[0]) for c in sub.addAction.call_args_list]
fake.cloud = FakeCloud()
menu = MagicMock(); PetApp._msg_actions(fake, menu); L = labels(menu)
assert {"📱 Link my phone...", "💌 Invite a friend...", "🔑 I have a code...", "🧪 Test chat..."} <= set(L), L
assert "💌 Messages..." not in L and "⚙ Settings..." not in L
fake.cloud.linked = True; fake.cloud._phones = 1
fake.cloud._rooms = [{"id": "r1", "partner": "Amy", "test": False}, {"id": "rT", "partner": "Test phone", "test": True}]
menu = MagicMock(); PetApp._msg_actions(fake, menu); L = labels(menu)
assert "💌 Messages..." in L and "Phones: 1 · Friends: 1" in L and "⚙ Settings..." in L and "🔑 I have a code..." in L
assert not any("Reply" in x for x in L)
fake.cloud = None; menu = MagicMock(); PetApp._msg_actions(fake, menu); assert not menu.addAction.called and not menu.addMenu.called
ok("app pump (messages, to-do first upload + phone items -> bubble, settings, reset) + menus")

# 手機加的待辦：狗冒泡泡（真的那個方法）
pet2 = PetWindow(Sprites(), settings)
pet2._set_state("idle", 50)
pet2.todo_from_phone("Buy milk")
assert pet2.bubble.text == "New task: Buy milk"
ok("dog bubble for a to-do added on the phone")

print("ALL PET MESSAGE TESTS PASSED")
