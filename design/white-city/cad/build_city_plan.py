"""按参考效果图「上视图」重建城市总平面图,输出 DXF(R12,AutoCAD / 各类 CAD 看图软件均可打开)。

    python design/white-city/cad/build_city_plan.py

产物(同目录):
    city_plan.dxf          CAD 图纸,单位 米,模型空间 1:1,按 1:2000 出图
    city_plan_preview.png  同一份几何画出的预览图,核对用

这是**依参考图的意向重建**,不是测绘:主干路走向、河道、桥、山体、高层组团的位置按参考图摆放,
街坊内部的建筑、行道树是按规则生成的。地形用若干山体叠加出高程场,再抽 5 m 等高线。

图层:
    TERRAIN-CONTOUR   首曲线(5 m)          TERRAIN-INDEX  计曲线(25 m,带高程标注)
    TERRAIN-SPOT      山顶高程点
    WATER             河道岸线               BRIDGE         桥梁
    ROAD-EDGE         道路边线               ROAD-CENTER    道路中心线(点划线)
    BLOCK             街坊用地边界           BUILDING       建筑轮廓
    BUILDING-TOWER    高层建筑轮廓(带层数)  TREE           树木
    ANNO              文字标注               FRAME          图框、指北针、比例尺
"""

import math
import random
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import shapely  # noqa: E402
from shapely.affinity import rotate  # noqa: E402
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

OUT = Path(__file__).resolve().parent
random.seed(20260916)
np.random.seed(20260916)

# ---------------------------------------------------------------- 坐标
# 参考图上视图面板约 700 × 525 像素;比例尺 1000 m ≈ 175 px,即 1 px ≈ 5.7 m。
# 图像坐标 y 向下,CAD 坐标 Y 向上。
PX = 5.7
W, H = 700 * PX, 525 * PX


def P(x, y):
    return (x * PX, (525 - y) * PX)


def pts(seq):
    return [P(x, y) for x, y in seq]


def smooth(points, n=12):
    """Catmull-Rom 平滑,让道路、河道成为连续曲线而不是折线。"""
    p = [points[0]] + list(points) + [points[-1]]
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = map(np.array, (p[i - 1], p[i], p[i + 1], p[i + 2]))
        for t in np.linspace(0, 1, n, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                                    + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)))
    out.append(points[-1])
    return out


# ---------------------------------------------------------------- 主要线形(按参考图摆放)
RING = smooth(pts([(-10, 236), (90, 226), (200, 210), (320, 188), (430, 160), (520, 128), (610, 98), (710, 76)]))
AVENUE = smooth(pts([(-10, 276), (150, 268), (300, 252), (430, 226), (560, 192), (710, 160)]))
WATERFRONT = smooth(pts([(-10, 312), (120, 318), (250, 326), (345, 326), (440, 308), (570, 272), (710, 240)]))
RIVER = smooth(pts([(-10, 356), (90, 352), (180, 360), (260, 376), (330, 396), (400, 422), (455, 452), (500, 490),
                    (525, 535)]))
BRIDGE = smooth(pts([(222, 432), (238, 400), (262, 368), (300, 340), (345, 326)]), 16)
SOUTH_RD = smooth(pts([(222, 432), (205, 470), (190, 535)]))
RIVERSIDE_E = smooth(pts([(440, 308), (485, 345), (560, 365), (640, 352), (710, 330)]))
HILL_RD = smooth(pts([(60, 535), (110, 470), (150, 440), (222, 432)]))

MAJOR = [(RING, 40), (AVENUE, 30), (WATERFRONT, 34), (SOUTH_RD, 22), (RIVERSIDE_E, 22), (HILL_RD, 16)]

EXTENT = box(0, 0, W, H)
river_poly = LineString(RIVER).buffer(48, cap_style="flat").intersection(EXTENT)

# 城区:北环路与滨水路之间
city_poly = Polygon(RING + WATERFRONT[::-1]).buffer(0).intersection(EXTENT)

# ---------------------------------------------------------------- 路网
# 城区街道顺着中央大道的弧度走:纵向街道是大道的平行偏移线,横向街道沿大道法线方向。
avenue_ls = LineString(AVENUE)
streets = []
for k in range(-6, 7):
    if k == 0:
        continue
    off = avenue_ls.offset_curve(k * 235)
    part = off.intersection(city_poly.buffer(-5))
    if not part.is_empty:
        streets.extend(getattr(part, "geoms", [part]))
