"""測試用的假 Firebase（本機 HTTP 伺服器）：匿名登入、換 token、Realtime Database REST、SSE 串流。

只做 cloud.py 用到的部分；安全規則只檢查「有登入」和「房間成員才讀得到房間」，
真正的規則（tools/build_rules.py）要在真的 Firebase 上測。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeFirebase:
    def __init__(self):
        self.root: dict = {}
        self.tokens: dict[str, str] = {}     # idToken → uid
        self.refresh: dict[str, str] = {}    # refreshToken → uid
        self.cond = threading.Condition()
        self.version = 0
        self.n = 0
        self.expire_all = False              # 測 token 過期
        self.requests: list[tuple[str, str]] = []
        srv = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        srv.daemon_threads = True
        self.server = srv
        self.port = srv.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    # ---------------------------------------------------------------- 資料
    def get(self, path: str):
        node = self.root
        for part in [p for p in path.strip("/").split("/") if p]:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def _resolve(self, v):
        if isinstance(v, dict):
            if v == {".sv": "timestamp"}:
                return int(time.time() * 1000)
            return {k: self._resolve(x) for k, x in v.items() if x is not None}
        return v

    def set(self, path: str, value):
        parts = [p for p in path.strip("/").split("/") if p]
        with self.cond:
            value = self._resolve(value)
            if not parts:
                self.root = value or {}
            else:
                node = self.root
                for part in parts[:-1]:
                    node = node.setdefault(part, {})
                if value is None:
                    node.pop(parts[-1], None)
                else:
                    node[parts[-1]] = value
            self.version += 1
            self.cond.notify_all()

    def member(self, uid: str, room: str) -> bool:
        return bool(self.get(f"rooms/{room}/members/{uid}"))

    # ---------------------------------------------------------------- HTTP
    def _handler(self):
        fb = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def _uid(self, q):
                tok = (q.get("auth") or [""])[0]
                if fb.expire_all:
                    return None
                return fb.tokens.get(tok)

            def do_POST(self):
                u = urllib.parse.urlparse(self.path)
                if u.path.endswith("accounts:signUp"):
                    fb.n += 1
                    uid = f"uid{fb.n}"
                    tok, ref = f"tok{fb.n}", f"ref{fb.n}"
                    fb.tokens[tok] = uid
                    fb.refresh[ref] = uid
                    self._body()
                    return self._send(200, {"idToken": tok, "refreshToken": ref, "localId": uid, "expiresIn": "3600"})
                if u.path.endswith("/token"):
                    form = urllib.parse.parse_qs(self._body().decode())
                    ref = form.get("refresh_token", [""])[0]
                    uid = fb.refresh.get(ref)
                    if not uid:
                        return self._send(400, {"error": "INVALID_REFRESH_TOKEN"})
                    fb.n += 1
                    tok = f"tok{fb.n}"
                    fb.tokens[tok] = uid
                    fb.expire_all = False
                    return self._send(200, {"id_token": tok, "refresh_token": ref, "user_id": uid, "expires_in": "3600"})
                self._db("POST")

            def do_GET(self):
                self._db("GET")

            def do_PUT(self):
                self._db("PUT")

            def do_PATCH(self):
                self._db("PATCH")

            def do_DELETE(self):
                self._db("DELETE")

            def _db(self, method):
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                path = urllib.parse.unquote(u.path)[:-len(".json")] if u.path.endswith(".json") else u.path
                fb.requests.append((method, path))
                uid = self._uid(q)
                body = self._body() if method != "GET" else b""
                if uid is None:
                    return self._send(401, {"error": "Auth token is expired"})
                parts = [p for p in path.strip("/").split("/") if p]
                if parts and parts[0] == "rooms" and len(parts) >= 2:
                    room = parts[1]
                    joining = len(parts) == 4 and parts[2] == "members" and parts[3] == uid
                    creating = method == "PATCH" and len(parts) == 2 and fb.get(f"rooms/{room}/meta") is None
                    if not (fb.member(uid, room) or joining or creating):
                        return self._send(401, {"error": "Permission denied"})
                if method == "GET" and "text/event-stream" in (self.headers.get("Accept") or ""):
                    return self._stream(path, q)
                if method == "GET":
                    return self._send(200, self._query(fb.get(path), q))
                data = json.loads(body) if body else None
                if method == "PUT":
                    fb.set(path, data)
                    return self._send(200, data)
                if method == "PATCH":
                    for k, v in (data or {}).items():
                        fb.set(f"{path}/{k}", v)
                    return self._send(200, data)
                if method == "POST":
                    key = f"-N{int(time.time() * 1000):013d}{fb.n:04d}"
                    fb.n += 1
                    fb.set(f"{path}/{key}", data)
                    return self._send(200, {"name": key})
                if method == "DELETE":
                    fb.set(path, None)
                    return self._send(200, None)

            def _query(self, data, q):
                if not isinstance(data, dict) or "orderBy" not in q:
                    return data
                items = sorted(data.items(), key=lambda kv: (kv[1] or {}).get("ts", 0))
                if "startAt" in q:
                    lo = float(q["startAt"][0])
                    items = [kv for kv in items if (kv[1] or {}).get("ts", 0) >= lo]
                if "limitToLast" in q:
                    items = items[-int(q["limitToLast"][0]):]
                return dict(items)

            def _stream(self, path, q):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                sent = set()

                def emit(ev, data):
                    self.wfile.write(f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode())
                    self.wfile.flush()

                try:
                    cur = self._query(fb.get(path), q) or {}
                    emit("put", {"path": "/", "data": cur or None})
                    sent |= set(cur)
                    ver = fb.version
                    while True:
                        with fb.cond:
                            fb.cond.wait_for(lambda: fb.version != ver or fb.expire_all, timeout=1.0)
                            ver = fb.version
                        if fb.expire_all:
                            emit("auth_revoked", "credential is no longer valid")
                            return
                        cur = self._query(fb.get(path), q) or {}
                        for k, v in cur.items():
                            if k not in sent:
                                sent.add(k)
                                emit("put", {"path": f"/{k}", "data": v})
                        self.wfile.write(b"event: keep-alive\ndata: null\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

        return H
