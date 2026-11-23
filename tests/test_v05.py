"""v0.5 測試（假 PySide6）：大便（稀有度、計時、最多 10 坨）、掃把、零食碗、新動畫有圖 / 沒圖的切換。
    python tests/test_v05.py
"""
import random
import sys, tempfile, time as _time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fakeqt"))
PROJ = HERE.parent
sys.path.insert(0, str(PROJ))

clock = [1000.0]
_time.monotonic = lambda: clock[0]

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QCursor
from unittest.mock import MagicMock


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
        self.optional = set()
        self.used = []
    def has(self, name): return name in self.optional
    def frame(self, name, d, t, flip=False):
        self.used.append(name); return Pix(hash((name, d)) % 1000)
    def frame_at(self, name, d, i, flip=False):
        self.used.append(name); return Pix(5000 + i)
    def shadow(self, *a): return None
    def held_grab(self, t, flip=False): return (0.5, 0.2)


from pet.settings import Settings
from pet import pet_window as PW
from pet import poop_rules as R
from pet import yard as Y
from pet.pet_window import PetWindow
from pet.todo import TodoStore
from pet.todo_window import TodoWindow
from pet.pomodoro import TomatoWindow

tmp = Path(tempfile.mkdtemp())
settings = Settings(tmp / "settings.json")
sprites = Sprites()
pet = PetWindow(sprites, settings)
tw = TodoWindow(TodoStore(tmp / "todo.json"), 160)
pet.attach_todo(tw)
pet.attach_pomodoro(TomatoWindow(PROJ / "assets", 160), MagicMock())
pet.attach_messages(MagicMock())
yard = pet.yard
S = 160
QCursor.setPos(QPoint(5, 5))


def step(sec=0.016):
    clock[0] += sec
    pet._tick()
    if pet.broom_timer.isActive(): pet._tick_broom()
    if tw._anim.isActive(): tw._anim_step()


def run_until(cond, limit=30.0, dt=0.016):
    t = 0.0
    while not cond():
        step(dt); t += dt
        assert t < limit, f"timeout, state={pet.state}"
    return t


def ok(s): print("ok -", s)


# ---------------------------------------------------------------- 1. 規則
rng = random.Random(7)
counts = {k: 0 for k in R.RARITY_KEYS}
for _ in range(20000):
    counts[R.roll_rarity(rng)] += 1
assert counts["common"] > counts["uncommon"] > counts["rare"] > counts["epic"] > counts["legendary"] > 0, counts
assert abs(counts["common"] / 20000 - 0.60) < 0.02 and abs(counts["legendary"] / 20000 - 0.01) < 0.005, counts
c = R.PoopClock(None, rng)
assert R.POOP_MIN_SEC <= c.remaining <= R.POOP_MAX_SEC
c.remaining = 2400.0
c.fed(); assert c.remaining == 1200.0
for _ in range(10): c.fed()
assert c.remaining == R.FED_MIN_SEC, c.remaining          # 吃再多至少還要等 60 秒
c.tick(59.0); assert not c.due
c.tick(2.0); assert c.due
assert R.PoopClock(123.0).remaining == 123.0 and R.PoopClock("x").remaining >= R.POOP_MIN_SEC
assert R.PoopClock(99999).remaining <= R.POOP_MAX_SEC      # 設定檔裡的怪數字 → 重新抽
ok(f"rarity weights {counts}, clock 30-60 min, treats halve the wait (min 60 s)")

# ---------------------------------------------------------------- 2. 時間到 → 蹲下 → 桌面上多一坨
assert R.POOP_MIN_SEC <= yard.clock.remaining <= R.POOP_MAX_SEC and not yard.poops
pet.gx, pet.gy = 600.0, 500.0
pet.facing_left = False
pet._set_state("idle", 50)
step(); assert pet.state == "idle"
yard.clock.remaining = 0.5
run_until(lambda: pet.state == "poop", limit=2.0)
assert pet.anim == "sit"                                   # 還沒有 poop 的圖：用 sit 湊
t = run_until(lambda: pet.state != "poop", limit=5.0)
assert abs(t - PW.POOP_SEC) < 0.1, t
assert len(yard.poops) == 1 and pet.state == "walk"
p = yard.poops[0]
assert abs(p.cx - (600.0 - PW.POOP_BEHIND * S)) < 1 and p.cy == 500.0 and p.isVisible()   # 在屁股後面（面向右 → 左邊）
assert R.POOP_MIN_SEC <= yard.clock.remaining <= R.POOP_MAX_SEC                           # 重新倒數 30~60 分鐘
assert settings.data["poops"] == [[round(p.cx), 500, p.rarity]]
assert settings.data["poop_log"]["made"] == {p.rarity: 1}
ok(f"due -> squat {t:.1f}s -> a {p.rarity} poop behind the dog, timer rerolled, saved to settings")