for d in np.arange(120, avenue_ls.length, 205):
    a_, b_ = avenue_ls.interpolate(d - 5), avenue_ls.interpolate(d + 5)
    tx, ty = b_.x - a_.x, b_.y - a_.y
    n = math.hypot(tx, ty)
    nx_, ny_ = -ty / n, tx / n
    c_ = avenue_ls.interpolate(d)
    cross = LineString([(c_.x - nx_ * 2000, c_.y - ny_ * 2000), (c_.x + nx_ * 2000, c_.y + ny_ * 2000)])
    part = cross.intersection(city_poly.buffer(-5))
    if not part.is_empty:
        streets.extend(getattr(part, "geoms", [part]))
streets = [s_ for s_ in streets if s_.length > 80]

road_polys = [LineString(line).buffer(w / 2, cap_style="flat") for line, w in MAJOR]
road_polys += [s.buffer(7, cap_style="flat") for s in streets]
bridge_poly = LineString(BRIDGE).buffer(12, cap_style="flat")
roads = unary_union(road_polys).difference(river_poly).intersection(EXTENT)

# ---------------------------------------------------------------- 街坊与建筑
blocks = city_poly.difference(unary_union([roads, river_poly]).buffer(4))
blocks = [b for b in getattr(blocks, "geoms", [blocks]) if b.area > 4000]

TOWER_ZONE = Polygon(pts([(520, 120), (700, 90), (700, 280), (540, 300), (500, 220)]))
buildings, towers = [], []
for blk in blocks:
    parcel = blk.buffer(-9)
    if parcel.is_empty:
        continue
    # 建筑朝向跟街坊走:取街坊最小外接矩形长边的方向
    mrr = list(blk.minimum_rotated_rectangle.exterior.coords)
    e1 = (mrr[1][0] - mrr[0][0], mrr[1][1] - mrr[0][1])
    e2 = (mrr[2][0] - mrr[1][0], mrr[2][1] - mrr[1][1])
    ex, ey = e1 if math.hypot(*e1) >= math.hypot(*e2) else e2
    angle = math.degrees(math.atan2(ey, ex))
    ocx, ocy = blk.centroid.x, blk.centroid.y
    local = rotate(parcel, -angle, origin=(ocx, ocy))
    minx, miny, maxx, maxy = local.bounds
    is_tower = blk.centroid.within(TOWER_ZONE)
    x = minx
    while x < maxx:
        lot_w = random.uniform(55, 90) if is_tower else random.uniform(32, 64)
        for side in (0, 1):
            depth = (maxy - miny) / 2
            y0 = miny + side * depth
            bw = lot_w * random.uniform(0.55, 0.85)
            bd = min(depth * random.uniform(0.5, 0.8), 70 if not is_tower else 90)
            bx = x + (lot_w - bw) / 2
            by = y0 + (depth - bd) * (0.15 if side == 0 else 0.85)
            fp = box(bx, by, bx + bw, by + bd)
            if fp.within(local) and fp.area > 250:
                g = rotate(fp, angle, origin=(ocx, ocy))
                (towers if is_tower and random.random() < 0.7 else buildings).append(g)
        x += lot_w + random.uniform(4, 10)

# 城外零散住宅(南岸坡地、东侧滨河路两侧)
scatter_zone = unary_union([
    Polygon(pts([(20, 400), (200, 390), (240, 470), (160, 525), (20, 525)])),
    Polygon(pts([(430, 340), (700, 330), (700, 470), (560, 480), (470, 430)])),
    Polygon(pts([(40, 320), (240, 330), (230, 365), (40, 345)])),
])
blocked = unary_union([roads.buffer(10), river_poly.buffer(20), bridge_poly.buffer(10)])
for _ in range(2600):
    x, y = random.uniform(0, W), random.uniform(0, H)
    pt = Point(x, y)
    if not pt.within(scatter_zone) or pt.within(blocked):
        continue
    w, d = random.uniform(14, 26), random.uniform(10, 18)
    fp = rotate(box(x - w / 2, y - d / 2, x + w / 2, y + d / 2), random.uniform(-20, 30), origin=(x, y))
    if not fp.intersects(blocked) and not any(fp.buffer(6).intersects(b) for b in buildings[-40:]):
        buildings.append(fp)

