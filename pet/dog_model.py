"""純 Python 的臘腸狗草圖模型（不依賴 Qt）。

狗由一串串 3D「管子」（連續的球）組成，局部座標：
    x = 往前（鼻子方向）, y = 狗的左邊, z = 往上, 地面 z = 0
畫的時候把每個管子投影成一排重疊的圓，所以同一個模型可以轉成 8 個方向。
Qt 程式（pet/sprites.py）和 Pillow 匯出工具（tools/export_sketches.py）
都只吃 build() 輸出的繪圖指令，兩邊畫出來會一樣。

座標輸出單位是「sprite 邊長的比例」(0~1)，renderer 再乘上像素大小。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# ---- 視角與版面 -------------------------------------------------------------
ELEVATION_DEG = 30.0                      # 3/4 視角的俯角
_SIN_E = math.sin(math.radians(ELEVATION_DEG))
_COS_E = math.cos(math.radians(ELEVATION_DEG))
GROUND_Y = 0.64                           # 影子中心（狗的腳底中點）在 sprite 的高度比例
HELD_GRAB = (0.5, 0.16)                   # 被拎起來時，游標抓住的位置（脖子）
OUTLINE = 0.012                           # 線條粗細（比例）

# 你參考圖的配色：頭紅、身體藍、腿黃、尾巴綠
PALETTE = {
    "head": "#E5483A",
    "body": "#2F5BEA",
    "leg": "#E8B21E",
    "tail": "#3DB54A",
    "ink": "#2B2B2B",
    "fill": "#FFFFFF",
    "belly": "#FFF1DC",
}

# ---- 動畫表 -----------------------------------------------------------------
# 名稱: (格數, 每秒格數, 是否分方向)
ANIMS = {
    "walk": (6, 10, True),
    "run": (6, 16, True),
    "idle": (4, 3, False),
    "sit": (4, 4, False),
    "sleep": (2, 1.2, False),
    "held": (6, 6, False),
    "happy": (6, 10, False),
    "belly": (6, 8, False),
}

DIRS8 = ["right", "down_right", "down", "down_left", "left", "up_left", "up", "up_right"]
DRAWN_DIRS = ["down", "down_right", "right", "up_right", "up"]       # 要畫的 5 個方向
MIRROR_OF = {"left": "right", "up_left": "up_right", "down_left": "down_right"}  # 其餘鏡像
DIR_ANGLE = {d: i * 45.0 for i, d in enumerate(DIRS8)}               # 螢幕角度，0=右, 90=下

# 不分方向的動作，畫的時候狗朝哪個角度
FRONT_ANGLE = {"idle": 60.0, "sit": 75.0, "sleep": 90.0, "held": 90.0, "happy": 60.0, "belly": 20.0}


def angle_to_dir(dx: float, dy: float) -> str:
    """螢幕上的移動向量 → 8 方向名稱（螢幕 y 往下為正）。"""
    ang = math.degrees(math.atan2(dy, dx)) % 360.0
    return DIRS8[int(round(ang / 45.0)) % 8]


# ---- 模型零件 ---------------------------------------------------------------
@dataclass
class Part:
    kind: str                 # "tube" 或 "line"
    points: list              # tube: [(x,y,z,r)]；line: [(x,y,z),(x,y,z)]
    outline: str | None       # 外框顏色 key；None = 不描邊
    fill: str = "fill"        # 填色 key
    width: float = 0.0        # line 的粗細
    bias: float = 0.0         # 深度偏移（正值 = 更靠前畫），給鼻子這種貼在表面的小東西


@dataclass
class Op:
    """投影後的繪圖指令，renderer 照順序畫就好。"""
    kind: str                 # "discs" | "line" | "text"
    data: list                # discs: [(u,v,r)]；line: [(u0,v0),(u1,v1)]；text: [(u,v)]
    outline: str | None
    fill: str
    width: float = 0.0
    text: str = ""


def _tube(points, outline, fill="fill", step=0.45, bias=0.0):
    """把控制點 (x,y,z,r) 補成夠密的一串球，看起來就是一根平滑的管子。"""
    out = []
    for a, b in zip(points, points[1:]):
        d = math.dist(a[:3], b[:3])
        n = max(1, math.ceil(d / (min(a[3], b[3]) * step)))
        for i in range(n):
            t = i / n
            out.append(tuple(a[k] + (b[k] - a[k]) * t for k in range(4)))
    out.append(tuple(points[-1]))
    return Part("tube", out, outline, fill, bias=bias)


def _ball(x, y, z, r, outline, fill="fill", bias=0.0):
    return Part("tube", [(x, y, z, r)], outline, fill, bias=bias)


def _line(a, b, width, color):
    return Part("line", [a, b], None, color, width=width)


def _place(parts, dx=0.0, dy=0.0, dz=0.0, yaw_deg=0.0):
    """把一組零件繞 z 軸轉 yaw 再平移。"""
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))

    def tf(x, y, z):
        return x * c - y * s + dx, x * s + y * c + dy, z + dz

    out = []
    for p in parts:
        if p.kind == "tube":
            pts = [tf(x, y, z) + (r,) for x, y, z, r in p.points]
        else:
            pts = [tf(*q) for q in p.points]
        out.append(Part(p.kind, pts, p.outline, p.fill, p.width, p.bias))
    return out


# ---- 身體部位 ---------------------------------------------------------------
def _head(*, eyes_open=True, ear_tip=(-0.015, 0.095, -0.15)):
    """頭（頭骨中心在原點、朝 +x）：大圓頭 + 長嘴 + 垂耳，照參考圖。"""
    parts = [
        _ball(0.0, 0.0, 0.0, 0.085, "head"),
        _tube([(0.06, 0.0, -0.015, 0.045), (0.19, 0.0, -0.055, 0.028)], "head"),
        _ball(0.205, 0.0, -0.052, 0.017, None, "ink", bias=0.06),          # 鼻子
    ]
    ex, ey, ez = ear_tip
    for side in (1, -1):
        if eyes_open:
            parts.append(_ball(0.06, side * 0.05, 0.035, 0.012, None, "ink"))
        else:
            parts.append(_line((0.048, side * 0.052, 0.038), (0.074, side * 0.048, 0.03), 0.008, "ink"))
        parts.append(_tube([(-0.035, side * 0.075, 0.045, 0.03), (ex - 0.025, side * ey, ez, 0.036)], "head"))
    return parts


def _legs(front_x, back_x, phase, amp, lift, gallop, hip_z):
    """四條短腿 + 小腳掌。walk 用對角步（trot），run 用前後腳一起（gallop）。"""
    tau = 2 * math.pi * phase
    if gallop:
        legs = [(front_x, 1, 0.0), (front_x, -1, 0.5), (back_x, 1, math.pi), (back_x, -1, math.pi + 0.5)]
    else:
        legs = [(front_x, 1, 0.0), (front_x, -1, math.pi), (back_x, 1, math.pi), (back_x, -1, 0.0)]
    parts = []
    for lx, side, ph in legs:
        dx = math.sin(tau + ph) * amp
        up = max(0.0, math.cos(tau + ph)) * lift
        y = side * 0.05
        fz = 0.025 + up
        parts.append(_tube([(lx, y, hip_z, 0.028), (lx + dx, y, fz + 0.01, 0.025)], "leg"))
        parts.append(_tube([(lx + dx, y, fz, 0.027), (lx + dx + 0.028, y, fz, 0.024)], "leg"))
    return parts


# ---- 姿勢 -------------------------------------------------------------------
# 每個姿勢回傳 (零件, x 位移讓狗置中, 額外繪圖指令)

def _standing(phase, *, amp=0.0, lift=0.0, gallop=False, bob=0.0, wag=0.02,
              breathe=0.0, ear_tip=(-0.015, 0.095, -0.15)):
    z = 0.17 + bob
    r = 0.085 * (1.0 + breathe)
    w = math.sin(4 * math.pi * phase) * wag
    parts = [
        _tube([(-0.26, 0.0, z, r), (0.18, 0.0, z, r * 0.95)], "body"),
        _tube([(0.15, 0.0, z + 0.02, 0.075), (0.27, 0.0, z + 0.12, 0.065)], "head"),   # 脖子
        _tube([(-0.27, 0.0, z + 0.03, 0.03), (-0.31, w * 0.5, z + 0.13, 0.022),
               (-0.33, w, z + 0.24, 0.01)], "tail"),
    ]
    parts += _place(_head(ear_tip=ear_tip), 0.31, 0.0, z + 0.14)
    parts += _legs(0.13, -0.20, phase, amp, lift, gallop, hip_z=z - 0.04)
    return parts, 0.10, []


def _walk(phase):
    return _standing(phase, amp=0.035, lift=0.02,
                     bob=0.006 * (1 - math.cos(4 * math.pi * phase)) / 2, wag=0.03)


def _run(phase):
    flap = 0.5 + 0.5 * math.sin(2 * math.pi * phase)
    return _standing(phase, amp=0.06, lift=0.035, gallop=True,
                     bob=0.015 * (1 - math.cos(2 * math.pi * phase)) / 2, wag=0.02,
                     ear_tip=(-0.06 - 0.05 * flap, 0.11, -0.10 + 0.07 * flap))


def _idle(phase):
    return _standing(phase, breathe=0.025 * math.sin(2 * math.pi * phase), wag=0.02)


def _happy(phase):
    hop = abs(math.sin(2 * math.pi * phase))
    return _standing(phase, bob=0.03 * hop, wag=0.08, ear_tip=(-0.04, 0.11, -0.13 + 0.05 * hop))


def _sit(phase):
    w = math.sin(4 * math.pi * phase) * 0.03
    parts = [
        _tube([(-0.12, 0.0, 0.09, 0.09), (0.08, 0.0, 0.24, 0.08)], "body"),
        _tube([(0.08, 0.0, 0.25, 0.072), (0.15, 0.0, 0.36, 0.065)], "head"),
        _tube([(-0.20, 0.0, 0.05, 0.028), (-0.30, w, 0.035, 0.02), (-0.38, 2 * w, 0.03, 0.01)], "tail"),
    ]
    parts += _place(_head(), 0.19, 0.0, 0.42)
    for side in (1, -1):
        y = side * 0.05
        parts.append(_tube([(0.10, y, 0.20, 0.028), (0.12, y, 0.035, 0.025)], "leg"))
        parts.append(_tube([(0.12, y, 0.025, 0.027), (0.15, y, 0.025, 0.024)], "leg"))
        parts.append(_ball(-0.07, side * 0.085, 0.07, 0.05, "leg"))
        parts.append(_tube([(-0.02, side * 0.09, 0.025, 0.027), (0.02, side * 0.09, 0.025, 0.024)], "leg"))
    return parts, 0.0, []


def _sleep(phase):
    br = 1.0 + 0.02 * math.sin(2 * math.pi * phase)
    rad = 0.13 * br
    pts = []
    n = 10
    for i in range(n):
        t = math.radians(215 - i * (230 / (n - 1)))       # 從屁股繞到胸口
        pts.append((rad * math.cos(t), rad * math.sin(t), 0.075, 0.08 * br))
    parts = [_tube(pts, "body")]
    # 尾巴沿著圈圈收在地上
    t0, t1 = math.radians(215), math.radians(250)
    parts.append(_tube([(rad * math.cos(t0), rad * math.sin(t0), 0.05, 0.026),
                        (0.2 * math.cos(t1), 0.2 * math.sin(t1), 0.035, 0.012)], "tail"))
    # 頭靠在尾巴旁邊，閉眼
    ha = math.radians(-60)
    hx, hy = rad * 0.95 * math.cos(ha), rad * 0.95 * math.sin(ha)
    tx, ty = rad * math.cos(math.radians(205)), rad * math.sin(math.radians(205))
    yaw = math.degrees(math.atan2(ty - hy, tx - hx))
    parts += _place(_head(eyes_open=False, ear_tip=(-0.05, 0.12, -0.06)), hx, hy, 0.09, yaw)
    z_text = "z" if phase < 0.5 else "z Z"
    extras = [Op("text", [(0.66, 0.30 - 0.04 * (phase % 0.5))], None, "ink", 0.10, z_text)]
    return parts, 0.0, extras


def _held(phase):
    s = math.sin(2 * math.pi * phase)
    st = 0.03 * s                                   # 被拎著會一直變長變短 😂

    def sway(z):
        return (0.55 - z) * 0.06 * s

    parts = [
        _tube([(0.0, 0.0, 0.55, 0.075), (-0.005, sway(0.2), 0.2, 0.085),
               (-0.01, sway(-0.14), -0.14 - st, 0.085)], "body"),
        _tube([(-0.03, sway(-0.16), -0.16 - st, 0.028),
               (-0.05, sway(-0.3) * 1.5, -0.30 - st, 0.012)], "tail"),
    ]
    parts += _place(_head(), 0.02, 0.0, 0.62)
    for side in (1, -1):
        k = math.sin(2 * math.pi * phase + side)
        parts.append(_tube([(0.05, side * 0.055, 0.47, 0.027),
                            (0.07, side * 0.07, 0.37 + 0.02 * k, 0.025)], "leg"))
        parts.append(_tube([(0.02, side * 0.055 + sway(-0.1), -0.10 - st, 0.027),
                            (0.03, side * 0.07 + sway(-0.2), -0.21 - st + 0.02 * k, 0.025)], "leg"))
    return parts, 0.0, []


def _belly(phase):
    w = 0.04 * math.sin(4 * math.pi * phase)
    parts = [
        _tube([(-0.24, 0.0, 0.09, 0.085), (0.16, 0.0, 0.09, 0.08)], "body", fill="belly"),
        _tube([(-0.30, 0.0, 0.08, 0.028), (-0.38, w * 0.5, 0.06, 0.02), (-0.45, w, 0.05, 0.01)], "tail"),
    ]
    parts += _place(_head(eyes_open=False, ear_tip=(-0.03, 0.14, -0.06)), 0.27, 0.0, 0.085)
    for lx, front in ((0.10, True), (-0.18, False)):
        for side in (1, -1):
            k = math.sin(2 * math.pi * phase + (0 if side > 0 else math.pi) + (0 if front else math.pi / 2))
            px = lx + 0.03 * k
            parts.append(_tube([(lx, side * 0.05, 0.14, 0.027), (px, side * 0.065, 0.25, 0.024)], "leg"))
            parts.append(_ball(px, side * 0.065, 0.265, 0.027, "leg"))
    return parts, 0.0, []


POSES = {
    "walk": _walk, "run": _run, "idle": _idle, "happy": _happy,
    "sit": _sit, "sleep": _sleep, "held": _held, "belly": _belly,
}


# ---- 投影 -------------------------------------------------------------------
def _project(parts, angle_deg, shift_x):
    a = math.radians(angle_deg)
    fx, fy = math.cos(a), -math.sin(a)        # 狗面向的方向（世界座標，Y 往畫面深處）
    lx, ly = -fy, fx                          # 狗的左邊

    def proj(x, y, z):
        x -= shift_x
        wx = x * fx + y * lx
        wy = x * fy + y * ly
        u = 0.5 + wx
        v = GROUND_Y - (wy * _SIN_E + z * _COS_E)
        depth = wy * _COS_E - z * _SIN_E       # 越大越遠，先畫
        return u, v, depth

    staged = []
    for p in parts:
        if p.kind == "tube":
            pts = [proj(x, y, z) + (r,) for x, y, z, r in p.points]
            depth = sum(q[2] for q in pts) / len(pts) - p.bias
            staged.append((depth, Op("discs", [(u, v, r) for u, v, _, r in pts], p.outline, p.fill)))
        else:
            (u0, v0, d0), (u1, v1, d1) = proj(*p.points[0]), proj(*p.points[1])
            staged.append(((d0 + d1) / 2 - p.bias, Op("line", [(u0, v0), (u1, v1)], None, p.fill, p.width)))
    staged.sort(key=lambda t: -t[0])
    return [op for _, op in staged]


def build(anim: str, direction: str, phase: float) -> list[Op]:
    """回傳某動作、某方向、某一格（phase 0~1）的繪圖指令。"""
    parts, shift, extras = POSES[anim](phase % 1.0)
    angle = DIR_ANGLE[direction] if ANIMS[anim][2] else FRONT_ANGLE[anim]
    return _project(parts, angle, shift) + extras