# 重開：桌面上的大便和倒數都還在
again = Y.Yard(PROJ / "assets", S, Settings(tmp / "settings.json"))
assert len(again.poops) == 1 and again.poops[0].rarity == p.rarity
assert abs(again.clock.remaining - yard.clock.remaining) < 0.2
for w in again.poops: w.hide()
ok("poops and the countdown survive a restart")

# ---------------------------------------------------------------- 3. 不方便的時候先憋著；最多 10 坨
pet._set_state("idle", 500)
yard.clock.remaining = 0.0
pet._start_list("pull")
for _ in range(20): step()
assert pet.busy and pet.state != "poop"
run_until(lambda: not pet.busy)
run_until(lambda: pet.state == "poop", limit=20.0)         # 搬完清單才去
run_until(lambda: pet.state != "poop", limit=5.0)
assert len(yard.poops) == 2
pet._set_state("idle", 500)
pet.start_pomodoro()
run_until(lambda: pet.state == "pomo_sit")
yard.clock.remaining = 0.0
for _ in range(200): step()
assert pet.state == "pomo_sit" and len(yard.poops) == 2    # 番茄鐘中不大便
pet.stop_pomodoro(quiet=True)
pet._set_state("idle", 500)
run_until(lambda: len(yard.poops) == 3, limit=20.0)
ok("waits while carrying the list / during a pomodoro, then goes")

pet.stay = True
for i in range(20):
    pet._set_state("idle", 500)
    yard.clock.remaining = 0.0
    for _ in range(int((PW.POOP_SEC + 0.3) / 0.016)): step()
assert len(yard.live_poops) == R.POOP_MAX == 10, len(yard.live_poops)
assert yard.full and yard.clock.due and pet.state != "poop"   # 滿了：憋著
said = []
pet.say = lambda text, *a, **k: said.append(text)
pet._set_state("idle", 500)
pet.start_poop()
assert pet.state == "idle" and said[-1] == "Too messy! Sweep first!"
assert sum(settings.data["poop_log"]["made"].values()) == 10
pet.stay = False
ok("never more than 10 on the desktop; the dog holds it until you sweep")

# ---------------------------------------------------------------- 4. 掃把：跟著游標，一次掃很多
for i, w in enumerate(yard.poops):                         # 排成一排
    w.place(300.0 + i * 60, 700.0)
yard.clock.remaining = 3000.0
pet.gx, pet.gy = 1500.0, 300.0
pet._set_state("idle", 500)
pet.toggle_broom()
assert yard.broom_on and yard.broom.isVisible() and said[-1] == "Sweep sweep!"
# 游標握在掃把中間：刷頭在游標下面，所以游標要比大便高一點
hdx = yard.broom.head[0] - yard.broom.grip[0]; hdy = yard.broom.head[1] - yard.broom.grip[1]
assert hdy > 20, (yard.broom.grip, yard.broom.head)
gy = int(690 - hdy)
QCursor.setPos(QPoint(100, gy))
for _ in range(60): step()                                 # 停著不動：掃把回正
assert len(yard.live_poops) == 10                          # 還沒碰到
hx, hy = yard.broom.head_at(100, gy); assert abs(hy - 690) < 3 and abs(hx - (100 + hdx)) < 3   # 沒在動：刷頭在正下方
x = 100
while x < 900:                                             # 掃把從左掃到右
    x += 25
    QCursor.setPos(QPoint(x, gy)); step()
