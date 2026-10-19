"""產生 firebase/database.rules.json（Firebase Realtime Database 安全規則）。

規則寫在這裡比較好讀（可以換行、加註解），跑一下就輸出成 Firebase 要的 JSON：
    py tools/build_rules.py
然後把 firebase/database.rules.json 的內容整個貼到 Firebase →  Realtime Database →「規則」→ 發布。

資料長這樣（v0.4，2 人一組；之後要多人只要把 SLOTS 改長）：
    codes/{6 碼}            配對碼：{room, slot, by, exp}，10 分鐘內有效，可以重複用（狗和手機都能用同一組碼加入）
    rooms/{room}/meta       {created, size}
    rooms/{room}/members/{uid}  {slot, kind: pet|phone, joined, code?}   每台裝置（狗或手機）一筆
    rooms/{room}/names/{slot}   這個位置的人叫什麼名字
    rooms/{room}/messages/{id}  {from: slot, text (1~60 字), ts: 伺服器時間, via: pet|phone}
    rooms/{room}/status/{slot}  {pet: 狗最後在線時間, delivered: 狗收到的最新訊息 ts, seen: 狗被點掉的最新訊息 ts}
"""
from __future__ import annotations

import json
from pathlib import Path

SLOTS = "ab"                 # 2 人一組；多人以後改成 "abcdef" 之類
MAX_TEXT = 60
CODE_LIFE_MAX_MS = 20 * 60 * 1000   # 配對碼最長 20 分鐘（程式用 10 分鐘，多留時間差）

SLOT_RE = f"/^[{SLOTS}]$/"
ME = "auth != null"


def one_line(s: str) -> str:
    return " ".join(s.split())


def member(uid_expr: str = "auth.uid") -> str:
    return f"root.child('rooms').child($room).child('members').child({uid_expr})"


def my_slot_new() -> str:
    """寫入後（newData）這個人在房間裡的位置；用在同一個請求裡一起建立成員的情況。"""
    return "newData.parent().parent().child('members').child(auth.uid).child('slot').val()"


CODE = "root.child('codes').child(newData.child('code').val())"

rules = {
    "rules": {
        "codes": {
            "$code": {
                # 知道碼才讀得到（codes 這層沒有 .read，所以不能整個列出來）
                ".read": ME,
                ".write": one_line(f"""
                    {ME} && (
                      (newData.exists()
                        && (!data.exists() || data.child('exp').val() < now)
                        && newData.child('by').val() === auth.uid
                        && root.child('rooms').child(newData.child('room').val()).child('members').child(auth.uid).exists())
                      || (!newData.exists() && data.exists()
                        && (data.child('by').val() === auth.uid || data.child('exp').val() < now))
                    )"""),
                ".validate": one_line(f"""
                    $code.matches(/^[0-9]{{6}}$/)
                    && newData.hasChildren(['room', 'slot', 'by', 'exp'])"""),
                "room": {".validate": "newData.isString() && newData.val().length <= 40"},
                "slot": {".validate": f"newData.isString() && newData.val().matches({SLOT_RE})"},
                "by": {".validate": "newData.isString()"},
                "exp": {".validate": one_line(f"""
                    newData.isNumber() && newData.val() > now && newData.val() <= now + {CODE_LIFE_MAX_MS}""")},
                "$other": {".validate": False},
            }
        },
        "rooms": {
            "$room": {
                # 房間成員才看得到房間（訊息、名字、狀態）
                ".read": one_line(f"{ME} && data.child('members').child(auth.uid).exists()"),
                "meta": {
                    ".write": one_line(f"{ME} && !data.exists()"),
                    ".validate": "newData.hasChildren(['created', 'size'])",
                    "created": {".validate": "newData.val() === now"},
                    "size": {".validate": f"newData.isNumber() && newData.val() === {len(SLOTS)}"},
                    "$other": {".validate": False},
                },
                "members": {
                    "$uid": {
                        ".write": one_line(f"""
                            {ME} && auth.uid === $uid && (
                              !newData.exists()
                              || (data.exists() && data.child('slot').val() === newData.child('slot').val())
                              || (!data.exists() && !root.child('rooms').child($room).child('meta').exists()
                                  && newData.child('slot').val() === 'a')
                              || (!data.exists() && newData.child('code').isString()
                                  && {CODE}.child('room').val() === $room
                                  && {CODE}.child('slot').val() === newData.child('slot').val()
                                  && {CODE}.child('exp').val() > now)
                            )"""),
                        ".validate": "newData.hasChildren(['slot', 'kind', 'joined'])",
                        "slot": {".validate": f"newData.isString() && newData.val().matches({SLOT_RE})"},
                        "kind": {".validate": "newData.isString() && newData.val().matches(/^(pet|phone)$/)"},
                        "joined": {".validate": "newData.isNumber()"},
                        "code": {".validate": "newData.isString()"},
                        "$other": {".validate": False},
                    }
                },
                "names": {
                    "$slot": {
                        # 只能改自己位置的名字
                        ".write": one_line(f"{ME} && {my_slot_new()} === $slot"),
                        ".validate": one_line(f"""
                            $slot.matches({SLOT_RE}) && newData.isString()
                            && newData.val().length >= 1 && newData.val().length <= 20"""),
                    }
                },
                "messages": {
                    ".indexOn": ["ts"],
                    "$msg": {
                        # 成員可以新增訊息；不能改、不能刪（聊天紀錄）
                        ".write": one_line(f"{ME} && !data.exists() && {member()}.exists()"),
                        ".validate": "newData.hasChildren(['from', 'text', 'ts', 'via'])",
                        "from": {".validate": f"newData.val() === {member()}.child('slot').val()"},
                        "text": {".validate": one_line(f"""
                            newData.isString() && newData.val().length >= 1 && newData.val().length <= {MAX_TEXT}""")},
                        "ts": {".validate": "newData.val() === now"},
                        "via": {".validate": "newData.isString() && newData.val().matches(/^(pet|phone)$/)"},
                        "$other": {".validate": False},
                    }
                },
                "status": {
                    "$slot": {
                        ".write": one_line(f"{ME} && {member()}.child('slot').val() === $slot"),
                        "pet": {".validate": "newData.isNumber() && newData.val() <= now"},
                        "delivered": {".validate": "newData.isNumber() && newData.val() <= now"},
                        "seen": {".validate": "newData.isNumber() && newData.val() <= now"},
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
