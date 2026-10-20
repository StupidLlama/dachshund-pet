"""v0.4.2 雙人訊息 + 手機同步：桌寵 ↔ Firebase Realtime Database（不依賴 Qt，只用 Python 內建套件）。

為什麼不用 firebase-admin：太大（之後打包 exe 會變胖），而且它是給伺服器用的。
這裡直接打 Firebase 的 REST API：
    登入      identitytoolkit accounts:signUp（匿名）→ idToken（1 小時）+ refreshToken（長期）
    換 token  securetoken /v1/token
    讀寫      {databaseURL}/路徑.json?auth=idToken
    即時更新  同一個網址加 Accept: text/event-stream（SSE 串流）

資料結構（詳見 tools/build_rules.py）：
    homes/{home}   一個人一個「家」：狗 + 手機、名字、聊天室列表、待辦清單、設定
    rooms/{room}   一個聊天室（1 對 1；SLOTS 改長就能群組）
    codes/{6 碼}   kind=home → 連自己的手機；kind=room → 邀請朋友

執行緒：網路的事全部在背景執行緒做，結果丟進 self.events（queue）。
Qt 那邊（app.py）用 QTimer 每 0.2 秒呼叫 drain() 拿出來處理，所以 Qt 物件只在主執行緒碰。
    家串流         homes/{home}：聊天室列表、待辦、設定、成員 → 事件 rooms / todo / settings
    每個聊天室一條  rooms/{room}/messages（orderBy ts, startAt 已讀+1）→ 事件 message
    心跳           每 60 秒告訴朋友「我的狗醒著」、更新朋友的名字

本機存檔 %APPDATA%\\DachshundPet\\cloud.json：uid、refreshToken、家、名字、每個聊天室的位置 / 朋友名字 / 已讀到哪。
"""
from __future__ import annotations

import json
import queue
import random
import string
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_TEXT = 60                    # 一則訊息最多幾個字（跟安全規則一樣）
MAX_TODO = 40
CODE_LIFE_SEC = 600              # 配對碼 10 分鐘有效
HEARTBEAT_SEC = 60               # 多久告訴朋友「我的狗還開著」
NAMES_POLL_SEC = 300             # 多久重新抓一次朋友的名字（還沒有名字時每次心跳都抓）
ONLINE_WINDOW_MS = 150_000       # 手機端：狗最後心跳在 2.5 分鐘內 = 在線
HISTORY_N = 100                  # 桌寵看最近幾則（跟手機一樣）
QUICK = ["Miss you!", "Drink water!", "Good luck today!", "Good night!", "Call me?"]   # 快捷訊息（跟手機 docs/app.js 一樣）
PWA_URL = "https://stupidllama.github.io/dachshund-pet/"
SLOTS = "ab"                     # 1 對 1（之後群組：改這裡和 tools/build_rules.py）
TEST_NAME = "Test phone"
STATE_VERSION = 2

AUTH_BASE = "https://identitytoolkit.googleapis.com/v1"
TOKEN_BASE = "https://securetoken.googleapis.com/v1"
SV_TIMESTAMP = {".sv": "timestamp"}


class CloudError(Exception):
    """給使用者看的錯誤（英文，桌寵介面是英文）。"""


def clean_text(text: str, n: int = MAX_TEXT) -> str:
    """壓掉多餘空白、換行，最多 n 字。"""
    return " ".join(str(text).split())[:n]


def clean_name(name: str) -> str:
    return " ".join(str(name).split())[:20]


def other_slot(slot: str) -> str:
    return next((s for s in SLOTS if s != slot), "b")


def random_id(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(n))


random_room_id = random_id


def random_code() -> str:
    return f"{random.SystemRandom().randrange(0, 1_000_000):06d}"


def load_config(path: Path) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("apiKey", "databaseURL"):
        if not cfg.get(key):
            raise CloudError(f"firebase config is missing {key}")
    cfg["databaseURL"] = cfg["databaseURL"].rstrip("/")
    return cfg


