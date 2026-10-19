"""v0.4 雙人訊息：桌寵 ↔ Firebase Realtime Database（不依賴 Qt，只用 Python 內建套件）。

為什麼不用 firebase-admin：太大（之後打包 exe 會變胖），而且它是給伺服器用的。
這裡直接打 Firebase 的 REST API：
    登入      identitytoolkit accounts:signUp（匿名）→ idToken（1 小時）+ refreshToken（長期）
    換 token  securetoken /v1/token
    讀寫      {databaseURL}/路徑.json?auth=idToken
    收訊息    同一個網址加 Accept: text/event-stream（SSE 串流，伺服器一有新訊息就推過來）

執行緒：網路的事全部在背景執行緒做，結果丟進 self.events（queue）。
Qt 那邊（app.py）用 QTimer 每 0.2 秒呼叫 drain() 拿出來處理，所以 Qt 物件只在主執行緒碰。

本機存檔 %APPDATA%\\DachshundPet\\cloud.json：uid、refreshToken、配對的房間、位置、名字、已看過的最新訊息時間。
資料結構和安全規則見 tools/build_rules.py。
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
CODE_LIFE_SEC = 600              # 配對碼 10 分鐘有效
HEARTBEAT_SEC = 60               # 多久告訴對方「我的狗還開著」
NAMES_POLL_SEC = 300             # 多久重新抓一次名字（對方改名）
ONLINE_WINDOW_MS = 150_000       # 手機端：狗最後心跳在 2.5 分鐘內 = 在線
HISTORY_N = 20                   # 桌寵右鍵看最近幾則
PWA_URL = "https://stupidllama.github.io/dachshund-pet/"
SLOTS = "ab"                     # 2 人一組（之後多人：改這裡和安全規則）

AUTH_BASE = "https://identitytoolkit.googleapis.com/v1"
TOKEN_BASE = "https://securetoken.googleapis.com/v1"
SV_TIMESTAMP = {".sv": "timestamp"}


class CloudError(Exception):
    """給使用者看的錯誤（英文，桌寵介面是英文）。"""


def clean_text(text: str) -> str:
    """壓掉多餘空白、換行，最多 MAX_TEXT 字。"""
    return " ".join(str(text).split())[:MAX_TEXT]


def clean_name(name: str) -> str:
    return " ".join(str(name).split())[:20]


def other_slot(slot: str) -> str:
    return next((s for s in SLOTS if s != slot), "b")


def random_room_id(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(n))


def random_code() -> str:
    return f"{random.SystemRandom().randrange(0, 1_000_000):06d}"


def load_config(path: Path) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("apiKey", "databaseURL"):
        if not cfg.get(key):
            raise CloudError(f"firebase config is missing {key}")
    cfg["databaseURL"] = cfg["databaseURL"].rstrip("/")
    return cfg


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
    FIELDS = {"uid": "", "refresh": "", "room": "", "slot": "", "my_name": "", "partner_name": "",
              "seen_ts": 0, "delivered_ts": 0, "test_mode": False}

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = dict(self.FIELDS)
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update({k: v for k, v in loaded.items() if k in self.FIELDS})
            except (OSError, json.JSONDecodeError):
                pass

    def __getitem__(self, key):
        with self.lock:
            return self.data.get(key, self.FIELDS.get(key))

    def update(self, **kw) -> None:
        with self.lock:
            self.data.update(kw)
            tmp = self.path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(self.path)
            except OSError:
                pass


# ====================================================================== 主體
class CloudClient:
    """events（主執行緒用 drain() 拿）：
        ("message", {"id", "from", "name", "text", "ts", "via"})   對方傳來的新訊息
        ("online", bool)                                            連上 / 斷線
        ("paired", {"partner": 名字或 ""})                           配對狀態改變（含解除配對：paired=False 見 unpaired）
        ("unpaired", None)
        ("names", {"me", "partner"})
        ("result", (callback, value, error))                         call() 的結果
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
        self._wake = threading.Event()          # 配對改變 → 串流重新連
        self._known: set[str] = set()           # 這次開機已經交給狗的訊息 id（避免重複）
        self._stream_resp = None
        self.online = False
        self.threads: list[threading.Thread] = []
        if start:
            self.start()

    # ------------------------------------------------------------------ 狀態
    @property
    def paired(self) -> bool:
        return bool(self.state["room"] and self.state["slot"])

    @property
    def my_name(self) -> str:
        return self.state["my_name"]

    @property
    def partner_name(self) -> str:
        return self.state["partner_name"] or "Your friend"

    def start(self) -> None:
        for fn in (self._stream_loop, self._heartbeat_loop):
            t = threading.Thread(target=fn, daemon=True, name=fn.__name__)
            t.start()
            self.threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._close_stream()

    def drain(self, limit: int = 50) -> list:
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
                except PermissionError:
                    pass                               # refreshToken 失效 → 重新匿名登入（會變成新的 uid）
            r = self._http("POST", f"{self.auth_base}/accounts:signUp?key={self.key}", {"returnSecureToken": True})
            self.id_token = r["idToken"]
            self.token_exp = time.time() + float(r.get("expiresIn", 3600))
            old_uid = self.state["uid"]
            self.state.update(uid=r["localId"], refresh=r["refreshToken"])
            if old_uid and old_uid != r["localId"] and self.paired:
                # 換了身分，舊的配對失效了
                self.state.update(room="", slot="", partner_name="")
                self.events.put(("unpaired", None))
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

    # ------------------------------------------------------------------ 配對
    def _room(self, sub: str = "") -> str:
        return f"rooms/{self.state['room']}" + (f"/{sub}" if sub else "")

    def ensure_room(self, my_name: str = "") -> str:
        """還沒有房間就開一個（自己是 a）。「連我的手機」不用先有朋友。"""
        if self.paired:
            if my_name and clean_name(my_name) != self.state["my_name"]:
                self.set_my_name(my_name)
            return self.state["room"]
        name = clean_name(my_name) or "Me"
        self._ensure_token()
        uid = self.state["uid"]
        room = random_room_id()
        self._req("PATCH", f"rooms/{room}", {
            "meta": {"created": SV_TIMESTAMP, "size": len(SLOTS)},
            f"members/{uid}": {"slot": "a", "kind": "pet", "joined": SV_TIMESTAMP},
            "names/a": name,
        })
        self._set_paired(room, "a", name, "")
        return room

    def create_pair(self, my_name: str) -> dict:
        """開新的一組（或用現有的），產生給朋友用的配對碼（對方位置）。"""
        room = self.ensure_room(my_name)
        self.state.update(test_mode=False)
        return {"code": self._make_code(other_slot(self.state["slot"])), "room": room}

    def link_phone(self, my_name: str = "") -> dict:
        """「📱 Link my phone」：自己位置的碼，手機輸入後就是你自己（朋友收得到你手機傳的）。"""
        self.ensure_room(my_name)
        return {"code": self._make_code(self.state["slot"])}

    def test_phone(self, my_name: str = "") -> dict:
        """「🧪 Test with my phone」：給手機「朋友那一邊」的碼，手機傳的訊息會跑到自己的狗頭上。"""
        self.ensure_room(my_name)
        self.state.update(test_mode=True)
        return {"code": self._make_code(other_slot(self.state["slot"]))}

    def make_link_code(self) -> dict:
        """已配對：產生自己位置的碼（給自己的手機連）。"""
        if not self.paired:
            raise CloudError("Not paired yet")
        return {"code": self._make_code(self.state["slot"])}

    def friend_code(self) -> dict:
        """已配對：產生給朋友的碼（對方位置）。用來邀請真的朋友時，測試模式就結束。"""
        if not self.paired:
            raise CloudError("Not paired yet")
        self.state.update(test_mode=False)
        return {"code": self._make_code(other_slot(self.state["slot"]))}

    @property
    def test_mode(self) -> bool:
        return bool(self.state["test_mode"])

    @property
    def has_partner(self) -> bool:
        return bool(self.paired and self.state["partner_name"])

    def _make_code(self, slot: str) -> str:
        for _ in range(8):
            code = random_code()
            body = {"room": self.state["room"], "slot": slot, "by": self.state["uid"],
                    "exp": int((time.time() + CODE_LIFE_SEC) * 1000)}
            try:
                self._req("PUT", f"codes/{code}", body)
                return code
            except CloudError as e:
                if "Permission" not in str(e):
                    raise
                # 這個碼別人正在用（或時間差太多）→ 換一個
        raise CloudError("Couldn't make a code. Is your computer clock right?")

    def join(self, code: str, my_name: str) -> dict:
        """輸入朋友的碼，加入那一組。"""
        code = "".join(ch for ch in str(code) if ch.isdigit())
        if len(code) != 6:
            raise CloudError("The code has 6 numbers")
        self._ensure_token()
        info = self._req("GET", f"codes/{code}")
        if not isinstance(info, dict) or info.get("exp", 0) < time.time() * 1000 - 60_000:
            raise CloudError("That code doesn't work. Ask for a new one!")
        room, slot = info["room"], info["slot"]
        uid = self.state["uid"]
        try:
            self._req("PUT", f"rooms/{room}/members/{uid}",
                      {"slot": slot, "kind": "pet", "joined": SV_TIMESTAMP, "code": code})
        except CloudError:
            raise CloudError("That code doesn't work. Ask for a new one!") from None
        name = clean_name(my_name)
        old = self.state["slot"] == slot and self.state["room"] == room
        self._set_paired(room, slot, name or self.state["my_name"], "", keep_seen=old)
        if name:
            self._req("PUT", f"rooms/{room}/names/{slot}", name)
        self.refresh_names()
        return {"partner": self.partner_name}

    def unpair(self) -> None:
        if self.paired:
            try:
                self._req("DELETE", self._room(f"members/{self.state['uid']}"))
            except Exception:
                pass                                   # 離線也讓本機解除
        self.state.update(room="", slot="", partner_name="", seen_ts=0, delivered_ts=0, test_mode=False)
        self._known.clear()
        self.events.put(("unpaired", None))
        self._restart_stream()

    def set_my_name(self, name: str) -> None:
        name = clean_name(name)
        if not name:
            raise CloudError("Name can't be empty")
        if self.paired:
            self._req("PUT", self._room(f"names/{self.state['slot']}"), name)
        self.state.update(my_name=name)

    def _set_paired(self, room: str, slot: str, my_name: str, partner: str, keep_seen: bool = False) -> None:
        kw = dict(room=room, slot=slot, my_name=my_name, partner_name=partner)
        if not keep_seen:
            kw.update(seen_ts=0, delivered_ts=0)
            self._known.clear()
        self.state.update(**kw)
        self.events.put(("paired", {"partner": partner}))
        self._restart_stream()

    def refresh_names(self) -> dict:
        if not self.paired:
            return {}
        names = self._req("GET", self._room("names")) or {}
        if not isinstance(names, dict):
            names = {}
        me = names.get(self.state["slot"]) or self.state["my_name"]
        partner = names.get(other_slot(self.state["slot"]), "")
        changed = (me, partner) != (self.state["my_name"], self.state["partner_name"])
        self.state.update(my_name=me, partner_name=partner)
        if changed:
            self.events.put(("names", {"me": me, "partner": partner}))
        return {"me": me, "partner": partner}

    def who_joined(self) -> dict:
        """配對視窗輪詢用：自己這邊有幾支手機、對方叫什麼（也會更新名字）。"""
        if not self.paired:
            return {"my_phones": 0, "partner": ""}
        members = self._req("GET", self._room("members")) or {}
        me = self.state["slot"]
        phones = sum(1 for m in members.values() if isinstance(m, dict) and m.get("slot") == me
                     and m.get("kind") == "phone")
        names = self.refresh_names()
        return {"my_phones": phones, "partner": names.get("partner", "")}

    def check_member(self) -> bool:
        """自己還在房間裡嗎（例如在別台電腦按了解除配對）。"""
        if not self.paired:
            return False
        try:
            me = self._req("GET", self._room(f"members/{self.state['uid']}"))
        except CloudError:
            me = None                                   # 不是成員就讀不到房間
        if not me:
            self.state.update(room="", slot="", partner_name="")
            self.events.put(("unpaired", None))
            self._restart_stream()
            return False
        return True

    # ------------------------------------------------------------------ 訊息
    def send(self, text: str) -> dict:
        text = clean_text(text)
        if not text:
            raise CloudError("Type something first")
        if not self.paired:
            raise CloudError("Pair with a friend first")
        msg = {"from": self.state["slot"], "text": text, "ts": SV_TIMESTAMP, "via": "pet"}
        r = self._req("POST", self._room("messages"), msg)
        return {"id": (r or {}).get("name", ""), "text": text}

    def history(self, n: int = HISTORY_N) -> list[dict]:
        if not self.paired:
            return []
        data = self._req("GET", self._room("messages"), query={"orderBy": '"ts"', "limitToLast": str(n)}) or {}
        return self._to_list(data, mine_too=True)

    def mark_seen(self, ts: int) -> None:
        """狗的泡泡被點掉了：記住看到哪裡，並告訴對方「已讀」。"""
        ts = int(ts)
        if ts <= int(self.state["seen_ts"] or 0):
            return
        self.state.update(seen_ts=ts)
        if self.paired:
            self.call(self._req, "PATCH", self._room(f"status/{self.state['slot']}"), {"seen": ts})

    def _mark_delivered(self, ts: int) -> None:
        if ts <= int(self.state["delivered_ts"] or 0):
            return
        self.state.update(delivered_ts=ts)
        try:
            self._req("PATCH", self._room(f"status/{self.state['slot']}"), {"delivered": ts})
        except Exception:
            pass

    def _to_list(self, data, mine_too: bool = False) -> list[dict]:
        out = []
        if not isinstance(data, dict):
            return out
        me = self.state["slot"]
        names = {me: self.state["my_name"] or "Me", other_slot(me): self.partner_name}
        for key, m in data.items():
            if not isinstance(m, dict) or not isinstance(m.get("text"), str):
                continue
            frm = m.get("from", "")
            if frm == me and not mine_too:
                continue
            out.append({"id": key, "from": frm, "mine": frm == me, "name": names.get(frm, "Friend"),
                        "text": m["text"][:MAX_TEXT], "ts": int(m.get("ts") or 0), "via": m.get("via", "")})
        out.sort(key=lambda x: (x["ts"], x["id"]))
        return out

    def _deliver(self, data) -> None:
        """串流送來的訊息（初始一整包或單則）→ 只交出對方的、還沒看過、這次還沒交過的。"""
        seen = int(self.state["seen_ts"] or 0)
        newest = 0
        if not self.state["partner_name"] and isinstance(data, dict) and data:
            try:
                self.refresh_names()                    # 朋友剛加入：先拿到名字，泡泡才顯示得出來
            except Exception:
                pass
        for m in self._to_list(data):
            if m["id"] in self._known or m["ts"] <= seen:
                continue
            self._known.add(m["id"])
            newest = max(newest, m["ts"])
            self.events.put(("message", m))
        if newest:
            self._mark_delivered(newest)

    # ------------------------------------------------------------------ 背景迴圈
    def _set_online(self, on: bool) -> None:
        if on != self.online:
            self.online = on
            self.events.put(("online", on))

    def _restart_stream(self) -> None:
        self._wake.set()
        self._close_stream()

    def _close_stream(self) -> None:
        r = self._stream_resp
        if r is not None:
            try:
                r.close()
            except Exception:
                pass

    def _stream_loop(self) -> None:
        backoff = 2.0
        first = True
        while not self._stop.is_set():
            self._wake.clear()
            if not self.paired:
                self._wake.wait(30.0)
                continue
            try:
                if first:
                    first = False
                    if not self.check_member():
                        continue
                    self.refresh_names()
                self._stream_once()
                backoff = 2.0
            except PermissionError:
                self._ensure_token_quiet(force=True)
            except CloudError as e:
                if "Permission" in str(e) and not self.check_member():
                    continue
                self._set_online(False)
            except Exception:
                if not self._wake.is_set():           # 自己關掉串流（配對改變）不算斷線
                    self._set_online(False)
            if self._stop.is_set():
                break
            if not self._wake.is_set():
                self._wake.wait(backoff)
                backoff = min(backoff * 2, 60.0)

    def _ensure_token_quiet(self, force: bool = False) -> None:
        try:
            self._ensure_token(force=force)
        except Exception:
            self._set_online(False)

    def _stream_once(self) -> None:
        """連一次 SSE，直到斷線、token 過期、配對改變。"""
        seen = int(self.state["seen_ts"] or 0)
        url = self._url(self._room("messages"), {"orderBy": '"ts"', "startAt": str(seen + 1)})
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        resp = self.opener.open(req, timeout=90)
        self._stream_resp = resp
        self._set_online(True)
        parser = SSEParser()
        try:
            while not self._stop.is_set() and not self._wake.is_set():
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
                        self._deliver(data)
                    elif path.count("/") == 1 and isinstance(data, dict):
                        self._deliver({path.strip("/"): data})
                elif name == "auth_revoked":
                    self._ensure_token(force=True)
                    return
                elif name == "cancel":
                    raise CloudError("Permission denied")
        finally:
            self._stream_resp = None
            try:
                resp.close()
            except Exception:
                pass

    def _heartbeat_loop(self) -> None:
        last_names = time.monotonic()
        while not self._stop.is_set():
            if not self.paired:
                self._stop.wait(5.0)
                continue
            try:
                self._req("PATCH", self._room(f"status/{self.state['slot']}"), {"pet": SV_TIMESTAMP})
                if not self.state["partner_name"] or time.monotonic() - last_names > NAMES_POLL_SEC:
                    last_names = time.monotonic()
                    self.refresh_names()
            except Exception:
                pass
            self._stop.wait(HEARTBEAT_SEC)


def _friendly(e: Exception) -> str:
    if isinstance(e, PermissionError):
        return "Permission denied"
    if isinstance(e, (urllib.error.URLError, OSError, TimeoutError)):
        return "Can't reach the internet"
    return "Something went wrong"
