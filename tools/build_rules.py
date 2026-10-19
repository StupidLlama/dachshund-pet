"""產生 firebase/database.rules.json（Firebase Realtime Database 安全規則）。v0.4.2 版：「家」+ 聊天室。

規則寫在這裡比較好讀（可以換行、加註解），跑一下就輸出成 Firebase 要的 JSON：
    py tools/build_rules.py
然後把 firebase/database.rules.json 的內容整個貼到 Firebase → Realtime Database →「規則」→ 發布。

資料長這樣：
    homes/{home}/                一個人一個「家」：他的狗 + 他的手機
        meta                     {created}
        members/{uid}            {kind: pet|phone, joined, code?}   每台裝置一筆
        name                     這個人的名字
        rooms/{room}             這個家在哪些聊天室、是哪個位置（"a" / "b"；自己跟自己的測試聊天室是 "ab"）
        todo/{id}                待辦清單 {text 1~40 字, done, ts, by: pet|phone}
        todo_date                待辦清單的日期（換日時狗會清掉打勾的）
        settings                 {wake_time "HH:MM", focus_min, break_min}（手機也能改）
    codes/{6 碼}                 {kind: home|room, target: home 或 room 的 id, slot?, by, exp}
                                 home = 連自己的手機；room = 邀請朋友。10 分鐘內有效
    rooms/{room}/                一個聊天室（現在 1 對 1，之後群組只要把 SLOTS 改長）
        meta                     {created, size}
        slots/{slot}             {home, code?}   這個位置是哪個家
        names/{slot}             名字（給對方看的）
        messages/{id}            {from: slot, text 1~60 字, ts: 伺服器時間, via: pet|phone}   不能改、不能刪
        status/{slot}            {pet: 狗心跳, delivered, seen}
誰算「聊天室成員」：某個位置的家裡有你這台裝置（uid）。
"""
from __future__ import annotations

import json
from pathlib import Path

SLOTS = "ab"                 # 1 對 1；之後群組改成 "abcdefgh" 之類（程式和規則都跟著走）
ROOM_SIZE = len(SLOTS)
MAX_TEXT = 60
MAX_TODO = 40
CODE_LIFE_MAX_MS = 20 * 60 * 1000   # 配對碼最長 20 分鐘（程式用 10 分鐘，多留時間差）

ME = "auth != null"
SLOT_RE = f"/^[{SLOTS}]$/"
SLOTS_RE = f"/^[{SLOTS}]+$/"


def one_line(s: str) -> str:
    return " ".join(s.split())


def in_home(home_expr: str) -> str:
    """這台裝置是不是那個家的成員。"""
    return f"root.child('homes').child({home_expr}).child('members').child(auth.uid).exists()"


def slot_home(room_expr: str, slot_expr: str) -> str:
    return f"root.child('rooms').child({room_expr}).child('slots').child({slot_expr}).child('home')"


def in_slot(room_expr: str, slot_expr: str) -> str:
    h = slot_home(room_expr, slot_expr)
    return f"({h}.isString() && {in_home(h + '.val()')})"


def room_member(room_expr: str) -> str:
    return "(" + " || ".join(in_slot(room_expr, f"'{s}'") for s in SLOTS) + ")"


def code(expr: str) -> str:
    return f"root.child('codes').child({expr})"


NEW_CODE = code("newData.child('code').val()")
CREATING_HOME = "!root.child('homes').child($home).child('meta').exists()"
CREATING_ROOM = "!root.child('rooms').child($room).child('meta').exists()"
NUM_LE_NOW = {".validate": "newData.isNumber() && newData.val() <= now"}