# ---------------------------------------------------------------- 地形
xs = np.linspace(0, W, 420)
ys = np.linspace(0, H, 315)
X, Y = np.meshgrid(xs, ys)


def hill(px, py, peak, sx, sy):
    x0, y0 = P(px, py)
    return peak * np.exp(-(((X - x0) / sx) ** 2 + ((Y - y0) / sy) ** 2))


Z = (12 + 0.004 * Y
     + hill(140, 140, 88, 520, 300)        # 西北山体
     + hill(330, 96, 52, 360, 220)         # 北侧小山
     + hill(20, 485, 80, 640, 380)         # 西南台地山
     + hill(690, 480, 50, 420, 300)        # 东南坡地
     + hill(610, 40, 62, 460, 260))        # 东北山脚

# 自然起伏:几组低频正弦叠加,让山体等高线不再是规整的同心椭圆
rng_t = np.random.default_rng(7)
for _ in range(7):
    kx, ky = rng_t.uniform(1 / 1800, 1 / 650, 2) * rng_t.choice([-1, 1], 2)
    Z += rng_t.uniform(1.5, 4.0) * np.sin(2 * math.pi * (kx * X + ky * Y) + rng_t.uniform(0, 6.3))

# 河谷下切
river_line = LineString(RIVER)
dist = shapely.distance(shapely.points(X.ravel(), Y.ravel()), river_line).reshape(X.shape)
Z -= 14 * np.exp(-(dist / 180) ** 2)

# 城区台地化:建成区地面拉平到接近 22 m,再做平滑,避免等高线在城区边缘断崖
in_city = shapely.contains_xy(city_poly.buffer(60), X, Y)
Z = np.where(in_city, 22 + 0.12 * (Z - 22), Z)
for _ in range(6):
    # 边缘复制填充再平均。np.roll 会把图幅对边的高程卷进来,在图框边上画出一圈假等高线
    Zp = np.pad(Z, 1, mode="edge")
    Z = (Zp[1:-1, 1:-1] + Zp[:-2, 1:-1] + Zp[2:, 1:-1] + Zp[1:-1, :-2] + Zp[1:-1, 2:]) / 5

levels = np.arange(10, float(Z.max()), 5)
cs = plt.figure().add_subplot().contour(X, Y, Z, levels=levels)
contours = []   # (level, [(x, y), ...])
for level, segs in zip(cs.levels, cs.allsegs):
    for seg in segs:
        if len(seg) < 4:
            continue
        line = LineString(seg)
        # 城区、河道里不画等高线(平面图上被建成区和水面覆盖)
        clipped = line.difference(unary_union([city_poly.buffer(-30), river_poly]))
        for part in getattr(clipped, "geoms", [clipped]):
            if part.length > 60:
                contours.append((float(level), list(part.coords)))
plt.close("all")

peaks = [(P(140, 140), None), (P(330, 96), None), (P(20, 485), None), (P(690, 480), None), (P(610, 40), None)]
spot_heights = []
for (px, py), _ in peaks:
    if 0 < px < W and 0 < py < H:
        i = int(py / H * (len(ys) - 1))
        j = int(px / W * (len(xs) - 1))
        spot_heights.append((px, py, float(Z[i, j])))

# ---------------------------------------------------------------- 树
tree_zones = unary_union([
    Polygon(pts([(440, 95), (580, 70), (600, 130), (470, 160)])),            # 东北树丛
    Polygon(pts([(0, 150), (300, 120), (330, 175), (0, 215)])),               # 北侧山脚
    Polygon(pts([(0, 380), (240, 385), (230, 525), (0, 525)])),               # 西南坡
    Polygon(pts([(470, 400), (700, 360), (700, 525), (520, 525)])),           # 东南坡
    river_poly.buffer(70).difference(river_poly.buffer(18)),                   # 河岸带
])
no_tree = unary_union([roads.buffer(3), river_poly, bridge_poly, unary_union(buildings + towers).buffer(4)])
trees = []
occupied = []
for _ in range(9000):
    x, y = random.uniform(0, W), random.uniform(0, H)
    pt = Point(x, y)
    if pt.within(tree_zones) and not pt.within(no_tree) and random.random() < 0.55:
        r = random.uniform(5, 10)
        if all((x - a) ** 2 + (y - b) ** 2 > (r + c + 2) ** 2 for a, b, c in occupied[-200:]):
            occupied.append((x, y, r))
            trees.append((x, y, r))