def apply_patch(tree, path: str, data, merge: bool = False):
    """把 SSE 的 put / patch 套到本機的副本上，回傳新的樹。"""
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        if merge and isinstance(tree, dict) and isinstance(data, dict):
            out = dict(tree)
            for k, v in data.items():
                out = apply_patch(out, k, v)
            return out
        return data
    tree = dict(tree) if isinstance(tree, dict) else {}
    node = tree
    for part in parts[:-1]:
        nxt = node.get(part)
        nxt = dict(nxt) if isinstance(nxt, dict) else {}
        node[part] = nxt
        node = nxt
    last = parts[-1]
    if merge and isinstance(data, dict):
        cur = dict(node.get(last)) if isinstance(node.get(last), dict) else {}
        for k, v in data.items():
            if v is None:
                cur.pop(k, None)
            else:
                cur[k] = v
        node[last] = cur
    elif data is None:
        node.pop(last, None)
    else:
        node[last] = data
    return tree


# ====================================================================== SSE 解析
class SSEParser:
    """把一行一行的 SSE 文字組成 (event, data)。Firebase 的 data 是 JSON。"""

    def __init__(self):
        self.event = None
        self.data: list[str] = []

    def feed(self, line: str):
        line = line.rstrip("\r\n")
        if line == "":
            if self.event is None and not self.data:
                return None
            ev = (self.event or "message", "\n".join(self.data))
            self.event, self.data = None, []
            return ev
        if line.startswith(":"):
            return None
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            self.event = value
        elif field == "data":
            self.data.append(value)
        return None


# ====================================================================== 本機存檔
class CloudState:
    FIELDS = {"version": STATE_VERSION, "uid": "", "refresh": "", "home": "", "name": "", "rooms": {}}

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = json.loads(json.dumps(self.FIELDS))
        self.old_pairing = False
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    if loaded.get("version") == STATE_VERSION:
                        self.data.update({k: v for k, v in loaded.items() if k in self.FIELDS})
                    else:                                   # v0.4 / v0.4.1 的舊配對：只留登入身分
                        self.data.update(uid=loaded.get("uid", ""), refresh=loaded.get("refresh", ""),
                                         name=loaded.get("my_name", ""))
                        self.old_pairing = bool(loaded.get("room"))
            except (OSError, json.JSONDecodeError):
                pass
        if not isinstance(self.data.get("rooms"), dict):
            self.data["rooms"] = {}

    def __getitem__(self, key):
        with self.lock:
            return self.data.get(key, self.FIELDS.get(key))

    def save(self) -> None:
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(self.path)
            except OSError:
                pass

    def update(self, **kw) -> None:
        with self.lock:
            self.data.update(kw)
            self.save()

    def room(self, rid: str) -> dict:
        with self.lock:
            return dict(self.data["rooms"].get(rid) or {})

    def set_room(self, rid: str, **kw) -> None:
        with self.lock:
            cur = dict(self.data["rooms"].get(rid) or {"slots": "", "partner": "", "seen_ts": 0, "delivered_ts": 0})
            cur.update(kw)
            self.data["rooms"][rid] = cur
            self.save()

    def drop_room(self, rid: str) -> None:
        with self.lock:
            self.data["rooms"].pop(rid, None)
            self.save()

    def room_ids(self) -> list[str]:
        with self.lock:
            return list(self.data["rooms"])