rules = {
    "rules": {
        # ---------------------------------------------------------------- 配對碼
        "codes": {
            "$code": {
                ".read": ME,                     # 知道碼才讀得到（codes 這層沒有 .read，不能列出全部）
                ".write": one_line(f"""
                    {ME} && (
                      (newData.exists()
                        && (!data.exists() || data.child('exp').val() < now)
                        && newData.child('by').val() === auth.uid
                        && ((newData.child('kind').val() === 'home' && {in_home("newData.child('target').val()")})
                            || (newData.child('kind').val() === 'room' && {room_member("newData.child('target').val()")})))
                      || (!newData.exists() && data.exists()
                        && (data.child('by').val() === auth.uid || data.child('exp').val() < now))
                    )"""),
                ".validate": one_line("""
                    $code.matches(/^[0-9]{6}$/)
                    && newData.hasChildren(['kind', 'target', 'by', 'exp'])
                    && (newData.child('kind').val() === 'home' || newData.child('slot').isString())"""),
                "kind": {".validate": "newData.isString() && newData.val().matches(/^(home|room)$/)"},
                "target": {".validate": "newData.isString() && newData.val().length <= 40"},
                "slot": {".validate": f"newData.isString() && newData.val().matches({SLOT_RE})"},
                "by": {".validate": "newData.isString()"},
                "exp": {".validate": one_line(f"""
                    newData.isNumber() && newData.val() > now && newData.val() <= now + {CODE_LIFE_MAX_MS}""")},
                "$other": {".validate": False},
            }
        },
        # ---------------------------------------------------------------- 家
        "homes": {
            "$home": {
                ".read": one_line(f"{ME} && {in_home('$home')}"),
                "meta": {
                    ".write": one_line(f"{ME} && !data.exists()"),
                    ".validate": "newData.hasChildren(['created'])",
                    "created": {".validate": "newData.val() === now"},
                    "$other": {".validate": False},
                },
                "members": {
                    "$uid": {
                        ".write": one_line(f"""
                            {ME} && (
                              (auth.uid === $uid && newData.exists() && !data.exists() && {CREATING_HOME})
                              || (auth.uid === $uid && newData.exists() && !data.exists()
                                  && newData.child('code').isString()
                                  && {NEW_CODE}.child('kind').val() === 'home'
                                  && {NEW_CODE}.child('target').val() === $home
                                  && {NEW_CODE}.child('exp').val() > now)
                              || (auth.uid === $uid && data.exists() && newData.exists())
                              || (!newData.exists() && data.exists() && (auth.uid === $uid || {in_home('$home')}))
                            )"""),
                        ".validate": "newData.hasChildren(['kind', 'joined'])",
                        "kind": {".validate": "newData.isString() && newData.val().matches(/^(pet|phone)$/)"},
                        "joined": {".validate": "newData.isNumber()"},
                        "code": {".validate": "newData.isString()"},
                        "$other": {".validate": False},
                    }
                },
                "name": {
                    ".write": one_line(f"{ME} && ({in_home('$home')} || {CREATING_HOME})"),
                    ".validate": "newData.isString() && newData.val().length >= 1 && newData.val().length <= 20",
                },
                "rooms": {
                    "$room": {
                        ".write": one_line(f"{ME} && {in_home('$home')}"),
                        ".validate": one_line(f"""
                            newData.isString() && newData.val().matches({SLOTS_RE})
                            && {slot_home('$room', "newData.val().substring(0, 1)")}.val() === $home"""),
                    }
                },
                "todo": {
                    "$item": {
                        ".write": one_line(f"{ME} && {in_home('$home')}"),
                        ".validate": "newData.hasChildren(['text', 'done', 'ts', 'by'])",
                        "text": {".validate": one_line(f"""
                            newData.isString() && newData.val().length >= 1 && newData.val().length <= {MAX_TODO}""")},
                        "done": {".validate": "newData.isBoolean()"},
                        "ts": {".validate": "newData.isNumber()"},
                        "by": {".validate": "newData.isString() && newData.val().matches(/^(pet|phone)$/)"},
                        "$other": {".validate": False},
                    }
                },
                "todo_date": {
                    ".write": one_line(f"{ME} && {in_home('$home')}"),
                    ".validate": "newData.isString() && newData.val().matches(/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/)",
                },
                "settings": {
                    ".write": one_line(f"{ME} && {in_home('$home')}"),
                    "wake_time": {".validate": "newData.isString() && newData.val().matches(/^([01][0-9]|2[0-3]):[0-5][0-9]$/)"},
                    "focus_min": {".validate": "newData.isNumber() && newData.val() >= 1 && newData.val() <= 120"},
                    "break_min": {".validate": "newData.isNumber() && newData.val() >= 1 && newData.val() <= 60"},
                    "$other": {".validate": False},
                },
                "$other": {".validate": False},
            }
        },
        # ---------------------------------------------------------------- 聊天室
        "rooms": {
            "$room": {
                ".read": one_line(f"{ME} && {room_member('$room')}"),
                "meta": {
                    ".write": one_line(f"{ME} && !data.exists()"),
                    ".validate": "newData.hasChildren(['created', 'size'])",
                    "created": {".validate": "newData.val() === now"},
                    "size": {".validate": f"newData.isNumber() && newData.val() === {ROOM_SIZE}"},
                    "$other": {".validate": False},
                },
                "slots": {
                    "$slot": {
                        ".write": one_line(f"""
                            {ME} && (
                              (newData.exists() && !data.exists() && {in_home("newData.child('home').val()")}
                                && ({CREATING_ROOM}
                                    || (newData.child('code').isString()
                                        && {NEW_CODE}.child('kind').val() === 'room'
                                        && {NEW_CODE}.child('target').val() === $room
                                        && {NEW_CODE}.child('slot').val() === $slot
                                        && {NEW_CODE}.child('exp').val() > now)))
                              || (!newData.exists() && data.exists() && {in_home("data.child('home').val()")})
                            )"""),
                        ".validate": f"$slot.matches({SLOT_RE}) && newData.hasChildren(['home'])",
                        "home": {".validate": "newData.isString() && newData.val().length <= 40"},
                        "code": {".validate": "newData.isString()"},
                        "$other": {".validate": False},
                    }
                },
                "names": {
                    "$slot": {
                        ".write": one_line(f"{ME} && {in_slot('$room', '$slot')}"),
                        ".validate": "newData.isString() && newData.val().length >= 1 && newData.val().length <= 20",
                    }
                },
                "messages": {
                    ".indexOn": ["ts"],
                    "$msg": {
                        ".write": one_line(f"{ME} && !data.exists() && {room_member('$room')}"),
                        ".validate": "newData.hasChildren(['from', 'text', 'ts', 'via'])",
                        "from": {".validate": one_line(f"""
                            newData.isString() && newData.val().matches({SLOT_RE})
                            && {in_slot('$room', 'newData.val()')}""")},
                        "text": {".validate": one_line(f"""
                            newData.isString() && newData.val().length >= 1 && newData.val().length <= {MAX_TEXT}""")},
                        "ts": {".validate": "newData.val() === now"},
                        "via": {".validate": "newData.isString() && newData.val().matches(/^(pet|phone)$/)"},
                        "$other": {".validate": False},
                    }
                },
                "status": {
                    "$slot": {
                        ".write": one_line(f"{ME} && {in_slot('$room', '$slot')}"),
                        "pet": NUM_LE_NOW,
                        "delivered": NUM_LE_NOW,
                        "seen": NUM_LE_NOW,
                        "$other": {".validate": False},
                    }
                },
                "$other": {".validate": False},
            }
        },
    }
}


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "firebase" / "database.rules.json"
    out.write_text(json.dumps(rules, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
