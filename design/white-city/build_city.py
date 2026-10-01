"""白模城市原型的数据:从 OpenStreetMap 抓一片墨尔本真实城区,压成前端直接能用的 city.json。

    python design/white-city/build_city.py

实验原型用(experimental),不是系统数据,不进 data/。一次性脚本,产物 city.json 与原型放在一起。
数据来源:OpenStreetMap(经 Overpass API),ODbL 许可,页面上必须署名。

区域:CBD 东缘 → Richmond → Yarra 河湾(Burnley),一条东西向长条,
城市由西向东平移时能一直走下去,而且带着河道、弯路和铁路。

输出坐标:以区域中心为原点的米制平面坐标(x 向东、y 向北),取整到分米存成整数以减小体积。
"""

import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
OUT = HERE / "city.json"
RAW = HERE / "_osm_raw.json"          # 原始响应缓存,重跑预处理时不必再请求(gitignore 与否由所有者定)

SOUTH, WEST, NORTH, EAST = -37.8385, 144.9660, -37.8120, 145.0340
ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
UA = "CSIT998-capstone-student-project/1.0"

QUERY = f"""[out:json][timeout:300];
(
  way["building"]({SOUTH},{WEST},{NORTH},{EAST});
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street)$"]({SOUTH},{WEST},{NORTH},{EAST});
  way["waterway"="river"]({SOUTH},{WEST},{NORTH},{EAST});
  way["railway"="rail"]({SOUTH},{WEST},{NORTH},{EAST});
  way["leisure"~"^(park|garden|pitch)$"]({SOUTH},{WEST},{NORTH},{EAST});
);
out geom tags;"""

ROAD_CLASS = {"motorway": 0, "trunk": 0, "primary": 0, "secondary": 1, "tertiary": 1,
              "residential": 2, "unclassified": 2, "living_street": 2}


def fetch() -> list[dict]:
    if RAW.exists():
        print(f"使用缓存 {RAW.name}")
        return json.loads(RAW.read_text(encoding="utf-8"))["elements"]
    payload = urllib.parse.urlencode({"data": QUERY}).encode()
    for attempt in range(2):
        for endpoint in ENDPOINTS:
            try:
                t0 = time.time()
                req = urllib.request.Request(endpoint, data=payload, headers={"User-Agent": UA})
                raw = urllib.request.urlopen(req, timeout=600).read()
                print(f"{endpoint} · {len(raw) / 1e6:.1f} MB · {time.time() - t0:.0f}s")
                RAW.write_bytes(raw)
                return json.loads(raw)["elements"]
            except Exception as exc:  # noqa: BLE001 —— 公共端点常限流,逐个试
                print(f"{endpoint} 失败({type(exc).__name__}: {exc})")
        if attempt == 0:
            time.sleep(30)
    raise SystemExit("所有 Overpass 端点都失败了")


LAT0, LON0 = (SOUTH + NORTH) / 2, (WEST + EAST) / 2
KX = 111_320 * math.cos(math.radians(LAT0))
KY = 110_574


def project(geom: list[dict]) -> list[tuple[float, float]]:
    return [((p["lon"] - LON0) * KX, (p["lat"] - LAT0) * KY) for p in geom]


def simplify(pts, tol):
    """Douglas-Peucker。"""
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = math.hypot(dx, dy) or 1e-9
    idx, dmax = 0, -1.0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x1 * y0 - y1 * x0) / norm
        if d > dmax:
            idx, dmax = i, d
    if dmax <= tol:
        return [pts[0], pts[-1]]
    return simplify(pts[:idx + 1], tol)[:-1] + simplify(pts[idx:], tol)


def simplify_ring(ring, tol):
    """闭合环不能直接喂 Douglas-Peucker:首尾是同一点,基线长度为 0,所有点都会被判成"在线上"。
    先从离起点最远的点把环切成两段,各自简化再拼回。"""
    if len(ring) < 4:
        return ring
    far = max(range(len(ring)), key=lambda i: math.dist(ring[0], ring[i]))
    a = simplify(ring[:far + 1], tol)
    b = simplify(ring[far:] + [ring[0]], tol)
    return a[:-1] + b[:-1]


def area(ring):
    return sum(ring[i][0] * ring[i - 1][1] - ring[i - 1][0] * ring[i][1] for i in range(len(ring))) / 2


def building_height(tags: dict, ring_area: float) -> float:
    for key in ("height", "building:height"):
        try:
            return max(3.0, float(str(tags[key]).replace("m", "").strip()))
        except (KeyError, ValueError):
            pass
    try:
        return max(3.0, float(tags["building:levels"]) * 3.2 + 1.0)
    except (KeyError, ValueError):
        pass
    kind = tags.get("building", "yes")
    if kind in ("house", "detached", "semidetached_house", "terrace", "residential", "bungalow"):
        return 7.0
    if kind in ("garage", "shed", "roof", "carport"):
        return 3.5
    # 无标注:按占地面积粗估。小房子两层,大体量四到六层
    return 7.0 if ring_area < 250 else 11.0 if ring_area < 1200 else 16.0


