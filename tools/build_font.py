"""手寫字型產生器：把寫好的 tools/font_template.png 照片 / 掃描檔轉成 TTF。

用法（需要 opencv-python、scikit-image、fonttools）：
    py -m pip install opencv-python scikit-image fonttools
    py tools/build_font.py 寫好的模板.png assets/fonts/EvanHand.ttf

步驟：四角黑方塊 → 透視校正回模板座標 → 取深色墨水（濾掉淺藍導線、灰框）
→ 大寫格若寫了「大寫+小寫」自動左右切開 → 各自貼齊基線
→ 骨架化後統一加粗 → 平滑描邊 → fontTools 組成 TTF
"""
import sys, cv2, numpy as np
from skimage.morphology import skeletonize
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen


def flatten_and_warp(path):
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    if im.shape[2] == 4:
        a = im[:, :, 3:4] / 255.0
        im = (im[:, :, :3] * a + 255 * (1 - a)).astype(np.uint8)
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(g, 80, 255, cv2.THRESH_BINARY_INV)
    n, _, st, cen = cv2.connectedComponentsWithStats(bw)
    marks = [cen[i] for i in range(1, n)
             if 0.7 < st[i][2] / st[i][3] < 1.4 and st[i][2] > 15 and st[i][4] > 0.85 * st[i][2] * st[i][3]]
    if len(marks) < 4:
        sys.exit("找不到四個角的黑方塊")
    marks = np.array(marks)
    s_, d_ = marks.sum(1), marks[:, 0] - marks[:, 1]
    src = np.float32([marks[s_.argmin()], marks[d_.argmax()], marks[d_.argmin()], marks[s_.argmax()]])
    dst = np.float32([[40, 40], [2240, 40], [40, 2660], [2240, 2660]])
    w = cv2.warpPerspective(im, cv2.getPerspectiveTransform(src, dst), (2280, 2700),
                            flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    hsv = cv2.cvtColor(w, cv2.COLOR_BGR2HSV)
    gw = cv2.cvtColor(w, cv2.COLOR_BGR2GRAY)
    return (gw < 120) & (hsv[:, :, 1] < 120)


ink = flatten_and_warp(sys.argv[1])
OUT = sys.argv[2]
CHARS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789") + list("!?.,:-'\"()")
COLS, CELL, M, TOP = 8, 260, 100, 260
U = 5.0                 # font units per template px（cap 140px → 700）
STROKE_R = 6            # 筆畫統一加粗：半徑 6px → 約 13px 寬
SB = 45                 # 左右留白 (units)

def cell(i):
    r, c = divmod(i, COLS)
    return M + c*CELL, TOP + r*CELL

def comps(mask):
    n, lab, st, cen = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return [(lab == k, st[k], cen[k]) for k in range(1, n) if st[k][4] >= 6]

glyph_src = {}   # char -> (mask in full-template coords, baseline_shift_px)
for i, ch in enumerate(CHARS):
    x0, y0 = cell(i)
    m = np.zeros_like(ink)
    m[y0+4:y0+CELL+18, x0+4:x0+CELL-3] = ink[y0+4:y0+CELL+18, x0+4:x0+CELL-3]
    if not m.any():
        continue
    base = y0 + 190
    if i < 26:   # 大寫格裡寫了「大寫+小寫」
        cs = comps(m)
        xs = np.where(m.any(axis=0))[0]
        lo, hi = xs.min(), xs.max()
        prof = m[:, lo:hi+1].sum(axis=0)
        a, b = int(len(prof)*0.3), int(len(prof)*0.8)
        # 最長的空白欄 → 分界；沒有就取最少墨水的欄
        best, run, start = None, 0, None
        for j in range(a, b):
            if prof[j] == 0:
                start = j if run == 0 else start; run += 1
                if best is None or run > best[0]: best = (run, start + run//2)
            else:
                run = 0
        split = lo + (best[1] if best else a + int(np.argmin(prof[a:b])))
        up = np.zeros_like(m); low = np.zeros_like(m)
        for cm, st, cen in cs:
            (up if cen[0] < split else low)[cm] = True
        # 基線對齊：大寫字底部貼齊基線（Q 尾巴、J 例外）
        ys = np.where(up.any(axis=1))[0]
        shift = 0 if ch in "QJ" else base - ys.max()
        if abs(shift) > 25: shift = 0
        glyph_src[ch] = (up, shift)
        lc = ch.lower()
        lshift = shift
        if lc not in "gjpqy":                      # 沒有下伸部的小寫各自貼基線
            lys = np.where(low.any(axis=1))[0]
            ls = base - lys.max()
            if abs(ls) <= 25: lshift = ls
        glyph_src[lc] = (low, lshift)
    else:
        ys = np.where(m.any(axis=1))[0]
        shift = base - ys.max() if ch.isdigit() or ch in "!?.:" else 0
        if abs(shift) > 25: shift = 0
        glyph_src[ch] = (m, shift)

def outline(mask, shift, ch):
    ys, xs = np.where(mask)
    y0, y1, x0, x1 = ys.min()-20, ys.max()+20, xs.min()-20, xs.max()+20
    sub = mask[y0:y1, x0:x1]
    sk = skeletonize(sub)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*STROKE_R+1, 2*STROKE_R+1))
    thick = cv2.dilate(sk.astype(np.uint8)*255, k)
    # 放大 4 倍再模糊 → 平滑邊緣
    S = 4
    big = cv2.resize(thick, None, fx=S, fy=S, interpolation=cv2.INTER_CUBIC)
    big = cv2.GaussianBlur(big, (0, 0), S*1.2)
    _, big = cv2.threshold(big, 127, 255, cv2.THRESH_BINARY)
    cnts, hier = cv2.findContours(big, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    base_y = None
    return cnts, hier, S, (x0, y0)

def build():
    fb = FontBuilder(1000, isTTF=True)
    order = [".notdef", "space"] + [f"g{ord(c):04X}" for c in glyph_src]
    fb.setupGlyphOrder(order)
    cmap = {32: "space"}
    cmap.update({ord(c): f"g{ord(c):04X}" for c in glyph_src})
    fb.setupCharacterMap(cmap)
    glyphs, metrics = {}, {}
    p = TTGlyphPen(None); glyphs[".notdef"] = p.glyph(); metrics[".notdef"] = (500, 0)
    p = TTGlyphPen(None); glyphs["space"] = p.glyph(); metrics["space"] = (300, 0)
    ymin_all, ymax_all = 0, 700
    for ch, (mask, shift) in glyph_src.items():
        cnts, hier, S, (ox, oy) = outline(mask, shift, ch)
        x0, y0 = cell(CHARS.index(ch.upper()) if ch.islower() else CHARS.index(ch))
        base = y0 + 190 - shift
        pen = TTGlyphPen(None)
        pts_all = []
        polys = []
        for ci, cn in enumerate(cnts):
            ap = cv2.approxPolyDP(cn, 1.6, True).reshape(-1, 2).astype(float)
            if len(ap) < 3: continue
            px = (ox + ap[:, 0] / S) * U
            py = (base - (oy + ap[:, 1] / S)) * U
            polys.append((ci, np.stack([px, py], 1)))
            pts_all.append(np.stack([px, py], 1))
        allp = np.concatenate(pts_all)
        minx = allp[:, 0].min()
        for ci, pl in polys:
            pl = pl.copy(); pl[:, 0] += SB - minx
            # TrueType：外框順時針、內洞逆時針（y 朝上）
            area = 0.5 * np.sum(pl[:, 0]*np.roll(pl[:, 1], -1) - np.roll(pl[:, 0], -1)*pl[:, 1])
            is_hole = hier[0][ci][3] != -1
            want_cw = not is_hole
            if (area < 0) != want_cw: pl = pl[::-1]
            pl = np.round(pl).astype(int)
            pen.moveTo(tuple(pl[0]))
            for q in pl[1:]: pen.lineTo(tuple(q))
            pen.closePath()
        glyphs[f"g{ord(ch):04X}"] = pen.glyph()
        w = allp[:, 0].max() - minx
        metrics[f"g{ord(ch):04X}"] = (int(round(w + 2*SB)), SB)
        ymin_all = min(ymin_all, allp[:, 1].min()); ymax_all = max(ymax_all, allp[:, 1].max())
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    asc, desc = int(ymax_all + 60), int(ymin_all - 60)
    fb.setupHorizontalHeader(ascent=asc, descent=desc)
    fam = "EvanHand"
    fb.setupNameTable({"familyName": fam, "styleName": "Regular", "uniqueFontIdentifier": fam + "-Regular",
                       "fullName": fam + " Regular", "psName": fam + "-Regular", "version": "Version 1.0"})
    fb.setupOS2(sTypoAscender=asc, sTypoDescender=desc, sTypoLineGap=100, usWinAscent=asc,
                usWinDescent=-desc, sxHeight=400, sCapHeight=700, achVendID="EVAN", fsType=0)
    fb.setupPost()
    fb.save(OUT)
    print("glyphs", len(glyphs), "asc", asc, "desc", desc)

build()
