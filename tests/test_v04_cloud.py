"""v0.4.2 cloud.py 測試：用本機假 Firebase（tests/fake_firebase.py）跑「家 + 聊天室」：
連手機的碼、邀請朋友、輸入碼、收發、已讀、重開、測試聊天室、待辦 / 設定同步、改名、離開、token 過期、全部重來。
    python tests/test_v04_cloud.py
"""
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from fake_firebase import FakeFirebase                     # noqa: E402
from pet import cloud as C                                 # noqa: E402

fb = FakeFirebase()
tmp = Path(tempfile.mkdtemp())
cfg = {"apiKey": "KEY", "databaseURL": fb.url}
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 不要走 proxy
clients = []


def client(name: str) -> C.CloudClient:
    c = C.CloudClient(cfg, tmp / f"{name}.json", auth_base=fb.url + "/v1", token_base=fb.url + "/v1",
                      opener=opener)
    clients.append(c)
    return c


def wait_event(c: C.CloudClient, kind: str, timeout: float = 8.0, pred=lambda v: True):
    """等某種事件；沒處理到的事件留給下一次。call() 的結果會順便呼叫 callback。"""
    end = time.time() + timeout
    seen = []
    backlog = c.__dict__.setdefault("_backlog", [])
    while time.time() < end:
        batch = backlog[:] + c.drain()
        backlog.clear()
        for i, (k, v) in enumerate(batch):
            seen.append(k)
            if k == "result":
                cb, value, err = v
                if cb:
                    cb(value, err)
            if k == kind and pred(v):
                backlog.extend(batch[i + 1:])
                return v
        time.sleep(0.05)
    raise AssertionError(f"no {kind} event (got {seen})")


def ok(msg):
    print("ok -", msg)


# ---------------------------------------------------------------- 工具函式
assert C.clean_text("  hi   there\n friend ") == "hi there friend"
assert len(C.clean_text("x" * 100)) == C.MAX_TEXT and len(C.clean_text("x" * 100, C.MAX_TODO)) == 40
assert C.other_slot("a") == "b" and C.other_slot("b") == "a"
p = C.SSEParser()
assert p.feed("event: put\n") is None and p.feed('data: {"path":"/"}\n') is None
assert p.feed("\n") == ("put", '{"path":"/"}')
t = C.apply_patch({}, "/", {"a": 1, "todo": {"x": {"text": "hi"}}})
t = C.apply_patch(t, "/todo/y", {"text": "yo"})
t = C.apply_patch(t, "/todo/x", None)
t = C.apply_patch(t, "/settings", {"focus_min": 30}, merge=True)
t = C.apply_patch(t, "/", {"b": 2}, merge=True)
assert t == {"a": 1, "b": 2, "todo": {"y": {"text": "yo"}}, "settings": {"focus_min": 30}}, t
ok("helpers, SSE parser, apply_patch")

# ---------------------------------------------------------------- 舊的 v0.4.1 存檔 → 只留登入身分
old = tmp / "old.json"
old.write_text(json.dumps({"uid": "u1", "refresh": "r1", "room": "R", "slot": "a", "my_name": "Evan"}))
st = C.CloudState(old)
assert st.old_pairing and st["uid"] == "u1" and st["home"] == "" and st["name"] == "Evan"
ok("old v0.4.1 save file -> keeps sign-in, drops the old pairing")

# ---------------------------------------------------------------- 家 + 連手機
A = client("A")
assert not A.linked
try:
    A.link_code("")
    raise AssertionError("no name accepted")
except C.CloudError:
    pass
r = A.link_code("Evan")
code = r["code"]
assert A.linked and fb.get(f"codes/{code}")["kind"] == "home" and fb.get(f"codes/{code}")["target"] == A.state["home"]
assert fb.get(f"homes/{A.state['home']}/name") == "Evan"
assert fb.get(f"homes/{A.state['home']}/members/{A.state['uid']}")["kind"] == "pet"
wait_event(A, "online", pred=lambda v: v)
ok(f"link my phone: home created, home code {code}")

# 手機加入家（模擬手機：直接寫資料）
fb.set(f"homes/{A.state['home']}/members/phoneUid", {"kind": "phone", "joined": 1, "code": code})
wait_event(A, "home", pred=lambda v: v["phones"] == 1)
ok("phone joins the home -> dog sees 1 phone")

# ---------------------------------------------------------------- 邀請朋友
inv = A.invite_code()
assert fb.get(f"codes/{inv['code']}")["kind"] == "room" and fb.get(f"codes/{inv['code']}")["slot"] == "b"
assert A.invite_code()["room"] == inv["room"]          # 朋友還沒加入：同一個聊天室再給一個碼
assert A.rooms() == []                                  # 還沒朋友 → 不算聊天室
B = client("B")
try:
    B.join(code, "Amy")
    raise AssertionError("home code accepted on a dog")