assert yard.broom.angle > 5                                # 往右拖：刷頭落在後面（往左歪）
assert not yard.live_poops, len(yard.live_poops)
assert sum(settings.data["poop_log"]["swept"].values()) == 10
assert "All clean! Thanks!" in said
assert settings.data["poops"] == []
run_until(lambda: not yard.poops, limit=1.0)               # 掃掉的動畫播完，視窗收掉
run_until(lambda: not yard.broom_on, limit=3.0)            # 全部掃完：掃把自己收起來
assert not yard.broom.isVisible()
pet.toggle_broom()
assert not yard.broom_on and said[-1] == "Nothing to sweep!"
ok("broom follows the cursor and sweeps 10 poops in one pass, logs them, then puts itself away")

yard.add_poop(400.0, 400.0, "legendary")
pet.toggle_broom(); assert yard.broom_on
QCursor.setPos(QPoint(1700, 900))
for _ in range(int(Y.BROOM_IDLE_SEC / 0.05) + 5): step(0.05)
assert not yard.broom_on and len(yard.live_poops) == 1     # 20 秒沒掃到東西：自己收起來
ok("broom puts itself away after 20 s of not sweeping")

# ---------------------------------------------------------------- 5. 零食碗
pet.gx, pet.gy = 600.0, 500.0
pet.facing_left = False
pet._set_state("idle", 500)
yard.clock.remaining = 2000.0
pet.start_treat()
assert yard.bowl.isVisible() and yard.bowl_full and pet.state == "treat_go"
assert abs(yard.bowl.cx - (600.0 + PW.TREAT_DIST * S)) < 1 and yard.bowl.cy == 500.0
run_until(lambda: pet.state == "eat", limit=5.0)
assert abs(pet.gx - (yard.bowl.cx - PW.EAT_REACH * S)) < 4 and not pet.facing_left   # 鼻子對著碗
assert pet.anim == "idle"                                  # 還沒有 eat 的圖
run_until(lambda: pet.state == "happy", limit=5.0)
assert not yard.bowl_full and abs(yard.clock.remaining - 1000.0) < 10               # 吃了：剩下的時間減半
run_until(lambda: not yard.bowl.isVisible(), limit=3.0)
ok("treat bowl: placed in front, dog runs over, eats, bowl disappears, next poop comes twice as fast")

pet._set_state("idle", 500)                                # 靠右邊牆：碗放另一邊
pet.gx = pet._ground_rect(pet._screen_here()).right() - 10
pet.facing_left = False
pet.start_treat()
assert yard.bowl.cx < pet.gx
pet._set_state("held"); step()                             # 吃到一半被拎走
pet.lift_v = 0.0; pet._set_state("drop", anim="held")
run_until(lambda: pet.state == "eat", limit=15.0)          # 放下後自己回去吃
run_until(lambda: pet.state == "happy", limit=5.0)
ok("bowl flips to the other side at the screen edge; a picked-up dog goes back to finish the treat")

pet._set_state("idle", 500)
pet.start_pomodoro()
run_until(lambda: pet.state == "pomo_sit")
pet.start_treat()
assert pet.state == "pomo_sit" and not yard.bowl_full and said[-1] == "Shh... focusing"
pet.stop_pomodoro(quiet=True)
ok("no treats while focusing")

# ---------------------------------------------------------------- 6. 新動畫：有圖就用，沒圖照舊
states = {}
def watch_pull():
    states.setdefault(pet.state, pet.anim); return not pet.busy

pet._set_state("idle", 500); pet.gx, pet.gy = 600.0, 500.0
QCursor.setPos(QPoint(1700, 100))
pet._start_list("pull"); run_until(watch_pull)
assert states["list_bite"] == "run" and states["list_tug"] == "run", states
states.clear()
pet._start_list("push"); run_until(watch_pull)
assert states["list_nudge"] == "run" and states["list_push"] == "run", states
states.clear()

for name, n in (("tug", 4), ("push", 4)):
    sprites.frames[(name, "front")] = [Pix(9000 + i) for i in range(n)]
