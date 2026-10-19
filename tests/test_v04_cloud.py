"""v0.4 cloud.py 測試：用本機假 Firebase（tests/fake_firebase.py）跑配對、收發、已讀、重開、token 過期、解除配對。
    python tests/test_v04_cloud.py
"""
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


def client(name: str) -> C.CloudClient:
    return C.CloudClient(cfg, tmp / f"{name}.json", auth_base=fb.url + "/v1", token_base=fb.url + "/v1",
                         opener=opener)


def wait_event(c: C.CloudClient, kind: str, timeout: float = 8.0, pred=lambda v: True):
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
                backlog.extend(batch[i + 1:])     # 沒處理到的留給下一次
                return v
        time.sleep(0.05)
    raise AssertionError(f"no {kind} event (got {seen})")


def ok(msg):
    print("ok -", msg)


# ---------------------------------------------------------------- 工具函式
assert C.clean_text("  hi   there\n friend ") == "hi there friend"
assert len(C.clean_text("x" * 100)) == C.MAX_TEXT
assert C.other_slot("a") == "b" and C.other_slot("b") == "a"
p = C.SSEParser()
assert p.feed("event: put\n") is None and p.feed('data: {"path":"/"}\n') is None
assert p.feed("\n") == ("put", '{"path":"/"}')
ok("helpers + SSE parser")

# ---------------------------------------------------------------- 配對
A = client("A")
B = client("B")
assert not A.paired
r = A.create_pair("Evan")
code = r["code"]
assert len(code) == 6 and code.isdigit() and A.paired and A.state["slot"] == "a"
assert fb.get(f"codes/{code}")["slot"] == "b"
assert fb.get(f"rooms/{A.state['room']}/names/a") == "Evan"
wait_event(A, "paired")
ok(f"create pair, code {code}")

try:
    B.join("123", "Amy")
    raise AssertionError("short code accepted")
except C.CloudError:
    pass
try:
    B.join("000000" if code != "000000" else "111111", "Amy")
    raise AssertionError("wrong code accepted")
except C.CloudError as e:
    assert "doesn't work" in str(e)
res = B.join(code, "Amy")
assert res["partner"] == "Evan" and B.state["slot"] == "b" and B.partner_name == "Evan"
assert fb.get(f"rooms/{A.state['room']}/names/b") == "Amy"
A.refresh_names()
assert A.partner_name == "Amy"
ok("join with code, names both ways")

link = A.make_link_code()["code"]
assert fb.get(f"codes/{link}")["slot"] == "a"
ok("phone link code is for my own slot")

# ---------------------------------------------------------------- 收發
wait_event(A, "online", pred=lambda v: v)
wait_event(B, "online", pred=lambda v: v)
B.send("  Hi   Evan!  ")
m = wait_event(A, "message")
assert m["text"] == "Hi Evan!" and m["name"] == "Amy" and m["from"] == "b" and not m["mine"]
time.sleep(0.3)
st = fb.get(f"rooms/{A.state['room']}/status/a")
assert st and st.get("delivered") == m["ts"], st
ok("B -> A message arrives over SSE, delivered mark")

A.send("Hey Amy")
m2 = wait_event(B, "message")
assert m2["text"] == "Hey Amy" and m2["name"] == "Evan"
# 自己傳的不會回到自己這邊
time.sleep(0.4)
assert not [e for e in A.drain() if e[0] == "message"]
ok("A -> B, own messages not echoed")

# 長訊息、空訊息
try:
    A.send("   ")
    raise AssertionError
except C.CloudError:
    pass
A.send("y" * 80)
assert len(wait_event(B, "message")["text"]) == 60
ok("empty rejected, long cut to 60")

# 已讀
A.mark_seen(m["ts"])
time.sleep(0.5)
assert fb.get(f"rooms/{A.state['room']}/status/a")["seen"] == m["ts"]
ok("seen mark")

# 狗關著時傳的：兩則，第一則已讀過
B.send("one")
B.send("two")
got = [wait_event(A, "message")["text"], wait_event(A, "message")["text"]]
assert got == ["one", "two"], got
A.stop()
t_one = [v for v in (fb.get(f"rooms/{A.state['room']}/messages") or {}).values() if v["text"] == "one"][0]["ts"]
A2 = client("A")      # 重開（同一個存檔）
A2.mark_seen(t_one)   # 只看過 "one"
A2._known.clear()
A2._restart_stream()
texts = []
end = time.time() + 6
while time.time() < end and "two" not in texts:
    for k, v in A2.drain():
        if k == "message":
            texts.append(v["text"])
    time.sleep(0.05)