# 行道树:滨水路、主干道两侧
for line, width in [(WATERFRONT, 34), (AVENUE, 30), (RING, 40)]:
    ls = LineString(line)
    for side in (-1, 1):
        off = ls.offset_curve(side * (width / 2 + 6))
        for d in np.arange(10, off.length, 28):
            p = off.interpolate(d)
            if 0 < p.x < W and 0 < p.y < H and not p.within(no_tree.difference(roads.buffer(3))):
                trees.append((p.x, p.y, 5.0))

# ---------------------------------------------------------------- DXF 输出(R12 ASCII)
LAYERS = {
    "TERRAIN-CONTOUR": 8, "TERRAIN-INDEX": 252, "TERRAIN-SPOT": 8,
    "WATER": 5, "BRIDGE": 30, "ROAD-EDGE": 7, "ROAD-CENTER": 1,
    "BLOCK": 9, "BUILDING": 7, "BUILDING-TOWER": 6, "TREE": 3, "ANNO": 7, "FRAME": 7,
}


def enc(text):
    """非 ASCII 字符写成 \\U+XXXX,CAD 读 R12 时按 Unicode 显示,不依赖系统代码页。"""
    return "".join(ch if ord(ch) < 128 else f"\\U+{ord(ch):04X}" for ch in text)


class Dxf:
    def __init__(self):
        self.ents = []

    def _add(self, *pairs):
        self.ents.extend(pairs)

    def poly(self, layer, coords, closed=False):
        coords = [c for c in coords]
        if len(coords) < 2:
            return
        self._add((0, "POLYLINE"), (8, layer), (66, 1), (10, 0.0), (20, 0.0), (30, 0.0), (70, 1 if closed else 0))
        for x, y in coords:
            self._add((0, "VERTEX"), (8, layer), (10, round(x, 3)), (20, round(y, 3)), (30, 0.0))
        self._add((0, "SEQEND"), (8, layer))

    def geom(self, layer, g):
        for part in getattr(g, "geoms", [g]):
            if isinstance(part, Polygon):
                self.poly(layer, list(part.exterior.coords)[:-1], True)
                for ring in part.interiors:
                    self.poly(layer, list(ring.coords)[:-1], True)
            elif isinstance(part, LineString):
                self.poly(layer, list(part.coords))

    def circle(self, layer, x, y, r):
        self._add((0, "CIRCLE"), (8, layer), (10, round(x, 3)), (20, round(y, 3)), (30, 0.0), (40, round(r, 3)))

    def line(self, layer, a, b):
        self._add((0, "LINE"), (8, layer), (10, a[0]), (20, a[1]), (30, 0.0), (11, b[0]), (21, b[1]), (31, 0.0))

    def text(self, layer, x, y, h, s, rot=0.0, align=0):
        pairs = [(0, "TEXT"), (8, layer), (7, "CN"), (10, round(x, 3)), (20, round(y, 3)), (30, 0.0),
                 (40, h), (1, enc(s)), (50, round(rot, 2))]
        if align:
            pairs += [(72, align), (11, round(x, 3)), (21, round(y, 3)), (31, 0.0)]
        self._add(*pairs)

    def write(self, path):
        out = []

        def g(code, value):
            out.append(f"{code:>3}\n{value}\n")

        g(0, "SECTION"); g(2, "HEADER")
        g(9, "$ACADVER"); g(1, "AC1009")
        g(9, "$DWGCODEPAGE"); g(3, "ANSI_936")
        g(9, "$EXTMIN"); g(10, -200.0); g(20, -700.0); g(30, 0.0)
        g(9, "$EXTMAX"); g(10, W + 200); g(20, H + 200); g(30, 0.0)
        g(9, "$LTSCALE"); g(40, 20.0)
        g(0, "ENDSEC")

        g(0, "SECTION"); g(2, "TABLES")
        g(0, "TABLE"); g(2, "LTYPE"); g(70, 2)
        g(0, "LTYPE"); g(2, "CONTINUOUS"); g(70, 0); g(3, "Solid line"); g(72, 65); g(73, 0); g(40, 0.0)
        g(0, "LTYPE"); g(2, "CENTER"); g(70, 0); g(3, "Center ____ _ ____ _"); g(72, 65); g(73, 4); g(40, 2.0)
        for v in (1.25, -0.25, 0.25, -0.25):
            g(49, v)
        g(0, "ENDTAB")
        g(0, "TABLE"); g(2, "STYLE"); g(70, 1)
        g(0, "STYLE"); g(2, "CN"); g(70, 0); g(40, 0.0); g(41, 1.0); g(50, 0.0); g(71, 0); g(42, 10.0)
        g(3, "simsun.ttc"); g(4, "")
        g(0, "ENDTAB")
        g(0, "TABLE"); g(2, "LAYER"); g(70, len(LAYERS))
        for name, color in LAYERS.items():
            g(0, "LAYER"); g(2, name); g(70, 0); g(62, color)
            g(6, "CENTER" if name == "ROAD-CENTER" else "CONTINUOUS")
        g(0, "ENDTAB")
        g(0, "ENDSEC")

        g(0, "SECTION"); g(2, "ENTITIES")
        for code, value in self.ents:
            g(code, value)
        g(0, "ENDSEC")
        g(0, "EOF")
        path.write_text("".join(out), encoding="ascii")


