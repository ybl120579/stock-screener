# -*- coding: utf-8 -*-
"""生成 App 图标（PWA / iOS 主屏）：深色底 + 渐变折线（首板冲高 → 回踩左侧锚点）。"""
import os
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
os.makedirs(OUT, exist_ok=True)

A = (91, 140, 255)      # #5b8cff
B = (192, 132, 252)     # #c084fc
BG = (13, 18, 32)


def lerp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def make(size, maskable=False, radius_ratio=0.22):
    S = 4  # 超采样，边缘更干净
    W = size * S
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    r = int(W * radius_ratio)
    d.rounded_rectangle([0, 0, W - 1, W - 1], radius=r, fill=BG)

    # 内发光方块：渐变描边
    pad = int(W * 0.10)
    for k in range(0, 6):
        t = k / 5
        d.rounded_rectangle([pad - k * 2, pad - k * 2, W - pad + k * 2, W - pad + k * 2],
                            radius=int(W * 0.16) + k * 2, outline=lerp(A, B, t) + (28,),
                            width=max(1, int(W * 0.006)))

    # 折线坐标（0~1）：起、冲高（首板）、回落（回踩）
    pts = [(0.17, 0.76), (0.30, 0.62), (0.43, 0.40), (0.52, 0.30), (0.60, 0.33),
           (0.72, 0.52), (0.83, 0.74)]
    if maskable:
        pts = [(0.20 + (x - 0.17) * 0.62, 0.50 + (y - 0.53) * 0.62) for x, y in pts]
    lw = max(2, int(W * 0.052 * (0.72 if maskable else 1)))

    # 左侧锚点虚线（回踩目标位）
    ay = pts[0][1] * W
    dash, gap = int(W * 0.035), int(W * 0.022)
    x = int(W * 0.13)
    while x < W * 0.87:
        d.line([x, ay, min(x + dash, W * 0.87), ay],
               fill=(143, 178, 255, 110), width=max(2, int(W * 0.010)))
        x += dash + gap

    # 用分段插值画渐变线
    total = len(pts) - 1
    for i in range(total):
        x1, y1 = pts[i][0] * W, pts[i][1] * W
        x2, y2 = pts[i + 1][0] * W, pts[i + 1][1] * W
        col = lerp(A, B, i / (total - 1))
        d.line([x1, y1, x2, y2], fill=col + (255,), width=lw, joint="curve")
        rr = lw // 2
        d.ellipse([x1 - rr, y1 - rr, x1 + rr, y1 + rr], fill=col + (255,))
        if i == total - 1:
            d.ellipse([x2 - rr, y2 - rr, x2 + rr, y2 + rr], fill=col + (255,))

    # 起点圆点（回踩锚点）
    x0, y0 = pts[-1][0] * W, pts[-1][1] * W
    rr = int(W * 0.030)
    d.ellipse([x0 - rr, y0 - rr, x0 + rr, y0 + rr], fill=(255, 255, 255, 240))

    return img.resize((size, size), Image.LANCZOS)


for s in (192, 512):
    make(s).save(os.path.join(OUT, f"icon-{s}.png"))
    print("icon-%d.png" % s)
make(512, maskable=True).save(os.path.join(OUT, "icon-512-maskable.png"))
make(180, radius_ratio=0.0).save(os.path.join(OUT, "icon-180.png"))   # iOS 自己加圆角
print("icon-512-maskable.png / icon-180.png")