assert texts == ["two"], texts
assert A2.state["uid"] == A.state["uid"]
ok("restart: same uid, only unseen messages come back")

# 歷史
h = A2.history()
assert [x["text"] for x in h][-3:] == ["y" * 60, "one", "two"] and h[-1]["name"] == "Amy" and h[0]["mine"] is False
assert any(x["mine"] for x in h)
ok("history (last 20, both sides)")

# token 過期 → 串流收到 auth_revoked → 換 token 繼續
fb.expire_all = True
time.sleep(1.5)
A2.token_exp = 0
B.send("after expiry")
assert wait_event(A2, "message", timeout=12)["text"] == "after expiry"
ok("token expiry: auth_revoked -> refresh -> keeps streaming")

# 改名
B.set_my_name("Amy B")
assert A2.refresh_names()["partner"] == "Amy B"
ok("rename")

# 心跳
time.sleep(0.5)
assert fb.get(f"rooms/{A2.state['room']}/status/a").get("pet")
ok("heartbeat")

# 解除配對
B.unpair()
assert not B.paired and fb.get(f"rooms/{A2.state['room']}/members/{B.state['uid']}") is None
wait_event(B, "unpaired")
try:
    B.send("x")
    raise AssertionError
except C.CloudError:
    pass
ok("unpair")

# 被別處解除（成員資料不見）→ check_member 發 unpaired
fb.set(f"rooms/{A2.state['room']}/members/{A2.state['uid']}", None)
assert A2.check_member() is False and not A2.paired
ok("removed elsewhere -> unpaired")

# call() 背景執行 + callback
C3 = client("C")
box = {}
C3.call(C3.create_pair, "Zed", callback=lambda v, e: box.update(v=v, e=e))
wait_event(C3, "paired")
wait_event(C3, "result")
assert box.get("v") and len(box["v"]["code"]) == 6 and box["e"] is None, box
C3.call(C3.join, "12", "x", callback=lambda v, e: box.update(err=e))
wait_event(C3, "result")
assert box["err"] == "The code has 6 numbers"
ok("call() results come back with callbacks")

# ---------------------------------------------------------------- v0.4.1 入口：不用朋友就能連手機、測試模式
D = client("D")
r = D.link_phone("Evan")
assert D.paired and D.state["slot"] == "a" and fb.get(f"codes/{r['code']}")["slot"] == "a"
room_d = D.state["room"]
assert D.link_phone("")["code"] and D.state["room"] == room_d          # 同一個房間
assert not D.has_partner and not D.test_mode
t = D.test_phone()
assert D.test_mode and fb.get(f"codes/{t['code']}")["slot"] == "b"
phone = client("Phone")
phone.join(t["code"], "Phone")
w = D.who_joined()
assert w["partner"] == "Phone" and D.has_partner and w["my_phones"] == 0
mine = client("MyPhone")
fb.set(f"rooms/{room_d}/members/{mine.state['uid'] or 'x'}", None)
# 自己的手機（kind phone、slot a）
mine._ensure_token()
fb.set(f"rooms/{room_d}/members/{mine.state['uid']}", {"slot": "a", "kind": "phone", "joined": 1})
assert D.who_joined()["my_phones"] == 1
inv = D.create_pair("")
assert not D.test_mode and fb.get(f"codes/{inv['code']}")["slot"] == "b"
# 已經在一組裡，輸入別組的碼 → 離開舊的、加入新的
E = client("E")
code_e = E.create_pair("Erin")["code"]
old_room = D.state["room"]
D.join(code_e, "Evan")
assert D.state["room"] == E.state["room"] and D.state["slot"] == "b" and not D.test_mode
assert fb.get(f"rooms/{old_room}/members/{D.state['uid']}") is None
D.unpair()
E.stop()
assert not D.paired and not D.test_mode
ok("link phone without a friend, test mode, who_joined, invite ends test mode")

for c in (A2, B, C3, D, phone, mine):
    c.stop()
fb.close()
print("ALL CLOUD TESTS PASSED")