dxf = Dxf()

for level, coords in contours:
    index = abs(level % 25) < 1e-6
    dxf.poly("TERRAIN-INDEX" if index else "TERRAIN-CONTOUR", coords)
    if index and len(coords) > 20:
        i = len(coords) // 2
        (x1, y1), (x2, y2) = coords[i], coords[i + 1]
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if ang > 90 or ang < -90:
            ang += 180
        dxf.text("TERRAIN-INDEX", x1, y1, 14, f"{level:.0f}", ang, align=1)
for x, y, z in spot_heights:
    dxf.poly("TERRAIN-SPOT", [(x - 8, y - 6), (x + 8, y - 6), (x, y + 8)], True)
    dxf.text("TERRAIN-SPOT", x + 14, y - 5, 16, f"{z:.1f}")

dxf.geom("WATER", river_poly.boundary)
dxf.geom("ROAD-EDGE", roads.boundary.intersection(EXTENT))
for line, _ in MAJOR:
    dxf.geom("ROAD-CENTER", LineString(line).intersection(EXTENT))
dxf.geom("BRIDGE", bridge_poly)
bridge_ls = LineString(BRIDGE)
for d in np.arange(20, bridge_ls.length, 30):                  # 桥墩
    p = bridge_ls.interpolate(d)
    if p.within(river_poly.buffer(10)):
        dxf.circle("BRIDGE", p.x, p.y, 3)
for blk in blocks:
    dxf.geom("BLOCK", blk)
for b in buildings:
    dxf.geom("BUILDING", b)
for t in towers:
    dxf.geom("BUILDING-TOWER", t)
    inner = t.buffer(-3)
    if not inner.is_empty:
        dxf.geom("BUILDING-TOWER", inner)
    c = t.centroid
    dxf.text("ANNO", c.x, c.y - 4, 8, f"{random.choice([18, 24, 28, 32, 36, 42])}F", align=1)
for x, y, r in trees:
    dxf.circle("TREE", x, y, r)

# 地名标注
labels = [
    ((250, 150), "北山 NORTH HILL", 30, 0), ((20, 440), "西南台地 SW TERRACE", 30, 0),
    ((300, 405), "河道 RIVER", 34, -22), ((265, 395), "桥 BRIDGE", 20, 45),
    ((600, 180), "高层组团 HIGH-RISE CLUSTER", 26, 8), ((220, 270), "中心城区 CITY CENTRE", 34, 4),
    ((360, 178), "北环路 NORTH RING RD", 18, 12), ((500, 305), "滨水大道 WATERFRONT AVE", 18, 8),
]
for (x, y), s, h, rot in labels:
    dxf.text("ANNO", *P(x, y), h, s, rot)