def fill_houses(buildings, roads, rivers, rails, parks, rnd):
    """OSM 在郊区住宅上画得不全,整片街区只有零星几栋,渲染出来一块密一块空。
    沿住宅街道两侧,凡是明显空着的位置补一栋普通两层住宅体块。
    **补的是视觉底色,不是数据**:单独存进 "bf",和真实建筑 "b" 分开。"""
    CELL = 40
    grid: dict[tuple[int, int], list] = {}

    def put(key_pts, item):
        for x, y in key_pts:
            grid.setdefault((int(x // CELL), int(y // CELL)), []).append(item)

    def near(x, y):
        cx, cy = int(x // CELL), int(y // CELL)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                yield from grid.get((cx + i, cy + j), ())

    for ring, _h in buildings:
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        put([(cx, cy)], ("b", cx, cy))

    def sample(line, step, kind, radius):
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            n = max(1, int(math.dist((x0, y0), (x1, y1)) // step))
            for k in range(n + 1):
                f = k / n
                put([(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)], (kind, x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, radius))

    for cls, line in roads:
        sample(line, 6, "road", 9 if cls == 2 else 13)
    for line in rivers:
        sample(line, 10, "water", 48)
    for line in rails:
        sample(line, 8, "rail", 14)

    park_boxes = [(min(p[0] for p in r), min(p[1] for p in r), max(p[0] for p in r), max(p[1] for p in r), r) for r in parks]

    def in_park(x, y):
        for x0, y0, x1, y1, ring in park_boxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                inside = False
                for i in range(len(ring)):
                    (ax, ay), (bx, by) = ring[i], ring[i - 1]
                    if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay + 1e-12) + ax:
                        inside = not inside
                if inside:
                    return True
        return False

    added = []
    for cls, line in roads:
        if cls != 2:
            continue
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            seg = math.dist((x0, y0), (x1, y1))
            if seg < 14:
                continue
            ux, uy = (x1 - x0) / seg, (y1 - y0) / seg
            nx, ny = -uy, ux
            for k in range(int(seg // 15)):
                along = 8 + k * 15
                if along > seg - 6:
                    break
                for side in (1, -1):
                    w, d = 8.5 + rnd() * 3, 11 + rnd() * 6
                    off = 9 + d / 2
                    cx, cy = x0 + ux * along + nx * side * off, y0 + uy * along + ny * side * off
                    clash = False
                    for item in near(cx, cy):
                        if item[0] == "b" and math.dist((cx, cy), item[1:3]) < 16:
                            clash = True; break
                        if item[0] in ("road", "water", "rail") and math.dist((cx, cy), item[1:3]) < item[3] + d / 2 - 1:
                            clash = True; break
                        if item[0] == "new" and math.dist((cx, cy), item[1:3]) < 12:
                            clash = True; break
                    if clash or in_park(cx, cy):
                        continue
                    hw, hd = w / 2, d / 2
                    corners = [(cx + ux * a * hw + nx * b * hd, cy + uy * a * hw + ny * b * hd)
                               for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                    if area(corners) < 0:
                        corners.reverse()
                    h = 6.5 + rnd() * 2.5
                    added.append((corners, h))
                    put([(cx, cy)], ("new", cx, cy))
    return added


def flat(pts):
    out = []
    for x, y in pts:
        out += [round(x * 10), round(y * 10)]
    return out


def main():
    elements = fetch()
    buildings, roads, rivers, rails, parks = [], [], [], [], []
    skipped = 0
    for el in elements:
        if el.get("type") != "way" or "geometry" not in el:
            continue
        tags = el.get("tags", {})
        pts = project(el["geometry"])
        if "building" in tags:
            ring = pts[:-1] if len(pts) > 3 and pts[0] == pts[-1] else pts
            ring = simplify_ring(ring, .45)
            a = area(ring)
            if len(ring) < 3 or abs(a) < 14:
                skipped += 1
                continue
            if a < 0:                       # 统一为逆时针
                ring.reverse()
            buildings.append((ring, building_height(tags, abs(a))))
        elif "highway" in tags:
            roads.append((ROAD_CLASS[tags["highway"]], simplify(pts, .8)))
        elif tags.get("waterway") == "river":
            rivers.append(simplify(pts, 1.5))
        elif tags.get("railway") == "rail":
            rails.append(simplify(pts, 1.0))
        elif "leisure" in tags and len(pts) > 3:
            ring = simplify_ring(pts[:-1] if pts[0] == pts[-1] else pts, 1.0)
            if abs(area(ring)) > 400:
                parks.append(ring)
    import random
    rnd = random.Random(20260914).random
    filled = fill_houses(buildings, roads, rivers, rails, parks, rnd)
    data = {
        "source": "© OpenStreetMap contributors (ODbL)",
        "bbox": [SOUTH, WEST, NORTH, EAST],
        "size": [round((EAST - WEST) * KX), round((NORTH - SOUTH) * KY)],
        "unit": "dm",
        "b": [[round(h * 10)] + flat(r) for r, h in buildings],
        "bf": [[round(h * 10)] + flat(r) for r, h in filled],
        "r": [[c] + flat(l) for c, l in roads], "w": [flat(l) for l in rivers],
        "rl": [flat(l) for l in rails], "p": [flat(r) for r in parks],
    }
    OUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    # 同一份数据包成脚本:页面直接双击打开(file://)时 fetch 读不了本地 JSON,<script> 可以
    (HERE / "city.js").write_text("window.CITY=" + json.dumps(data, separators=(",", ":")) + ";", encoding="utf-8")
    hs = sorted(h for _r, h in buildings)
    print(f"建筑 {len(buildings)} + 补全住宅 {len(filled)}(丢弃过小 {skipped})· 道路 {len(roads)} · 河 {len(rivers)} · 铁路 {len(rails)} · 公园 {len(parks)}")
    print(f"高度 中位 {hs[len(hs) // 2]:.1f} m · 90% {hs[int(len(hs) * .9)]:.1f} m · 最高 {hs[-1]:.1f} m")
    print(f"区域 {data['size'][0]} × {data['size'][1]} m · {OUT.name} {OUT.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
