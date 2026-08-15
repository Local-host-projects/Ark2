import re
from PIL import Image, ImageDraw

SVG = open("static/logo.svg", encoding="utf-8").read()
GOLD = (201, 162, 39, 255)

paths = re.findall(r'<path d="([^"]+)"', SVG)


def tokenize(d):
    toks = re.findall(r"[MmLlCcSsQqTtZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d)
    return toks


def sample_cubic(p0, p1, p2, p3, n=24):
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


polys = []
for d in paths:
    toks = tokenize(d)
    i = 0
    cur = (0.0, 0.0)
    start = None
    poly = []
    while i < len(toks):
        t = toks[i]
        if t in ("M", "m"):
            i += 1
            cur = (float(toks[i]), float(toks[i + 1]))
            if t == "m":
                pass  # treat as absolute (fine for this file)
            start = cur
            poly = [cur]
            i += 2
        elif t in ("C", "c"):
            c1 = (float(toks[i + 1]), float(toks[i + 2]))
            c2 = (float(toks[i + 3]), float(toks[i + 4]))
            p3 = (float(toks[i + 5]), float(toks[i + 6]))
            if t == "c":
                c1 = (cur[0] + c1[0], cur[1] + c1[1])
                c2 = (cur[0] + c2[0], cur[1] + c2[1])
                p3 = (cur[0] + p3[0], cur[1] + p3[1])
            poly.extend(sample_cubic(cur, c1, c2, p3)[1:])
            cur = p3
            i += 7
        elif t == "z":
            if start:
                poly.append(start)
            polys.append(poly)
            break
        else:
            break

allpts = [p for poly in polys for p in poly]
minx = min(p[0] for p in allpts)
maxx = max(p[0] for p in allpts)
miny = min(p[1] for p in allpts)
maxy = max(p[1] for p in allpts)
w = maxx - minx
h = maxy - miny


def render(size, pad_frac=0.08):
    pad = max(w, h) * pad_frac
    box = (minx - pad, miny - pad, maxx + pad, maxy + pad)
    bw = box[2] - box[0]
    bh = box[3] - box[1]
    scale = size / max(bw, bh)
    img = Image.new("RGBA", (size, size), (16, 14, 11, 255))
    draw = ImageDraw.Draw(img)
    for poly in polys:
        pts = [((p[0] - box[0]) * scale + (size - bw * scale) / 2,
                (p[1] - box[1]) * scale + (size - bh * scale) / 2) for p in poly]
        draw.polygon(pts, fill=GOLD)
    return img


for size in (32, 192, 512):
    img = render(size)
    img.save(f"static/icon-{size}.png", "PNG")
    print(f"wrote static/icon-{size}.png")