# 图框、指北针、比例尺、标题栏
M = 120
frame = box(-M, -M - 520, W + M, H + M)
dxf.geom("FRAME", frame)
dxf.geom("FRAME", box(-M + 30, -M - 490, W + M - 30, H + M - 30))
nx, ny = W - 150, H - 170
dxf.circle("FRAME", nx, ny, 70)
dxf.poly("FRAME", [(nx, ny + 90), (nx - 26, ny - 40), (nx, ny - 10), (nx + 26, ny - 40)], True)
dxf.text("FRAME", nx, ny + 105, 40, "N", align=1)
sx, sy = W - 1300, -M - 150
for a, b in [(0, 100), (100, 500), (500, 1000)]:
    dxf.poly("FRAME", [(sx + a, sy), (sx + b, sy), (sx + b, sy + 16), (sx + a, sy + 16)], True)
for v in (0, 100, 500, 1000):
    dxf.text("FRAME", sx + v, sy + 30, 28, f"{v}", align=1)
dxf.text("FRAME", sx + 1040, sy - 2, 28, "m")
dxf.text("FRAME", sx, sy + 80, 30, "SCALE 1:2000")
tx, ty = -M + 80, -M - 200
dxf.text("FRAME", tx, ty, 60, "RHINE LAB  城市模型总平面图")
dxf.text("FRAME", tx, ty - 90, 32, "CITY MODEL REFERENCE - SITE PLAN / TOP VIEW")
dxf.text("FRAME", tx, ty - 150, 26, "单位:米  等高距 5 m(计曲线 25 m)  出图比例 1:2000  依参考效果图意向重建,非测绘成果")
dxf.write(OUT / "city_plan.dxf")

# ---------------------------------------------------------------- 预览图(同一份几何)
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
fig, ax = plt.subplots(figsize=(18, 14), dpi=110)
ax.set_facecolor("#f7f6f2")
for level, coords in contours:
    c = np.array(coords)
    ax.plot(c[:, 0], c[:, 1], color="#8f8a80" if level % 25 == 0 else "#c9c4ba",
            lw=0.9 if level % 25 == 0 else 0.45)


def fill(g, **kw):
    for part in getattr(g, "geoms", [g]):
        if isinstance(part, Polygon):
            ax.fill(*part.exterior.xy, **kw)


fill(river_poly, color="#cfe0ea", ec="#6d93aa", lw=0.8)
fill(roads, color="#ffffff", ec="#6b6b6b", lw=0.5)
fill(bridge_poly, color="#ffffff", ec="#b36b2c", lw=0.9)
for line, _ in MAJOR:
    c = np.array(LineString(line).intersection(EXTENT).coords)
    ax.plot(c[:, 0], c[:, 1], color="#d04a3a", lw=0.4, ls=(0, (12, 3, 2, 3)))
for blk in blocks:
    fill(blk, color="#efece6", ec="#b9b4aa", lw=0.3)
for b in buildings:
    fill(b, color="#dcd8d0", ec="#3c3c3c", lw=0.35)
for t in towers:
    fill(t, color="#cdbfd6", ec="#5a3f6b", lw=0.5)
for x, y, r in trees:
    ax.add_patch(plt.Circle((x, y), r, fc="#cfe0c4", ec="#5f8a4f", lw=0.3))
for (x, y), s, h, rot in labels:
    ax.text(*P(x, y), s, fontsize=h / 3.2, rotation=rot, color="#333")
for x, y, z in spot_heights:
    ax.plot(x, y, "k^", ms=4)
    ax.text(x + 14, y, f"{z:.1f}", fontsize=7)
ax.plot(*frame.exterior.xy, color="k", lw=1)
ax.set_xlim(-M, W + M)
ax.set_ylim(-M - 520, H + M)
ax.set_aspect("equal")
ax.axis("off")
ax.text(-M + 80, -M - 200, "RHINE LAB  城市模型总平面图  SITE PLAN 1:2000", fontsize=16)
fig.savefig(OUT / "city_plan_preview.png", bbox_inches="tight")

print(f"等高线 {len(contours)} 条 · 街坊 {len(blocks)} · 建筑 {len(buildings)} · 高层 {len(towers)} · 树 {len(trees)}")
print(f"已写出 {OUT / 'city_plan.dxf'}({(OUT / 'city_plan.dxf').stat().st_size / 1e6:.1f} MB)与预览图")
