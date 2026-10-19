"""從狗的圖片自動算影子，換圖之後影子會自己跟著變。

做法：
1. 把同一個動作的每一格縮成小格子，疊起來看哪些位置「大部分時間有狗」
2. 只取下半部（尾巴、豎起的耳朵在空中，不會在地上留影子）
3. 對這些點做主成分分析，得到身體的中心、方向、長度、寬度
4. 讓橢圓的最低點剛好貼著腳底，看起來就像影子在狗正下方

這個檔案不依賴 Qt，桌寵程式和預覽工具共用同一套算法。
"""
from __future__ import annotations

import math

GRID = 64                 # 縮成 64×64 來算，夠準又很快
ALPHA_ON = 128            # alpha 大於這個值算「有狗」
KEEP_RATIO = 0.35         # 從上面數下來 35% 以上的部分不算（尾巴、耳朵）
MIN_OCC = 0.34            # 至少三分之一的格子有狗才算（擺動的腳不會讓影子亂跳）
FEET_TOL = 0.035          # 離地面線多近算「腳踩在地上」
FEET_WEIGHT = 0.85        # 影子中心 85% 看腳、15% 看身體


def shadow_from_masks(masks: list[list[list[bool]]],
                      lying: bool = False) -> tuple[float, float, float, float, float] | None:
    """masks: 每一格動畫的 GRID×GRID 布林陣列（masks[f][y][x]）。

    回傳 (cx, cy, a, b, angle_deg)，前四個是 sprite 邊長的比例（0~1），
    angle 是螢幕角度（0 = 水平，正值 = 順時針）。沒有內容時回傳 None。
    lying=True 給躺在地上的動作（翻肚、睡覺）：影子貼著身體本身，不是貼著腳。
    """
    if not masks:
        return None
    n = len(masks)
    occ = [[0] * GRID for _ in range(GRID)]
    for m in masks:
        for y in range(GRID):
            row, orow = m[y], occ[y]
            for x in range(GRID):
                if row[x]:
                    orow[x] += 1
    need = max(1, math.ceil(n * MIN_OCC))
    pts = [(x + 0.5, y + 0.5) for y in range(GRID) for x in range(GRID) if occ[y][x] >= need]
    if len(pts) < 6:
        return None
    top = min(p[1] for p in pts)
    bottom = max(p[1] for p in pts)
    cut = top + KEEP_RATIO * (bottom - top)
    low = [p for p in pts if p[1] >= cut] or pts

    k = len(low)
    mx = sum(p[0] for p in low) / k
    my = sum(p[1] for p in low) / k
    sxx = sum((p[0] - mx) ** 2 for p in low) / k
    syy = sum((p[1] - my) ** 2 for p in low) / k
    sxy = sum((p[0] - mx) * (p[1] - my) for p in low) / k
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)          # 長軸的角度
    tr, det = sxx + syy, sxx * syy - sxy * sxy
    disc = math.sqrt(max(0.0, tr * tr / 4 - det))
    l1, l2 = tr / 2 + disc, max(0.0, tr / 2 - disc)

    a = 1.75 * math.sqrt(l1)                                # 均勻長條：半長 ≈ √3·σ
    b = min(max(1.35 * math.sqrt(l2), 0.05 * GRID), 0.13 * GRID)   # 比身體寬一點，才看得到
    a = max(a, b)

    # 影子中心對準「腳」：找出踩在地上的那幾段（腳底輪廓的下包絡線），
    # 取最前面和最後面那隻腳的中點。頭和耳朵很大，用整隻狗的重心會把影子往前拉。
    cols: dict[int, float] = {}
    for x, y in pts:
        if y > cols.get(int(x), -1.0):
            cols[int(x)] = y
    contour = sorted((x + 0.5, y) for x, y in cols.items())
    hull = _lower_hull(contour)
    tol = FEET_TOL * GRID
    c, s = math.cos(theta), math.sin(theta)
    if lying:
        # 躺著：影子中心就是身體中心，沿著身體的方向，往下貼著身體的底邊
        cx = mx
        span = [y - (x - mx) * math.tan(theta) for x, y in contour if abs(x - mx) <= 0.6 * a]
        base = sorted(span)[len(span) // 2] if span else bottom      # 身體底邊（取中位數，不被頭和腳拉走）
        cy = base + (cx - mx) * math.tan(theta) + 0.015 * GRID - b * 0.6
    else:
        feet = [(x, y) for x, y in contour if y >= _hull_y(hull, x) - tol]
        fx = (feet[0][0] + feet[-1][0]) / 2
        cx = FEET_WEIGHT * fx + (1 - FEET_WEIGHT) * mx
        # 讓橢圓最低點貼在腳底稍微下面一點
        reach_y = math.sqrt((a * s) ** 2 + (b * c) ** 2)
        cy = _hull_y(hull, cx) + 0.03 * GRID - reach_y
    return cx / GRID, cy / GRID, a / GRID, b / GRID, math.degrees(theta)


def _lower_hull(pts):
    """腳底輪廓的下包絡線（螢幕座標 y 往下，所以取 y 最大的那一側）。"""
    hull: list[tuple[float, float]] = []
    for p in pts:
        while len(hull) >= 2:
            (x1, y1), (x2, y2) = hull[-2], hull[-1]
            if (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1) >= 0:
                hull.pop()
            else:
                break
        hull.append(p)
    return hull


def _hull_y(hull, x: float) -> float:
    if x <= hull[0][0]:
        return hull[0][1]
    for (x1, y1), (x2, y2) in zip(hull, hull[1:]):
        if x1 <= x <= x2:
            return y1 + (y2 - y1) * (x - x1) / max(1e-9, x2 - x1)
    return hull[-1][1]


def mirror(params):
    """左右鏡像後的影子參數。"""
    if params is None:
        return None
    cx, cy, a, b, ang = params
    return 1.0 - cx, cy, a, b, -ang