# ====================================================================== 主體
class CloudClient:
    """events（主執行緒用 drain() 拿）：
        ("message", {"room", "id", "from", "name", "text", "ts", "via", "mine"})   朋友傳來的新訊息
        ("rooms", [{"id", "partner", "test"}])        聊天室列表或朋友名字變了
        ("todo", {"items": {id: {...}}, "date": "YYYY-MM-DD" 或 ""})   家裡的待辦清單（手機改了也會來）
        ("settings", {...})                           家裡的設定（起床時間、番茄鐘）
        ("online", bool)                              連上 / 斷線
        ("home", {"name", "phones"})                  家的狀態（名字、連了幾支手機）
        ("reset", None)                               家不見了 / 被移出（回到沒連線的狀態）
        ("result", (callback, value, error))          call() 的結果
    """

    def __init__(self, config: dict, state_path: Path, *, auth_base: str = AUTH_BASE,
                 token_base: str = TOKEN_BASE, opener=None, start: bool = True):
        self.cfg = config
        self.db = config["databaseURL"]
        self.key = config["apiKey"]
        self.auth_base = auth_base.rstrip("/")
        self.token_base = token_base.rstrip("/")
        self.opener = opener or urllib.request.build_opener()
        self.state = CloudState(state_path)
        self.events: queue.Queue = queue.Queue()
        self.id_token = ""
        self.token_exp = 0.0
        self._auth_lock = threading.Lock()
        self._stop = threading.Event()
        self._home_wake = threading.Event()
        self._home_resp = None
        self.home_data: dict = {}               # 家的副本（家串流維護）
        self._room_threads: dict[str, dict] = {}
        self._known: set[str] = set()            # 這次開機已經交給狗的訊息 id
        self._lock = threading.RLock()
        self.online = False
        self.threads: list[threading.Thread] = []
        if start:
            self.start()

    # ------------------------------------------------------------------ 狀態
    @property
    def linked(self) -> bool:
        """有沒有「家」（連過手機或加過朋友）。"""
        return bool(self.state["home"])

    paired = linked                              # 舊名字

    @property
    def my_name(self) -> str:
        return self.state["name"]

    @property
    def old_pairing(self) -> bool:
        return self.state.old_pairing

    def rooms(self) -> list[dict]:
        """聊天室列表（給選單、訊息視窗用）。還沒有朋友加入的邀請不算。"""
        out = []
        for rid in self.state.room_ids():
            r = self.state.room(rid)
            test = r.get("slots") == "".join(SLOTS)
            if r.get("partner") or test:
                out.append({"id": rid, "partner": r.get("partner") or TEST_NAME, "test": test})
        out.sort(key=lambda x: (x["test"], x["partner"].lower()))
        return out

    def partner_of(self, rid: str) -> str:
        r = self.state.room(rid)
        return r.get("partner") or (TEST_NAME if r.get("slots") == "".join(SLOTS) else "Friend")

    def my_slot(self, rid: str) -> str:
        """狗在這個聊天室用的位置（測試聊天室 "ab" → 狗是 a，手機是 b）。"""
        return (self.state.room(rid).get("slots") or "a")[0]

    def phones(self) -> int:
        members = self.home_data.get("members") if isinstance(self.home_data, dict) else None
        if not isinstance(members, dict):
            return 0
        return sum(1 for m in members.values() if isinstance(m, dict) and m.get("kind") == "phone")

    def start(self) -> None:
        for fn in (self._home_loop, self._heartbeat_loop):
            t = threading.Thread(target=fn, daemon=True, name=fn.__name__)
            t.start()
            self.threads.append(t)
        if self.linked:
            self._sync_room_threads()

    def stop(self) -> None:
        self._stop.set()
        self._home_wake.set()
        self._close(self._home_resp)
        with self._lock:
            for t in self._room_threads.values():
                t["stop"].set()
                self._close(t.get("resp"))

    def drain(self, limit: int = 100) -> list:
        out = []
        for _ in range(limit):
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                break
        return out

    def call(self, fn, *args, callback=None) -> None:
        """在背景執行 fn(*args)；結果用 ("result", (callback, 值, 錯誤)) 回到主執行緒。"""
        def run():
            try:
                value, err = fn(*args), None
            except CloudError as e:
                value, err = None, str(e)
            except Exception as e:                     # 網路錯誤等等
                value, err = None, _friendly(e)
            self.events.put(("result", (callback, value, err)))
        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------ HTTP
    def _http(self, method: str, url: str, body=None, form: dict | None = None, timeout: float = 20.0):
        data = None
        headers = {}
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if e.code in (401, 403):
                raise PermissionError(detail or str(e)) from None
            if "ADMIN_ONLY_OPERATION" in detail:
                raise CloudError("Anonymous sign-in is off in Firebase") from None
            raise CloudError(f"Server error {e.code}") from None
        return json.loads(raw.decode("utf-8")) if raw else None

    def _ensure_token(self, force: bool = False) -> str:
        with self._auth_lock:
            if not force and self.id_token and time.time() < self.token_exp - 300:
                return self.id_token
            refresh = self.state["refresh"]
            if refresh:
                try:
                    r = self._http("POST", f"{self.token_base}/token?key={self.key}",
                                   form={"grant_type": "refresh_token", "refresh_token": refresh})
                    self.id_token = r["id_token"]
                    self.token_exp = time.time() + float(r.get("expires_in", 3600))
                    self.state.update(refresh=r.get("refresh_token", refresh), uid=r.get("user_id", self.state["uid"]))
                    return self.id_token
                except (PermissionError, CloudError):
                    pass                               # refreshToken 失效 → 重新匿名登入（會變成新的 uid）
            r = self._http("POST", f"{self.auth_base}/accounts:signUp?key={self.key}", {"returnSecureToken": True})
            self.id_token = r["idToken"]
            self.token_exp = time.time() + float(r.get("expiresIn", 3600))
            old_uid = self.state["uid"]
            self.state.update(uid=r["localId"], refresh=r["refreshToken"])
            if old_uid and old_uid != r["localId"] and self.linked:
                self._reset_local()                    # 換了身分，舊的家進不去了
            return self.id_token

    def _url(self, path: str, query: dict | None = None) -> str:
        q = {"auth": self._ensure_token()}
        if query:
            q.update(query)
        return f"{self.db}/{path.strip('/')}.json?{urllib.parse.urlencode(q)}"

    def _req(self, method: str, path: str, body=None, query: dict | None = None):
        try:
            return self._http(method, self._url(path, query), body)
        except PermissionError:
            # token 可能剛好過期：換一次再試；還是不行就是安全規則擋掉
            self._ensure_token(force=True)
            try:
                return self._http(method, self._url(path, query), body)
            except PermissionError:
                raise CloudError("Permission denied") from None

    # ------------------------------------------------------------------ 家
    def _home(self, sub: str = "") -> str:
        return f"homes/{self.state['home']}" + (f"/{sub}" if sub else "")

    def ensure_home(self, name: str = "") -> str:
        """還沒有家就建一個（這隻狗是第一個成員）。有名字就順便更新。"""
        name = clean_name(name)
        if self.linked:
            if name and name != self.state["name"]:
                self.set_my_name(name)
            return self.state["home"]
        if not name:
            raise CloudError("Type your name first")
        self._ensure_token()
        home = random_id()
        self._req("PATCH", f"homes/{home}", {
            "meta": {"created": SV_TIMESTAMP},
            f"members/{self.state['uid']}": {"kind": "pet", "joined": SV_TIMESTAMP},
            "name": name,
        })
        self.state.update(home=home, name=name, rooms={})
        self.state.old_pairing = False
        self._known.clear()
        self._restart_home()
        return home

    def link_code(self, name: str = "") -> dict:
        """「📱 Link my phone」：連自己手機的碼（手機輸入後就在你的家裡）。"""
        self.ensure_home(name)
        return {"code": self._make_code("home", self.state["home"])}

    def invite_code(self, name: str = "") -> dict:
        """「💌 Invite a friend」：開一個新聊天室（或用還沒人加入的那個），給朋友的碼。"""
        self.ensure_home(name)
        rid = self._pending_room() or self._new_room(test=False)
        return {"code": self._make_code("room", rid, other_slot(self.my_slot(rid))), "room": rid}

    def test_chat(self, name: str = "") -> dict:
        """「🧪 Test chat」：自己跟自己的聊天室（狗是 a、你的手機是 b），手機傳的訊息會跑到自己的狗頭上。"""
        self.ensure_home(name)
        for rid in self.state.room_ids():
            if self.state.room(rid).get("slots") == "".join(SLOTS):
                return {"room": rid}
        return {"room": self._new_room(test=True)}

    def _pending_room(self) -> str:
        for rid in self.state.room_ids():
            r = self.state.room(rid)
            if r.get("slots") and len(r["slots"]) == 1 and not r.get("partner"):
                return rid
        return ""

    def _new_room(self, test: bool) -> str:
        home, name = self.state["home"], self.state["name"] or "Me"
        rid = random_id()
        slots = "".join(SLOTS) if test else SLOTS[0]
        body = {"meta": {"created": SV_TIMESTAMP, "size": len(SLOTS)}}
        for s in slots:
            body[f"slots/{s}"] = {"home": home}
        self._req("PATCH", f"rooms/{rid}", body)            # 先建聊天室（規則：還沒有 meta 才能自己佔位置）
        self._req("PATCH", f"rooms/{rid}/names", {s: (name if i == 0 else TEST_NAME) for i, s in enumerate(slots)})
        self._req("PUT", self._home(f"rooms/{rid}"), slots)  # 再登記到家裡（規則會檢查位置真的是這個家）
        self.state.set_room(rid, slots=slots, partner=TEST_NAME if test else "", seen_ts=0, delivered_ts=0)
        self._sync_room_threads()
        self._emit_rooms()
        return rid

    def _make_code(self, kind: str, target: str, slot: str = "") -> str:
        for _ in range(8):
            code = random_code()
            body = {"kind": kind, "target": target, "by": self.state["uid"],
                    "exp": int((time.time() + CODE_LIFE_SEC) * 1000)}
            if slot:
                body["slot"] = slot
            try:
                self._req("PUT", f"codes/{code}", body)
                return code
            except CloudError as e:
                if "Permission" not in str(e):
                    raise
                # 這個碼別人正在用（或時間差太多）→ 換一個
        raise CloudError("Couldn't make a code. Is your computer clock right?")

    def join(self, code: str, name: str = "") -> dict:
        """「🔑 I have a code」：輸入朋友給的碼，加一個聊天室。"""
        code = "".join(ch for ch in str(code) if ch.isdigit())
        if len(code) != 6:
            raise CloudError("The code has 6 numbers")
        self._ensure_token()
        info = self._req("GET", f"codes/{code}")
        if not isinstance(info, dict) or info.get("exp", 0) < time.time() * 1000 - 60_000:
            raise CloudError("That code doesn't work. Ask for a new one!")
        if info.get("kind") == "home":
            raise CloudError("That's a code for linking a phone. Type it on your phone.")
        rid, slot = info["target"], info["slot"]
        if rid in self.state.room_ids():
            raise CloudError("You're already in that chat")
        self.ensure_home(name)
        home = self.state["home"]
        try:
            self._req("PUT", f"rooms/{rid}/slots/{slot}", {"home": home, "code": code})
        except CloudError:
            raise CloudError("That code doesn't work. Ask for a new one!") from None
        self._req("PUT", f"rooms/{rid}/names/{slot}", self.state["name"] or "Friend")
        self._req("PUT", self._home(f"rooms/{rid}"), slot)
        self.state.set_room(rid, slots=slot, partner="", seen_ts=0, delivered_ts=0)
        partner = self._refresh_room_names(rid)
        self._sync_room_threads()
        self._emit_rooms()
        return {"room": rid, "partner": partner}

    def leave_room(self, rid: str) -> None:
        """離開一個聊天室（朋友那邊會看到你不在了）。"""
        slots = self.state.room(rid).get("slots") or ""
        for s in slots:
            for part in ("names", "slots"):               # 先刪名字（規則：還在位置上才能改名字），朋友那邊就不會再顯示你
                try:
                    self._req("DELETE", f"rooms/{rid}/{part}/{s}")
                except Exception:
                    pass
        try:
            self._req("DELETE", self._home(f"rooms/{rid}"))
        except Exception:
            pass
        self.state.drop_room(rid)
        self._sync_room_threads()
        self._emit_rooms()

    def set_my_name(self, name: str) -> None:
        name = clean_name(name)
        if not name:
            raise CloudError("Name can't be empty")
        if self.linked:
            self._req("PUT", self._home("name"), name)
            for rid in self.state.room_ids():
                try:
                    self._req("PUT", f"rooms/{rid}/names/{self.my_slot(rid)}", name)
                except Exception:
                    pass
        self.state.update(name=name)

    def unlink_phones(self) -> int:
        """把連在這個家的手機都移掉（手機要重新輸入碼）。"""
        members = self._req("GET", self._home("members")) or {}
        n = 0
        for uid, m in members.items():
            if isinstance(m, dict) and m.get("kind") == "phone":
                self._req("DELETE", self._home(f"members/{uid}"))
                n += 1
        return n

    def reset(self) -> None:
        """全部重來：離開所有聊天室、離開家。"""
        if self.linked:
            for rid in self.state.room_ids():
                try:
                    self.leave_room(rid)
                except Exception:
                    pass
            try:
                self._req("DELETE", self._home(f"members/{self.state['uid']}"))
            except Exception:
                pass
        self._reset_local()

    def _reset_local(self) -> None:
        self.state.update(home="", rooms={})
        self.home_data = {}
        self._known.clear()
        self._sync_room_threads()
        self.events.put(("reset", None))
        self._restart_home()

    # ------------------------------------------------------------------ 訊息
    def send(self, rid: str, text: str) -> dict:
        text = clean_text(text)
        if not text:
            raise CloudError("Type something first")
        if rid not in self.state.room_ids():
            raise CloudError("That chat is gone")
        msg = {"from": self.my_slot(rid), "text": text, "ts": SV_TIMESTAMP, "via": "pet"}
        r = self._req("POST", f"rooms/{rid}/messages", msg)
        return {"id": (r or {}).get("name", ""), "text": text, "room": rid}

    def history(self, rid: str, n: int = HISTORY_N) -> list[dict]:
        if rid not in self.state.room_ids():
            return []
        data = self._req("GET", f"rooms/{rid}/messages", query={"orderBy": '"ts"', "limitToLast": str(n)}) or {}
        return self._to_list(rid, data, mine_too=True)

    def mark_seen(self, rid: str, ts: int) -> None:
        """狗的泡泡被點掉了：記住看到哪裡，並告訴朋友「已讀」。"""
        ts = int(ts)
        r = self.state.room(rid)
        if not r or ts <= int(r.get("seen_ts") or 0):
            return
        self.state.set_room(rid, seen_ts=ts)
        self.call(self._req, "PATCH", f"rooms/{rid}/status/{self.my_slot(rid)}", {"seen": ts})

    def _mark_delivered(self, rid: str, ts: int) -> None:
        if ts <= int(self.state.room(rid).get("delivered_ts") or 0):
            return
        self.state.set_room(rid, delivered_ts=ts)
        try:
            self._req("PATCH", f"rooms/{rid}/status/{self.my_slot(rid)}", {"delivered": ts})
        except Exception:
            pass

    def _to_list(self, rid: str, data, mine_too: bool = False) -> list[dict]:
        out = []
        if not isinstance(data, dict):
            return out
        me = self.my_slot(rid)
        partner = self.partner_of(rid)
        for key, m in data.items():
            if not isinstance(m, dict) or not isinstance(m.get("text"), str):
                continue
            frm = m.get("from", "")
            mine = frm == me
            if mine and not mine_too:
                continue
            out.append({"room": rid, "id": key, "from": frm, "mine": mine,
                        "name": (self.state["name"] or "Me") if mine else partner,
                        "text": m["text"][:MAX_TEXT], "ts": int(m.get("ts") or 0), "via": m.get("via", "")})
        out.sort(key=lambda x: (x["ts"], x["id"]))
        return out

    def _deliver(self, rid: str, data) -> None:
        """串流送來的訊息 → 只交出朋友的、還沒看過、這次還沒交過的。"""
        if not isinstance(data, dict) or not data:
            return
        r = self.state.room(rid)
        if not r:
            return
        if not r.get("partner") and r.get("slots") != "".join(SLOTS):
            try:
                self._refresh_room_names(rid)            # 朋友剛加入：先拿到名字，泡泡才顯示得出來
            except Exception:
                pass
        seen = int(r.get("seen_ts") or 0)
        newest = 0
        for m in self._to_list(rid, data, mine_too=True):
            key = f"{rid}/{m['id']}"
            if key in self._known or m["ts"] <= seen:
                continue
            self._known.add(key)
            if m["mine"]:                                # 自己（例如用手機）傳的：只更新訊息視窗，不冒泡泡
                self.events.put(("echo", m))
                continue
            newest = max(newest, m["ts"])
            self.events.put(("message", m))
        if newest:
            self._mark_delivered(rid, newest)

    def _refresh_room_names(self, rid: str) -> str:
        names = self._req("GET", f"rooms/{rid}/names") or {}
        r = self.state.room(rid)
        slots = r.get("slots") or ""
        if slots == "".join(SLOTS):
            partner = TEST_NAME
        else:
            partner = next((v for k, v in (names.items() if isinstance(names, dict) else []) if k not in slots), "")
        if r and partner != r.get("partner"):
            self.state.set_room(rid, partner=partner)
            self._emit_rooms()
        return partner

    def refresh_names(self) -> dict:
        for rid in self.state.room_ids():
            try:
                self._refresh_room_names(rid)
            except Exception:
                pass
        return {"rooms": self.rooms()}

    def _emit_rooms(self) -> None:
        self.events.put(("rooms", self.rooms()))

    # ------------------------------------------------------------------ 待辦、設定
    @staticmethod
    def _todo_body(it: dict) -> dict:
        return {"text": clean_text(it.get("text", ""), MAX_TODO) or "?", "done": bool(it.get("done")),
                "ts": int(it.get("ts") or time.time() * 1000), "by": it.get("by") or "pet"}

    def todo_put(self, item: dict) -> None:
        """新增或更新一項（item 要有 id、text、done、ts）。"""
        if self.linked and item.get("id"):
            self._req("PUT", self._home(f"todo/{item['id']}"), self._todo_body(item))

    def todo_remove(self, item_id: str) -> None:
        if self.linked and item_id:
            self._req("DELETE", self._home(f"todo/{item_id}"))

    def todo_upload(self, items: list[dict], date_str: str) -> None:
        """第一次連上：把電腦上的清單整個傳上去（雲端是空的時候）。"""
        if not self.linked:
            return
        body = {it["id"]: self._todo_body(it) for it in items if it.get("id")}
        if body:
            self._req("PATCH", self._home("todo"), body)
        self._req("PUT", self._home("todo_date"), date_str)

    def todo_rollover(self, done_ids: list[str], date_str: str) -> None:
        """換日：刪掉打勾的項目、更新日期。"""
        if not self.linked:
            return
        if done_ids:
            self._req("PATCH", self._home("todo"), {i: None for i in done_ids})
        self._req("PUT", self._home("todo_date"), date_str)

    def settings_put(self, settings: dict) -> None:
        if self.linked:
            body = {k: settings[k] for k in ("wake_time", "focus_min", "break_min") if k in settings}
            self._req("PATCH", self._home("settings"), body)

    # ------------------------------------------------------------------ 背景：家串流
    def _set_online(self, on: bool) -> None:
        if on != self.online:
            self.online = on
            self.events.put(("online", on))

    @staticmethod
    def _close(resp) -> None:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def _restart_home(self) -> None:
        self._home_wake.set()
        self._close(self._home_resp)

    def _home_loop(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            self._home_wake.clear()
            if not self.linked:
                self._set_online(False)
                self._home_wake.wait(30.0)
                continue
            try:
                self._stream_home()
                backoff = 2.0
            except PermissionError:
                try:
                    self._ensure_token(force=True)
                except Exception:
                    self._set_online(False)
            except CloudError as e:
                if "Permission" in str(e):
                    self._check_home()
                self._set_online(False)
            except Exception:
                if not self._home_wake.is_set():
                    self._set_online(False)
            if self._stop.is_set():
                break
            if not self._home_wake.is_set():
                self._home_wake.wait(backoff)
                backoff = min(backoff * 2, 60.0)

    def _check_home(self) -> None:
        """讀不到家了：是不是被移出（例如在別台電腦按了全部重來）。"""
        try:
            me = self._req("GET", self._home(f"members/{self.state['uid']}"))
        except CloudError:
            me = None
        if not me and self.linked:
            self._reset_local()

    def _stream_home(self) -> None:
        url = self._url(self._home())
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        resp = self.opener.open(req, timeout=90)
        self._home_resp = resp
        self._set_online(True)
        parser = SSEParser()
        try:
            while not self._stop.is_set() and not self._home_wake.is_set():
                raw = resp.readline()
                if not raw:
                    break
                ev = parser.feed(raw.decode("utf-8", "replace"))
                if ev is None:
                    continue
                name, payload = ev
                if name in ("put", "patch"):
                    msg = json.loads(payload) if payload else None
                    if not isinstance(msg, dict):
                        continue
                    self._on_home_change(msg.get("path", "/"), msg.get("data"), name == "patch")
                elif name == "auth_revoked":
                    self._ensure_token(force=True)
                    return
                elif name == "cancel":
                    raise CloudError("Permission denied")
        finally:
            self._home_resp = None
            self._close(resp)

    def _on_home_change(self, path: str, data, merge: bool) -> None:
        first = path.strip("/").split("/")[0] if path.strip("/") else ""
        self.home_data = apply_patch(self.home_data, path, data, merge) or {}
        if not self.home_data and not first:
            self._check_home()
            return
        h = self.home_data
        if first in ("", "todo", "todo_date"):
            self.events.put(("todo", {"items": dict(h.get("todo") or {}), "date": h.get("todo_date") or ""}))
        if first in ("", "settings") and isinstance(h.get("settings"), dict):
            self.events.put(("settings", dict(h["settings"])))
        if first in ("", "name") and isinstance(h.get("name"), str) and h["name"] != self.state["name"]:
            self.state.update(name=h["name"])               # 手機改了名字
        if first in ("", "members", "name"):
            self.events.put(("home", {"name": self.state["name"], "phones": self.phones()}))
        if first in ("", "rooms"):
            self._apply_room_index(h.get("rooms") or {})

    def _apply_room_index(self, index: dict) -> None:
        """家裡的聊天室列表（手機加了朋友、別的裝置離開聊天室）→ 本機跟著改。"""
        if not isinstance(index, dict):
            index = {}
        changed = False
        for rid, slots in index.items():
            if not isinstance(slots, str):
                continue
            r = self.state.room(rid)
            if not r:
                self.state.set_room(rid, slots=slots)
                changed = True
                try:
                    self._refresh_room_names(rid)
                except Exception:
                    pass
            elif r.get("slots") != slots:
                self.state.set_room(rid, slots=slots)
                changed = True
        for rid in self.state.room_ids():
            if rid not in index:
                self.state.drop_room(rid)
                changed = True
        if changed:
            self._sync_room_threads()
            self._emit_rooms()

    # ------------------------------------------------------------------ 背景：每個聊天室一條訊息串流
    def _sync_room_threads(self) -> None:
        with self._lock:
            want = set(self.state.room_ids()) if self.linked else set()
            for rid in list(self._room_threads):
                if rid not in want:
                    t = self._room_threads.pop(rid)
                    t["stop"].set()
                    self._close(t.get("resp"))
            for rid in want:
                if rid not in self._room_threads and not self._stop.is_set():
                    t = {"stop": threading.Event(), "resp": None}
                    t["thread"] = threading.Thread(target=self._room_loop, args=(rid, t), daemon=True)
                    self._room_threads[rid] = t
                    t["thread"].start()

    def _room_loop(self, rid: str, t: dict) -> None:
        backoff = 2.0
        while not self._stop.is_set() and not t["stop"].is_set():
            try:
                self._stream_room(rid, t)
                backoff = 2.0
            except PermissionError:
                try:
                    self._ensure_token(force=True)
                except Exception:
                    pass
            except Exception:
                pass
            if t["stop"].wait(backoff):
                break
            backoff = min(backoff * 2, 60.0)

    def _stream_room(self, rid: str, t: dict) -> None:
        seen = int(self.state.room(rid).get("seen_ts") or 0)
        url = self._url(f"rooms/{rid}/messages", {"orderBy": '"ts"', "startAt": str(seen + 1)})
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        resp = self.opener.open(req, timeout=90)
        t["resp"] = resp
        parser = SSEParser()
        try:
            while not self._stop.is_set() and not t["stop"].is_set():
                raw = resp.readline()
                if not raw:
                    break
                ev = parser.feed(raw.decode("utf-8", "replace"))
                if ev is None:
                    continue
                name, payload = ev
                if name in ("put", "patch"):
                    msg = json.loads(payload) if payload else None
                    if not isinstance(msg, dict):
                        continue
                    path, data = msg.get("path", "/"), msg.get("data")
                    if path == "/":
                        self._deliver(rid, data)
                    elif path.count("/") == 1 and isinstance(data, dict):
                        self._deliver(rid, {path.strip("/"): data})
                elif name == "auth_revoked":
                    self._ensure_token(force=True)
                    return
                elif name == "cancel":
                    raise CloudError("Permission denied")
        finally:
            t["resp"] = None
            self._close(resp)

    # ------------------------------------------------------------------ 背景：心跳
    def _heartbeat_loop(self) -> None:
        last_names = 0.0
        while not self._stop.is_set():
            if self.linked:
                for rid in self.state.room_ids():
                    try:
                        self._req("PATCH", f"rooms/{rid}/status/{self.my_slot(rid)}", {"pet": SV_TIMESTAMP})
                    except Exception:
                        pass
                now = time.monotonic()
                if now - last_names > NAMES_POLL_SEC or any(
                        not self.state.room(r).get("partner") for r in self.state.room_ids()):
                    last_names = now
                    self.refresh_names()
            self._stop.wait(HEARTBEAT_SEC)


def _friendly(e: Exception) -> str:
    if isinstance(e, PermissionError):
        return "Permission denied"
    if isinstance(e, (urllib.error.URLError, OSError, TimeoutError)):
        return "Can't reach the internet"
    return "Something went wrong"