sprites.optional = {"tug", "push", "bark", "carry", "startle", "study", "snore", "eat", "poop", "dizzy", "spin", "sniff"}
pet._set_state("idle", 500)
pet._start_list("pull"); run_until(watch_pull)
assert states["list_bite"] == "tug" and states["list_tug"] == "tug" and tw.is_open, states
states.clear()
pet._start_list("push"); run_until(watch_pull)
assert states["list_nudge"] == "push" and states["list_push"] == "push" and not tw.is_open, states
pet._set_state("idle", 500); pet.sleep(); assert pet.state == "sleep" and pet.anim == "snore"
pet._set_state("idle", 500); pet.dizzy(); assert pet.anim == "dizzy"
pet._set_state("idle", 500); pet.startle(); assert pet.state == "hop" and pet.anim == "startle" and pet.frame_lock is None
run_until(lambda: pet.state == "sit")
pet._set_state("idle", 500); pet.start_sniff(); assert pet.anim == "sniff"
pet._set_state("idle", 500); pet.start_spin(); assert pet.anim == "spin"
run_until(lambda: pet.state != "spin", limit=5.0)
pet._set_state("idle", 500); pet.start_poop(); assert pet.anim == "poop"
run_until(lambda: pet.state != "poop", limit=5.0)
pet._set_state("idle", 500); pet.start_treat()
run_until(lambda: pet.state == "eat", limit=8.0); assert pet.anim == "eat"
run_until(lambda: pet.state == "happy", limit=5.0)
pet._set_state("idle", 500); pet.start_pomodoro(); run_until(lambda: pet.state == "pomo_sit"); assert pet.anim == "study"
pet.stop_pomodoro(quiet=True)
pet._set_state("idle", 500); pet._msg_bark(); assert pet.anim == "bark"
ok("each new animation is used as soon as its art exists; without art the old stand-ins still play")

# ---------------------------------------------------------------- 7. 零食稀有度 + 效果
sprites.optional = set()
b = R.Buffs()
b.add("run", "rare"); assert b.value("run") == 1.45 and b.active["run"][1] == 15 * 60
b.add("run", "common"); assert b.active["run"][0] == "rare"                  # 比較不稀有：不變
b.add("run", "legendary"); assert b.value("run") == 2.0 and b.active["run"][1] == 30 * 60
b.tick(30 * 60 + 1); assert b.value("run") == 1.0 and b.top() is None
b.add("luck", "epic"); b.add("poop", "uncommon"); assert b.top() == "epic"
assert R.Buffs(b.to_json()).active == b.active and R.Buffs({"run": ["rare", 99999], "x": ["rare", 5]}).active == {}
rng = random.Random(1)
lucky = sum(R.roll_rarity(rng, luck=6.0) != "common" for _ in range(20000)) / 20000
assert lucky > 0.75, lucky                                                   # 平常 40%，雞腿 Legendary ×6 → 80%
ok(f"buffs: stronger replaces, same refreshes, weaker ignored, expire, saved; luck x6 -> {lucky:.0%} non-common")

def eat(treat_key, rarity):
    pet._set_state("idle", 500); pet.gx, pet.gy = 600.0, 500.0; pet.facing_left = False
    yard.bowl.hide(); yard.bowl.full = False
    pet.start_treat()
    yard.bowl.fill(treat_key, rarity)                                        # 固定零食和稀有度來測
    run_until(lambda: pet.state == "happy", limit=12.0)

yard.buffs = R.Buffs()
eat("treat_03", "rare")                                                      # 飼料：大便倒數走 2.5 倍快
assert yard.buffs.active["poop"][0] == "rare" and "Uh oh..." in said
r0 = yard.clock.remaining = 1000.0
for _ in range(10): step(0.1)
assert abs((r0 - yard.clock.remaining) - 2.5) < 0.05, r0 - yard.clock.remaining
eat("treat_01", "legendary")                                                 # 骨頭：跑 2 倍快
assert yard.buffs.value("run") == 2.0 and yard.buffs.top() == "legendary"
pet._set_state("idle", 500); pet.gx, pet.gy = 300.0, 500.0
x0 = pet.gx; pet._move_toward(900.0, 500.0, 100.0, 0.1)
assert abs((pet.gx - x0) - 100.0 * 2.0 * pet.k * 0.1) < 0.01
eat("treat_02", "epic")                                                      # 雞腿：稀有大便
assert yard.buffs.value("luck") == 4.0
assert settings.data["buffs"]["run"][0] == "legendary" and set(settings.data["buffs"]) == {"run", "poop", "luck"}
again = Y.Yard(PROJ / "assets", S, Settings(tmp / "settings.json"))
assert set(again.buffs.active) == {"run", "poop", "luck"}
for w in again.poops: w.hide()
ok("kibble = poop clock x2.5 (rare), bone = run x2 (legendary), drumstick = luck x4 (epic); buffs survive a restart")

print("\nALL v0.5 TESTS PASSED")