except C.CloudError as e:
    assert "phone" in str(e)
try:
    B.join("000000" if inv["code"] != "000000" else "111111", "Amy")
    raise AssertionError("wrong code accepted")
except C.CloudError as e:
    assert "doesn't work" in str(e)
res = B.join(inv["code"], "Amy")
assert res["partner"] == "Evan" and B.linked and B.state["home"] != A.state["home"]
assert fb.get(f"rooms/{inv['room']}/slots/b")["home"] == B.state["home"]
assert fb.get(f"homes/{B.state['home']}/rooms/{inv['room']}") == "b"
try:
    B.join(inv["code"], "Amy")
    raise AssertionError("joined twice")
except C.CloudError as e:
    assert "already" in str(e)
A.refresh_names()
assert A.rooms() == [{"id": inv["room"], "partner": "Amy", "test": False}]
assert B.rooms() == [{"id": inv["room"], "partner": "Evan", "test": False}]
ok("invite a friend -> friend's dog joins with the code (gets its own home)")

# ---------------------------------------------------------------- 收發
rid = inv["room"]
time.sleep(0.5)
B.send(rid, "  Hi   Evan!  ")
m = wait_event(A, "message")
assert m["text"] == "Hi Evan!" and m["name"] == "Amy" and m["room"] == rid and not m["mine"]
time.sleep(0.3)
assert fb.get(f"rooms/{rid}/status/a")["delivered"] == m["ts"]
A.send(rid, "Hey Amy")
m2 = wait_event(B, "message")
assert m2["text"] == "Hey Amy" and m2["name"] == "Evan"
time.sleep(0.4)
assert not [e for e in A.drain() if e[0] == "message"]          # 自己傳的不會回來
try:
    A.send(rid, "   ")
    raise AssertionError
except C.CloudError:
    pass
A.send(rid, "y" * 80)
assert len(wait_event(B, "message")["text"]) == 60
A.mark_seen(rid, m["ts"])
time.sleep(0.5)
assert fb.get(f"rooms/{rid}/status/a")["seen"] == m["ts"]
ok("messages both ways, delivered + seen, 60 chars")

# 狗關著時傳的兩則，重開後只補沒看過的
B.send(rid, "one")
B.send(rid, "two")
assert [wait_event(A, "message")["text"], wait_event(A, "message")["text"]] == ["one", "two"]
A.stop()
t_one = [v for v in fb.get(f"rooms/{rid}/messages").values() if v["text"] == "one"][0]["ts"]
A2 = client("A")
A2.mark_seen(rid, t_one)
texts = []
end = time.time() + 6
while time.time() < end and "two" not in texts:
    for k, v in A2.drain():
        if k == "message":
            texts.append(v["text"])
    time.sleep(0.05)
assert texts == ["two"], texts
assert A2.state["uid"] == A.state["uid"] and A2.state["home"] == A.state["home"]
h = A2.history(rid)
assert [x["text"] for x in h][-3:] == ["y" * 60, "one", "two"] and any(x["mine"] for x in h)
ok("restart: same home, only unseen messages come back; history")

# ---------------------------------------------------------------- 測試聊天室（手機假裝朋友）
tc = A2.test_chat()
trid = tc["room"]
assert fb.get(f"rooms/{trid}/slots/a")["home"] == A2.state["home"] == fb.get(f"rooms/{trid}/slots/b")["home"]
assert fb.get(f"homes/{A2.state['home']}/rooms/{trid}") == "ab"
assert A2.test_chat()["room"] == trid                         # 只會有一個
assert {"id": trid, "partner": "Test phone", "test": True} in A2.rooms()
time.sleep(0.5)
fb.set(f"rooms/{trid}/messages/-Ntest1", {"from": "b", "text": "from my phone", "ts": int(time.time() * 1000), "via": "phone"})
mt = wait_event(A2, "message", pred=lambda v: v["room"] == trid)
assert mt["text"] == "from my phone" and mt["name"] == "Test phone"
ok("test chat: phone (slot b) -> own dog")

# ---------------------------------------------------------------- 待辦、設定同步
A2.todo_upload([{"id": "t1", "text": "Calculus", "done": False, "ts": 1}], "2026-10-19")
ev = wait_event(A2, "todo", pred=lambda v: "t1" in v["items"] and v["date"])
assert ev["date"] == "2026-10-19"
fb.set(f"homes/{A2.state['home']}/todo/t2", {"text": "From phone", "done": False, "ts": 2, "by": "phone"})
ev = wait_event(A2, "todo", pred=lambda v: "t2" in v["items"])
assert ev["items"]["t2"]["by"] == "phone"
A2.todo_put({"id": "t1", "text": "Calculus", "done": True, "ts": 1})
assert fb.get(f"homes/{A2.state['home']}/todo/t1")["done"] is True
A2.todo_rollover(["t1"], "2026-10-20")
assert fb.get(f"homes/{A2.state['home']}/todo/t1") is None and fb.get(f"homes/{A2.state['home']}/todo_date") == "2026-10-20"
A2.todo_remove("t2")
assert not fb.get(f"homes/{A2.state['home']}/todo")
A2.settings_put({"wake_time": "07:30", "focus_min": 30, "break_min": 5, "junk": 1})
assert fb.get(f"homes/{A2.state['home']}/settings") == {"wake_time": "07:30", "focus_min": 30, "break_min": 5}
fb.set(f"homes/{A2.state['home']}/settings/focus_min", 45)
assert wait_event(A2, "settings", pred=lambda v: v.get("focus_min") == 45)["wake_time"] == "07:30"
ok("to-do + settings sync both ways (phone edits arrive as events)")

# ---------------------------------------------------------------- 手機在家裡加了朋友 → 狗也跟著有這個聊天室
Cdog = client("Cdog")
inv_c = Cdog.invite_code("Cara")
fb.set(f"rooms/{inv_c['room']}/slots/b", {"home": A2.state["home"], "code": inv_c["code"]})
fb.set(f"rooms/{inv_c['room']}/names/b", "Evan")
fb.set(f"homes/{A2.state['home']}/rooms/{inv_c['room']}", "b")
rooms_ev = wait_event(A2, "rooms", pred=lambda v: any(x["id"] == inv_c["room"] for x in v))
assert any(x["partner"] == "Cara" for x in rooms_ev), rooms_ev
time.sleep(0.5)
Cdog.send(inv_c["room"], "hi from Cara")
mc = wait_event(A2, "message", pred=lambda v: v["room"] == inv_c["room"])
assert mc["name"] == "Cara"
ok("phone adds a friend -> the dog gets that chat too (multiple chats)")

# ---------------------------------------------------------------- token 過期
fb.expire_all = True
time.sleep(1.5)
A2.token_exp = 0
B.send(rid, "after expiry")
assert wait_event(A2, "message", timeout=12, pred=lambda v: v["room"] == rid)["text"] == "after expiry"
ok("token expiry: auth_revoked -> refresh -> keeps streaming")

# ---------------------------------------------------------------- 改名、心跳
B.set_my_name("Amy B")
assert fb.get(f"homes/{B.state['home']}/name") == "Amy B" and fb.get(f"rooms/{rid}/names/b") == "Amy B"
A2.refresh_names()
assert any(x["partner"] == "Amy B" for x in A2.rooms())
time.sleep(0.5)
assert fb.get(f"rooms/{rid}/status/a").get("pet")
ok("rename everywhere, heartbeat")

# ---------------------------------------------------------------- 離開聊天室、手機的移出、全部重來
B.leave_room(rid)
assert fb.get(f"rooms/{rid}/slots/b") is None and fb.get(f"homes/{B.state['home']}/rooms/{rid}") is None
assert fb.get(f"rooms/{rid}/names/b") is None                     # 名字也拿掉了
assert B.rooms() == []
try:
    B.send(rid, "x")
    raise AssertionError
except C.CloudError:
    pass
assert A2.unlink_phones() == 1
A2.reset()
wait_event(A2, "reset")
assert not A2.linked and A2.rooms() == []
ok("leave a chat, unlink phones, start over")

# 家被別處刪掉 → reset
fb.set(f"homes/{Cdog.state['home']}/members/{Cdog.state['uid']}", None)
Cdog._check_home()
assert not Cdog.linked
ok("removed from home elsewhere -> reset")

# ---------------------------------------------------------------- call() 背景執行 + callback
D = client("D")
box = {}
D.call(D.link_code, "Zed", callback=lambda v, e: box.update(v=v, e=e))
wait_event(D, "result")
assert box["v"] and len(box["v"]["code"]) == 6 and box["e"] is None
D.call(D.join, "12", "x", callback=lambda v, e: box.update(err=e))
wait_event(D, "result")
assert box["err"] == "The code has 6 numbers"
ok("call() results come back with callbacks")

for c in clients:
    c.stop()
fb.close()
print("ALL CLOUD TESTS PASSED")
